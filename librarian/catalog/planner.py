"""Arrangement planner - uses Claude to propose novel compositions (Phase 3A)."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from loop_library.models.arrangement import (
    ArrangementProposal,
    ArrangementStep,
    ArrangementValidation,
)
from loop_library.tools.claude import ClaudeClient
from loop_library.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class InvestigationBrief(BaseModel):
    """7-category investigation brief from the human conductor via Kiloa."""

    deliverable: str
    context: Optional[str] = None
    proposed_approach: Optional[str] = None
    tools_and_data: Optional[str] = None
    exclusions: Optional[str] = None
    precision: Optional[str] = None
    intent: Optional[str] = None
    conductor_context: Optional[str] = None


class LibrarianPlan(BaseModel):
    """Extended arrangement plan returned by the Librarian."""

    proposal: ArrangementProposal
    human_sketch_comparison: str | None = Field(
        default=None,
        description="How the Librarian's plan differs from the human's Category 3 sketch",
    )
    estimated_duration_seconds: int | None = Field(
        default=None,
        description="Rough estimate of execution time",
    )
    conductors_involved: list[str] = Field(
        default_factory=list,
        description="Conductor names that would be involved in execution",
    )


# Available instruments and their descriptions
INSTRUMENT_CATALOG: dict[str, dict[str, Any]] = {
    "note": {
        "description": "Simple, single-pass response for straightforward queries",
        "capabilities": ["reasoning"],
        "max_iterations": 1,
        "best_for": "Quick answers, simple questions, summarization",
        "executable": True,
    },
    "research": {
        "description": "Iterative web research using scientific method",
        "capabilities": ["reasoning", "web_search"],
        "max_iterations": 5,
        "best_for": "Fact-finding, current events, comparisons, deep investigation",
        "executable": True,
    },
    "synthesis": {
        "description": "Merges multiple inputs into coherent output",
        "capabilities": ["reasoning", "synthesis"],
        "max_iterations": 2,
        "best_for": "Combining research results, resolving contradictions",
        "executable": True,
    },
    "vision": {
        "description": "Analyzes images and extracts information",
        "capabilities": ["reasoning", "vision"],
        "max_iterations": 3,
        "best_for": "Image analysis, visual content understanding",
        "executable": True,
    },
    "plaid_financial": {
        "description": "Pulls and analyzes financial transaction data via Plaid API",
        "capabilities": ["data_retrieval", "financial_analysis"],
        "max_iterations": 3,
        "best_for": "Spending breakdowns, budget analysis, financial trends",
        "conductor": "malama",
        "executable": False,
    },
    "youtube_analytics": {
        "description": "Analyzes YouTube channel and video performance data",
        "capabilities": ["data_retrieval", "content_analysis"],
        "max_iterations": 3,
        "best_for": "Video performance, retention curves, audience patterns",
        "conductor": "roy",
        "executable": False,
    },
    "health_correlation": {
        "description": "Correlates health data from Apple Health",
        "capabilities": ["data_retrieval", "correlation_analysis"],
        "max_iterations": 3,
        "best_for": "Sleep patterns, activity trends, health correlations",
        "conductor": "ascle",
        "executable": False,
    },
    "calendar_planning": {
        "description": "Reads calendar data and helps with scheduling and planning",
        "capabilities": ["data_retrieval", "planning"],
        "max_iterations": 2,
        "best_for": "Trip planning, schedule analysis, event coordination",
        "conductor": "task_conductor",
        "executable": False,
    },
    "cross_domain": {
        "description": "Connects patterns across multiple conductor domains",
        "capabilities": ["synthesis", "pattern_detection"],
        "max_iterations": 3,
        "best_for": "Finding connections between health, finances, content, and schedule",
        "conductor": "lucid",
        "executable": False,
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


BRIEF_PLANNING_PROMPT = """You are the Librarian for Loop Symphony, an autonomous research orchestration system.

You are planning an investigation based on a structured brief from a human conductor.

## Available Instruments

{instrument_catalog}

## Composition Types

1. **single** - Use one instrument directly
2. **sequential** - Pipeline of instruments where each step's output feeds the next
3. **parallel** - Multiple instruments run simultaneously, then merge results

## Investigation Brief

{brief}

## Instructions

1. Use the Primary Objective as your main goal.
2. Use Situation Context to understand urgency and scope.
3. If a Human's Proposed Approach is provided (has_sketch={has_sketch}), compare your plan against it and note differences in "human_sketch_comparison".
4. Use Available Tools and Data to inform instrument selection.
5. Use Exclusions as hard constraints on scope.
6. Use Precision Requirements to set confidence thresholds and depth.
7. Frame your rationale around the Decision Context if provided.
8. If your plan uses instruments marked as PLANNED (not yet executable), note this in the rationale and include executable fallback instruments (research + synthesis) in the actual steps.
9. Identify which conductors would be involved based on the instruments selected.

