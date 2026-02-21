"""Termination evaluator for done signal detection."""

from dataclasses import dataclass

from loop_library.models.finding import Finding
from loop_library.models.outcome import Outcome


@dataclass
class TerminationResult:
    """Result of termination evaluation."""

    should_terminate: bool
    outcome: Outcome | None
    reason: str


class TerminationEvaluator:
    """Evaluates whether a loop should terminate.

    Checks in order:
    1. Bounds: iteration >= max_iterations -> BOUNDED
    2. Confidence: delta < threshold for 2+ cycles -> COMPLETE
    3. Saturation: no new findings -> SATURATED
    """

    def __init__(
        self,
        *,
        confidence_threshold: float = 0.8,
        confidence_delta_threshold: float = 0.05,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.confidence_delta_threshold = confidence_delta_threshold

    def evaluate(
        self,
        findings: list[Finding],
        iteration: int,
        max_iterations: int,
        confidence_history: list[float],
        previous_finding_count: int = 0,
    ) -> TerminationResult:
        """Evaluate whether the loop should terminate."""
        # Check 1: Bounds
        if iteration >= max_iterations:
            return TerminationResult(
                should_terminate=True,
                outcome=Outcome.BOUNDED,
                reason=f"Reached maximum iterations ({max_iterations})",
            )

        # Check 2: Confidence convergence
        if len(confidence_history) >= 2:
            current = confidence_history[-1]
            previous = confidence_history[-2]
            delta = abs(current - previous)

            if delta < self.confidence_delta_threshold:
                if current >= self.confidence_threshold:
                    return TerminationResult(
                        should_terminate=True,
                        outcome=Outcome.COMPLETE,
                        reason=f"Confidence converged at {current:.2f} (delta={delta:.3f})",
                    )
                if len(confidence_history) >= 3:
                    prev_delta = abs(confidence_history[-2] - confidence_history[-3])
                    if prev_delta < self.confidence_delta_threshold:
                        return TerminationResult(
                            should_terminate=True,
                            outcome=Outcome.INCONCLUSIVE,
                            reason=f"Confidence stalled at {current:.2f} for 2+ iterations",
                        )

        # Check 3: Saturation
        current_finding_count = len(findings)
        if iteration > 1 and current_finding_count <= previous_finding_count:
            return TerminationResult(
                should_terminate=True,
                outcome=Outcome.SATURATED,
                reason="No new findings discovered",
            )

        return TerminationResult(
            should_terminate=False,
            outcome=None,
            reason="Continue research",
        )

    def calculate_confidence(
        self,
        findings: list[Finding],
        sources_count: int,
        has_answer: bool = False,
    ) -> float:
        """Calculate confidence score based on findings quality."""
        if not findings:
            return 0.0

        base = 0.3
        finding_boost = min(0.2, len(findings) * 0.05)
        source_boost = min(0.2, sources_count * 0.04)
        answer_boost = 0.2 if has_answer else 0.0
        avg_finding_confidence = sum(f.confidence for f in findings) / len(findings)
        confidence_boost = avg_finding_confidence * 0.1

        return min(1.0, base + finding_boost + source_boost + answer_boost + confidence_boost)
