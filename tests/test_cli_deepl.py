"""The deepl-api command line: key source, presets, output path, Finnish fixer."""

import pytest

from srtranslator import __main__ as cli
from srtranslator import trans_cli
from srtranslator.presets import INSTRUCTION_PRESETS, instruction_preset

SOURCE = """1
00:00:00,000 --> 00:00:02,000
Hello there.

2
00:00:03,000 --> 00:00:05,000
How are you?
"""


class CapturingTranslator:
    """Stands in for DeeplApi and records what main() built it with."""

    built: dict = {}
    max_char = 5000
    max_items = 50

    def __init__(self, **kwargs):
        CapturingTranslator.built = kwargs

    def translate(self, text, source_language, destination_language, context=None):
        if isinstance(text, list):
            return [f"FI:{line}" for line in text]
        return f"FI:{text}"

    def quit(self):
        pass


@pytest.fixture
def source_file(tmp_path, monkeypatch):
    path = tmp_path / "movie.srt"
    path.write_text(SOURCE, encoding="utf-8")
    monkeypatch.setitem(cli.BUILTIN_TRANSLATORS, "deepl-api", CapturingTranslator)
    return path


@pytest.fixture
def fixer_calls(monkeypatch):
    calls = []

    def fake_fixer(self, filepath, command="fix-finnish-subs", args=None):
        calls.append([command, filepath, *(args or [])])
        return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

    monkeypatch.setattr(cli.SrtFile, "run_external_fixer", fake_fixer)
    return calls


def run(source_file, *extra):
    return cli.main(
        [str(source_file), "-t", "deepl-api", "--no-proofread", "-i", "en", "-o", "fi", *extra]
    )


def test_key_comes_from_the_environment(source_file, fixer_calls, monkeypatch):
    monkeypatch.setenv("DEEPL_API_KEY", "env-key")
    assert run(source_file) == 0
    assert CapturingTranslator.built["api_key"] == "env-key"


def test_missing_key_is_an_error(source_file, monkeypatch):
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        run(source_file)


def test_preset_and_extra_instructions_are_combined(source_file, fixer_calls, monkeypatch):
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    assert run(source_file, "--instruction-preset", "fi", "--instruction", "Extra rule") == 0
    assert CapturingTranslator.built["custom_instructions"] == [
        *INSTRUCTION_PRESETS["fi"],
        "Extra rule",
    ]


def test_glossary_id_is_passed_through(source_file, fixer_calls, monkeypatch):
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    assert run(source_file, "--glossary-id", "g-123") == 0
    assert CapturingTranslator.built["glossary_id"] == "g-123"


def test_output_path_and_finnish_fixer(source_file, fixer_calls, monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    out = tmp_path / "movie.fi.srt"
    assert run(source_file, "--output", str(out)) == 0

    assert "FI:Hello there." in out.read_text(encoding="utf-8")
    assert fixer_calls == [
        [
            "fix-finnish-subs",
            str(out),
            *cli.FIXER_ARGS,
            "--report",
            f"{out}.fixer-report.txt",
        ]
    ]
    assert "--no-ai-review" in cli.FIXER_ARGS


def test_fixer_skipped_for_other_languages(source_file, fixer_calls, monkeypatch):
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    code = cli.main([str(source_file), "-t", "deepl-api", "--no-proofread", "-i", "en", "-o", "sv"])
    assert code == 0
    assert fixer_calls == []


def test_presets_fit_deepl_limits():
    for name, instructions in INSTRUCTION_PRESETS.items():
        assert 0 < len(instructions) <= 10, name
        assert all(len(text) <= 300 for text in instructions), name


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError, match="Unknown instruction preset"):
        instruction_preset("xx")


# --- srtranslator-trans ------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [("en", "en"), ("sq", "sq"), ("pt", "pt"), ("pt-br", "pt"), ("no", "nb"),
     ("Norwegian", "nb"), ("auto", "auto"), ("xx", "auto")],
)  # fmt: skip
def test_source_language_codes(given, expected):
    assert trans_cli.get_source_language_code(given) == expected


def test_plex_output_name(tmp_path):
    assert trans_cli.build_plex_output_path(tmp_path / "tt1.src.srt", "fi").name == "tt1.fi.srt"
    assert trans_cli.build_plex_output_path(tmp_path / "Show.S01E02.en.srt", "fi").name == (
        "Show.S01E02.fi.srt"
    )


def test_trans_runs_the_full_pipeline_without_the_key(tmp_path, monkeypatch):
    source = tmp_path / "tt1.src.srt"
    source.write_text(SOURCE, encoding="utf-8")
    (tmp_path / "tt1.src.srt.tmp").write_text("stale", encoding="utf-8")
    monkeypatch.setenv("DEEPL_API_KEY", "secret-key")
    seen = []

    def fake_main(argv):
        seen.append(argv)
        out = argv[argv.index("--output") + 1]
        open(out, "w", encoding="utf-8").write(SOURCE)
        return 0

    monkeypatch.setattr(trans_cli.srtranslator_cli, "main", fake_main)

    assert trans_cli.main(["-s", "sq", str(source)]) == 0

    argv = seen[0]
    assert "secret-key" not in argv and "--auth" not in argv
    for flag in ("--filter-sdh", "--merge-fragments"):
        assert flag in argv
    assert argv[argv.index("--src-lang") + 1] == "sq"
    assert argv[argv.index("--instruction-preset") + 1] == "fi"
    assert argv[argv.index("--output") + 1] == str(tmp_path / "tt1.fi.srt")
    assert not (tmp_path / "tt1.src.srt.tmp").exists()


