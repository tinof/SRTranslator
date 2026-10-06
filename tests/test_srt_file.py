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


def test_build_deepl_context_is_chronological(tmp_path):
    subtitles = [
        srt.Subtitle(1, timedelta(seconds=0), timedelta(seconds=1), "Intro"),
        srt.Subtitle(2, timedelta(seconds=1), timedelta(seconds=2), "Question"),
        # A pause of 40 seconds starts a new scene
        srt.Subtitle(3, timedelta(seconds=42), timedelta(seconds=43), "Answer"),
        srt.Subtitle(4, timedelta(seconds=43.5), timedelta(seconds=44), "Follow up"),
    ]
    path = write_sample_srt(tmp_path, srt.compose(subtitles))
    srt_file = SrtFile(str(path))

    assert srt_file._detect_scenes() == [0, 2]

    # Context for the second cue: what came before, the cue itself, what follows.
    # It may cross the scene boundary, because names and topics carry over.
    context = srt_file._build_deepl_context(chunk_start_idx=1, chunk_end_idx=1)
    assert context == "Intro\nQuestion\nAnswer\nFollow up"


def test_build_deepl_context_after_context_starts_at_chunk_end(tmp_path):
    subtitles = [
        srt.Subtitle(i + 1, timedelta(seconds=i), timedelta(seconds=i + 0.5), f"Line {i}")
        for i in range(6)
    ]
    path = write_sample_srt(tmp_path, srt.compose(subtitles))
    srt_file = SrtFile(str(path))

    context = srt_file._build_deepl_context(
        chunk_start_idx=1, chunk_end_idx=3, max_chars_before=7, max_chars_after=7
    )
    assert context == "Line 0\nLine 1\nLine 2\nLine 3\nLine 4"


def test_context_skips_already_translated_lines_on_resume(tmp_path):
    """A resumed run must not feed translated text back as source context."""
    subtitles = [
        srt.Subtitle(i + 1, timedelta(seconds=i), timedelta(seconds=i + 0.5), text)
        for i, text in enumerate(["First", "Second", "Third", "Fourth"])
    ]
    path = write_sample_srt(tmp_path, srt.compose(subtitles))
    srt_file = SrtFile(str(path))
    srt_file.start_from = 2

    context = srt_file._build_deepl_context(chunk_start_idx=2, chunk_end_idx=2)

    assert context is not None
    assert "First" not in context
    assert "Second" not in context
    # The line after the chunk is still legitimate context
    assert "Fourth" in context


def test_fit_context_keeps_body_under_limit():
    import json

    from srtranslator.util import (
        MAX_REQUEST_BODY_BYTES,
        REQUEST_OVERHEAD_BYTES,
        fit_context,
    )

    text = ["A" * 1000]
    context = "\n".join(f"line {i}" for i in range(40000))

    fitted = fit_context(context, text)

    body = len(json.dumps(fitted)) + len(json.dumps(text[0]))
    assert body <= MAX_REQUEST_BODY_BYTES - REQUEST_OVERHEAD_BYTES
    # The tail is kept, because the nearest lines matter most
    assert fitted.endswith("line 39999")
    # Whole lines only, never a partial one
    assert all(line.startswith("line ") for line in fitted.split("\n"))


def test_fit_context_measures_the_escaped_wire_size():
    """Non-ASCII is sent as \\uXXXX, so UTF-8 byte counting under-counts."""
    from srtranslator.util import MAX_REQUEST_BODY_BYTES, fit_context

    # Under UTF-8 accounting this fits; on the wire it is roughly twice as big
    context = "\n".join("日本語" * 20 for _ in range(550))
    assert len(context.encode("utf-8")) < MAX_REQUEST_BODY_BYTES

    fitted = fit_context(context, ["x"])

    assert fitted is not None
    assert len(fitted) < len(context), "should have trimmed on wire size"


def test_fit_context_passes_small_context_through():
    from srtranslator.util import fit_context

    assert fit_context("short", ["a"]) == "short"
    assert fit_context(None, ["a"]) is None
