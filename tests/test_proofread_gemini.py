import pytest

from srtranslator.proofread.backends import gemini
from srtranslator.proofread.models import BackendError, BackendUnavailable

pytest.importorskip("google.genai")


class FakeUsage:
    prompt_token_count = 24_000
    candidates_token_count = 900
    thoughts_token_count = 4_100
    cached_content_token_count = 0


class FakeResponse:
    def __init__(self, text="", parsed=None):
        self.text = text
        self.parsed = parsed
        self.usage_metadata = FakeUsage()
        self.candidates = []


class FakeModels:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate_content(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        outcome = self._responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, responses, **kwargs):
        self.models = FakeModels(responses)
        self.kwargs = kwargs


@pytest.fixture
def clear_env(monkeypatch):
    for name in (
        "GEMINI_USE_VERTEX",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_CLOUD_PROJECT",
        "VERTEX_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "VERTEX_LOCATION",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "SRTRANSLATOR_PROOFREAD_MODEL",
        "GEMINI_THINKING_LEVEL",
    ):
        monkeypatch.delenv(name, raising=False)


def install_fake_client(monkeypatch, responses):
    recorded = {}

    def factory(**kwargs):
        recorded.update(kwargs)
        return FakeClient(responses, **kwargs)

    from google import genai

    monkeypatch.setattr(genai, "Client", factory)
    return recorded


def test_from_env_prefers_vertex(monkeypatch, clear_env):
    monkeypatch.setenv("GEMINI_USE_VERTEX", "True")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    recorded = install_fake_client(monkeypatch, [])

    backend = gemini.GeminiBackend.from_env()

    assert recorded == {"vertexai": True, "project": "my-project", "location": "global"}
    assert backend.model == gemini.DEFAULT_MODEL
    assert backend.thinking_level == "medium"


def test_from_env_falls_back_to_an_api_key(monkeypatch, clear_env):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("SRTRANSLATOR_PROOFREAD_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "low")
    recorded = install_fake_client(monkeypatch, [])

    backend = gemini.GeminiBackend.from_env()

    assert recorded == {"api_key": "secret"}
    assert backend.model == "gemini-3.5-flash-lite"
    assert backend.thinking_level == "low"


def test_from_env_without_credentials_is_unavailable(monkeypatch, clear_env):
    install_fake_client(monkeypatch, [])
    with pytest.raises(BackendUnavailable):
        gemini.GeminiBackend.from_env()


def test_vertex_without_a_project_is_unavailable(monkeypatch, clear_env):
    monkeypatch.setenv("GEMINI_USE_VERTEX", "1")
    install_fake_client(monkeypatch, [])
    with pytest.raises(BackendUnavailable) as error:
        gemini.GeminiBackend.from_env()
    assert "GOOGLE_CLOUD_PROJECT" in str(error.value)


def test_credentials_available_reads_the_environment(monkeypatch, clear_env):
    assert gemini.credentials_available() is False
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    assert gemini.credentials_available() is True
    monkeypatch.setenv("GEMINI_USE_VERTEX", "1")
    assert gemini.credentials_available() is False
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    assert gemini.credentials_available() is True


def test_review_decodes_json_and_token_usage():
    client = FakeClient([FakeResponse(text='{"patches": [{"id": 1}]}')])
    backend = gemini.GeminiBackend(client, model="gemini-3.8-flash")

    response = backend.review("system", "content", response_schema=dict)

    assert response.patches == [{"id": 1}]
    assert response.usage.prompt_tokens == 24_000
    assert response.usage.thoughts_tokens == 4_100
    config = client.models.calls[0]["config"]
    # The SDK normalises the level to its own enum.
    assert str(config.thinking_config.thinking_level.value).lower() == "medium"
    assert config.system_instruction == "system"


def test_review_retries_a_quota_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda _seconds: None)
    client = FakeClient(
        [
            RuntimeError("429 RESOURCE_EXHAUSTED"),
            FakeResponse(text='{"patches": []}'),
        ]
    )
    backend = gemini.GeminiBackend(client)

    response = backend.review("system", "content", response_schema=dict)

    assert response.patches == []
    assert len(client.models.calls) == 2


def test_review_gives_up_on_an_error_that_will_not_pass(monkeypatch):
    monkeypatch.setattr(gemini.time, "sleep", lambda _seconds: None)
    client = FakeClient([ValueError("400 INVALID_ARGUMENT")])
    backend = gemini.GeminiBackend(client)

    with pytest.raises(BackendError):
        backend.review("system", "content", response_schema=dict)

    assert len(client.models.calls) == 1


def test_an_empty_response_is_an_error():
    backend = gemini.GeminiBackend(FakeClient([FakeResponse(text="")]))
    with pytest.raises(BackendError) as error:
        backend.review("system", "content", response_schema=dict)
    assert "empty response" in str(error.value)


def test_a_cached_prefix_replaces_the_system_instruction():
    client = FakeClient([FakeResponse(text='{"patches": []}')])
    backend = gemini.GeminiBackend(client)

    backend.review("system", "content", response_schema=dict, cached_content="caches/1")

    config = client.models.calls[0]["config"]
    assert config.cached_content == "caches/1"
    assert config.system_instruction is None


def test_sdk_available_survives_a_missing_namespace_package(monkeypatch):
    """An install without the extra has no 'google' package at all, and find_spec
    raises there instead of answering."""
    import importlib.util

    def explode(name):
        raise ModuleNotFoundError("No module named 'google'")

    monkeypatch.setattr(importlib.util, "find_spec", explode)
    assert gemini.sdk_available() is False


# --- regressions found in adversarial review -------------------------------


@pytest.mark.parametrize("payload", ["{}", "[]", '{"error": "quota exceeded"}'])
def test_a_response_without_patches_is_a_failure_not_an_empty_review(payload):
    """These were decoded as successful reviews that happened to find nothing,
    so a quota error looked like a clean subtitle."""
    backend = gemini.GeminiBackend(FakeClient([FakeResponse(text=payload)]))
    with pytest.raises(BackendError) as error:
        backend.review("system", "content", response_schema=dict)
    assert "no 'patches' field" in str(error.value)


def test_an_empty_patch_list_is_still_a_valid_review():
    backend = gemini.GeminiBackend(FakeClient([FakeResponse(text='{"patches": []}')]))
    assert backend.review("system", "content", response_schema=dict).patches == []


def test_a_client_that_cannot_authenticate_is_reported_as_unavailable(monkeypatch, clear_env):
    """google.auth raises its own exception types. Escaping from here they reached
    main()'s handler and cost the user their finished translation."""
    monkeypatch.setenv("GEMINI_USE_VERTEX", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")

    from google import genai

    def explode(**kwargs):
        raise RuntimeError("could not find default credentials")

    monkeypatch.setattr(genai, "Client", explode)

    with pytest.raises(BackendUnavailable) as error:
        gemini.GeminiBackend.from_env()
    assert "Could not reach Vertex AI" in str(error.value)
