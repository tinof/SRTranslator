"""The proof-reader never sees markup, and italics survive its corrections."""

import pytest

from srtranslator.proofread.backends.fake import FakeBackend
from srtranslator.proofread.document import document_from_srt_file, italics_state
from srtranslator.proofread.engine import ProofreadOptions, proofread_pair, proofread_srt_file
from srtranslator.proofread.prompt import build_transcript
from srtranslator.srt_file import SrtFile

pytest.importorskip("pydantic")

SOURCE = """
1
00:00:00,000 --> 00:00:02,000
<i>I saw her leave the bank.</i>

2
00:00:02,500 --> 00:00:04,500
She said <i>no</i>.
"""

TRANSLATED = """
1
00:00:00,000 --> 00:00:02,000
<i>Näin hänen lähtevän penkiltä.</i>

2
00:00:02,500 --> 00:00:04,500
Hän sanoi <i>ei</i>.
"""


def patch(cue_id, before, after):
    return {
        "id": cue_id,
        "before": before,
        "after": after,
        "category": "wrong_sense",
        "severity": "major",
        "source_evidence": "bank",
        "reason": "test",
    }


@pytest.fixture
def in_flight(tmp_path, write_srt):
    """An SrtFile with italics kept, in the state translate() leaves it."""
    sub = SrtFile(write_srt(tmp_path / "en.srt", SOURCE), keep_italics=True)
    done = SrtFile(write_srt(tmp_path / "fi.srt", TRANSLATED), keep_italics=True)
    for original, finished in zip(sub.subtitles, done.subtitles, strict=True):
        original.content = finished.content
    return sub


def test_italics_state():
    assert italics_state("<i>whole</i>") == "all"
    assert italics_state("a <i>word</i>") == "partial"
    assert italics_state("<i>-Yes</i>////<i>-No</i>") == "partial"
    assert italics_state("plain") == "none"


def test_the_model_sees_no_tags(in_flight):
    document = document_from_srt_file(in_flight, "en", "fi")
    transcript = build_transcript(document)
    assert "<i>" not in transcript
    assert "Näin hänen lähtevän penkiltä." in transcript


def test_a_fully_italic_cue_keeps_its_italics(in_flight, tmp_path):
    backend = FakeBackend(
        [patch(1, "Näin hänen lähtevän penkiltä.", "Näin hänen lähtevän pankista.")]
    )
    result = proofread_srt_file(
        in_flight, backend, ProofreadOptions(report_path=str(tmp_path / "r.json")), "en", "fi"
    )

    assert result.status == "applied"
    assert in_flight.subtitles[0].content == "<i>Näin hänen lähtevän pankista.</i>"


def test_a_partly_italic_cue_is_not_rewritten(in_flight, tmp_path):
    backend = FakeBackend([patch(2, "Hän sanoi ei.", "Hän kieltäytyi.")])
    result = proofread_srt_file(
        in_flight, backend, ProofreadOptions(report_path=str(tmp_path / "r.json")), "en", "fi"
    )

    assert [r.reason for r in result.rejected] == ["italic_markup"]
    assert in_flight.subtitles[1].content == "Hän sanoi <i>ei</i>."


def test_pair_mode_reapplies_whole_cue_italics(tmp_path, write_srt):
    source = write_srt(tmp_path / "en.srt", SOURCE)
    translated = write_srt(tmp_path / "fi.srt", TRANSLATED)
    backend = FakeBackend(
        [patch(1, "Näin hänen lähtevän penkiltä.", "Näin hänen lähtevän pankista.")]
    )

    proofread_pair(
        source, translated, backend, ProofreadOptions(report_path=str(tmp_path / "r.json")),
        "en", "fi",
    )  # fmt: skip

    assert "<i>Näin hänen lähtevän pankista.</i>" in open(translated, encoding="utf-8").read()


def test_flagged_cues_get_a_check_line(in_flight):
    in_flight.attention = {1: "untranslated"}
    transcript = build_transcript(document_from_srt_file(in_flight, "en", "fi"))
    assert "CHECK: the translation is identical to the original" in transcript
    assert transcript.count("CHECK:") == 1
