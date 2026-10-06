"""Gemini backend, on Vertex AI or the Gemini Developer API.

google-genai is imported inside the functions that need it, so importing this
module to ask whether credentials exist does not require the optional extra.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from typing import Any

from ..models import BackendError, BackendResponse, BackendUnavailable, BackendUsage

LOG = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_THINKING_LEVEL = "medium"
DEFAULT_LOCATION = "global"

#: Vertex answers a burst against its shared quota with these rather than with a
#: queue, so a run without retries loses whole batches at random.
RETRYABLE_MARKERS = (
    "429",
    "RESOURCE_EXHAUSTED",
    "503",
    "UNAVAILABLE",
    "500",
    "INTERNAL",
    "DEADLINE_EXCEEDED",
)

_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def use_vertex() -> bool:
    return _truthy(os.environ.get("GEMINI_USE_VERTEX")) or _truthy(
        os.environ.get("GOOGLE_GENAI_USE_VERTEXAI")
    )


def api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def credentials_available() -> bool:
    """Whether a Gemini call could be made at all, without making one."""
    if use_vertex():
        return bool(os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("VERTEX_PROJECT"))
    return bool(api_key())


def sdk_available() -> bool:
    import importlib.util

    try:
        # find_spec raises rather than returning None when the parent namespace
        # package is itself missing, which is the ordinary case on an install
        # without the proofread extra.
        return importlib.util.find_spec("google.genai") is not None
    except (ImportError, AttributeError, ValueError):
        return False


def default_model() -> str:
    return os.environ.get("SRTRANSLATOR_PROOFREAD_MODEL") or DEFAULT_MODEL


def default_thinking_level() -> str:
    return os.environ.get("GEMINI_THINKING_LEVEL") or DEFAULT_THINKING_LEVEL


def _is_retryable(error: Exception) -> bool:
    text = f"{type(error).__name__}: {error}"
    return any(marker in text for marker in RETRYABLE_MARKERS)


class GeminiBackend:
    """One configured reviewing model."""

    name = "gemini"

    def __init__(
        self,
        client: Any,
        model: str = DEFAULT_MODEL,
        *,
        thinking_level: str = DEFAULT_THINKING_LEVEL,
        temperature: float = 0.2,
        max_output_tokens: int = 16_384,
        max_retries: int = 5,
    ) -> None:
        self._client = client
        self.model = model
        self.thinking_level = thinking_level
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.max_retries = max_retries

    @classmethod
    def from_env(
        cls,
        model: str | None = None,
        *,
        thinking_level: str | None = None,
        **kwargs: Any,
    ) -> GeminiBackend:
        """Build a backend from the ambient Google credentials.

        Raises:
            BackendUnavailable: google-genai is not installed, or nothing in the
                environment says how to authenticate.
        """
        try:
            from google import genai
        except ImportError as error:
            raise BackendUnavailable(
                "google-genai is not installed. Install the extra with: "
                'uv tool install "srtranslator[proofread]"'
            ) from error

        if use_vertex():
            project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("VERTEX_PROJECT")
            if not project:
                raise BackendUnavailable(
                    "GEMINI_USE_VERTEX is set but GOOGLE_CLOUD_PROJECT is not."
                )
            location = (
                os.environ.get("GOOGLE_CLOUD_LOCATION")
                or os.environ.get("VERTEX_LOCATION")
                or DEFAULT_LOCATION
            )
            try:
                client = genai.Client(vertexai=True, project=project, location=location)
            except Exception as error:  # noqa: BLE001 - auth failures are untyped
                raise BackendUnavailable(f"Could not reach Vertex AI: {error}") from error
            LOG.debug(
                "Proof-reading through Vertex AI (project=%s, location=%s)", project, location
            )
        else:
            key = api_key()
            if not key:
                raise BackendUnavailable(
                    "No Gemini credentials. Set GEMINI_API_KEY, or set GEMINI_USE_VERTEX=1 "
                    "with GOOGLE_CLOUD_PROJECT and application default credentials."
                )
            try:
                client = genai.Client(api_key=key)
            except Exception as error:  # noqa: BLE001 - client errors are untyped
                raise BackendUnavailable(f"Could not build a Gemini client: {error}") from error
            LOG.debug("Proof-reading through the Gemini Developer API")

        return cls(
            client,
            model=model or default_model(),
            thinking_level=thinking_level or default_thinking_level(),
            **kwargs,
        )

    def _config(self, system_instruction: str, response_schema: Any, cached_content: str | None):
        from google.genai import types

        settings: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema": response_schema,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            # thinking_level, never thinking_budget: sending both is an error,
            # and the budget form is not accepted by the Gemini 3 models.
            "thinking_config": types.ThinkingConfig(thinking_level=self.thinking_level),
        }
        if cached_content:
            # The cached prefix already carries the instruction.
            settings["cached_content"] = cached_content
        else:
            settings["system_instruction"] = system_instruction

        return types.GenerateContentConfig(**settings)

    def review(
        self,
        system_instruction: str,
        user_content: str,
        *,
        response_schema: Any,
        cached_content: str | None = None,
    ) -> BackendResponse:
        config = self._config(system_instruction, response_schema, cached_content)
        response = self._call(user_content, config)
        return self._decode(response)

    def _call(self, user_content: str, config: Any):
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                return self._client.models.generate_content(
                    model=self.model, contents=user_content, config=config
                )
            except Exception as error:  # noqa: BLE001 - provider errors are untyped
                last_error = error
                if not _is_retryable(error) or attempt == self.max_retries - 1:
                    break
                delay = min(30.0, 2.0 * (2**attempt)) + random.uniform(0, 1)
                LOG.warning(
                    "Proof-reading call failed (%s), retrying in %.1fs", type(error).__name__, delay
                )
                time.sleep(delay)

        raise BackendError(f"Gemini call failed: {last_error}") from last_error

    def _decode(self, response: Any) -> BackendResponse:
        usage = self._usage(response)
        raw_text = getattr(response, "text", "") or ""

        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            payload = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed
        elif raw_text.strip():
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError as error:
                raise BackendError(f"Gemini returned text that is not JSON: {error}") from error
        else:
            reason = ""
            for candidate in getattr(response, "candidates", None) or []:
                reason = str(getattr(candidate, "finish_reason", "") or "")
                break
            raise BackendError(f"Gemini returned an empty response (finish_reason={reason or '?'})")

        # An answer that does not carry a patches field is a failed call, not a
        # clean review. Defaulting to an empty list reported quota errors and
        # bare objects as successful reviews that found nothing.
        if not isinstance(payload, dict) or "patches" not in payload:
            summary = raw_text.strip()[:200] or type(payload).__name__
            raise BackendError(f"Gemini returned no 'patches' field: {summary}")

        patches = payload["patches"]
        if not isinstance(patches, list):
            raise BackendError("Gemini returned a 'patches' field that is not a list")

        return BackendResponse(patches=patches, usage=usage, model=self.model, raw_text=raw_text)

    @staticmethod
    def _usage(response: Any) -> BackendUsage:
        metadata = getattr(response, "usage_metadata", None)
        if metadata is None:
            return BackendUsage()

        def count(field: str) -> int:
            return int(getattr(metadata, field, 0) or 0)

        return BackendUsage(
            prompt_tokens=count("prompt_token_count"),
            output_tokens=count("candidates_token_count"),
            thoughts_tokens=count("thoughts_token_count"),
            cached_tokens=count("cached_content_token_count"),
        )

    def create_cached_prefix(
        self, system_instruction: str, prefix_text: str, ttl_seconds: int
    ) -> str | None:
        from google.genai import types

        try:
            cache = self._client.caches.create(
                model=self.model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_instruction,
                    contents=[prefix_text],
                    ttl=f"{ttl_seconds}s",
                ),
            )
        except Exception as error:  # noqa: BLE001 - caching is an optimisation
            LOG.warning("Could not cache the transcript, continuing without it: %s", error)
            return None
        return getattr(cache, "name", None)

    def delete_cached_prefix(self, name: str) -> None:
        try:
            self._client.caches.delete(name=name)
        except Exception as error:  # noqa: BLE001
            LOG.debug("Could not delete cache %s: %s", name, error)
