"""Base instrument protocol and types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from loop_symphony.models.finding import Finding
from loop_symphony.models.outcome import Outcome
from loop_symphony.models.task import TaskContext


@dataclass
class InstrumentResult:
    """Result from instrument execution."""

    outcome: Outcome
    findings: list[Finding]
    summary: str
    confidence: float
    iterations: int
    sources_consulted: list[str] = field(default_factory=list)
    discrepancy: str | None = None
    suggested_followups: list[str] = field(default_factory=list)


class BaseInstrument(ABC):
    """Base class for all instruments.

    Instruments are the execution units that process queries
    using different strategies (atomic, iterative, etc.).
    """

    name: str
    max_iterations: int
    required_capabilities: frozenset[str]
    optional_capabilities: frozenset[str] = frozenset()

    @abstractmethod
    async def execute(
        self,
        query: str,
        context: TaskContext | None = None,
    ) -> InstrumentResult:
        """Execute the instrument on a query.

        Args:
            query: The user's query to process
            context: Optional context about the user/conversation

        Returns:
            InstrumentResult with findings and metadata
        """
        ...
