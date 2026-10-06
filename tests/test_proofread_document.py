import textwrap
from datetime import timedelta

import pytest

from srtranslator.proofread.document import (
    ProofreadAlignmentError,
    ProofreadCue,
    ProofreadDocument,
    detect_scene_starts,
    document_from_pair,
    document_from_srt_file,
    is_dialogue_text,
    target_to_internal,
    to_display,
)
from srtranslator.srt_file import SrtFile


def cue(start: float, end: float, cue_id: int = 1) -> ProofreadCue:
    return ProofreadCue(
        id=cue_id,
        start=timedelta(seconds=start),
        end=timedelta(seconds=end),
        source="",
        target="",
        is_dialogue=False,
    )


def test_placeholder_round_trip():
    assert to_display("-Kylla////-Ei") == "-Kylla\n-Ei"
    assert target_to_internal("-Kylla\n-Ei", True) == "-Kylla////-Ei"
    assert target_to_internal("yksi\nkaksi", False) == "yksi kaksi"


def test_is_dialogue_text():
    assert is_dialogue_text("-Kylla\n-Ei")
    assert is_dialogue_text("- Kylla")
    assert not is_dialogue_text("Kylla\n-Ei")
    assert not is_dialogue_text("")


def test_detect_scene_starts_splits_on_a_two_second_gap():
    cues = [cue(0, 1, 1), cue(1.5, 2.5, 2), cue(10, 11, 3)]
    assert detect_scene_starts(cues) == [0, 2]


def test_document_from_srt_file_pairs_source_with_translation(tmp_path, write_srt):
    path = write_srt(
        tmp_path / "in.srt",
        """
        1
        00:00:00,000 --> 00:00:02,000
        I saw her.

        2
        00:00:02,500 --> 00:00:04,500
        -Yes
        -No
        """,
    )
    sub = SrtFile(path)
    # Stand in for translate(), which leaves one line per cue with the placeholder.
    sub.subtitles[0].content = "Nain hanet."
    sub.subtitles[1].content = "-Kylla////-Ei"

    document = document_from_srt_file(sub, "en", "fi")

    assert [c.id for c in document.cues] == [1, 2]
    assert document.cues[0].source == "I saw her."
    assert document.cues[0].target == "Nain hanet."
    assert document.cues[1].target == "-Kylla\n-Ei"
    assert document.cues[1].is_dialogue is True
    assert document.name == "in.srt"


def test_document_from_pair_aligns_by_index(source_path, translated_path):
    document, subs = document_from_pair(source_path, translated_path, "en", "fi")

    assert len(document.cues) == 4
    assert len(subs) == 4
    assert document.cues[0].source == "I saw her leave the bank."
    assert document.cues[0].target == "Näin hänen lähtevän penkiltä."
    assert document.cues[1].is_dialogue is True
    # A 5.5 s gap between cue 2 and cue 3 starts a second scene.
    assert document.scene_starts == [0, 2]


def test_document_from_pair_refuses_mismatched_files(tmp_path, source_path, write_srt):
    short = write_srt(
        tmp_path / "short_fi.srt",
        """
        1
        00:00:00,000 --> 00:00:02,000
        Vain yksi.
        """,
    )
    with pytest.raises(ProofreadAlignmentError) as error:
        document_from_pair(source_path, short, "en", "fi")
    assert "4 cues" in str(error.value)


def test_resume_keeps_the_source_text_for_already_translated_cues(tmp_path, write_srt):
    """A resumed run must still compare Finnish against English, not against Finnish."""
    path = write_srt(
        tmp_path / "sample.srt",
        """
        1
        00:00:00,000 --> 00:00:02,000
        I saw her leave.

        2
        00:00:02,500 --> 00:00:04,500
        Are you sure?
        """,
    )
    (tmp_path / "sample.srt.tmp").write_text(
        textwrap.dedent(
            """
            1
            00:00:00,000 --> 00:00:02,000
            Näin hänen lähtevän.
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    sub = SrtFile(path)

    assert sub.start_from == 1
    assert sub.raw_contents[1] == "I saw her leave."
    assert sub.raw_contents[2] == "Are you sure?"


# --- regressions found in adversarial review -------------------------------


def test_typographic_dialogue_dashes_count_as_dialogue():
    """A translator may return en dashes for the hyphens it was given. Treating
    such a cue as narration flattened its correction and lost a speaker turn."""
    assert is_dialogue_text("–Kyllä\n–Ei")
    assert is_dialogue_text("—Kyllä\n—Ei")
    assert target_to_internal("–Kyllä\n–Ei", True) == "–Kyllä////–Ei"


def test_an_en_dash_cue_round_trips_through_the_pipeline_form():
    document = ProofreadDocument(
        cues=[
            ProofreadCue(
                id=1,
                start=timedelta(0),
                end=timedelta(seconds=3),
                source="-Yes\n-No",
                target=to_display("–Kyllä////–Ei"),
                is_dialogue=is_dialogue_text(to_display("–Kyllä////–Ei")),
            )
        ],
        scene_starts=[0],
        source_lang="en",
        target_lang="fi",
    )
    cue = document.cues[0]
    assert cue.is_dialogue is True
    assert target_to_internal("–Kyllä\n–En", cue.is_dialogue) == "–Kyllä////–En"


def test_alignment_error_is_a_proofread_error():
    """The CLI catches ProofreadError; a bare Exception reached the user as a traceback."""
    from srtranslator.proofread.models import ProofreadError

    assert issubclass(ProofreadAlignmentError, ProofreadError)


def test_pair_mode_refuses_files_whose_timelines_diverge(tmp_path, write_srt):
    """Equal cue counts do not mean the cues correspond. A dropped opening cue
    pairs every line with the wrong source, and the preconditions cannot see it."""
    source = write_srt(
        tmp_path / "s.srt",
        """
        1
        00:00:01,000 --> 00:00:02,000
        One.

        2
        00:00:03,000 --> 00:00:04,000
        Two.

        3
        00:00:30,000 --> 00:00:31,000
        Three.
        """,
    )
    shifted = write_srt(
        tmp_path / "t.srt",
        """
        1
        00:00:03,000 --> 00:00:04,000
        Kaksi.

        2
        00:00:30,000 --> 00:00:31,000
        Kolme.

        3
        00:01:00,000 --> 00:01:01,000
        Neljä.
        """,
    )
    with pytest.raises(ProofreadAlignmentError) as error:
        document_from_pair(source, shifted, "en", "fi")
    assert "drift apart" in str(error.value)


def test_pair_mode_accepts_a_uniformly_resynced_translation(tmp_path, write_srt):
    """ffsubsync shifts every cue by the same amount; that is still the same file."""
    source = write_srt(
        tmp_path / "s.srt",
        """
        1
        00:00:01,000 --> 00:00:02,000
        One.

        2
        00:00:03,000 --> 00:00:04,000
        Two.
        """,
    )
    resynced = write_srt(
        tmp_path / "t.srt",
        """
        1
        00:00:03,500 --> 00:00:04,500
        Yksi.

        2
        00:00:05,500 --> 00:00:06,500
        Kaksi.
        """,
    )
    document, _ = document_from_pair(source, resynced, "en", "fi")
    assert [(c.source, c.target) for c in document.cues] == [("One.", "Yksi."), ("Two.", "Kaksi.")]
