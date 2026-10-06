"""SrtFile from input bytes to translated cues: decoding, cleanup, chunks, retries."""

from datetime import timedelta

import pytest
import srt

from srtranslator.srt_file import SrtFile


def write_srt(tmp_path, subtitles, name="sample.srt", encoding="utf-8"):
    path = tmp_path / name
    path.write_bytes(srt.compose(subtitles).encode(encoding))
    return str(path)


def cue(index, start, end, text):
    return srt.Subtitle(index, timedelta(seconds=start), timedelta(seconds=end), text)


class RecordingTranslator:
    """Translates by prefixing, and records every request it receives."""

    max_char = 5000
    max_items = None

    def __init__(self, replies=None):
        self.requests = []
        self.replies = replies or {}

    def translate(self, text, source_language, destination_language, context=None):
        self.requests.append((text, context))
        if isinstance(text, list):
            return [self.replies.get(line, f"FI:{line}") for line in text]
        return self.replies.get(("single", text), f"FI:{text}")


def test_cp1252_file_is_decoded(tmp_path):
    path = write_srt(tmp_path, [cue(1, 0, 1, "Hyvää päivää")], encoding="cp1252")
    assert SrtFile(path).subtitles[0].content == "Hyvää päivää"


def test_empty_cue_is_dropped_not_sent_as_dots(tmp_path):
    path = write_srt(tmp_path, [cue(1, 0, 1, "<b></b>"), cue(2, 2, 3, "Hello")])
    sub = SrtFile(path)
    assert [(s.index, s.content) for s in sub.subtitles] == [(1, "Hello")]


def test_italics_kept_only_when_asked(tmp_path):
    path = write_srt(tmp_path, [cue(1, 0, 1, "<i>Hello</i> <b>you</b>")])
    assert SrtFile(path, keep_italics=True).subtitles[0].content == "<i>Hello</i> you"
    assert SrtFile(path).subtitles[0].content == "Hello you"


def test_italic_dialogue_still_counts_as_dialogue(tmp_path):
    path = write_srt(tmp_path, [cue(1, 0, 1, "<i>-Yes</i>\n<i>-No</i>")])
    sub = SrtFile(path, keep_italics=True)
    assert sub.subtitles[0].content == "<i>-Yes////-No</i>"
    assert sub.raw_contents[1] == "-Yes -No"


def test_filter_and_merge_run_before_translation(tmp_path):
    pytest.importorskip("subtitle_filter")
    path = write_srt(
        tmp_path,
        [
            cue(1, 0, 1, "[THUNDER]"),
            cue(2, 2, 3.2, "I think that we"),
            cue(3, 3.3, 4.5, "should go now."),
        ],
    )
    sub = SrtFile(path, filter_sdh=True, merge_fragments=True)
    assert [(s.index, s.content) for s in sub.subtitles] == [(1, "I think that we should go now.")]


def test_resume_does_not_refilter_the_backup(tmp_path):
    pytest.importorskip("subtitle_filter")
    path = write_srt(tmp_path, [cue(1, 0, 1, "[NOISE]"), cue(2, 2, 3, "One"), cue(3, 4, 5, "Two")])
    backup = tmp_path / "sample.srt.tmp"
    backup.write_text(srt.compose([cue(1, 2, 3, "Yksi")]), encoding="utf-8")

    sub = SrtFile(path, filter_sdh=True)

    assert sub.start_from == 1
    assert [s.content for s in sub.subtitles] == ["Yksi", "Two"]
    assert sub.raw_contents == {1: "One", 2: "Two"}


# --- chunk planning ----------------------------------------------------------


def test_chunks_follow_scenes(tmp_path):
    # Two scenes 60 s apart; each fits a request, both together do not.
    scene_a = [cue(i + 1, i, i + 0.5, "a" * 40) for i in range(5)]
    scene_b = [cue(i + 6, 70 + i, 70.5 + i, "b" * 40) for i in range(5)]
    sub = SrtFile(write_srt(tmp_path, scene_a + scene_b))
    assert sub._plan_chunks(max_char=300) == [(0, 4), (5, 9)]


def test_small_scenes_share_a_request(tmp_path):
    scene_a = [cue(1, 0, 1, "short")]
    scene_b = [cue(2, 60, 61, "also short")]
    sub = SrtFile(write_srt(tmp_path, scene_a + scene_b))
    assert sub._plan_chunks(max_char=5000) == [(0, 1)]


def test_oversized_scene_splits_at_its_longest_pause(tmp_path):
    starts = [0, 1, 2, 12, 13, 14]  # the pause before the fourth cue is longest
    subs = [cue(i + 1, s, s + 0.5, "x" * 40) for i, s in enumerate(starts)]
    sub = SrtFile(write_srt(tmp_path, subs))
    assert sub._plan_chunks(max_char=200) == [(0, 2), (3, 5)]


