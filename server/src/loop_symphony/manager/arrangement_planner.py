"""Arrangement planner - uses Claude to propose novel compositions (Phase 3A)."""

import json
import logging
from typing import Any

from loop_symphony.models.arrangement import (
    ArrangementProposal,
    ArrangementStep,
    ArrangementValidation,
)
from loop_symphony.tools.claude import ClaudeClient
from loop_symphony.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Available instruments and their descriptions
INSTRUMENT_CATALOG = {
    "note": {
        "description": "Simple, single-pass response for straightforward queries",
        "capabilities": ["reasoning"],
        "max_iterations": 1,
        "best_for": "Quick answers, simple questions, summarization",
    },
    "research": {
        "description": "Iterative web research using scientific method",
        "capabilities": ["reasoning", "web_search"],
        "max_iterations": 5,
        "best_for": "Fact-finding, current events, comparisons, deep investigation",
    },
    "synthesis": {
        "description": "Merges multiple inputs into coherent output",
        "capabilities": ["reasoning", "synthesis"],
        "max_iterations": 2,
        "best_for": "Combining research results, resolving contradictions",
    },
    "vision": {
        "description": "Analyzes images and extracts information",
        "capabilities": ["reasoning", "vision"],
        "max_iterations": 3,
        "best_for": "Image analysis, visual content understanding",
    },
}


PLANNING_PROMPT = """You are an arrangement planner for Loop Symphony, an autonomous research system.

Your task is to analyze a user query and propose the best instrument arrangement to answer it.

## Available Instruments

{instrument_catalog}

## Composition Types

1. **single** - Use one instrument directly
   - Best for: Simple queries that one instrument handles well

2. **sequential** - Pipeline of instruments where each step's output feeds the next
   - Example: research -> synthesis (research first, then synthesize findings)
   - Best for: Multi-phase tasks, research-then-summarize patterns

3. **parallel** - Multiple instruments run simultaneously, then merge results
   - Example: [research, note] -> synthesis (get multiple perspectives, then merge)
   - Best for: Competing hypotheses, triangulation, comprehensive coverage

## Scientific Method Requirement

All arrangements must follow scientific method principles:
- Clear hypothesis or goal
- Systematic information gathering
- Evidence-based conclusions
- Explicit termination criteria

## Your Task

Analyze this query and propose the best arrangement:

QUERY: {query}

Respond with a JSON object matching this schema:
{{
    "type": "single" | "sequential" | "parallel",
    "rationale": "Why this arrangement fits the task",
    "termination_criteria": "How we know when the task is complete",

    // For single:
    "instrument": "instrument_name",

    // For sequential:
    "steps": [
        {{"instrument": "name", "config": null | {{"max_iterations": N}}}}
    ],

    // For parallel:
    "branches": ["instrument1", "instrument2"],
    "merge_instrument": "synthesis",
    "timeout_seconds": null | 30.0
}}

Respond ONLY with the JSON object, no other text."""


class ArrangementPlanner:
    """Plans novel arrangements using Claude.

    Analyzes task requirements and proposes appropriate instrument
    compositions. Validates proposals against registered capabilities.
    """

    def __init__(
        self,
        claude: ClaudeClient,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.claude = claude
        self.registry = registry

    def _build_catalog(self) -> str:
        """Build human-readable catalog of available instruments."""
        lines = []
        for name, info in INSTRUMENT_CATALOG.items():
            lines.append(f"### {name}")
            lines.append(f"- Description: {info['description']}")
            lines.append(f"- Capabilities: {', '.join(info['capabilities'])}")
            lines.append(f"- Max iterations: {info['max_iterations']}")
            lines.append(f"- Best for: {info['best_for']}")
            lines.append("")
        return "\n".join(lines)

    def _parse_response(self, response: str) -> ArrangementProposal:
        """Parse Claude's JSON response into an ArrangementProposal."""
        # Try to extract JSON from response
        text = response.strip()

        # Handle markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (``` markers)
            text = "\n".join(lines[1:-1])

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse arrangement JSON: {e}")
            # Fall back to simple note instrument
            return ArrangementProposal(
                type="single",
                rationale="Fallback: could not parse planner response",
                termination_criteria="Single-pass completion",
                instrument="note",
            )

        # Convert steps if present
        if data.get("steps"):
            data["steps"] = [ArrangementStep(**s) for s in data["steps"]]

        return ArrangementProposal(**data)

    async def plan(self, query: str) -> ArrangementProposal:
        """Analyze a query and propose an arrangement.

        Args:
            query: The user's task query

        Returns:
            ArrangementProposal with recommended composition
        """
        catalog = self._build_catalog()
        prompt = PLANNING_PROMPT.format(
            instrument_catalog=catalog,
            query=query,
        )

        logger.info(f"Planning arrangement for query: {query[:100]}...")

        response = await self.claude.complete(
            prompt=prompt,
            system="You are a precise JSON generator. Output only valid JSON.",
        )

        proposal = self._parse_response(response)

        logger.info(
            f"Proposed arrangement: type={proposal.type}, "
            f"rationale={proposal.rationale[:50]}..."
        )

        return proposal

    def validate(self, proposal: ArrangementProposal) -> ArrangementValidation:
        """Validate that all instruments in the proposal exist.

        Args:
            proposal: The arrangement proposal to validate

        Returns:
            ArrangementValidation with errors and warnings
        """
        errors: list[str] = []
        warnings: list[str] = []
        known_instruments = set(INSTRUMENT_CATALOG.keys())

        if proposal.type == "single":
            if not proposal.instrument:
                errors.append("Single arrangement requires 'instrument' field")
            elif proposal.instrument not in known_instruments:
                errors.append(f"Unknown instrument: {proposal.instrument}")

        elif proposal.type == "sequential":
            if not proposal.steps:
                errors.append("Sequential arrangement requires 'steps' field")
            else:
                for i, step in enumerate(proposal.steps):
                    if step.instrument not in known_instruments:
                        errors.append(
                            f"Unknown instrument in step {i + 1}: {step.instrument}"
                        )

        elif proposal.type == "parallel":
            if not proposal.branches:
                errors.append("Parallel arrangement requires 'branches' field")
            else:
                for branch in proposal.branches:
                    if branch not in known_instruments:
                        errors.append(f"Unknown branch instrument: {branch}")

            if proposal.merge_instrument not in known_instruments:
                errors.append(
                    f"Unknown merge instrument: {proposal.merge_instrument}"
                )

        # Warnings
        if not proposal.termination_criteria:
            warnings.append("No termination criteria specified")

        return ArrangementValidation(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def get_available_instruments(self) -> dict[str, Any]:
        """Return catalog of available instruments for inspection."""
        return INSTRUMENT_CATALOG.copy()
