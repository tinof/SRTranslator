from datetime import timedelta

import pytest
import srt

from srtranslator import preprocess

pytest.importorskip("subtitle_filter")


def cue(index, start, end, text):
    return srt.Subtitle(index, timedelta(seconds=start), timedelta(seconds=end), text)


def filtered(*texts):
    subs = [cue(i + 1, i * 2, i * 2 + 1, text) for i, text in enumerate(texts)]
    return [sub.content for sub in preprocess.filter_sdh(subs)]


# --- decoding ---------------------------------------------------------------


def test_decode_cp1252_keeps_accented_letters():
    raw = "Hyvää päivää, näkemiin ja kiitos kaikesta, ystävät".encode("cp1252")
    assert preprocess.decode_subtitle_bytes(raw) == (
        "Hyvää päivää, näkemiin ja kiitos kaikesta, ystävät"
    )


def test_decode_utf8_with_bom():
    assert preprocess.decode_subtitle_bytes("﻿Hei".encode()) == "Hei"


# --- markup -----------------------------------------------------------------


def test_clean_markup_keeps_font_text_and_italics():
    text = '<font color="#ffff00">Hi</font> <B>there</B> <I>you</I> {\\an8}'
    assert preprocess.clean_markup(text, keep_italics=True).strip() == "Hi there <i>you</i>"
    assert preprocess.clean_markup(text, keep_italics=False).strip() == "Hi there you"


def test_italic_lines_become_one_span():
    # DeepL dropped "pull" from "<i>You're gonna have</i> <i>to pull me up!</i>".
    text = "<i>You're gonna have</i>\n<i>to pull me up!</i>"
    assert preprocess.clean_markup(text, keep_italics=True) == (
        "<i>You're gonna have\nto pull me up!</i>"
    )


def test_balance_italics_closes_and_drops_empty_spans():
    assert preprocess.balance_italics("<i>open") == "<i>open</i>"
    assert preprocess.balance_italics("close</i> here") == "close here"
    assert preprocess.balance_italics("<i> </i>text") == " text"


# --- hearing-impaired filter -------------------------------------------------


def test_font_tagged_dialogue_keeps_its_text():
    # subtitle-filter's own rule deleted everything inside <font>.
    assert filtered('<font color="#ffff00">-Hi there</font>\n-Bye') == ["-Hi there\n-Bye"]


def test_two_italic_spans_survive_the_slash_rule():
    # "</i> ... </i>" looked like a /sound effect/ to subtitle-filter.
    assert filtered("<i>Hello</i> and <i>world</i>") == ["<i>Hello</i> and <i>world</i>"]


def test_sound_effect_and_music_cues_are_dropped():
    assert filtered("[DOOR SLAMS]", "{\\an8}[MUSIC]", "♪ la la la ♪", "Stay.") == ["Stay."]


def test_inline_sound_effect_is_removed():
    assert filtered("(whispering) Come here.") == ["Come here."]


def test_capitalised_speaker_labels_are_removed():
    assert filtered("JOHN: Hi") == ["Hi"]
    assert filtered("JOHN: Hi\nMARY: Hello") == ["- Hi\n- Hello"]


def test_sentence_with_a_colon_is_not_a_speaker_label():
    # subtitle-filter removed any capitalised phrase before a colon.
    assert filtered("The plan is simple: we run.") == ["The plan is simple: we run."]


def test_numbers_slashes_and_ampersands_survive():
    assert filtered("I'm your #1 fan, and/or 24/7.") == ["I'm your #1 fan, and/or 24/7."]
    assert filtered("Tom & Jerry say 3 < 5") == ["Tom & Jerry say 3 < 5"]


def test_credit_cue_is_dropped_and_rest_renumbered():
    subs = [cue(1, 0, 1, "Subtitles by someone"), cue(2, 2, 3, "Hello.")]
    result = preprocess.filter_sdh(subs)
    assert [(sub.index, sub.content) for sub in result] == [(1, "Hello.")]


