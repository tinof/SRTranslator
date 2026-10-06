"""A backend that answers from a canned list instead of calling a model.

Used by the test suite and by ``--proofread-backend fake``, which exercises the
whole CLI path, the guards and the report without a network call.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import BackendError, BackendResponse, BackendUsage


class FakeBackend:
    name = "fake"

    def __init__(
        self,
        patches: list[dict[str, Any]] | None = None,
        *,
        model: str = "fake-model",
        usage: BackendUsage | None = None,
        error: Exception | None = None,
        responses: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        self.model = model
        self._patches = patches or []
        self._responses = responses
        self._usage = usage or BackendUsage(prompt_tokens=1000, output_tokens=100)
        self._error = error
        self.calls: list[dict[str, Any]] = []
        self.caches: list[str] = []

    @classmethod
    def from_file(cls, path: str, **kwargs: Any) -> FakeBackend:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            payload = payload.get("patches", [])
        return cls(payload, **kwargs)

    def review(
        self,
        system_instruction: str,
        user_content: str,
        *,
        response_schema: Any,
        cached_content: str | None = None,
    ) -> BackendResponse:
        index = len(self.calls)
        self.calls.append(
            {
                "system_instruction": system_instruction,
                "user_content": user_content,
                "cached_content": cached_content,
            }
        )
        if self._error is not None:
            raise BackendError(str(self._error)) from self._error

        if self._responses is not None:
            patches = self._responses[index] if index < len(self._responses) else []
        else:
            patches = self._patches

        return BackendResponse(
            patches=list(patches),
            usage=self._usage,
            model=self.model,
            raw_text=json.dumps({"patches": patches}, ensure_ascii=False),
        )

    def create_cached_prefix(
        self, system_instruction: str, prefix_text: str, ttl_seconds: int
    ) -> str | None:
        name = f"fake-cache-{len(self.caches)}"
        self.caches.append(name)
        return name

    def delete_cached_prefix(self, name: str) -> None:
        if name in self.caches:
            self.caches.remove(name)
