import json

import pytest

from srtranslator.proofread.backends.fake import FakeBackend
from srtranslator.proofread.document import ProofreadCue, ProofreadDocument
from srtranslator.proofread.engine import (
    ProofreadOptions,
    plan_batches,
    proofread_pair,
    proofread_srt_file,
    run_proofread,
)
from srtranslator.proofread.models import BackendUsage, ProofreadError
from srtranslator.srt_file import SrtFile

pytest.importorskip("pydantic")

BANK_PATCH = {
    "id": 1,
    "before": "Näin hänen lähtevän penkiltä.",
    "after": "Näin hänen lähtevän pankista.",
    "category": "wrong_sense",
    "severity": "major",
    "source_evidence": "leave the bank",
    "reason": "'bank' is the building here, not a seat.",
}


def make_document(count: int = 4) -> ProofreadDocument:
    from datetime import timedelta

    cues = [
        ProofreadCue(
            id=index,
            start=timedelta(seconds=index * 5),
            end=timedelta(seconds=index * 5 + 3),
            source=f"Line {index}.",
            target=f"Rivi {index}.",
            is_dialogue=False,
        )
        for index in range(1, count + 1)
    ]
    return ProofreadDocument(
        cues=cues,
        scene_starts=list(range(0, count, 2)),
        source_lang="en",
        target_lang="fi",
        name="test.srt",
    )


def translated_srt_file(source_path, translated_path) -> SrtFile:
    """An SrtFile in the state translate() leaves behind."""
    sub = SrtFile(source_path)
    translated = SrtFile(translated_path)
    for original, finished in zip(sub.subtitles, translated.subtitles, strict=True):
        original.content = finished.content
    return sub


# --- pipeline mode ----------------------------------------------------------


def test_applies_a_clean_patch_and_writes_a_report(source_path, translated_path, tmp_path):
    sub = translated_srt_file(source_path, translated_path)
    backend = FakeBackend([BANK_PATCH])
    options = ProofreadOptions(report_path=str(tmp_path / "report.json"))

    result = proofread_srt_file(sub, backend, options, "en", "fi")

    assert result.status == "applied"
    assert len(result.applied) == 1
    assert sub.subtitles[0].content == "Näin hänen lähtevän pankista."
    # Untouched cues keep their placeholder form for wrap_lines().
    assert sub.subtitles[1].content == "-Oletko varma?////-Aivan varma."

    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "applied"
    assert report["cues"] == 4
    assert report["applied"][0]["category"] == "wrong_sense"
    assert report["usage"]["prompt_tokens"] == 1000
    assert report["prompt_digest"]


def test_a_dialogue_patch_keeps_the_line_break_placeholder(source_path, translated_path, tmp_path):
    sub = translated_srt_file(source_path, translated_path)
    patch = {
        "id": 2,
        "before": "-Oletko varma?\n-Aivan varma.",
        "after": "-Oletko varma?\n-Aivan.",
        "category": "omission",
        "severity": "minor",
        "source_evidence": "Quite sure.",
        "reason": "tighter",
    }
    result = proofread_srt_file(
        sub,
        FakeBackend([patch]),
        ProofreadOptions(report_path=str(tmp_path / "r.json")),
        "en",
        "fi",
    )

    assert result.status == "applied"
    assert sub.subtitles[1].content == "-Oletko varma?////-Aivan."
    sub.wrap_lines(line_wrap_limit=42)
    assert sub.subtitles[1].content == "-Oletko varma?\n-Aivan."


def test_dry_run_reports_without_touching_the_subtitles(source_path, translated_path, tmp_path):
    sub = translated_srt_file(source_path, translated_path)
    before = sub.subtitles[0].content

    result = proofread_srt_file(
        sub,
        FakeBackend([BANK_PATCH]),
        ProofreadOptions(dry_run=True, report_path=str(tmp_path / "r.json")),
        "en",
        "fi",
    )

    assert result.status == "dry_run"
    assert len(result.applied) == 1
    assert sub.subtitles[0].content == before
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["status"] == "dry_run"


def test_a_backend_failure_never_loses_the_translation(source_path, translated_path, tmp_path):
    sub = translated_srt_file(source_path, translated_path)
    before = [subtitle.content for subtitle in sub.subtitles]

    result = proofread_srt_file(
        sub,
        FakeBackend(error=RuntimeError("503 UNAVAILABLE")),
        ProofreadOptions(report_path=str(tmp_path / "r.json")),
        "en",
        "fi",
    )

    assert result.status == "error"
    assert "503" in result.error
    assert [subtitle.content for subtitle in sub.subtitles] == before
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["status"] == "error"


