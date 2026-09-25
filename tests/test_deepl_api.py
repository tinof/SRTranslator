import logging

import pytest

import srtranslator.translators.deepl_api as deepl_api
from srtranslator.translators.deepl_api import DeeplApi


class FakeTextResult:
    def __init__(self, text, billed_characters=0, model_type_used=None):
        self.text = text
        self.billed_characters = billed_characters
        self.model_type_used = model_type_used


class FakeClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.calls = []

    def translate_text(self, text, **kwargs):
        self.calls.append({"text": text, **kwargs})
        if isinstance(text, list):
            return [
                FakeTextResult(f"translated {item}", len(item), "quality_optimized")
                for item in text
            ]
        return FakeTextResult(f"translated {text}", len(text), "quality_optimized")


@pytest.fixture
def fake_client(monkeypatch):
    created = []

    def factory(api_key):
        client = FakeClient(api_key)
        created.append(client)
        return client

    monkeypatch.setattr(deepl_api.deepl, "DeepLClient", factory)
    return created


def test_defaults_to_next_gen_model_and_auto_source(fake_client):
    DeeplApi("key").translate_single("Hello", "auto", "es")

    call = fake_client[0].calls[0]
    assert call["model_type"] == "quality_optimized"
    assert call["source_lang"] is None
    assert call["target_lang"] == "es"


def test_formatting_options_are_still_forwarded(fake_client):
    """The options added alongside context must survive the client rewrite."""
    DeeplApi("key").translate_single("Hello", "en", "es")

    call = fake_client[0].calls[0]
    assert call["preserve_formatting"] is True
    assert call["tag_handling"] == "xml"
    assert call["split_sentences"] == "nonewlines"


def test_explicit_source_language_is_forwarded(fake_client):
    DeeplApi("key").translate_single("Hello", "en", "es")

    assert fake_client[0].calls[0]["source_lang"] == "en"


def test_global_and_chunk_context_are_joined(fake_client):
    translator = DeeplApi("key", context="A spy movie")
    translator.translate_single("Hello", "en", "es", context="Hi\nThere")

    assert fake_client[0].calls[0]["context"] == "A spy movie\n\nHi\nThere"


def test_context_omitted_when_empty(fake_client):
    DeeplApi("key").translate_single("Hello", "en", "es")

    assert "context" not in fake_client[0].calls[0]


@pytest.mark.parametrize("target", ["es", "en-GB", "ZH-HANS", "fi", "sv"])
def test_custom_instructions_forwarded_for_every_target(fake_client, target):
    """DeepL does not restrict instructions by target language.

    Verified against the live API: Finnish and Swedish are both accepted and
    the instruction is honoured, so this class must not invent an allowlist.
    """
    translator = DeeplApi("key", custom_instructions=["Keep names untranslated"])
    translator.translate_single("Hello", "en", target)

    assert fake_client[0].calls[0]["custom_instructions"] == ["Keep names untranslated"]


def test_custom_instructions_allowed_with_latency_model(fake_client):
    """Verified against the live API: the combination works and is honoured."""
    translator = DeeplApi("key", model_type="latency_optimized", custom_instructions=["Keep names"])
    translator.translate_single("Hello", "en", "es")

    call = fake_client[0].calls[0]
    assert call["model_type"] == "latency_optimized"
    assert call["custom_instructions"] == ["Keep names"]


def test_too_many_custom_instructions_rejected(fake_client):
    with pytest.raises(ValueError, match="at most"):
        DeeplApi("key", custom_instructions=[f"rule {i}" for i in range(11)])


def test_overlong_custom_instruction_rejected(fake_client):
    with pytest.raises(ValueError, match="300"):
        DeeplApi("key", custom_instructions=["x" * 301])


def test_batch_returns_strings_and_sums_billed_characters(fake_client):
    translator = DeeplApi("key")
    result = translator.translate_batch(["one", "two"], "en", "es")

    assert result == ["translated one", "translated two"]
    assert translator.billed_characters == len("one") + len("two")


def test_translate_dispatches_list_to_batch(fake_client):
    translator = DeeplApi("key")

    assert translator.translate(["one"], "en", "es") == ["translated one"]
    assert isinstance(fake_client[0].calls[0]["text"], list)


def test_model_used_logged_once(fake_client, caplog):
    translator = DeeplApi("key")

    with caplog.at_level(logging.INFO, logger="srtranslator"):
        translator.translate_single("one", "en", "es")
        translator.translate_single("two", "en", "es")

    assert sum("DeepL model used" in r.message for r in caplog.records) == 1


def test_quit_without_any_call_does_not_raise(fake_client):
    DeeplApi("key").quit()


def test_stray_xml_characters_are_escaped_in_text_and_context(fake_client):
    """In XML mode DeepL parses text and context; a bare "&" failed the whole request."""
    ad = "AI translation & ad-free subs"
    DeeplApi("key").translate_batch([ad, "3 < 5", "<i>Tom & Jerry</i>"], "nl", "fi", ad)

    call = fake_client[0].calls[0]
    assert call["text"] == [
        "AI translation &amp; ad-free subs",
        "3 &lt; 5",
        "<i>Tom &amp; Jerry</i>",
    ]
    assert call["context"] == "AI translation &amp; ad-free subs"


def test_existing_xml_entities_are_left_alone_but_html_ones_are_escaped(fake_client):
    DeeplApi("key").translate_single("a &amp; b &#233; &nbsp; c", "en", "fi")

    assert fake_client[0].calls[0]["text"] == "a &amp; b &#233; &amp;nbsp; c"


def test_result_entities_are_unescaped(fake_client, monkeypatch):
    """DeepL returns XML-escaped text, including a plain ">" as "&gt;"."""
    monkeypatch.setattr(
        FakeClient,
        "translate_text",
        lambda self, text, **kwargs: [FakeTextResult("<i>3 &lt; 5 &gt; 1</i> &amp; &quot;x&quot;")],
    )

    assert DeeplApi("key").translate_batch(["x"], "en", "fi") == ['<i>3 < 5 > 1</i> & "x"']


def test_no_escaping_without_xml_tag_handling(fake_client):
    DeeplApi("key", tag_handling=None).translate_single("a & b < c", "en", "fi")

    assert fake_client[0].calls[0]["text"] == "a & b < c"
