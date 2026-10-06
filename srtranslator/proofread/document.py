"""Bilingual view of a subtitle file, built for review by a language model.

The document is the single representation both the prompt and the guards work
from. It pairs every cue's source text with its translation and keeps the cue
identity (the SRT index) so patches map back by id, never by position.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta

import srt
from srt import Subtitle

from .models import ProofreadError

# Mirrors SrtFile._detect_scenes. A gap this long reads as a cut to the viewer,
# so dialogue either side of it rarely belongs to the same exchange.
SCENE_GAP_SECONDS = 2.0

# SrtFile encodes the line break of a dash-dialogue cue as this placeholder while
# the text is in flight, and wrap_lines() turns it back into a newline.
DIALOGUE_LINE_BREAK = "////"

# Any of these opens a speaker turn. SrtFile itself only writes the ASCII hyphen,
# but a translation engine may return typographic dashes instead, and a finished
# file written by another tool may use them throughout.
DIALOGUE_DASHES = ("-", "–", "—")


class ProofreadAlignmentError(ProofreadError):
    """The source file and the translated file do not describe the same cues."""


@dataclass
class ProofreadCue:
    """One subtitle cue with both languages side by side."""

    id: int
    start: timedelta
    end: timedelta
    source: str
    target: str
    is_dialogue: bool

    @property
    def duration_seconds(self) -> float:
        return max((self.end - self.start).total_seconds(), 0.0)


@dataclass
class ProofreadDocument:
    """Every cue of one programme, in reading order."""

    cues: list[ProofreadCue]
    scene_starts: list[int]
    source_lang: str
    target_lang: str
    name: str = ""
    _by_id: dict[int, ProofreadCue] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {cue.id: cue for cue in self.cues}

    def by_id(self) -> dict[int, ProofreadCue]:
        return self._by_id

    def get(self, cue_id: int) -> ProofreadCue | None:
        return self._by_id.get(cue_id)

    def __len__(self) -> int:
        return len(self.cues)


def is_dialogue_text(text: str) -> bool:
    """True when every line of a cue is a dash-marked speaker turn.

    Typographic dashes count. Recognising only the ASCII hyphen here, while the
    guards accepted all three, meant a cue whose dashes came back from the
    translator as en dashes was treated as narration: its correction was then
    flattened to one line and the second speaker's turn was lost.
    """
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return False
    return all(line.lstrip().startswith(DIALOGUE_DASHES) for line in lines)


def to_display(content: str) -> str:
    """Internal cue text as the model should see it, with real line breaks."""
    return content.replace(DIALOGUE_LINE_BREAK, "\n").strip()


def target_to_internal(text: str, is_dialogue: bool) -> str:
    """Reverse of to_display, matching what SrtFile._clean_subs_content produces.

    A dash-dialogue cue keeps its break as the placeholder so wrap_lines() can
    restore it. Any other cue is flattened to one line, because wrapping happens
    later and decides the breaks itself.
    """
    text = text.strip()
    if is_dialogue:
        return text.replace("\n", DIALOGUE_LINE_BREAK)
    return " ".join(text.split())


def detect_scene_starts(
    cues: list[ProofreadCue], gap_seconds: float = SCENE_GAP_SECONDS
) -> list[int]:
    """Positions in ``cues`` where a new scene begins.

    Same rule as SrtFile._detect_scenes, applied to the document so the pipeline
    and the standalone pair mode segment a file identically.
    """
    if not cues:
        return []

    starts = [0]
    for position in range(1, len(cues)):
        gap = (cues[position].start - cues[position - 1].end).total_seconds()
        if gap >= gap_seconds:
            starts.append(position)
    return starts


def document_from_srt_file(sub, source_lang: str, target_lang: str) -> ProofreadDocument:
    """Build a document from an in-flight SrtFile, after translate().

    ``sub.content`` holds the translation at this point and ``sub.raw_contents``
    still holds the source text, keyed by the same cue index.
    """
    cues: list[ProofreadCue] = []
    for subtitle in sub.subtitles:
        target = to_display(subtitle.content)
        cues.append(
            ProofreadCue(
                id=subtitle.index,
                start=subtitle.start,
                end=subtitle.end,
                source=sub.raw_contents.get(subtitle.index, "").strip(),
                target=target,
                is_dialogue=is_dialogue_text(target),
            )
        )

    return ProofreadDocument(
        cues=cues,
        scene_starts=detect_scene_starts(cues),
        source_lang=source_lang,
        target_lang=target_lang,
        name=os.path.basename(sub.filepath),
    )


def _parse_srt(path: str) -> list[Subtitle]:
    with open(path, encoding="utf-8", errors="ignore") as handle:
        return list(srt.sort_and_reindex(list(srt.parse(handle))))


#: A translated file may have been re-synced against the video, which shifts every
#: cue by roughly the same amount. A dropped or inserted cue instead shifts only
#: part of the file, so it is the spread of the offsets, not their size, that says
#: the two files are not describing the same cues.
MAX_OFFSET_SPREAD_SECONDS = 5.0


def _check_timeline_alignment(
    source_subs: list[Subtitle],
    translated_subs: list[Subtitle],
    source_path: str,
    translated_path: str,
) -> None:
    """Refuse two files whose cues do not line up, even if the counts match.

    Pairing by position is only safe while the two files describe the same cues.
    A file missing its opening cue pairs every line with the wrong source, and the
    patch preconditions cannot catch it: they quote the target text, which matches
    perfectly while the source beside it is wrong.
    """
    offsets = [
        (translated.start - source.start).total_seconds()
        for source, translated in zip(source_subs, translated_subs, strict=True)
    ]
    if not offsets:
        return

    spread = max(offsets) - min(offsets)
    if spread > MAX_OFFSET_SPREAD_SECONDS:
        raise ProofreadAlignmentError(
            f"{os.path.basename(source_path)} and {os.path.basename(translated_path)} have "
            f"{len(offsets)} cues each, but their timings drift apart by {spread:.1f}s. "
            "They are probably not the same cues. Proof-reading needs a translation of "
            "this exact file."
        )


def document_from_pair(
    source_path: str,
    translated_path: str,
    source_lang: str,
    target_lang: str,
) -> tuple[ProofreadDocument, list[Subtitle]]:
    """Build a document from an original file and its finished translation.

    Returns the document and the parsed translated subtitles, so the caller can
    write the patched file back from the same objects.

    Raises:
        ProofreadAlignmentError: the two files do not have the same cue count.
            Aligning them would be a guess, and a wrong guess would rewrite cues
            against the wrong source.
    """
    source_subs = _parse_srt(source_path)
    translated_subs = _parse_srt(translated_path)

    if len(source_subs) != len(translated_subs):
        raise ProofreadAlignmentError(
            f"{os.path.basename(source_path)} has {len(source_subs)} cues but "
            f"{os.path.basename(translated_path)} has {len(translated_subs)}. "
            "Proof-reading needs the same cues in both files."
        )

    _check_timeline_alignment(source_subs, translated_subs, source_path, translated_path)

    cues: list[ProofreadCue] = []
    for source_sub, translated_sub in zip(source_subs, translated_subs, strict=True):
        target = translated_sub.content.strip()
        cues.append(
            ProofreadCue(
                id=translated_sub.index,
                start=translated_sub.start,
                end=translated_sub.end,
                source=" ".join(source_sub.content.split()),
                target=target,
                is_dialogue=is_dialogue_text(target),
            )
        )

    document = ProofreadDocument(
        cues=cues,
        scene_starts=detect_scene_starts(cues),
        source_lang=source_lang,
        target_lang=target_lang,
        name=os.path.basename(translated_path),
    )
    return document, translated_subs