def test_chunks_respect_max_items(tmp_path):
    subs = [cue(i + 1, i, i + 0.5, "hi") for i in range(7)]
    sub = SrtFile(write_srt(tmp_path, subs))
    chunks = sub._plan_chunks(max_char=5000, max_items=3)
    assert all(last - first + 1 <= 3 for first, last in chunks)
    assert chunks[0][0] == 0 and chunks[-1][1] == 6


def test_chunks_start_after_resume_point(tmp_path):
    subs = [cue(i + 1, i, i + 0.5, "hi") for i in range(4)]
    sub = SrtFile(write_srt(tmp_path, subs))
    sub.start_from = 2
    assert sub._plan_chunks(max_char=5000) == [(2, 3)]


# --- translation -------------------------------------------------------------


def test_translate_sends_chronological_context(tmp_path):
    subs = [cue(i + 1, i, i + 0.5, text) for i, text in enumerate(["One", "Two", "Three"])]
    sub = SrtFile(write_srt(tmp_path, subs))
    translator = RecordingTranslator()

    sub.translate(translator, "en", "fi")

    text, context = translator.requests[0]
    assert text == ["One", "Two", "Three"]
    assert context == "One\nTwo\nThree"
    assert [s.content for s in sub.subtitles] == ["FI:One", "FI:Two", "FI:Three"]


def test_count_mismatch_raises(tmp_path):
    sub = SrtFile(write_srt(tmp_path, [cue(1, 0, 1, "One"), cue(2, 1, 2, "Two")]))

    class Short(RecordingTranslator):
        def translate(self, text, *args, **kwargs):
            return ["only one"]

    with pytest.raises(RuntimeError, match="returned 1 cues for a request of 2"):
        sub.translate(Short(), "en", "fi")


def test_empty_translation_is_retried_once(tmp_path):
    sub = SrtFile(write_srt(tmp_path, [cue(1, 0, 1, "Hello there")]))
    translator = RecordingTranslator(
        replies={"Hello there": "", ("single", "Hello there"): "Hei siellä"}
    )

    sub.translate(translator, "en", "fi")

    assert sub.subtitles[0].content == "Hei siellä"
    assert sub.attention == {}


def test_untranslated_cue_is_flagged_after_a_failed_retry(tmp_path):
    line = "This sentence came back in English"
    sub = SrtFile(write_srt(tmp_path, [cue(1, 0, 1, line)]))
    translator = RecordingTranslator(replies={line: line, ("single", line): line})

    sub.translate(translator, "en", "fi")

    assert sub.attention == {1: "untranslated"}


def test_short_unchanged_cue_is_not_suspicious(tmp_path):
    sub = SrtFile(write_srt(tmp_path, [cue(1, 0, 1, "Okay, Mike.")]))
    translator = RecordingTranslator(replies={"Okay, Mike.": "Okay, Mike."})

    sub.translate(translator, "en", "fi")

    assert sub.attention == {}
    assert len(translator.requests) == 1


def test_stray_dialogue_placeholder_is_removed(tmp_path):
    sub = SrtFile(write_srt(tmp_path, [cue(1, 0, 1, "Hello there")]))
    translator = RecordingTranslator(replies={"Hello there": "Hei////siellä"})

    sub.translate(translator, "en", "fi")

    assert sub.subtitles[0].content == "Hei siellä"


def test_lost_speaker_line_is_flagged(tmp_path):
    sub = SrtFile(write_srt(tmp_path, [cue(1, 0, 1, "-Yes\n-No")]))
    translator = RecordingTranslator(replies={"-Yes////-No": "-Kyllä ei"})

    sub.translate(translator, "en", "fi")

    assert sub.attention == {1: "dialogue_lines"}


# --- review regressions -------------------------------------------------------


def test_still_empty_cue_keeps_source_text_so_resume_stays_aligned(tmp_path):
    subs = [cue(i + 1, i * 40, i * 40 + 1, f"Line number {i}") for i in range(4)]
    path = write_srt(tmp_path, subs)
    sub = SrtFile(path)
    translator = RecordingTranslator(replies={"Line number 1": "", ("single", "Line number 1"): ""})

    sub.translate(translator, "en", "fi")

    assert sub.attention == {2: "empty"}
    assert [s.content for s in sub.subtitles][1] == "Line number 1"
    sub.save_backup()
    assert srt.compose(sub.subtitles).count("-->") == 4


def test_skewed_long_scene_plans_without_recursion_error(tmp_path):
    # One scene, pauses growing towards the end: the longest pause is always last.
    subs, start = [], 0.0
    for i in range(1500):
        subs.append(cue(i + 1, start, start + 0.5, "word " * 8))
        start += 0.5 + i * 0.0001
    sub = SrtFile(write_srt(tmp_path, subs))
    chunks = sub._plan_chunks(max_char=5000, max_items=50)
    assert chunks[0][0] == 0 and chunks[-1][1] == 1499


def test_wrapping_ignores_tag_characters():
    text = "<i>Tämä rivi on juuri sopivan pitkä</i>"
    assert SrtFile.wrap_line(text, line_wrap_limit=36, max_lines=2) == text
