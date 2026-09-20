import textwrap
from datetime import timedelta

import srt

from srtranslator.srt_file import SrtFile


def write_sample_srt(tmp_path, content: str):
    path = tmp_path / "sample.srt"
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    return path


def test_clean_subtitles_and_dialog_markers(tmp_path):
    path = write_sample_srt(
        tmp_path,
        """
        1
        00:00:00,000 --> 00:00:01,000
        Hello <b>world</b>

        2
        00:00:01,500 --> 00:00:02,500
        -Yes
        -No
        """,
    )

    srt_file = SrtFile(str(path))

    assert srt_file.subtitles[0].content == "Hello world"
    # Dialog markers should be preserved with placeholder
    assert srt_file.subtitles[1].content == "-Yes////-No"


def test_wrap_line_preserves_words(tmp_path):
    path = write_sample_srt(
        tmp_path,
        """
        1
        00:00:00,000 --> 00:00:01,000
        Just a placeholder
        """,
    )
    srt_file = SrtFile(str(path))

    original = "This is a long line that should wrap nicely"

    # With room for more lines, every line respects the limit
    wrapped = srt_file.wrap_line(original, line_wrap_limit=12, max_lines=10).split("\n")
    assert all(len(line) <= 12 for line in wrapped)

    # Subtitles cap at max_lines, so the last line is allowed to overflow
    capped = srt_file.wrap_line(original, line_wrap_limit=12, max_lines=2).split("\n")
    assert len(capped) == 2

    # No words are broken in either case
    for lines in (wrapped, capped):
        assert " ".join(lines).split() == original.split()


def test_get_next_chunk_respects_limit(tmp_path):
    # Build three short subtitles so total length forces two chunks
    subtitles = [
        srt.Subtitle(1, timedelta(seconds=0), timedelta(seconds=1), "AAA"),
        srt.Subtitle(2, timedelta(seconds=1), timedelta(seconds=2), "BBBB"),
        srt.Subtitle(3, timedelta(seconds=2), timedelta(seconds=3), "CCCCC"),
    ]
    content = srt.compose(subtitles)
    path = write_sample_srt(tmp_path, content)

    srt_file = SrtFile(str(path))

    chunks = list(srt_file._get_next_chunk(chunk_size=10))
    assert len(chunks) == 2
    assert [sub.content for sub in chunks[0]] == ["AAA", "BBBB"]
    assert [sub.content for sub in chunks[1]] == ["CCCCC"]


def test_build_deepl_context_includes_neighbors(tmp_path):
    subtitles = [
        srt.Subtitle(1, timedelta(seconds=0), timedelta(seconds=1), "Intro"),
        srt.Subtitle(2, timedelta(seconds=1), timedelta(seconds=2), "Question"),
        # Gap of 3 seconds starts new scene
        srt.Subtitle(3, timedelta(seconds=5), timedelta(seconds=6), "Answer"),
        srt.Subtitle(4, timedelta(seconds=6.5), timedelta(seconds=7), "Follow up"),
    ]
    content = srt.compose(subtitles)
    path = write_sample_srt(tmp_path, content)
    srt_file = SrtFile(str(path))

    scenes = srt_file._detect_scenes()
    assert scenes == [0, 2]

    # Build context for second subtitle (index 1) inside first scene
    context = srt_file._build_deepl_context(
        scene_index=0,
        chunk_start_idx=1,
        chunk_end_idx=1,
        scene_start_idx=0,
        scene_end_idx=1,
    )

    assert context is not None
    # Context is raw dialogue, without headers or line numbers
    assert "Intro" in context
    assert "Answer" not in context  # next scene never bleeds in

    # Context for first subtitle of second scene should include upcoming line
    context_scene_two = srt_file._build_deepl_context(
        scene_index=1,
        chunk_start_idx=2,
        chunk_end_idx=2,
        scene_start_idx=2,
        scene_end_idx=3,
    )

    assert context_scene_two is not None
    assert "Follow up" in context_scene_two
    assert "Intro" not in context_scene_two  # previous scene never bleeds in


def test_context_skips_already_translated_lines_on_resume(tmp_path):
    """A resumed run must not feed translated text back as source context."""
    subtitles = [
        srt.Subtitle(i + 1, timedelta(seconds=i), timedelta(seconds=i + 0.5), text)
        for i, text in enumerate(["First", "Second", "Third", "Fourth"])
    ]
    path = write_sample_srt(tmp_path, srt.compose(subtitles))
    srt_file = SrtFile(str(path))
    srt_file.start_from = 2

    context = srt_file._build_deepl_context(
        scene_index=0,
        chunk_start_idx=2,
        chunk_end_idx=2,
        scene_start_idx=0,
        scene_end_idx=3,
    )

    assert context is None or ("First" not in context and "Second" not in context)


def test_fit_context_keeps_body_under_limit():
    from srtranslator.util import MAX_REQUEST_BODY_BYTES, fit_context

    text = ["A" * 1000]
    context = "\n".join(f"line {i}" for i in range(40000))

    fitted = fit_context(context, text)

    body = len(fitted.encode("utf-8")) + len(text[0].encode("utf-8"))
    assert body <= MAX_REQUEST_BODY_BYTES
    # The tail is kept, because the nearest lines matter most
    assert fitted.endswith("line 39999")


def test_fit_context_passes_small_context_through():
    from srtranslator.util import fit_context

    assert fit_context("short", ["a"]) == "short"
    assert fit_context(None, ["a"]) is None
