"""Model backends for the proof-reading stage."""

from .base import ProofreadBackend
from .fake import FakeBackend

__all__ = ["FakeBackend", "ProofreadBackend"]
