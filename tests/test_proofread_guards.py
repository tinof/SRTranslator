from datetime import timedelta

import pytest

from srtranslator.proofread import guards
from srtranslator.proofread.apply import decide
from srtranslator.proofread.document import ProofreadCue, ProofreadDocument
from srtranslator.proofread.models import Patch


def make_cue(target: str, cue_id: int = 1, seconds: float = 4.0) -> ProofreadCue:
    return ProofreadCue(
        id=cue_id,
        start=timedelta(0),
        end=timedelta(seconds=seconds),
        source="source text",
        target=target,
        is_dialogue=target.strip().startswith("-"),
    )


def make_patch(before: str, after: str, **kwargs) -> Patch:
    fields = {
        "id": 1,
        "before": before,
        "after": after,
        "category": "mistranslation",
        "severity": "major",
        "source_evidence": "",
        "reason": "",
    }
    fields.update(kwargs)
    return Patch(**fields)


def make_document(cues: list[ProofreadCue]) -> ProofreadDocument:
    return ProofreadDocument(
        cues=cues, scene_starts=[0], source_lang="en", target_lang="fi", name="test"
    )


# --- precondition -----------------------------------------------------------


def test_precondition_accepts_an_exact_quote():
    cue = make_cue("Hän otti laukun.")
    patch = make_patch("Hän otti laukun.", "Hän otti salkun.")
    assert guards.check_precondition(patch, cue) is None


def test_precondition_tolerates_spacing_but_not_wording():
    cue = make_cue("-Kyllä\n-Ei")
    assert guards.check_precondition(make_patch("-Kyllä\n   -Ei", "-Kyllä\n-En"), cue) is None
    assert (
        guards.check_precondition(make_patch("-Kyllä\n-Ehkä", "-Kyllä\n-En"), cue)
        == "stale_precondition"
    )


# --- structure --------------------------------------------------------------


def test_structure_requires_the_same_speaker_turns():
    cue = make_cue("-Kyllä\n-Ei")
    assert guards.check_structure(make_patch("-Kyllä\n-Ei", "-Kyllä\n-En"), cue) is None
    assert (
        guards.check_structure(make_patch("-Kyllä\n-Ei", "Kyllä ei"), cue) == "line_count_changed"
    )
    assert (
        guards.check_structure(make_patch("-Kyllä\n-Ei", "-Kyllä\nEi"), cue) == "dialogue_dash_lost"
    )


def test_structure_rejects_a_dash_appearing_in_a_narration_cue():
    cue = make_cue("Hän otti laukun.")
    patch = make_patch("Hän otti laukun.", "-Hän otti laukun.")
    assert guards.check_structure(patch, cue) == "dialogue_dash_changed"


# --- numbers ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("before", "after", "category", "evidence", "expected"),
    [
        ("Kello on 5.", "Kello on 5.30.", "mistranslation", "half past five", None),
        ("Kello on 5.", "Kello on 6.", "mistranslation", "six o'clock", None),
        ("Kello on 5.", "Kello on 6.", "mistranslation", "", "numbers_changed"),
        ("Kello on 5.", "Kello on 6.", "readability", "6", "numbers_changed"),
        ("Kello on 5.", "Kello oli 5.", "mistranslation", "", None),
    ],
)
def test_numbers_change_only_with_evidence(before, after, category, evidence, expected):
    patch = make_patch(before, after, category=category, source_evidence=evidence)
    assert guards.check_numbers(patch) == expected


# --- negation ---------------------------------------------------------------


def test_negation_may_not_be_dropped_without_evidence():
    patch = make_patch("En tiedä.", "Tiedän.", category="wrong_sense", source_evidence="x")
    assert guards.check_negation(patch) == "negation_changed"


def test_negation_may_be_corrected_as_a_mistranslation_with_evidence():
    patch = make_patch("En tiedä.", "Tiedän.", category="mistranslation", source_evidence="I know.")
    assert guards.check_negation(patch) is None


def test_negation_untouched_passes():
    assert guards.check_negation(make_patch("En tiedä.", "En tajua.")) is None


# --- length -----------------------------------------------------------------


def test_length_rejects_a_much_longer_correction():
    cue = make_cue("Hän lähti.", seconds=4.0)
    patch = make_patch("Hän lähti.", "Hän lähti talosta hyvin kiireesti ja sulki oven.")
    assert guards.check_length(patch, cue, 0.25, 17.0) == "too_long"


def test_length_rejects_a_correction_that_will_not_be_read_in_time():
    # This cue is already too fast to read; a correction may not make it worse.
    cue = make_cue("Hän lähti talosta heti.", seconds=1.0)
    patch = make_patch("Hän lähti talosta heti.", "Hän lähti talosta nyt heti.")
    assert guards.check_length(patch, cue, 5.0, 17.0) == "too_fast_to_read"


