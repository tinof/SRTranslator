"""Bilingual proof-reading of a finished translation.

A machine translator sees a few lines at a time. It cannot tell which sense of an
ambiguous word this scene calls for, whether an idiom should be carried over, or
whether two characters have been addressing each other formally all along. This
stage reads the whole programme in both languages at once and proposes
corrections only where the meaning came out wrong.

Every correction is checked in code before it is allowed anywhere near the file:
it must quote the text it is replacing, keep the speaker turns, the numbers and
the negations, and fit in the time the cue is on screen.
"""

from .document import (
    ProofreadAlignmentError,
    ProofreadCue,
    ProofreadDocument,
    document_from_pair,
    document_from_srt_file,
)
from .engine import (
    ProofreadOptions,
    ProofreadResult,
    proofread_pair,
    proofread_srt_file,
    run_proofread,
)
from .models import (
    BackendError,
    BackendUnavailable,
    BackendUsage,
    Patch,
    ProofreadError,
    RejectedPatch,
)

__all__ = [
    "BackendError",
    "BackendUnavailable",
    "BackendUsage",
    "Patch",
    "ProofreadAlignmentError",
    "ProofreadCue",
    "ProofreadDocument",
    "ProofreadError",
    "ProofreadOptions",
    "ProofreadResult",
    "RejectedPatch",
    "document_from_pair",
    "document_from_srt_file",
    "proofread_pair",
    "proofread_srt_file",
    "run_proofread",
]