Respond with a JSON object:
{{
    "type": "single" | "sequential" | "parallel",
    "rationale": "Why this arrangement fits, framed around the decision context",
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
    "timeout_seconds": null | 30.0,

    // Extra fields:
    "human_sketch_comparison": "How this plan differs from the human's sketch (null if no sketch provided)",
    "estimated_duration_seconds": 60,
    "conductors_involved": ["conductor_name"]
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

    def _build_catalog(self, include_planned: bool = False) -> str:
        """Build human-readable catalog of available instruments.

        Args:
            include_planned: If True, include non-executable instruments with status notes.
        """
        lines = []
        for name, info in INSTRUMENT_CATALOG.items():
            if not include_planned and not info.get("executable", True):
                continue
            lines.append(f"### {name}")
            lines.append(f"- Description: {info['description']}")
            lines.append(f"- Capabilities: {', '.join(info['capabilities'])}")
            lines.append(f"- Max iterations: {info['max_iterations']}")
            lines.append(f"- Best for: {info['best_for']}")
            if not info.get("executable", True):
                conductor = info.get("conductor", "unknown")
                lines.append(f"- Status: PLANNED (not yet executable) — conductor: {conductor}")
                lines.append("- Fallback: Use research + synthesis instead")
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

    def _check_instrument(
        self, name: str, errors: list[str], warnings: list[str], context: str = "",
    ) -> None:
        """Check if an instrument exists and is executable."""
        if name not in INSTRUMENT_CATALOG:
            errors.append(f"Unknown instrument{context}: {name}")
        elif not INSTRUMENT_CATALOG[name].get("executable", True):
            conductor = INSTRUMENT_CATALOG[name].get("conductor", "unknown")
            warnings.append(
                f"Instrument{context} '{name}' is planned but not yet executable "
                f"(conductor: {conductor}). Will fall back to research + synthesis."
            )

    def validate(self, proposal: ArrangementProposal) -> ArrangementValidation:
        """Validate that all instruments in the proposal exist.

        Args:
            proposal: The arrangement proposal to validate

        Returns:
            ArrangementValidation with errors and warnings
        """
        errors: list[str] = []
        warnings: list[str] = []

        if proposal.type == "single":
            if not proposal.instrument:
                errors.append("Single arrangement requires 'instrument' field")
            else:
                self._check_instrument(proposal.instrument, errors, warnings)

        elif proposal.type == "sequential":
            if not proposal.steps:
                errors.append("Sequential arrangement requires 'steps' field")
            else:
                for i, step in enumerate(proposal.steps):
                    self._check_instrument(
                        step.instrument, errors, warnings,
                        context=f" in step {i + 1}",
                    )

        elif proposal.type == "parallel":
            if not proposal.branches:
                errors.append("Parallel arrangement requires 'branches' field")
            else:
                for branch in proposal.branches:
                    self._check_instrument(branch, errors, warnings)

            self._check_instrument(
                proposal.merge_instrument, errors, warnings,
                context=" (merge)",
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

    async def plan_from_brief(self, brief: InvestigationBrief) -> LibrarianPlan:
        """Plan an arrangement from a structured investigation brief.

        Args:
            brief: The 7-category investigation brief from the human conductor.

        Returns:
            LibrarianPlan wrapping an ArrangementProposal with extra fields.
        """
        catalog = self._build_catalog(include_planned=True)
        prompt = self._build_brief_prompt(brief, catalog)

        logger.info(f"Planning from brief: {brief.deliverable[:100]}...")

        response = await self.claude.complete(
            prompt=prompt,
            system="You are a precise JSON generator. Output only valid JSON.",
        )

        return self._parse_brief_response(response, brief)

    def _build_brief_prompt(self, brief: InvestigationBrief, catalog: str) -> str:
        """Build the planning prompt from an investigation brief."""
        sections = [
            f"## Primary Objective (Deliverable)\n{brief.deliverable}",
        ]
        if brief.context:
            sections.append(f"## Situation Context\n{brief.context}")
        if brief.proposed_approach:
            sections.append(
                f"## Human's Proposed Approach (compare your plan against this)\n"
                f"{brief.proposed_approach}"
            )
        if brief.tools_and_data:
            sections.append(f"## Available Tools and Data\n{brief.tools_and_data}")
        if brief.exclusions:
            sections.append(f"## Exclusions and Constraints\n{brief.exclusions}")
        if brief.precision:
            sections.append(f"## Precision Requirements\n{brief.precision}")
        if brief.intent:
            sections.append(f"## Decision Context (frame conclusions around this)\n{brief.intent}")
        if brief.conductor_context:
            sections.append(f"## Conductor Context\n{brief.conductor_context}")

        brief_text = "\n\n".join(sections)

        return BRIEF_PLANNING_PROMPT.format(
            instrument_catalog=catalog,
            brief=brief_text,
            has_sketch="true" if brief.proposed_approach else "false",
        )

    def _parse_brief_response(
        self, response: str, brief: InvestigationBrief
    ) -> LibrarianPlan:
        """Parse Claude's JSON response into a LibrarianPlan."""
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse brief plan JSON: {e}")
            proposal = ArrangementProposal(
                type="single",
                rationale="Fallback: could not parse planner response",
                termination_criteria="Single-pass completion",
                instrument="note",
            )
            return LibrarianPlan(proposal=proposal)

        # Extract LibrarianPlan-level fields
        human_sketch_comparison = data.pop("human_sketch_comparison", None)
        estimated_duration_seconds = data.pop("estimated_duration_seconds", None)
        conductors_involved = data.pop("conductors_involved", [])

        # Convert steps if present
        if data.get("steps"):
            data["steps"] = [ArrangementStep(**s) for s in data["steps"]]

        # Remove any fields not in ArrangementProposal
        proposal_fields = {
            "type", "rationale", "termination_criteria",
            "steps", "branches", "merge_instrument",
            "timeout_seconds", "instrument",
        }
        proposal_data = {k: v for k, v in data.items() if k in proposal_fields}

        proposal = ArrangementProposal(**proposal_data)

        return LibrarianPlan(
            proposal=proposal,
            human_sketch_comparison=human_sketch_comparison,
            estimated_duration_seconds=estimated_duration_seconds,
            conductors_involved=conductors_involved,
        )