def test_a_malformed_answer_is_refused_whole(source_path, translated_path, tmp_path):
    sub = translated_srt_file(source_path, translated_path)
    broken = dict(BANK_PATCH)
    del broken["category"]

    result = proofread_srt_file(
        sub,
        FakeBackend([BANK_PATCH, broken]),
        ProofreadOptions(report_path=str(tmp_path / "r.json")),
        "en",
        "fi",
    )

    assert result.status == "error"
    assert result.applied == []
    assert sub.subtitles[0].content == "Näin hänen lähtevän penkiltä."


# --- cost and batching ------------------------------------------------------


def test_the_cost_guard_skips_before_calling_the_model():
    backend = FakeBackend([BANK_PATCH], model="gemini-3.8-flash")
    result = run_proofread(make_document(), backend, ProofreadOptions(max_cost_usd=0.0001))

    assert result.status == "skipped"
    assert "over the" in result.error
    assert backend.calls == []


def test_an_unpriced_model_never_trips_the_cost_guard():
    backend = FakeBackend([], model="some-new-model")
    result = run_proofread(make_document(), backend, ProofreadOptions(max_cost_usd=0.0001))

    assert result.status == "applied"
    assert len(backend.calls) == 1


def test_plan_batches_never_splits_a_scene():
    document = make_document(10)  # scenes every 2 cues
    assert plan_batches(document, max_cues=4) == [(1, 4), (5, 8), (9, 10)]


def test_plan_batches_keeps_an_oversized_scene_whole():
    document = make_document(6)
    document.scene_starts = [0]
    assert plan_batches(document, max_cues=2) == [(1, 6)]


def test_a_large_document_is_cached_and_reviewed_in_batches():
    document = make_document(40)
    backend = FakeBackend(responses=[[], [], [], []], model="gemini-3.8-flash")
    options = ProofreadOptions(
        batch_token_threshold=10, batch_max_cues=10, max_cost_usd=0, report_path=None
    )

    result = run_proofread(document, backend, options)

    assert result.status == "applied"
    assert result.batches == 4
    assert len(backend.calls) == 4
    # One cache holds the transcript for every call, and it is released again.
    assert all(call["cached_content"] == "fake-cache-0" for call in backend.calls)
    assert backend.caches == []
    assert "Review ONLY the cues with ids 1 to 10" in backend.calls[0]["user_content"]


def test_usage_is_summed_across_batches():
    document = make_document(40)
    backend = FakeBackend(
        responses=[[], [], [], []],
        usage=BackendUsage(prompt_tokens=100, output_tokens=10, thoughts_tokens=5),
        model="gemini-3.8-flash",
    )
    result = run_proofread(
        document,
        backend,
        ProofreadOptions(batch_token_threshold=10, batch_max_cues=10, max_cost_usd=0),
    )

    assert result.usage.prompt_tokens == 400
    assert result.usage.thoughts_tokens == 20
    assert result.cost_usd is not None and result.cost_usd > 0


# --- pair mode --------------------------------------------------------------


def test_pair_mode_edits_in_place_and_keeps_a_backup(source_path, translated_path, tmp_path):
    original = open(translated_path, encoding="utf-8").read()

    result = proofread_pair(
        source_path,
        translated_path,
        FakeBackend([BANK_PATCH]),
        ProofreadOptions(report_path=str(tmp_path / "r.json")),
        "en",
        "fi",
    )

    assert result.status == "applied"
    written = open(translated_path, encoding="utf-8").read()
    assert "Näin hänen lähtevän pankista." in written
    # Everything the review did not touch is untouched.
    assert "-Oletko varma?\n-Aivan varma." in written
    assert open(f"{translated_path}.bak", encoding="utf-8").read() == original


def test_pair_mode_keeps_the_line_breaks_a_correction_came_back_with(
    source_path, translated_path, tmp_path
):
    """Nothing wraps after pair mode, so the model's own layout is the layout."""
    patch = {
        "id": 1,
        "before": "Näin hänen lähtevän penkiltä.",
        "after": "Näin hänen lähtevän\npankista.",
        "category": "wrong_sense",
        "severity": "critical",
        "source_evidence": "leave the bank",
        "reason": "the building",
    }
    proofread_pair(
        source_path,
        translated_path,
        FakeBackend([patch]),
        ProofreadOptions(report_path=str(tmp_path / "r.json")),
        "en",
        "fi",
    )

    assert "Näin hänen lähtevän\npankista." in open(translated_path, encoding="utf-8").read()


def test_pair_mode_rewraps_a_long_correction(source_path, translated_path, tmp_path):
    patch = {
        "id": 3,
        "before": "Hän otti laukun mukaansa.",
        "after": "Hän otti salkun mukaansa sinne.",
        "category": "wrong_sense",
        "severity": "major",
        "source_evidence": "the case",
        "reason": "case is a briefcase",
    }
    proofread_pair(
        source_path,
        translated_path,
        FakeBackend([patch]),
        ProofreadOptions(wrap_limit=20, max_lines=2, report_path=str(tmp_path / "r.json")),
        "en",
        "fi",
    )

    written = open(translated_path, encoding="utf-8").read()
    assert "Hän otti salkun\nmukaansa sinne." in written


