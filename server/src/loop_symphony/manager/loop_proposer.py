"""Loop proposer - proposes new loop types for complex tasks (Phase 3B).

Level 5 creativity: When existing instruments and compositions don't fit,
propose entirely new loop specifications with custom phases.
"""

import json
import logging
from typing import Any

from loop_symphony.models.loop_proposal import (
    LoopPhase,
    LoopProposal,
    LoopProposalValidation,
)
from loop_symphony.tools.claude import ClaudeClient

logger = logging.getLogger(__name__)

# Scientific method phases that should be covered
SCIENTIFIC_METHOD_PHASES = {
    "hypothesize": ["hypothesize", "hypothesis", "conjecture", "propose", "theorize"],
    "gather": ["gather", "collect", "search", "find", "research", "investigate"],
    "analyze": ["analyze", "examine", "evaluate", "assess", "compare", "test"],
    "synthesize": ["synthesize", "summarize", "conclude", "integrate", "combine"],
}

# Known instruments that can be used in phases
KNOWN_INSTRUMENTS = {"note", "research", "synthesis", "vision"}

PROPOSAL_PROMPT = """You are a loop architect for Loop Symphony, an autonomous research system.

Your task is to design a NEW loop type for a task that doesn't fit existing instruments.

## Existing Instruments (can be used in phases)
- **note**: Simple single-pass response (1 iteration)
- **research**: Iterative web research using scientific method (up to 5 iterations)
- **synthesis**: Merge multiple inputs into coherent output (up to 2 iterations)
- **vision**: Analyze images (up to 3 iterations)

## Scientific Method Requirement

All loops MUST follow scientific method principles. Your phases should cover:
1. **Hypothesize**: Form initial hypothesis or research question
2. **Gather**: Collect evidence, data, or information
3. **Analyze**: Evaluate and test the gathered information
4. **Synthesize**: Draw conclusions and integrate findings

## Phase Actions

Each phase can use one of these actions:
- `instrument`: Use an existing instrument (note, research, synthesis, vision)
- `prompt`: Execute a custom prompt (you define the prompt_template)
- `spawn`: Spawn a sub-task for complex sub-problems

## Prompt Templates

For `prompt` actions, use these placeholders:
- `{{query}}`: The original user query
- `{{previous_findings}}`: Findings from previous phases
- `{{phase_name}}`: Current phase name

## Your Task

Design a loop for this query:

QUERY: {query}

Respond with a JSON object:
{{
    "name": "loop_name_in_snake_case",
    "description": "What this loop is designed for",
    "phases": [
        {{
            "name": "phase_name",
            "description": "What this phase does",
            "action": "instrument" | "prompt" | "spawn",
            "instrument": "instrument_name",  // if action=instrument
            "prompt_template": "Custom prompt with {{query}}...",  // if action=prompt
            "max_iterations": 1
        }}
    ],
    "termination_criteria": "How we know when complete",
    "max_total_iterations": 10,
    "required_capabilities": ["reasoning", "web_search"],
    "scientific_method_phases": ["hypothesize", "gather", "analyze", "synthesize"]
}}

Design a loop that:
1. Has 3-6 phases covering the scientific method
2. Uses existing instruments where appropriate
3. Defines custom prompts for specialized steps
4. Has clear termination criteria
5. Stays within 10-15 total iterations

Respond ONLY with the JSON object."""