def test_trans_needs_the_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    assert trans_cli.main([str(tmp_path / "x.srt")]) == 1


def test_trans_reports_a_failed_translation(tmp_path, monkeypatch):
    source = tmp_path / "a.srt"
    source.write_text(SOURCE, encoding="utf-8")
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    monkeypatch.setattr(trans_cli.srtranslator_cli, "main", lambda argv: 1)
    assert trans_cli.main([str(source)]) == 1


def test_regional_finnish_runs_the_fixer():
    assert cli.is_finnish("fi-FI") and cli.is_finnish("FI") and not cli.is_finnish("sv")


def test_regional_target_file_name_is_lower_case(tmp_path):
    out = trans_cli.build_plex_output_path(tmp_path / "tt1.src.srt", "pt-PT")
    assert out.name == "tt1.pt-pt.srt"


# --- Codex review regressions -------------------------------------------------


def _fake_pipeline(monkeypatch, seen):
    def fake_main(argv):
        seen.append(argv)
        out = argv[argv.index("--output") + 1]
        open(out, "w", encoding="utf-8").write(SOURCE)
        return 0

    monkeypatch.setattr(trans_cli.srtranslator_cli, "main", fake_main)


def test_mkv_extraction_never_touches_an_existing_srt(tmp_path, monkeypatch):
    mkv = tmp_path / "movie.mkv"
    mkv.write_bytes(b"")
    existing = tmp_path / "movie.srt"
    existing.write_text("keep me", encoding="utf-8")
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    seen = []
    _fake_pipeline(monkeypatch, seen)

    def fake_extract(mkv_file, output_srt, source_lang="en"):
        assert output_srt != existing
        output_srt.write_text(SOURCE, encoding="utf-8")
        return "en"

    monkeypatch.setattr(trans_cli, "extract_subtitle_from_mkv", fake_extract)

    assert trans_cli.main([str(mkv)]) == 0
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["movie.fi.srt", "movie.mkv", "movie.srt"]


def test_mkv_uses_the_source_language_sidecar(tmp_path, monkeypatch):
    mkv = tmp_path / "movie.mkv"
    mkv.write_bytes(b"")
    (tmp_path / "movie.en.srt").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "movie.sv.srt").write_text(SOURCE, encoding="utf-8")
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    seen = []
    _fake_pipeline(monkeypatch, seen)

    assert trans_cli.main(["-s", "sv", str(mkv)]) == 0
    argv = seen[0]
    assert argv[0] == str(tmp_path / "movie.sv.srt")
    assert argv[argv.index("--src-lang") + 1] == "sv"


def test_extracted_track_language_overrides_the_requested_one(tmp_path, monkeypatch):
    mkv = tmp_path / "movie.mkv"
    mkv.write_bytes(b"")
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    seen = []
    _fake_pipeline(monkeypatch, seen)

    def fake_extract(mkv_file, output_srt, source_lang="en"):
        output_srt.write_text(SOURCE, encoding="utf-8")
        return "de"  # no Swedish track; the German one was used

    monkeypatch.setattr(trans_cli, "extract_subtitle_from_mkv", fake_extract)

    assert trans_cli.main(["-s", "sv", str(mkv)]) == 0
    assert seen[0][seen[0].index("--src-lang") + 1] == "de"


@pytest.mark.parametrize(
    ("tag", "expected"),
    [("eng", "en"), ("swe", "sv"), ("nob", "nb"), ("und", "auto"), ("", "auto")],
)
def test_track_source_language(tag, expected):
    assert trans_cli.track_source_language(tag) == expected


def test_batch_takes_source_language_sidecars(tmp_path):
    names = ["A.S01E01.en.srt", "A.S01E02.srt", "A.S01E02.fi.srt", "A.S01E03.sv.srt",
             "A.S01E04.srt", "A.S01E04.en.srt"]  # fmt: skip
    files = [tmp_path / n for n in names]
    chosen = [p.name for p in trans_cli.batch_sources(files, "en", "fi")]
    assert chosen == ["A.S01E01.en.srt", "A.S01E02.srt", "A.S01E04.srt"]


def test_required_proofread_that_cannot_run_exits_non_zero(
    source_file, fixer_calls, monkeypatch, tmp_path
):
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    monkeypatch.setattr(cli, "run_pipeline_proofread", lambda args, sub, dest: False)
    out = tmp_path / "movie.fi.srt"

    code = cli.main(
        [str(source_file), "-t", "deepl-api", "--proofread", "-i", "en", "-o", "fi",
         "--output", str(out)]
    )  # fmt: skip

    assert code == 3
    assert out.exists()  # the paid translation is still saved


def test_batch_reads_three_letter_and_non_language_suffixes(tmp_path):
    names = ["A.S01E01.eng.srt", "tt1.src.srt", "A.S01E02.fin.srt", "A.S01E03.swe.srt"]
    files = [tmp_path / n for n in names]
    chosen = sorted(p.name for p in trans_cli.batch_sources(files, "en", "fi"))
    assert chosen == ["A.S01E01.eng.srt", "tt1.src.srt"]
