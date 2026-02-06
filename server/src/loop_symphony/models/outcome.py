"""Outcome enum and termination types."""

from enum import Enum


class Outcome(str, Enum):
    """Task completion outcome types.

    COMPLETE: Task finished with high confidence
    SATURATED: No new information being discovered
    BOUNDED: Hit iteration/time limits
    INCONCLUSIVE: Conflicting or unclear results
    """

    COMPLETE = "complete"
    SATURATED = "saturated"
    BOUNDED = "bounded"
    INCONCLUSIVE = "inconclusive"


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"  # Trust level 0: plan returned, waiting for approval
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
