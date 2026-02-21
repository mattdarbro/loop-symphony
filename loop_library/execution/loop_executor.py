"""Loop executor - executes proposed loop specifications (Phase 3B)."""

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.models.finding import Finding
from loop_library.models.loop_proposal import LoopPhase, LoopProposal
from loop_library.models.outcome import Outcome
from loop_library.models.task import TaskContext, TaskRequest
from loop_library.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)


@runtime_checkable
class InstrumentProvider(Protocol):
    """Protocol for objects that provide instrument lookup and execution."""
    instruments: dict[str, BaseInstrument]

    async def execute(self, request: TaskRequest) -> object: ...


class LoopExecutor:
    """Executes proposed loop specifications."""

    def __init__(
        self,
        claude: ClaudeClient,
        conductor: InstrumentProvider,
    ) -> None:
        self.claude = claude
        self.conductor = conductor

    async def _execute_instrument_phase(
        self, phase: LoopPhase, query: str, context: TaskContext | None,
        previous_findings: list[Finding],
    ) -> InstrumentResult:
        instrument = self.conductor.instruments.get(phase.instrument)
        if instrument is None:
            raise ValueError(f"Unknown instrument: {phase.instrument}")

        input_results = None
        if previous_findings:
            input_results = [{
                "findings": [f.model_dump(mode="json") for f in previous_findings],
                "phase": "previous",
            }]

        phase_context = context.model_copy(update={
            "input_results": input_results,
        }) if context else TaskContext(input_results=input_results)

        return await instrument.execute(query, phase_context)

    async def _execute_prompt_phase(
        self, phase: LoopPhase, query: str, previous_findings: list[Finding],
    ) -> InstrumentResult:
        findings_text = ""
        if previous_findings:
            findings_text = "\n".join(
                f"- {f.content} (confidence: {f.confidence})"
                for f in previous_findings
            )

        prompt = phase.prompt_template.format(
            query=query,
            previous_findings=findings_text or "No previous findings",
            phase_name=phase.name,
        )

        response = await self.claude.complete(
            prompt=prompt,
            system=f"You are executing the '{phase.name}' phase. Be thorough and specific.",
        )

        finding = Finding(
            content=f"[{phase.name}] {response}",
            source=f"phase:{phase.name}",
            confidence=0.7,
        )

        return InstrumentResult(
            outcome=Outcome.COMPLETE,
            findings=[finding],
            summary=response[:500],
            confidence=0.7,
            iterations=1,
            sources_consulted=[f"phase:{phase.name}"],
        )

    async def _execute_spawn_phase(
        self, phase: LoopPhase, query: str, context: TaskContext | None,
        previous_findings: list[Finding],
    ) -> InstrumentResult:
        sub_query = f"{phase.description}: {query}"

        if context and context.spawn_fn:
            return await context.spawn_fn(sub_query, context)

        sub_request = TaskRequest(query=sub_query, context=context)
        response = await self.conductor.execute(sub_request)

        return InstrumentResult(
            outcome=response.outcome,
            findings=response.findings,
            summary=response.summary,
            confidence=response.confidence,
            iterations=response.metadata.iterations,
            sources_consulted=response.metadata.sources_consulted,
            discrepancy=response.discrepancy,
            suggested_followups=response.suggested_followups,
        )

    async def execute(
        self, proposal: LoopProposal, query: str, context: TaskContext | None = None,
    ) -> InstrumentResult:
        logger.info(f"Executing loop '{proposal.name}' with {len(proposal.phases)} phases")

        all_findings: list[Finding] = []
        all_sources: list[str] = []
        total_iterations = 0
        last_summary = ""
        last_confidence = 0.0

        for phase_idx, phase in enumerate(proposal.phases):
            logger.info(f"Phase {phase_idx + 1}/{len(proposal.phases)}: {phase.name}")

            if total_iterations >= proposal.max_total_iterations:
                logger.info(
                    f"Reached max iterations ({proposal.max_total_iterations}), "
                    f"stopping at phase {phase_idx + 1}"
                )
                break

            try:
                if phase.action == "instrument":
                    result = await self._execute_instrument_phase(phase, query, context, all_findings)
                elif phase.action == "prompt":
                    result = await self._execute_prompt_phase(phase, query, all_findings)
                elif phase.action == "spawn":
                    result = await self._execute_spawn_phase(phase, query, context, all_findings)
                else:
                    raise ValueError(f"Unknown phase action: {phase.action}")

                all_findings.extend(result.findings)
                all_sources.extend(result.sources_consulted)
                total_iterations += result.iterations
                last_summary = result.summary
                last_confidence = result.confidence

                logger.info(
                    f"Phase {phase.name} complete: "
                    f"{len(result.findings)} findings, "
                    f"confidence={result.confidence:.2f}"
                )

                if result.outcome == Outcome.INCONCLUSIVE:
                    logger.info(f"Early termination: phase {phase.name} was INCONCLUSIVE")
                    return InstrumentResult(
                        outcome=Outcome.INCONCLUSIVE,
                        findings=all_findings,
                        summary=f"Loop terminated early at phase '{phase.name}': {result.summary}",
                        confidence=last_confidence,
                        iterations=total_iterations,
                        sources_consulted=sorted(set(all_sources)),
                        discrepancy=result.discrepancy,
                    )

            except Exception as e:
                logger.error(f"Phase {phase.name} failed: {e}")
                return InstrumentResult(
                    outcome=Outcome.INCONCLUSIVE,
                    findings=all_findings,
                    summary=f"Loop failed at phase '{phase.name}': {str(e)}",
                    confidence=0.3,
                    iterations=total_iterations,
                    sources_consulted=sorted(set(all_sources)),
                    discrepancy=f"Phase '{phase.name}' error: {str(e)}",
                )

        if total_iterations >= proposal.max_total_iterations:
            outcome = Outcome.BOUNDED
        elif last_confidence >= 0.8:
            outcome = Outcome.COMPLETE
        else:
            outcome = Outcome.SATURATED

        return InstrumentResult(
            outcome=outcome,
            findings=all_findings,
            summary=last_summary,
            confidence=last_confidence,
            iterations=total_iterations,
            sources_consulted=sorted(set(all_sources)),
        )