def test_length_accepts_a_correction_of_similar_size():
    cue = make_cue("Hän otti laukun.", seconds=4.0)
    patch = make_patch("Hän otti laukun.", "Hän otti salkun.")
    assert guards.check_length(patch, cue, 0.25, 17.0) is None


# --- sanity and severity ----------------------------------------------------


def test_sanity_rejects_empty_and_marked_up_text():
    assert guards.check_sanity(make_patch("Hei", "   ")) == "empty_after"
    assert guards.check_sanity(make_patch("Hei", "<i>Hei</i>")) == "markup_in_after"


def test_severity_filter():
    patch = make_patch("a", "b", severity="minor")
    assert guards.check_severity(patch, "minor") is None
    assert guards.check_severity(patch, "major") == "below_min_severity"


# --- the decision as a whole ------------------------------------------------


def test_decide_reports_unknown_and_duplicate_ids():
    document = make_document([make_cue("Hän otti laukun.", 1)])
    patches = [
        make_patch("Hän otti laukun.", "Hän otti salkun.", id=1, severity="minor"),
        make_patch("Hän otti laukun.", "Hän vei salkun.", id=1, severity="critical"),
        make_patch("Mitä?", "Mitä nyt?", id=99),
    ]

    decision = decide(document, patches)

    assert [p.after for p in decision.accepted] == ["Hän vei salkun."]
    reasons = sorted(item.reason for item in decision.rejected)
    assert reasons == ["duplicate_id", "unknown_id"]


def test_decide_aborts_when_the_review_rewrites_too_much():
    cues = [make_cue(f"Hän sanoi rivin {index}.", index) for index in range(1, 11)]
    document = make_document(cues)
    patches = [
        make_patch(
            f"Hän sanoi rivin {index}.",
            f"Hän kertoi rivin {index}.",
            id=index,
            source_evidence="line",
        )
        for index in range(1, 5)
    ]

    decision = decide(document, patches, max_change_fraction=0.30)

    assert decision.aborted is True
    assert decision.accepted == []
    assert "4 of 10" in decision.abort_reason
    assert all(item.reason == "change_cap_exceeded" for item in decision.rejected)


def test_decide_accepts_a_clean_patch():
    document = make_document([make_cue("Näin hänen lähtevän penkiltä.", 1, seconds=4.0)])
    patch = make_patch(
        "Näin hänen lähtevän penkiltä.",
        "Näin hänen lähtevän pankista.",
        id=1,
        category="wrong_sense",
        source_evidence="leave the bank",
    )

    decision = decide(document, [patch])

    assert decision.rejected == []
    assert decision.accepted[0].after == "Näin hänen lähtevän pankista."


# --- regressions found in adversarial review -------------------------------


def test_a_speakers_words_may_not_be_deleted_behind_their_dash():
    """Line count and dash both survive, but the second speaker says nothing."""
    cue = make_cue("-Oletko varma?\n-Aivan varma.")
    patch = make_patch("-Oletko varma?\n-Aivan varma.", "-Oletko varma?\n-", category="omission")
    assert guards.check_structure(patch, cue) == "empty_speaker_turn"


def test_negation_is_checked_per_speaker_not_per_cue():
    """One speaker's negation removed while another's remains kept the whole-cue
    check happy, which is the exact flip the guard exists to prevent."""
    patch = make_patch(
        "-En tule.\n-En lähde.", "-Tulen.\n-En lähde.", category="wrong_sense", source_evidence="x"
    )
    assert guards.check_negation(patch) == "negation_changed"


def test_a_legitimate_per_line_rewording_still_passes():
    patch = make_patch("-En tule.\n-En lähde.", "-En saavu.\n-En lähde.")
    assert guards.check_negation(patch) is None


def test_the_line_break_placeholder_may_not_arrive_from_the_model():
    """wrap_lines() would turn it into a speaker line the structure check never saw."""
    assert guards.check_sanity(make_patch("Hei", "-Oletko?////-Kyllä.")) == "placeholder_in_after"
    assert guards.check_sanity(make_patch("Hei", "Rivi\\Ntoinen")) == "placeholder_in_after"


def test_guards_run_against_the_text_that_will_be_written():
    """A blank line the guards discarded used to reach the file as a third line."""
    document = make_document([make_cue("-Oletko varma?\n-Aivan.", 1)])
    patch = make_patch(
        "-Oletko varma?\n-Aivan.",
        "-Oletko?\n\n-Aivan.",
        id=1,
        category="omission",
        source_evidence="sure",
    )

    decision = decide(document, [patch])

    assert decision.accepted[0].after == "-Oletko?\n-Aivan."
