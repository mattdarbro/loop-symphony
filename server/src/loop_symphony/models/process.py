"""Process visibility types per PRD Section 4."""

from enum import Enum


class ProcessType(str, Enum):
    """Process visibility classification.

    AUTONOMIC: Invisible to user. Single-cycle, atomic operations.
    SEMI_AUTONOMIC: Automatic but overridable. Iterative, bounded operations.
    CONSCIOUS: Full user awareness. Multi-step orchestration.
    """

    AUTONOMIC = "autonomic"
    SEMI_AUTONOMIC = "semi_autonomic"
    CONSCIOUS = "conscious"
