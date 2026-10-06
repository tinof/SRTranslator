"""Plain data types shared by the proof-reading stage.

Nothing here imports pydantic or google-genai, so the guards, the report and the
CLI wiring stay importable without the optional extra installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

CATEGORIES: tuple[str, ...] = (
    "mistranslation",
    "wrong_sense",
    "omission",
    "idiom",
    "address_form",
    "consistency",
    "gender_number",
)

SEVERITIES: tuple[str, ...] = ("minor", "major", "critical")

#: Categories that may legitimately change a number or a negation, because the
#: source shows the translation got it wrong.
MEANING_CATEGORIES: frozenset[str] = frozenset({"mistranslation", "wrong_sense", "gender_number"})


def severity_rank(severity: str) -> int:
    try:
        return SEVERITIES.index(severity)
    except ValueError:
        return -1


@dataclass
class Patch:
    """One proposed correction to one cue."""

    id: int
    before: str
    after: str
    category: str
    severity: str
    source_evidence: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "before": self.before,
            "after": self.after,
            "category": self.category,
            "severity": self.severity,
            "source_evidence": self.source_evidence,
            "reason": self.reason,
        }


@dataclass
class RejectedPatch:
    patch: Patch
    reason: str

    def to_dict(self) -> dict[str, Any]:
        payload = self.patch.to_dict()
        payload["rejected_reason"] = self.reason
        return payload


@dataclass
class BackendUsage:
    """Token counts as the provider reported them."""

    prompt_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    cached_tokens: int = 0

    def __add__(self, other: BackendUsage) -> BackendUsage:
        return BackendUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            thoughts_tokens=self.thoughts_tokens + other.thoughts_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "thoughts_tokens": self.thoughts_tokens,
            "cached_tokens": self.cached_tokens,
        }


@dataclass
class BackendResponse:
    """What one model call returned, before any validation."""

    patches: list[dict[str, Any]] = field(default_factory=list)
    usage: BackendUsage = field(default_factory=BackendUsage)
    model: str = ""
    raw_text: str = ""


class ProofreadError(Exception):
    """Any failure of the proof-reading stage."""


class BackendError(ProofreadError):
    """The model call itself failed."""


class BackendUnavailable(ProofreadError):
    """No usable backend: the extra is missing, or no credentials are set."""
