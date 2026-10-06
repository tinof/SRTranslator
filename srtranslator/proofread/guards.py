"""Checks a patch must pass before it is allowed to touch a subtitle.

Every check here is arithmetic or string comparison done in code. The model's own
claims about what it preserved are never taken as evidence, because a reviewer
model that is wrong about the translation is just as capable of being wrong about
its own patch.

Each function returns ``None`` when the patch passes, or a short reason string
that goes into the report when it does not.
"""

from __future__ import annotations

import re
import unicodedata

from .document import DIALOGUE_DASHES, DIALOGUE_LINE_BREAK, ProofreadCue
from .models import MEANING_CATEGORIES, Patch, severity_rank

#: Finnish negation, verb forms and imperatives. Dropping or adding one of these
#: reverses a line, which is the error a proof-reader must never introduce.
NEGATION_WORDS: frozenset[str] = frozenset(
    {
        "ei",
        "en",
        "et",
        "emme",
        "ette",
        "eivät",
        "eikä",
        "enkä",
        "etkä",
        "emmekä",
        "ettekä",
        "eivätkä",
        "älä",
        "älkää",
        "älkäämme",
        "äläkä",
        "älkääkä",
        "älköön",
    }
)

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_NUMBER_RE = re.compile(r"\d+(?:[.,:]\d+)*")
_MARKUP_RE = re.compile(r"[<>{}]")


def normalize(text: str) -> str:
    """Compare-ready form of a cue: same words, same lines, no spacing noise.

    Models reliably reproduce the words of a line and unreliably reproduce its
    indentation, so spacing is normalised away while the line structure that
    carries speaker identity is kept.
    """
    text = unicodedata.normalize("NFC", text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def canonical(text: str) -> str:
    """The exact text that will be written, given this correction.

    Guards used to run against the model's raw string while a tidied version was
    written, so a blank line the guards had discarded still reached the file as a
    third speaker line. Everything downstream now validates and applies this.
    """
    text = unicodedata.normalize("NFC", text)
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def flatten(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def dialogue_line_count(text: str) -> int:
    return sum(1 for line in text.split("\n") if line.strip().startswith(DIALOGUE_DASHES))


def check_severity(patch: Patch, min_severity: str) -> str | None:
    if severity_rank(patch.severity) < severity_rank(min_severity):
        return "below_min_severity"
    return None


def check_no_change(patch: Patch) -> str | None:
    if normalize(patch.after) == normalize(patch.before):
        return "no_change"
    return None


def check_precondition(patch: Patch, cue: ProofreadCue) -> str | None:
    """The cue must still hold the text the model says it is correcting.

    This is what makes a patch safe to apply out of order, and what catches a
    model that quoted a cue it invented or mixed up two ids.
    """
    if normalize(patch.before) != normalize(cue.target):
        return "stale_precondition"
    return None


def check_structure(patch: Patch, cue: ProofreadCue) -> str | None:
    """Speaker turns must survive the correction.

    A merged or dropped dialogue dash silently reassigns a line to the wrong
    character, which reads as a translation error of its own.
    """
    before_lines = [line for line in normalize(patch.before).split("\n") if line]
    after_lines = [line for line in normalize(patch.after).split("\n") if line]

    if cue.is_dialogue:
        if len(after_lines) != len(before_lines):
            return "line_count_changed"
        if not all(line.startswith(DIALOGUE_DASHES) for line in after_lines):
            return "dialogue_dash_lost"
        # A line that is only its marker deletes what that speaker said while
        # leaving the shape of the cue intact, so the count checks above pass.
        if any(not line.lstrip("".join(DIALOGUE_DASHES)).strip() for line in after_lines):
            return "empty_speaker_turn"
        return None

    if dialogue_line_count(patch.after) != dialogue_line_count(patch.before):
        return "dialogue_dash_changed"
    return None


def check_numbers(patch: Patch) -> str | None:
    """Times, amounts and counts stay as they are unless the source says otherwise."""
    before_numbers = sorted(_NUMBER_RE.findall(patch.before))
    after_numbers = sorted(_NUMBER_RE.findall(patch.after))
    if before_numbers == after_numbers:
        return None

    # The evidence is quoted from the original, where a number is as likely to be
    # spelled out ("half past five") as written in digits, so only its presence
    # is required, not its form.
    if patch.category in MEANING_CATEGORIES and patch.source_evidence.strip():
        return None
    return "numbers_changed"


def _negated(text: str) -> bool:
    return bool({word.lower() for word in _WORD_RE.findall(text)} & NEGATION_WORDS)


def check_negation(patch: Patch) -> str | None:
    """A correction may not quietly flip a line from negative to positive.

    Checked line by line when the correction keeps the same number of lines. A
    single verdict for the whole cue let one speaker's negation be removed while
    another speaker's kept the cue looking negative, which is exactly the flip
    this guard exists to catch.
    """
    before_lines = [line for line in canonical(patch.before).split("\n") if line]
    after_lines = [line for line in canonical(patch.after).split("\n") if line]

    if len(before_lines) == len(after_lines):
        pairs = list(zip(before_lines, after_lines, strict=True))
    else:
        pairs = [(patch.before, patch.after)]

    if all(_negated(before) == _negated(after) for before, after in pairs):
        return None

    if patch.category == "mistranslation" and patch.source_evidence.strip():
        return None
    return "negation_changed"


def check_length(
    patch: Patch,
    cue: ProofreadCue,
    max_growth: float,
    target_cps: float,
) -> str | None:
    """A correction has to fit in the time the cue is on screen.

    Wrapping happens after this stage and cannot create time, so a patch that
    makes an already fast cue faster is rejected instead of being wrapped into an
    unreadable subtitle.
    """
    before_length = len(flatten(patch.before))
    after_length = len(flatten(patch.after))

    if before_length and after_length > before_length * (1 + max_growth):
        return "too_long"

    duration = cue.duration_seconds
    if duration > 0:
        before_cps = before_length / duration
        after_cps = after_length / duration
        if after_cps > max(target_cps * 1.15, before_cps):
            return "too_fast_to_read"

    return None


def check_sanity(patch: Patch) -> str | None:
    if not patch.after.strip():
        return "empty_after"
    if _MARKUP_RE.search(patch.after):
        return "markup_in_after"
    # The model never sees this placeholder, so it has no business returning one.
    # wrap_lines() would turn it into a line break after every guard had passed,
    # adding speaker lines the structure check never saw.
    if DIALOGUE_LINE_BREAK in patch.after or "\\" in patch.after:
        return "placeholder_in_after"
    return None
