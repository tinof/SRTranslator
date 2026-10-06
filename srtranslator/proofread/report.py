"""The record of what a proof-reading run proposed, applied and refused.

Every run writes one, including runs that changed nothing, so a translation can
always be traced back to the review that produced it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .models import BackendUsage, Patch, RejectedPatch

REPORT_VERSION = 1


@dataclass
class ProofreadReport:
    status: str
    model: str
    thinking_level: str
    prompt_digest: str
    input_path: str = ""
    source_path: str = ""
    source_lang: str = ""
    target_lang: str = ""
    cues: int = 0
    scenes: int = 0
    batches: int = 1
    estimate: dict[str, Any] = field(default_factory=dict)
    usage: BackendUsage | None = None
    cost_usd: float | None = None
    applied: list[Patch] = field(default_factory=list)
    rejected: list[RejectedPatch] = field(default_factory=list)
    error: str = ""
    abort_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": REPORT_VERSION,
            # timezone.utc, not datetime.UTC: the package still supports 3.10,
            # where the shorter alias does not exist.
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),  # noqa: UP017
            "status": self.status,
            "input": self.input_path,
            "source": self.source_path,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "model": self.model,
            "thinking_level": self.thinking_level,
            "prompt_digest": self.prompt_digest,
            "cues": self.cues,
            "scenes": self.scenes,
            "batches": self.batches,
            "estimate": self.estimate,
            "usage": None if self.usage is None else self.usage.to_dict(),
            "cost_usd": None if self.cost_usd is None else round(self.cost_usd, 4),
            "error": self.error,
            "abort_reason": self.abort_reason,
            "applied": [patch.to_dict() for patch in self.applied],
            "rejected": [item.to_dict() for item in self.rejected],
        }


def write_report(report: ProofreadReport, path: str) -> str:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path
