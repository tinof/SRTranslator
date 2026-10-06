"""DeepL custom-instruction presets, one list per target language.

DeepL accepts at most 10 instructions of 300 characters each per request. They
steer register and word choice sentence by sentence; they are not a prompt.

The Finnish preset is distilled from llm-subtrans instructions_fi.txt. Checked
against the live API on 2026-10-06: DeepL accepts instructions for FI and
follows them. On 15 test lines the output was 20% shorter, filler words were
gone, and sinä/te still matched the speakers. "Keep the profanity" made DeepL
swear harder than the source, hence the wording of the profanity rule.
"""

from __future__ import annotations

INSTRUCTION_PRESETS: dict[str, list[str]] = {
    "fi": [
        "These are film and TV subtitles. Translate concisely and drop filler words "
        "such as 'you know', 'well', 'I mean' and 'like'.",
        "Address one person with informal 'sinä' forms. Use 'te' only for a group, or "
        "for a clearly formal situation such as a stranger addressed as sir or doctor.",
        "Use natural, idiomatic Finnish. Translate the meaning, not the English "
        "sentence structure.",
        "Keep the tone of the original, including sarcasm and humour.",
        "Match the strength of any profanity: do not make it stronger or milder.",
        "Keep personal names and place names as they are in the source.",
        "Do not add quotation marks or other punctuation that the source does not have.",
        "Prefer short, common words that are quick to read on screen.",
    ],
}


def instruction_preset(name: str) -> list[str]:
    """The instructions of a preset, by target language code (e.g. "fi")."""
    key = (name or "").strip().lower().split("-")[0]
    if key not in INSTRUCTION_PRESETS:
        known = ", ".join(sorted(INSTRUCTION_PRESETS))
        raise ValueError(f"Unknown instruction preset '{name}'. Known presets: {known}")
    return list(INSTRUCTION_PRESETS[key])
