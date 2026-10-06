"""What the proof-reading engine needs from a model."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..models import BackendResponse


@runtime_checkable
class ProofreadBackend(Protocol):
    """One reviewing model, already configured with its generation settings."""

    name: str
    model: str

    def review(
        self,
        system_instruction: str,
        user_content: str,
        *,
        response_schema: Any,
        cached_content: str | None = None,
    ) -> BackendResponse:
        """Ask for corrections and return the decoded patches plus token usage.

        Raises:
            BackendError: the call failed after the backend's own retries.
        """
        ...

    def create_cached_prefix(
        self, system_instruction: str, prefix_text: str, ttl_seconds: int
    ) -> str | None:
        """Store a reusable prompt prefix, or return None if unsupported."""
        ...

    def delete_cached_prefix(self, name: str) -> None:
        """Release a prefix created by create_cached_prefix."""
        ...
