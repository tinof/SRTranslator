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
