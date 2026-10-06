"""The JSON schema the model must answer with.

This is the only module that needs pydantic, and it is imported lazily so the
rest of the package works without the ``proofread`` extra installed.

The shapes stay deliberately plain (str, int and Literal only, no defaults and no
unions) because that is the subset google-genai converts to a Gemini response
schema without surprises.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .models import Patch


class Patch_(BaseModel):
    """One correction. Named with a trailing underscore to leave the plain
    dataclass in models.py holding the public name."""

    id: int = Field(description="The [id] of the cue this correction applies to.")
    before: str = Field(description="The current translation of that cue, copied exactly.")
    after: str = Field(description="The corrected translation.")
    category: Literal[
        "mistranslation",
        "wrong_sense",
        "omission",
        "idiom",
        "address_form",
        "consistency",
        "gender_number",
    ] = Field(description="Which kind of meaning problem this is.")
    severity: Literal["minor", "major", "critical"] = Field(
        description="How much the problem changes what the viewer understands."
    )
    source_evidence: str = Field(
        description="The words in the original that show the current translation is wrong."
    )
    reason: str = Field(description="One sentence explaining the correction.")


class ProofreadResponse(BaseModel):
    """The whole answer: every cue that needs a correction, and nothing else."""

    patches: list[Patch_] = Field(
        description="Corrections, one per cue. Empty when the translation is sound."
    )


def response_schema() -> type[BaseModel]:
    return ProofreadResponse


def parse_response(raw: Any) -> list[Patch]:
    """Validate a decoded model answer and return plain patches.

    Raises:
        ValueError: the answer does not match the schema. The caller rejects the
            whole response rather than applying a partially understood one.
    """
    try:
        validated = ProofreadResponse.model_validate(raw)
    except ValidationError as error:
        raise ValueError(f"response does not match the proof-reading schema: {error}") from error

    return [
        Patch(
            id=item.id,
            before=item.before,
            after=item.after,
            category=item.category,
            severity=item.severity,
            source_evidence=item.source_evidence,
            reason=item.reason,
        )
        for item in validated.patches
    ]
