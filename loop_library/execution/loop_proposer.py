"""Loop proposer - proposes new loop types for complex tasks (Phase 3B)."""

import json
import logging

from loop_library.models.loop_proposal import (
    LoopPhase,
    LoopProposal,
    LoopProposalValidation,
)
from loop_library.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)

SCIENTIFIC_METHOD_PHASES = {
    "hypothesize": ["hypothesize", "hypothesis", "conjecture", "propose", "theorize"],
    "gather": ["gather", "collect", "search", "find", "research", "investigate"],
    "analyze": ["analyze", "examine", "evaluate", "assess", "compare", "test"],
    "synthesize": ["synthesize", "summarize", "conclude", "integrate", "combine"],
}

KNOWN_INSTRUMENTS = {"note", "research", "synthesis", "vision"}

PROPOSAL_PROMPT = """You are a loop architect for Loop Symphony, an autonomous research system.

Your task is to design a NEW loop type for a task that doesn't fit existing instruments.

## Existing Instruments (can be used in phases)
- **note**: Simple single-pass response (1 iteration)
- **research**: Iterative web research using scientific method (up to 5 iterations)
- **synthesis**: Merge multiple inputs into coherent output (up to 2 iterations)
- **vision**: Analyze images (up to 3 iterations)

## Scientific Method Requirement
All loops MUST follow scientific method principles.

## Phase Actions
- `instrument`: Use an existing instrument
- `prompt`: Execute a custom prompt
- `spawn`: Spawn a sub-task

## Your Task
Design a loop for this query:

QUERY: {query}

Respond with a JSON object:
{{
    "name": "loop_name_in_snake_case",
    "description": "What this loop is designed for",
    "phases": [...],
    "termination_criteria": "How we know when complete",
    "max_total_iterations": 10,
    "required_capabilities": ["reasoning"],
    "scientific_method_phases": ["hypothesize", "gather", "analyze", "synthesize"]
}}

Respond ONLY with the JSON object."""


class LoopProposer:
    """Proposes new loop types for complex tasks."""

    def __init__(self, claude: ClaudeClient) -> None:
        self.claude = claude

    def _parse_response(self, response: str) -> LoopProposal:
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse loop proposal JSON: {e}")
            return LoopProposal(
                name="fallback_research",
                description="Fallback: could not parse proposal",
                phases=[
                    LoopPhase(name="research", description="Research the topic",
                              action="instrument", instrument="research"),
                    LoopPhase(name="synthesize", description="Synthesize findings",
                              action="instrument", instrument="synthesis"),
                ],
                termination_criteria="Research and synthesis complete",
                scientific_method_phases=["gather", "synthesize"],
            )

        if data.get("phases"):
            data["phases"] = [LoopPhase(**p) for p in data["phases"]]

        return LoopProposal(**data)

    async def propose(self, query: str) -> LoopProposal:
        prompt = PROPOSAL_PROMPT.format(query=query)
        logger.info(f"Proposing loop for: {query[:50]}...")

        response = await self.claude.complete(
            prompt=prompt,
            system="You are a precise JSON generator. Output only valid JSON.",
        )

        proposal = self._parse_response(response)
        logger.info(f"Proposed loop '{proposal.name}' with {len(proposal.phases)} phases")
        return proposal

    def _check_scientific_method_coverage(self, proposal: LoopProposal) -> dict[str, bool]:
        coverage = {phase: False for phase in SCIENTIFIC_METHOD_PHASES}
        for phase in proposal.phases:
            phase_text = f"{phase.name} {phase.description}".lower()
            for method_phase, keywords in SCIENTIFIC_METHOD_PHASES.items():
                if any(kw in phase_text for kw in keywords):
                    coverage[method_phase] = True
        for declared_phase in proposal.scientific_method_phases:
            if declared_phase in coverage:
                coverage[declared_phase] = True
        return coverage

    def validate(self, proposal: LoopProposal) -> LoopProposalValidation:
        errors: list[str] = []
        warnings: list[str] = []

        if len(proposal.phases) < 2:
            errors.append("Loop must have at least 2 phases")

        for i, phase in enumerate(proposal.phases):
            if phase.action == "instrument":
                if not phase.instrument:
                    errors.append(f"Phase {i+1} ({phase.name}): instrument action requires instrument field")
                elif phase.instrument not in KNOWN_INSTRUMENTS:
                    errors.append(f"Phase {i+1} ({phase.name}): unknown instrument '{phase.instrument}'")
            elif phase.action == "prompt":
                if not phase.prompt_template:
                    errors.append(f"Phase {i+1} ({phase.name}): prompt action requires prompt_template field")

        coverage = self._check_scientific_method_coverage(proposal)
        uncovered = [phase for phase, covered in coverage.items() if not covered]

        if len(uncovered) >= 3:
            errors.append(f"Insufficient scientific method coverage. Missing: {uncovered}")
        elif uncovered:
            warnings.append(f"Partial scientific method coverage. Could add: {uncovered}")

        if not proposal.termination_criteria or len(proposal.termination_criteria) < 10:
            warnings.append("Termination criteria should be more specific")

        if proposal.max_total_iterations > 20:
            errors.append("max_total_iterations cannot exceed 20")
        elif proposal.max_total_iterations > 15:
            warnings.append("High iteration count may cause long execution times")

        if "reasoning" not in proposal.required_capabilities:
            warnings.append("Most loops require 'reasoning' capability")

        return LoopProposalValidation(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            scientific_method_coverage=coverage,
        )

    def get_execution_estimate(self, proposal: LoopProposal) -> dict[str, int]:
        total_iterations = sum(p.max_iterations for p in proposal.phases)
        total_iterations = min(total_iterations, proposal.max_total_iterations)
        estimated_seconds = total_iterations * 5
        return {
            "estimated_iterations": total_iterations,
            "estimated_duration_seconds": estimated_seconds,
        }
