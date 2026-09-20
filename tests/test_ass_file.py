import textwrap

import pytest

from srtranslator.ass_file import AssFile

ASS_HEADER = """
[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def write_ass(tmp_path, *texts):
    lines = [
        f"Dialogue: 0,0:00:{i:02d}.00,0:00:{i + 1:02d}.00,Default,,0,0,0,,{text}"
        for i, text in enumerate(texts)
    ]
    path = tmp_path / "sample.ass"
    path.write_text(
        textwrap.dedent(ASS_HEADER).strip() + "\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return path


def texts(ass_file):
    return [event.text for event in ass_file.subtitles.events]


@pytest.mark.parametrize(
    "original",
    [
        r"The ship is ready\Nto sail.",
        r"Hello\NWorld",
        r"a\Nb",
        r"one\Ntwo\Nthree",
        r"spaced \N break",
    ],
)
def test_line_break_placeholder_round_trips(tmp_path, original):
    r"""\N survives the encode/restore cycle without eating neighbours."""
    ass_file = AssFile(str(write_ass(tmp_path, original)))

    # Encoded for translation: no raw \N, neighbouring characters intact
    encoded = texts(ass_file)[0]
    assert r"\N" not in encoded
    for word in original.replace(r"\N", " ").split():
        assert word in encoded

    # Restored on the way out
    ass_file.wrap_lines()
    assert texts(ass_file)[0] == original.replace(" \\N ", "\\N")


def test_neighbouring_characters_are_not_eaten(tmp_path):
    ass_file = AssFile(str(write_ass(tmp_path, r"The ship is ready\Nto sail.")))

    encoded = texts(ass_file)[0]
    assert "ready" in encoded
    assert "to sail." in encoded
    assert "read " not in encoded


def test_restore_tolerates_collapsed_backslashes(tmp_path):
    """A translator may return fewer backslashes than were sent."""
    ass_file = AssFile(str(write_ass(tmp_path, r"Hello\NWorld")))
    ass_file.subtitles.events[0].text = "Hola \\\\ Mundo"

    ass_file.wrap_lines()

    assert texts(ass_file)[0] == r"Hola\NMundo"


def test_single_backslash_is_left_alone(tmp_path):
    ass_file = AssFile(str(write_ass(tmp_path, "path C:\\temp here")))

    ass_file.wrap_lines()

    assert "\\N" not in texts(ass_file)[0]


def test_context_includes_current_chunk(tmp_path):
    ass_file = AssFile(str(write_ass(tmp_path, "First line.", "Second line.")))

    context = ass_file._build_deepl_context(
        scene_index=0,
        chunk_start_idx=1,
        chunk_end_idx=1,
        scene_start_idx=0,
        scene_end_idx=1,
    )

    assert context is not None
    assert "First line." in context


def test_context_skips_already_translated_lines_on_resume(tmp_path):
    ass_file = AssFile(str(write_ass(tmp_path, "First.", "Second.", "Third.")))
    # Simulate a resumed run: the first two entries hold translated text
    ass_file.start_from = 2

    context = ass_file._build_deepl_context(
        scene_index=0,
        chunk_start_idx=2,
        chunk_end_idx=2,
        scene_start_idx=0,
        scene_end_idx=2,
    )

    # With the floor there is no history left at all, and nothing after it
    assert context is None


def test_context_has_no_placeholder_leftovers(tmp_path):
    ass_file = AssFile(str(write_ass(tmp_path, r"ready\Nto sail", "-Yes\n-No", "Later.")))

    context = ass_file._build_deepl_context(
        scene_index=0,
        chunk_start_idx=2,
        chunk_end_idx=2,
        scene_start_idx=0,
        scene_end_idx=2,
    )

    assert context is not None
    assert "\\" not in context
    assert "////" not in context
    assert "ready to sail" in context


def test_dash_dialogue_line_break_round_trips(tmp_path):
    r"""Two-speaker lines must get the placeholder like any other line.

    The dash branch used to `continue` past the \N encoding, so the most common
    multi-line ASS case went to the translator with a raw \N and lost its break.
    """
    original = r"-Are you sure?\N-Quite sure."
    ass_file = AssFile(str(write_ass(tmp_path, original)))

    encoded = texts(ass_file)[0]
    assert r"\N" not in encoded, "dash line skipped the placeholder encoding"
    assert "Are you sure?" in encoded
    assert "Quite sure." in encoded

    ass_file.wrap_lines()
    assert texts(ass_file)[0] == original


class FakeTranslator:
    """Returns each line prefixed, preserving whatever placeholders it is given."""

    max_char = 40

    def __init__(self):
        self.contexts = []

    def translate(self, text, source_language, destination_language, context=None):
        self.contexts.append(context)
        return [f"ES:{line}" for line in text]

    def quit(self):
        pass


def test_chunk_index_advances_across_chunks(tmp_path):
    """The second chunk must not report the first chunk's indices."""
    # max_char=40 forces more than one chunk
    ass_file = AssFile(
        str(write_ass(tmp_path, "First line here.", "Second line here.", "Third line here."))
    )
    translator = FakeTranslator()

    ass_file.translate(translator, "en", "es")

    assert len(translator.contexts) > 1, "test needs at least two chunks"

    # The last chunk sits after the earlier lines, so they are its history.
    # When the chunk index never advances, the walk starts at -1, the history is
    # empty, and the earlier lines never appear at all.
    last = translator.contexts[-1]
    assert last is not None
    assert "First line here." in last, "chunk index did not advance; history is empty"