def test_pair_mode_leaves_the_file_alone_when_nothing_is_accepted(
    source_path, translated_path, tmp_path
):
    original = open(translated_path, encoding="utf-8").read()
    stale = dict(BANK_PATCH, before="Jotain aivan muuta.")

    result = proofread_pair(
        source_path,
        translated_path,
        FakeBackend([stale]),
        ProofreadOptions(report_path=str(tmp_path / "r.json")),
        "en",
        "fi",
    )

    assert result.applied == []
    assert result.rejected[0].reason == "stale_precondition"
    assert open(translated_path, encoding="utf-8").read() == original
    assert not (tmp_path / "movie_fi.srt.bak").exists()


# --- regressions found in adversarial review -------------------------------


def test_a_report_path_may_not_overwrite_a_subtitle(source_path, translated_path):
    """The report is written with mode "w". Aimed at a subtitle it replaced it
    with JSON, and a dry run did it too, with no backup."""
    original = open(translated_path, encoding="utf-8").read()

    with pytest.raises(ProofreadError) as error:
        proofread_pair(
            source_path,
            translated_path,
            FakeBackend([]),
            ProofreadOptions(dry_run=True, report_path=translated_path),
            "en",
            "fi",
        )

    assert "would overwrite" in str(error.value)
    assert open(translated_path, encoding="utf-8").read() == original


def test_a_report_path_may_not_overwrite_the_source(source_path, translated_path):
    original = open(source_path, encoding="utf-8").read()
    with pytest.raises(ProofreadError):
        proofread_pair(
            source_path,
            translated_path,
            FakeBackend([]),
            ProofreadOptions(report_path=source_path),
            "en",
            "fi",
        )
    assert open(source_path, encoding="utf-8").read() == original


def test_the_report_path_is_checked_before_the_model_is_called(source_path, translated_path):
    backend = FakeBackend([BANK_PATCH])
    with pytest.raises(ProofreadError):
        proofread_pair(
            source_path,
            translated_path,
            backend,
            ProofreadOptions(report_path=translated_path),
            "en",
            "fi",
        )
    assert backend.calls == []


def test_a_failing_report_write_does_not_lose_the_corrections(
    source_path, translated_path, tmp_path
):
    """An OSError from the report used to escape into main()'s backup path."""
    sub = translated_srt_file(source_path, translated_path)
    blocked = tmp_path / "a_directory"
    blocked.mkdir()

    result = proofread_srt_file(
        sub, FakeBackend([BANK_PATCH]), ProofreadOptions(report_path=str(blocked)), "en", "fi"
    )

    assert result.status == "applied"
    assert result.report_path == ""
    assert sub.subtitles[0].content == "Näin hänen lähtevän pankista."


def test_an_en_dash_dialogue_correction_keeps_its_line_break(tmp_path, write_srt):
    """DeepL may return typographic dashes. The cue was then treated as narration
    and its correction flattened, silently merging two speakers into one line."""
    path = write_srt(
        tmp_path / "m.srt",
        """
        1
        00:00:01,000 --> 00:00:04,000
        -Are you sure?
        -Quite sure.
        """,
    )
    sub = SrtFile(path)
    sub.subtitles[0].content = "–Oletko varma?////–Aivan varma."

    patch = {
        "id": 1,
        "before": "–Oletko varma?\n–Aivan varma.",
        "after": "–Oletko varma?\n–Aivan.",
        "category": "omission",
        "severity": "minor",
        "source_evidence": "Quite sure.",
        "reason": "tighter",
    }
    result = proofread_srt_file(
        sub,
        FakeBackend([patch]),
        ProofreadOptions(report_path=str(tmp_path / "r.json")),
        "en",
        "fi",
    )

    assert result.status == "applied"
    assert sub.subtitles[0].content == "–Oletko varma?////–Aivan."
    sub.wrap_lines(line_wrap_limit=42)
    assert sub.subtitles[0].content == "–Oletko varma?\n–Aivan."


def test_a_report_path_may_not_be_a_link_to_a_subtitle(source_path, translated_path, tmp_path):
    import os

    # In pipeline mode the protected subtitle is the input file being translated.
    symlink = tmp_path / "report-link.json"
    os.symlink(source_path, symlink)
    hardlink = tmp_path / "report-hard.json"
    os.link(source_path, hardlink)

    for path in (symlink, hardlink):
        sub = translated_srt_file(source_path, translated_path)
        with pytest.raises(ProofreadError, match="would overwrite"):
            proofread_srt_file(
                sub,
                FakeBackend([BANK_PATCH]),
                ProofreadOptions(report_path=str(path)),
                "en",
                "fi",
                report_for=translated_path,
            )
