"""The instruction and the bilingual transcript the reviewer model reads."""

from __future__ import annotations

import hashlib
from datetime import timedelta

from .document import ProofreadDocument

#: Bumped whenever the wire format of the transcript changes, so reports from
#: different formats are never compared as if they were the same experiment.
PROMPT_FORMAT_VERSION = "1"

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "fi": "Finnish",
    "sv": "Swedish",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
    "pl": "Polish",
    "da": "Danish",
    "nb": "Norwegian",
    "et": "Estonian",
    "ru": "Russian",
    "ja": "Japanese",
}

_BASE_INSTRUCTION = """\
You are a senior subtitle translation reviewer. You are given one complete programme as numbered
cues. Each cue shows the ORIGINAL in {source_name} and the TRANSLATION in {target_name} produced by
a machine translator that saw only a few neighbouring lines at a time.

Read the whole programme before you judge any single cue. Work out who the speakers are, how they
relate to each other, and what is actually happening. A translation that looks fine on its own can
still be wrong once you know the scene.

Report ONLY cues where the translation changes, loses or invents meaning. Use these categories:
- mistranslation: the translation says something the original does not say.
- wrong_sense: an ambiguous word or phrase was translated in the wrong sense for this context.
- omission: meaning that is present in the original is missing, or content was invented.
- idiom: an idiom, slang expression or fixed phrase was translated literally and now reads wrong.
- address_form: the formality of address is wrong for these speakers, or it changes between cues
  where the relationship has not changed.
- consistency: a name, title, term or recurring phrase is rendered differently in different cues.
- gender_number: wrong person, gender, number or tense, so the wrong party does the action.

Do NOT report any of the following. Later stages of the pipeline handle them, and a patch that
touches them will be thrown away:
- line length, reading speed, line breaks or where a line is split
- punctuation style, quote marks, dashes, ellipses, capitalisation or spelling conventions
- wording that is already correct but which you would have phrased differently

A cue with no meaning problem must not appear in your answer. If the whole translation is sound,
return an empty list of patches. That is a valid and expected answer.

Rules for every patch you do return:
- "before" is the TRANSLATION of that cue, copied exactly as it is shown to you.
- "after" is the corrected translation: natural, idiomatic, concise subtitle {target_name}.
- Keep "after" about as long as "before". A subtitle has to be read in the time it is on screen, so
  a correction that is much longer will be rejected.
- Keep the same number of lines. If a line of the cue begins with "-", that dash marks a change of
  speaker: keep one dash per line, on the same lines.
- Keep every number, name and negation as it is, unless the original shows it is wrong. When you do
  change one, quote the words from the original in "source_evidence".
- "source_evidence" quotes the part of the ORIGINAL that justifies your change.
- "severity": critical if the meaning is reversed or destroyed, major if a viewer would notice the
  error, minor if it is slightly off but still understandable.

Answer with JSON that matches the given schema, and nothing else."""

_FINNISH_NOTES = """\

Notes for Finnish:
- Address forms: sinuttelu and teitittely must fit the relationship and must not drift from cue to
  cue while that relationship stays the same. English "you" gives the machine translator no signal,
  so this is the single most common error in this material.
- A "-" at the start of a line is a dialogue marker for a second speaker. It is never a hyphen and
  never part of the word that follows.
- Match the register of the original. Spoken, colloquial dialogue should not become formal written
  Finnish, and a formal speech should not become slang.
- Watch compound words and cases that change who does what to whom."""


def language_name(code: str) -> str:
    code = (code or "").strip().lower()
    if code in ("", "auto"):
        return "the original language"
    base = code.split("-")[0]
    return LANGUAGE_NAMES.get(base, code.upper())


def build_system_instruction(source_lang: str, target_lang: str) -> str:
    instruction = _BASE_INSTRUCTION.format(
        source_name=language_name(source_lang),
        target_name=language_name(target_lang),
    )
    if (target_lang or "").strip().lower().startswith("fi"):
        instruction += "\n" + _FINNISH_NOTES
    return instruction


def _timestamp(value: timedelta) -> str:
    total = int(max(value.total_seconds(), 0))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _label(code: str) -> str:
    base = (code or "").strip().lower().split("-")[0]
    return (base or "src").upper()


def build_transcript(document: ProofreadDocument) -> str:
    """The whole programme as numbered bilingual cues, grouped into scenes."""
    source_label = _label(document.source_lang)
    target_label = _label(document.target_lang)
    if source_label in ("SRC", "AUTO") or source_label == target_label:
        source_label, target_label = "ORIGINAL", "TRANSLATION"

    indent = " " * (len(target_label) + 4)
    scene_starts = set(document.scene_starts)
    scene_number = 0

    lines = [
        f"PROGRAMME: {document.name or 'subtitle'}",
        f"SOURCE: {document.source_lang}   TARGET: {document.target_lang}   "
        f"CUES: {len(document.cues)}",
        "",
    ]

    for position, cue in enumerate(document.cues):
        if position in scene_starts:
            scene_number += 1
            if position:
                lines.append("")
            lines.append(f"=== SCENE {scene_number} ===")

        target = cue.target.replace("\n", "\n" + indent)
        lines.append(f"[{cue.id}] ({_timestamp(cue.start)}-{_timestamp(cue.end)})")
        lines.append(f"  {source_label}: {cue.source}")
        lines.append(f"  {target_label}: {target}")

    return "\n".join(lines)


def build_user_content(document: ProofreadDocument, id_range: tuple[int, int] | None = None) -> str:
    """The transcript, optionally narrowed to one range of cue ids to review.

    The transcript is always whole. Only the instruction at the end changes, so a
    batched run can reuse the transcript as a cached prefix while each call
    reviews a different stretch of it.
    """
    content = build_transcript(document)
    if id_range is None:
        return content

    return f"{content}\n\n{range_instruction(*id_range)}"


def range_instruction(first: int, last: int) -> str:
    """Narrows one call to part of the programme, the rest staying as context."""
    return (
        f"Review ONLY the cues with ids {first} to {last}. Use everything else as context. "
        "Do not return patches for cues outside that range."
    )


def prompt_digest(system_instruction: str) -> str:
    """Identifies the instruction a report was produced with."""
    payload = f"v{PROMPT_FORMAT_VERSION}\n{system_instruction}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]
