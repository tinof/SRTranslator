"""Input preparation for a subtitle file, before any text reaches a translator.

Three jobs, in the order SrtFile runs them:

1. Decode the file without losing characters (``decode_subtitle_bytes``).
2. Remove hearing-impaired annotations: sound effects, music, speaker labels
   (``filter_sdh``). Built on the ``subtitle-filter`` package that llm-subtrans
   also uses, with its lossy rules replaced.
3. Join a sentence that the source split across two short cues
   (``merge_continuations``), so the translator sees whole sentences.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from srt import Subtitle

LOG = logging.getLogger("srtranslator")

# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

#: Below this confidence chardet guesses too often on short files.
CHARDET_MIN_CONFIDENCE = 0.7


def decode_subtitle_bytes(raw: bytes) -> str:
    """Decode a subtitle file, trying the encodings subtitles actually use.

    UTF-8 first (with or without a BOM). Then chardet when it is confident, then
    cp1252 and latin-1, which decode every byte. Reading with errors="ignore", as
    before, silently dropped every accented letter of a cp1252 file.
    """
    for encoding in ("utf-8-sig",):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass

    try:
        import chardet

        guess = chardet.detect(raw)
        encoding = guess.get("encoding")
        if encoding and (guess.get("confidence") or 0) >= CHARDET_MIN_CONFIDENCE:
            try:
                return raw.decode(encoding)
            except (LookupError, UnicodeDecodeError):
                pass
    except ImportError:
        pass

    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


# ---------------------------------------------------------------------------
# Markup
# ---------------------------------------------------------------------------

#: Every HTML-style tag and every ASS override block such as {\an8}.
TAG_RE = re.compile(r"<[^>]*>|\{\\[^}]*\}")
_FONT_TAG_RE = re.compile(r"</?font\b[^>]*>", re.IGNORECASE)
_ASS_OVERRIDE_RE = re.compile(r"\{\\[^}]*\}")
_ITALIC_TAG_RE = re.compile(r"<(/?)i\s*>", re.IGNORECASE)
#: Any tag that is not <i> or </i>.
_OTHER_TAG_RE = re.compile(r"<(?!/?i\s*>)[^>]*>", re.IGNORECASE)


def strip_tags(text: str) -> str:
    """Text as the viewer reads it: no tags, no ASS overrides."""
    return TAG_RE.sub("", text)


def clean_markup(text: str, keep_italics: bool = False) -> str:
    """Remove markup that carries no meaning for a translator.

    Font and colour tags go, but their text stays: a speaker coloured yellow
    still says the line. Italics stay when ``keep_italics`` is set, normalised
    to lowercase ``<i>`` and balanced.
    """
    text = _FONT_TAG_RE.sub("", text)
    text = _ASS_OVERRIDE_RE.sub("", text)
    if not keep_italics:
        return TAG_RE.sub("", text)
    text = _OTHER_TAG_RE.sub("", text)
    text = _ITALIC_TAG_RE.sub(lambda m: f"<{m.group(1)}i>", text)
    return join_italic_spans(balance_italics(text))


def join_italic_spans(text: str) -> str:
    """Make italic lines that follow each other one span: <i>a</i> <i>b</i> -> <i>a b</i>.

    An italic cue is usually tagged line by line. Flattened to one line, that
    reads as two spans, and DeepL then scatters the tags across the Finnish word
    order and can drop the words between them ("You're gonna have / to pull me
    up!" lost "pull").
    """
    return re.sub(r"</i>(\s*)<i>", r"\1", text)


def balance_italics(text: str) -> str:
    """Pair every <i> with a </i> and drop italic spans that hold no text."""
    depth = 0
    parts: list[str] = []
    for token in re.split(r"(</?i>)", text):
        if token == "<i>":
            if depth:
                continue  # already open; nested italics mean nothing in SRT
            depth = 1
            parts.append(token)
        elif token == "</i>":
            if not depth:
                continue  # a closing tag with no opening one
            depth = 0
            parts.append(token)
        else:
            parts.append(token)
    if depth:
        parts.append("</i>")

    balanced = "".join(parts)
    return re.sub(r"<i>(\s*)</i>", r"\1", balanced)


def is_markup_only(text: str) -> bool:
    """True when nothing readable is left once markup and symbols are removed."""
    visible = strip_tags(text)
    return not re.sub(r"[\s\-‐–—_?#¶.♪*]", "", visible)


# ---------------------------------------------------------------------------
# Hearing-impaired filtering
# ---------------------------------------------------------------------------

# subtitle-filter works line by line with regexes that read "/" and "#" as
# annotation delimiters. These private-use characters stand in for the text
# that must survive it, and are swapped back afterwards.
_ITALIC_OPEN = ""
_ITALIC_CLOSE = ""
_SAFE_SLASH = ""
_SAFE_HASH = ""

#: "and/or", "24/7": a slash between two word characters is text, not "/effect/".
_INWORD_SLASH_RE = re.compile(r"(?<=\w)/(?=\w)")
#: "#1 fan", "#2": a hash before a digit is text, not a music marker.
_NUMBER_HASH_RE = re.compile(r"#(?=\d)")

#: A speaker label in capitals at the start of a line: "JOHN:", "MAN #2:",
#: "DR. SMITH:". Mixed-case text before a colon is left alone, so "The plan is
#: simple: we run" keeps its first half. subtitle-filter's own rule removed it.
_SPEAKER_LABEL_RE = re.compile(r"^(\s*[-‐–—]?\s*)([A-Z][A-Z0-9 .'#-]*[A-Z0-9.]):\s*")


def _protect(text: str) -> str:
    text = _ITALIC_TAG_RE.sub(lambda m: _ITALIC_CLOSE if m.group(1) else _ITALIC_OPEN, text)
    text = _INWORD_SLASH_RE.sub(_SAFE_SLASH, text)
    return _NUMBER_HASH_RE.sub(_SAFE_HASH, text)


def _restore(text: str) -> str:
    text = text.replace(_SAFE_SLASH, "/").replace(_SAFE_HASH, "#")
    return text.replace(_ITALIC_OPEN, "<i>").replace(_ITALIC_CLOSE, "</i>")


def remove_speaker_labels(text: str) -> str:
    """Drop capitalised speaker labels; two labelled lines become dash dialogue."""
    lines = text.split("\n")
    labelled = [bool(_SPEAKER_LABEL_RE.match(line)) for line in lines]
    if not any(labelled):
        return text

    dialogue = sum(labelled) > 1
    cleaned = []
    for line, has_label in zip(lines, labelled, strict=True):
        if has_label:
            match = _SPEAKER_LABEL_RE.match(line)
            assert match is not None
            rest = line[match.end() :]
            prefix = "- " if dialogue or match.group(1).strip() else ""
            line = f"{prefix}{rest}"
        cleaned.append(line)
    return "\n".join(cleaned)


def filter_sdh(subtitles: list[Subtitle]) -> list[Subtitle]:
    """Remove hearing-impaired annotations and return the cues that keep text.

    Uses subtitle-filter's per-cue rules for asterisks, music, sound effects,
    credits, comma spacing and lone dashes. Its font rule (which deletes the text
    inside <font>) and its speaker rule (which deletes any capitalised phrase
    before a colon) are replaced by ``clean_markup`` and ``remove_speaker_labels``.
    Cues left with no readable text are dropped and the rest renumbered.
    """
    try:
        from subtitle_filter.libs.subtitle import Subtitle as FilterCue
    except ImportError:
        LOG.warning("subtitle-filter is not installed, hearing-impaired filtering skipped")
        return subtitles

    kept: list[Subtitle] = []
    for subtitle in subtitles:
        text = clean_markup(subtitle.content, keep_italics=True)
        text = remove_speaker_labels(text)

        cue = FilterCue()
        cue.index = subtitle.index or 1
        cue.contents = _protect(text)
        cue.remove_asterisks()
        if cue.index:
            cue.remove_music()
        if cue.index:
            cue.remove_sound_effects()
        if cue.index:
            cue.remove_author()
        if cue.index:
            cue.fix_comma_spaces()
            cue.remove_single_dash()
        if not cue.index:
            continue

        text = balance_italics(_restore(cue.contents))
        text = "\n".join(line.strip() for line in text.split("\n") if line.strip())
        if is_markup_only(text):
            continue
        subtitle.content = text
        kept.append(subtitle)

    removed = len(subtitles) - len(kept)
    if removed:
        LOG.info("Hearing-impaired filter removed %d cue(s)", removed)
    return _reindex(kept)


# ---------------------------------------------------------------------------
# Continuation merging
# ---------------------------------------------------------------------------

#: Limits ported from llm-subtrans SubtitleProcessor (merge_fragments).
MERGE_MAX_FRAGMENT_SECONDS = 1.5
MERGE_MAX_GAP_SECONDS = 0.3
MERGE_MAX_TOTAL_SECONDS = 6.0
MERGE_MAX_CHARS = 84
#: The merged cue must still be readable in its time on screen. Without this a
#: short fragment joined to a long line made a cue fix-finnish-subs split again.
MERGE_MAX_CPS = 17.0

_SENTENCE_END_RE = re.compile(r"[.!?…:;♪]['\"”’»)\]]*$")
_DASHES = ("-", "‐", "–", "—")


def _is_dialogue(text: str) -> bool:
    lines = [line for line in strip_tags(text).split("\n") if line.strip()]
    return any(line.lstrip().startswith(_DASHES) for line in lines)


def _ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_END_RE.search(strip_tags(text).rstrip()))


def _seconds(value: timedelta) -> float:
    return value.total_seconds()


def _join_text(first: str, second: str) -> str:
    joined = f"{first.rstrip()} {second.lstrip()}"
    # "<i>half of</i> <i>a sentence</i>" reads as one italic span.
    joined = join_italic_spans(joined)
    return balance_italics(" ".join(joined.split()))


def merge_continuations(
    subtitles: list[Subtitle],
    max_fragment: float = MERGE_MAX_FRAGMENT_SECONDS,
    max_gap: float = MERGE_MAX_GAP_SECONDS,
    max_total: float = MERGE_MAX_TOTAL_SECONDS,
    max_chars: int = MERGE_MAX_CHARS,
    max_cps: float = MERGE_MAX_CPS,
) -> list[Subtitle]:
    """Join a short cue to the next one when they are halves of one sentence.

    A translator handles each cue on its own, so a sentence split across two
    cues comes back as two fragments with the wrong word order. Finnish moves
    verbs and cases around more than English does, which makes this worse.

    Two cues merge only when one of them is a short fragment, the gap between
    them is tiny, the first does not end a sentence, neither is dash dialogue,
    and the result stays short enough to read (characters and reading speed). The merged cue runs from the
    first start to the second end. It is not split back after translation.
    """
    if not subtitles:
        return subtitles

    merged: list[Subtitle] = [subtitles[0]]
    count = 0
    for current in subtitles[1:]:
        previous = merged[-1]
        gap = _seconds(current.start - previous.end)
        previous_length = _seconds(previous.end - previous.start)
        current_length = _seconds(current.end - current.start)
        total = _seconds(current.end - previous.start)
        joined = _join_text(previous.content, current.content)

        mergeable = (
            0 <= gap <= max_gap
            and min(previous_length, current_length) <= max_fragment
            and total <= max_total
            and not _ends_sentence(previous.content)
            and not _is_dialogue(previous.content)
            and not _is_dialogue(current.content)
            and len(strip_tags(joined)) <= max_chars
            and total > 0
            and len(strip_tags(joined)) / total <= max_cps
        )
        if mergeable:
            previous.content = joined
            previous.end = current.end
            count += 1
            continue
        merged.append(current)

    if count:
        LOG.info("Merged %d split sentence fragment(s)", count)
    return _reindex(merged)


def _reindex(subtitles: list[Subtitle]) -> list[Subtitle]:
    for number, subtitle in enumerate(subtitles, start=1):
        subtitle.index = number
    return subtitles
