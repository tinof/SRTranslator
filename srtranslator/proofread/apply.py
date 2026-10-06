"""Turn a model's proposed patches into a decision about each cue.

Nothing is written here. The caller gets the accepted and rejected lists and
decides what to do with them, so a dry run and a real run take exactly the same
path up to this point.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import guards
from .document import ProofreadDocument
from .models import Patch, RejectedPatch, severity_rank

#: However short the programme, this many corrections never trip the change cap.
MIN_PATCHES_ALLOWED = 3


@dataclass
class ApplyDecision:
    accepted: list[Patch] = field(default_factory=list)
    rejected: list[RejectedPatch] = field(default_factory=list)
    aborted: bool = False
    abort_reason: str = ""


def _dedupe(patches: list[Patch], rejected: list[RejectedPatch]) -> list[Patch]:
    """One patch per cue: the most severe wins, the rest are recorded.

    A model asked to review a whole programme sometimes reports the same cue
    twice from two angles. Applying both in turn would make the second one fail
    its own precondition, which reads as a mysterious rejection in the report.
    """
    best: dict[int, Patch] = {}
    losers: list[Patch] = []

    for patch in patches:
        current = best.get(patch.id)
        if current is None:
            best[patch.id] = patch
            continue
        if severity_rank(patch.severity) > severity_rank(current.severity):
            best[patch.id] = patch
            losers.append(current)
        else:
            losers.append(patch)

    for patch in losers:
        rejected.append(RejectedPatch(patch, "duplicate_id"))

    return [best[key] for key in sorted(best)]


def decide(
    document: ProofreadDocument,
    patches: list[Patch],
    *,
    min_severity: str = "minor",
    max_growth: float = 0.25,
    target_cps: float = 17.0,
    max_change_fraction: float = 0.30,
) -> ApplyDecision:
    """Run every guard over every patch and report what survives."""
    decision = ApplyDecision()
    by_id = document.by_id()

    for raw in _dedupe(patches, decision.rejected):
        # Guard and apply the same string. Tidying after validation would mean the
        # checks below ran against text that is not what reaches the subtitle.
        patch = replace(raw, after=guards.canonical(raw.after))

        cue = by_id.get(patch.id)
        if cue is None:
            decision.rejected.append(RejectedPatch(patch, "unknown_id"))
            continue

        reason = (
            guards.check_severity(patch, min_severity)
            or guards.check_no_change(patch)
            or guards.check_precondition(patch, cue)
            or guards.check_structure(patch, cue)
            or guards.check_numbers(patch)
            or guards.check_negation(patch)
            or guards.check_length(patch, cue, max_growth, target_cps)
            or guards.check_sanity(patch)
        )

        if reason:
            decision.rejected.append(RejectedPatch(patch, reason))
        else:
            decision.accepted.append(patch)

    total = len(document.cues)
    if total and max_change_fraction > 0:
        fraction = len(decision.accepted) / total
        # A handful of corrections is always allowed. Without this floor a short
        # file could never be corrected at all, because one patch in five cues is
        # already 20% of the programme.
        allowance = max(MIN_PATCHES_ALLOWED, total * max_change_fraction)
        if len(decision.accepted) > allowance:
            # A review that rewrites a third of the programme is not correcting
            # mistranslations any more, whatever it says in its reasons. Refuse
            # the whole batch rather than let a style rewrite through cue by cue.
            decision.aborted = True
            decision.abort_reason = (
                f"{len(decision.accepted)} of {total} cues patched "
                f"({fraction:.0%} > {max_change_fraction:.0%} limit)"
            )
            for patch in decision.accepted:
                decision.rejected.append(RejectedPatch(patch, "change_cap_exceeded"))
            decision.accepted = []

    return decision