def test_emptied_italic_span_leaves_no_stray_space():
    assert filtered("<i>(on radio)</i> <i>Copy that.</i>") == ["<i>Copy that.</i>"]


# --- continuation merging ----------------------------------------------------


def merged(*cues):
    return [
        (sub.start.total_seconds(), sub.end.total_seconds(), sub.content)
        for sub in preprocess.merge_continuations(list(cues))
    ]


def test_split_sentence_is_merged_with_combined_timing():
    assert merged(cue(1, 0, 1.2, "I think that we"), cue(2, 1.3, 2.5, "should go now.")) == [
        (0.0, 2.5, "I think that we should go now.")
    ]


def test_sentence_end_blocks_a_merge():
    result = merged(cue(1, 0, 1.0, "Stop."), cue(2, 1.1, 2.0, "Now"))
    assert len(result) == 2


def test_long_gap_blocks_a_merge():
    assert len(merged(cue(1, 0, 1.0, "And then"), cue(2, 1.5, 2.0, "he left."))) == 2


def test_dialogue_never_merges():
    result = merged(cue(1, 0, 1.0, "-Wait"), cue(2, 1.1, 2.0, "for me"))
    assert len(result) == 2


def test_merge_respects_the_character_cap():
    long_a = "a " * 30
    long_b = "b " * 30
    assert len(merged(cue(1, 0, 1.0, long_a), cue(2, 1.1, 2.0, long_b))) == 2


def test_merge_that_would_read_too_fast_is_skipped():
    # 80 characters in 3.5 seconds is 23 characters per second.
    first = cue(1, 0, 2.4, "Amidst all the crazy, crazy stunts she's done,")
    second = cue(2, 2.45, 3.5, "I think there's some real beauty")
    assert len(merged(first, second)) == 2


def test_two_long_cues_do_not_merge():
    # Neither half is a short fragment.
    assert len(merged(cue(1, 0, 2.0, "We were going"), cue(2, 2.1, 4.0, "to the park."))) == 2


def test_merged_italics_stay_one_balanced_span():
    assert merged(cue(1, 0, 1.0, "<i>I never</i>"), cue(2, 1.1, 2.0, "<i>said that.</i>")) == [
        (0.0, 2.0, "<i>I never said that.</i>")
    ]


# --- review regressions -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "encoding"),
    [
        ("Hyvää päivää", "cp1252"),
        ("Hej då, vi ses på måndag. Åh nej!", "cp1252"),
        ("“Hyvää” – sanoi hän… ’ok’", "cp1252"),
        ("¿Qué pasa? ¡Mañana!", "cp1252"),
        ("Zażółć gęślą jaźń, příliš žluťoučký kůň", "cp1250"),
        ("Привет, как дела? Всё хорошо.", "cp1251"),
        ("Hyvää", "utf-16"),
    ],
)
def test_short_files_decode_in_their_own_encoding(text, encoding):
    body = "".join(f"{i}\n00:00:0{i},000 --> 00:00:0{i},900\n{text}\n\n" for i in range(1, 4))
    assert text in preprocess.decode_subtitle_bytes(body.encode(encoding))


def test_utf8_with_one_broken_byte_keeps_its_letters():
    raw = ("Hyvää päivää ystävä, mitä kuuluu tänään?\n" * 20).encode() + b"\x81 ok"
    assert preprocess.decode_subtitle_bytes(raw).startswith("Hyvää päivää ystävä")


def test_dialogue_between_two_sound_effects_survives():
    assert filtered("[door slams] I'm here. [gunshot]") == ["I'm here."]
    assert filtered("Hey (laughs) you (sighs) there") == ["Hey you there"]


def test_capitalised_words_that_are_not_speakers_stay():
    assert filtered("OK: fine") == ["OK: fine"]
    assert filtered("TV: on") == ["TV: on"]


def test_text_between_angle_brackets_is_not_a_tag():
    assert preprocess.strip_tags("a < b and c > d") == "a < b and c > d"
