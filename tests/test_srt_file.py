import srt
import textwrap
from datetime import timedelta

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

    wrapped = srt_file.wrap_line(
        "This is a long line that should wrap nicely", line_wrap_limit=12
    ).split("\n")

    assert all(len(line) <= 12 for line in wrapped)
    # Ensure no words are broken
    for line in wrapped:
        for word in line.split():
            assert word in "This is a long line that should wrap nicely"


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
    assert "Previous dialogue" in context
    assert "1. Intro" in context
    assert "Upcoming dialogue" not in context

    # Context for first subtitle of second scene should include upcoming line
    context_scene_two = srt_file._build_deepl_context(
        scene_index=1,
        chunk_start_idx=2,
        chunk_end_idx=2,
        scene_start_idx=2,
        scene_end_idx=3,
    )

    assert context_scene_two is not None
    assert "Upcoming dialogue" in context_scene_two
    assert "4. Follow up" in context_scene_two
