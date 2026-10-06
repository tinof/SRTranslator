import json

import pytest

from srtranslator import __main__ as cli

pytest.importorskip("pydantic")

BANK_PATCH = {
    "id": 1,
    "before": "Näin hänen lähtevän penkiltä.",
    "after": "Näin hänen lähtevän pankista.",
    "category": "wrong_sense",
    "severity": "major",
    "source_evidence": "leave the bank",
    "reason": "the building, not a seat",
}


class ExplodingTranslator:
    """Any attempt to translate in a proof-read-only run is a bug."""

    max_char = 1500

    def __init__(self, **kwargs):
        raise AssertionError("a translator must not be constructed for --proofread-only")


class FakeTranslator:
    max_char = 1500

    def __init__(self, **kwargs):
        pass

    def translate(self, text, source_language, destination_language, context=None):
        return [f"FI:{line}" for line in text]

    def quit(self):
        pass


@pytest.fixture
def patch_file(tmp_path):
    path = tmp_path / "patches.json"
    path.write_text(json.dumps({"patches": [BANK_PATCH]}), encoding="utf-8")
    return str(path)


def test_proofread_only_never_builds_a_translator(
    monkeypatch, source_path, translated_path, patch_file, tmp_path
):
    monkeypatch.setitem(cli.BUILTIN_TRANSLATORS, "deepl-scrap", ExplodingTranslator)
    original = open(translated_path, encoding="utf-8").read()

    code = cli.main(
        [
            translated_path,
            "--proofread-only",
            "--source",
            source_path,
            "-o",
            "fi",
            "--proofread-backend",
            "fake",
            "--proofread-fake-patches",
            patch_file,
            "--proofread-report",
            str(tmp_path / "r.json"),
        ]
    )

    assert code == 0
    written = open(translated_path, encoding="utf-8").read()
    assert "Näin hänen lähtevän pankista." in written
    assert "Sitten meillä ei ole mitään." in written
    assert open(f"{translated_path}.bak", encoding="utf-8").read() == original
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["status"] == "applied"


def test_proofread_only_needs_a_source(translated_path):
    with pytest.raises(SystemExit):
        cli.main([translated_path, "--proofread-only", "-o", "fi"])


def test_source_without_proofread_only_is_an_error(translated_path, source_path):
    with pytest.raises(SystemExit):
        cli.main([translated_path, "--source", source_path, "-o", "fi"])


def test_pipeline_runs_the_review_before_wrapping(monkeypatch, tmp_path, write_srt, patch_file):
    path = write_srt(
        tmp_path / "movie.srt",
        """
        1
        00:00:00,000 --> 00:00:06,000
        I saw her leave the bank just after six that evening.
        """,
    )
    # Long enough that wrapping splits it. The patch quotes the unwrapped text, so
    # this test fails if the review is ever moved to after wrap_lines().
    patches = tmp_path / "p.json"
    patches.write_text(
        json.dumps(
            {
                "patches": [
                    dict(
                        BANK_PATCH,
                        before="FI:I saw her leave the bank just after six that evening.",
                        after="Näin hänen lähtevän pankista juuri kuuden jälkeen sinä iltana.",
                    )
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(cli.BUILTIN_TRANSLATORS, "deepl-scrap", FakeTranslator)

    code = cli.main(
        [
            path,
            "-o",
            "fi",
            "--no-external-fixer",
            "--proofread",
            "--proofread-backend",
            "fake",
            "--proofread-fake-patches",
            str(patches),
        ]
    )

    assert code == 0
    output = tmp_path / "movie_fi.srt"
    written = output.read_text(encoding="utf-8")
    # The correction is present AND has been wrapped afterwards, which only holds
    # if the review ran on the unwrapped text.
    assert "Näin hänen lähtevän pankista" in written
    assert "\n" in written.split("00:00:06,000")[1].strip()

    report = json.loads((tmp_path / "movie_fi.srt.proofread.json").read_text(encoding="utf-8"))
    assert report["status"] == "applied"
    assert report["input"] == path


def test_no_proofread_skips_the_stage(monkeypatch, tmp_path, write_srt):
    path = write_srt(
        tmp_path / "movie.srt",
        """
        1
        00:00:00,000 --> 00:00:02,000
        Hello.
        """,
    )
    monkeypatch.setitem(cli.BUILTIN_TRANSLATORS, "deepl-scrap", FakeTranslator)
    monkeypatch.setattr(
        cli, "build_proofread_backend", lambda *a, **k: pytest.fail("stage must not run")
    )

    assert cli.main([path, "-o", "fi", "--no-external-fixer", "--no-proofread"]) == 0
    assert not (tmp_path / "movie_fi.srt.proofread.json").exists()


def test_auto_mode_is_off_without_credentials(monkeypatch):
    parser = cli.build_parser()
    args = parser.parse_args(["x.srt", "-o", "fi"])

    monkeypatch.setattr(cli.gemini_backend, "sdk_available", lambda: True)
    monkeypatch.setattr(cli.gemini_backend, "credentials_available", lambda: False)
    assert cli.proofread_enabled(args) is False

    monkeypatch.setattr(cli.gemini_backend, "credentials_available", lambda: True)
    assert cli.proofread_enabled(args) is True

    monkeypatch.setattr(cli.gemini_backend, "sdk_available", lambda: False)
    assert cli.proofread_enabled(args) is False


def test_explicit_flags_beat_the_environment(monkeypatch):
    parser = cli.build_parser()
    monkeypatch.setattr(cli.gemini_backend, "sdk_available", lambda: False)
    monkeypatch.setattr(cli.gemini_backend, "credentials_available", lambda: False)

    assert cli.proofread_enabled(parser.parse_args(["x.srt", "--proofread"])) is True
    assert cli.proofread_enabled(parser.parse_args(["x.srt", "--no-proofread"])) is False


def test_mismatched_files_report_an_error_instead_of_a_traceback(
    tmp_path, source_path, write_srt, patch_file
):
    """ProofreadAlignmentError did not inherit ProofreadError, so this escaped
    main() as an uncaught exception instead of returning 1."""
    short = write_srt(
        tmp_path / "short_fi.srt",
        """
        1
        00:00:00,000 --> 00:00:02,000
        Vain yksi.
        """,
    )

    code = cli.main(
        [
            short,
            "--proofread-only",
            "--source",
            source_path,
            "-o",
            "fi",
            "--proofread-backend",
            "fake",
            "--proofread-fake-patches",
            patch_file,
        ]
    )

    assert code == 1