class LoopProposer:
    """Proposes new loop types for complex tasks.

    Uses Claude to analyze tasks and design custom loop specifications
    when existing instruments don't fit.
    """

    def __init__(self, claude: ClaudeClient) -> None:
        self.claude = claude

    def _parse_response(self, response: str) -> LoopProposal:
        """Parse Claude's JSON response into a LoopProposal."""
        text = response.strip()

        # Handle markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse loop proposal JSON: {e}")
            # Return a fallback proposal
            return LoopProposal(
                name="fallback_research",
                description="Fallback: could not parse proposal",
                phases=[
                    LoopPhase(
                        name="research",
                        description="Research the topic",
                        action="instrument",
                        instrument="research",
                    ),
                    LoopPhase(
                        name="synthesize",
                        description="Synthesize findings",
                        action="instrument",
                        instrument="synthesis",
                    ),
                ],
                termination_criteria="Research and synthesis complete",
                scientific_method_phases=["gather", "synthesize"],
            )

        # Convert phases
        if data.get("phases"):
            data["phases"] = [LoopPhase(**p) for p in data["phases"]]

        return LoopProposal(**data)

    async def propose(self, query: str) -> LoopProposal:
        """Propose a new loop type for a query.

        Args:
            query: The user's task query

        Returns:
            LoopProposal with custom loop specification
        """
        prompt = PROPOSAL_PROMPT.format(query=query)

        logger.info(f"Proposing loop for: {query[:50]}...")

        response = await self.claude.complete(
            prompt=prompt,
            system="You are a precise JSON generator. Output only valid JSON.",
        )

        proposal = self._parse_response(response)

        logger.info(
            f"Proposed loop '{proposal.name}' with {len(proposal.phases)} phases"
        )

        return proposal

    def _check_scientific_method_coverage(
        self, proposal: LoopProposal
    ) -> dict[str, bool]:
        """Check which scientific method phases are covered."""
        coverage = {phase: False for phase in SCIENTIFIC_METHOD_PHASES}

        # Check phase names and descriptions for scientific method keywords
        for phase in proposal.phases:
            phase_text = f"{phase.name} {phase.description}".lower()
            for method_phase, keywords in SCIENTIFIC_METHOD_PHASES.items():
                if any(kw in phase_text for kw in keywords):
                    coverage[method_phase] = True

        # Also check the declared scientific_method_phases
        for declared_phase in proposal.scientific_method_phases:
            if declared_phase in coverage:
                coverage[declared_phase] = True

        return coverage

    def validate(self, proposal: LoopProposal) -> LoopProposalValidation:
        """Validate a loop proposal.

        Checks:
        - At least 2 phases
        - Scientific method coverage
        - Valid instruments referenced
        - Termination criteria present
        - Iteration bounds

        Args:
            proposal: The loop proposal to validate

        Returns:
            LoopProposalValidation with errors and warnings
        """
        errors: list[str] = []
        warnings: list[str] = []

        # Check phase count
        if len(proposal.phases) < 2:
            errors.append("Loop must have at least 2 phases")

        # Check each phase
        for i, phase in enumerate(proposal.phases):
            if phase.action == "instrument":
                if not phase.instrument:
                    errors.append(f"Phase {i+1} ({phase.name}): instrument action requires instrument field")
                elif phase.instrument not in KNOWN_INSTRUMENTS:
                    errors.append(f"Phase {i+1} ({phase.name}): unknown instrument '{phase.instrument}'")
            elif phase.action == "prompt":
                if not phase.prompt_template:
                    errors.append(f"Phase {i+1} ({phase.name}): prompt action requires prompt_template field")
            # spawn action doesn't require additional fields

        # Check scientific method coverage
        coverage = self._check_scientific_method_coverage(proposal)
        uncovered = [phase for phase, covered in coverage.items() if not covered]

        if len(uncovered) >= 3:
            errors.append(
                f"Insufficient scientific method coverage. Missing: {uncovered}"
            )
        elif uncovered:
            warnings.append(
                f"Partial scientific method coverage. Could add: {uncovered}"
            )

        # Check termination criteria
        if not proposal.termination_criteria or len(proposal.termination_criteria) < 10:
            warnings.append("Termination criteria should be more specific")

        # Check iteration bounds
        if proposal.max_total_iterations > 20:
            errors.append("max_total_iterations cannot exceed 20")
        elif proposal.max_total_iterations > 15:
            warnings.append("High iteration count may cause long execution times")

        # Check capabilities
        if "reasoning" not in proposal.required_capabilities:
            warnings.append("Most loops require 'reasoning' capability")

        return LoopProposalValidation(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            scientific_method_coverage=coverage,
        )

    def get_execution_estimate(self, proposal: LoopProposal) -> dict[str, int]:
        """Estimate execution metrics for a proposal.

        Args:
            proposal: The validated loop proposal

        Returns:
            Dict with estimated iterations and duration
        """
        total_iterations = sum(p.max_iterations for p in proposal.phases)
        total_iterations = min(total_iterations, proposal.max_total_iterations)

        # Rough estimate: 5 seconds per iteration
        estimated_seconds = total_iterations * 5

        return {
            "estimated_iterations": total_iterations,
            "estimated_duration_seconds": estimated_seconds,
        }
