import pytest

pytest.importorskip("pydantic")

from srtranslator.proofread.models import CATEGORIES, SEVERITIES  # noqa: E402
from srtranslator.proofread.prompt import (  # noqa: E402
    build_system_instruction,
    build_transcript,
    build_user_content,
    prompt_digest,
)
from srtranslator.proofread.schema import (  # noqa: E402
    ProofreadResponse,
    parse_response,
    response_schema,
)

VALID = {
    "patches": [
        {
            "id": 7,
            "before": "Näin hänen lähtevän penkiltä.",
            "after": "Näin hänen lähtevän pankista.",
            "category": "wrong_sense",
            "severity": "major",
            "source_evidence": "leave the bank",
            "reason": "the building, not a seat",
        }
    ]
}


def literal_values(field: str) -> set[str]:
    annotation = ProofreadResponse.model_fields["patches"].annotation.__args__[0]
    return set(annotation.model_fields[field].annotation.__args__)


def test_the_schema_offers_exactly_the_documented_vocabulary():
    assert literal_values("category") == set(CATEGORIES)
    assert literal_values("severity") == set(SEVERITIES)


def test_round_trip():
    patches = parse_response(VALID)
    assert len(patches) == 1
    assert patches[0].id == 7
    assert patches[0].category == "wrong_sense"


def test_a_missing_field_is_refused():
    broken = {"patches": [{k: v for k, v in VALID["patches"][0].items() if k != "after"}]}
    with pytest.raises(ValueError):
        parse_response(broken)


def test_an_invented_category_is_refused():
    broken = {"patches": [dict(VALID["patches"][0], category="style")]}
    with pytest.raises(ValueError):
        parse_response(broken)


def test_an_empty_answer_is_valid():
    assert parse_response({"patches": []}) == []


def test_google_genai_accepts_the_schema():
    types = pytest.importorskip("google.genai.types")
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=response_schema(),
        thinking_config=types.ThinkingConfig(thinking_level="medium"),
        temperature=0.2,
    )
    assert config.response_schema is ProofreadResponse


def test_the_instruction_names_the_languages_and_carries_finnish_notes():
    finnish = build_system_instruction("en", "fi")
    assert "English" in finnish and "Finnish" in finnish
    assert "sinuttelu" in finnish

    swedish = build_system_instruction("en", "sv")
    assert "sinuttelu" not in swedish
    assert prompt_digest(finnish) != prompt_digest(swedish)


def test_the_transcript_numbers_cues_and_marks_scenes(source_path, translated_path):
    from srtranslator.proofread.document import document_from_pair

    document, _ = document_from_pair(source_path, translated_path, "en", "fi")
    transcript = build_transcript(document)

    assert "=== SCENE 1 ===" in transcript
    assert "=== SCENE 2 ===" in transcript
    assert "[1] (00:00-00:02)" in transcript
    assert "  EN: I saw her leave the bank." in transcript
    assert "  FI: Näin hänen lähtevän penkiltä." in transcript

    ranged = build_user_content(document, (2, 3))
    assert "Review ONLY the cues with ids 2 to 3." in ranged


def test_an_auto_source_language_is_labelled_readably(source_path, translated_path):
    from srtranslator.proofread.document import document_from_pair

    document, _ = document_from_pair(source_path, translated_path, "auto", "fi")
    transcript = build_transcript(document)

    assert "  ORIGINAL: I saw her leave the bank." in transcript
    assert "  TRANSLATION: Näin hänen lähtevän penkiltä." in transcript
    assert "the original language" in build_system_instruction("auto", "fi")
