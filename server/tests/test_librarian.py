"""Tests for the Librarian subsystem (brief planning, catalog, execution)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from librarian.catalog.planner import (
    ArrangementPlanner,
    INSTRUMENT_CATALOG,
    InvestigationBrief,
    LibrarianPlan,
)
from loop_library.models.arrangement import (
    ArrangementProposal,
    ArrangementStep,
)


# ── Model Tests ─────────────────────────────────────────────────────────


class TestInvestigationBrief:
    """Tests for InvestigationBrief model."""

    def test_minimal_brief(self):
        brief = InvestigationBrief(deliverable="Find the best coffee shop")
        assert brief.deliverable == "Find the best coffee shop"
        assert brief.context is None
        assert brief.intent is None

    def test_full_brief(self):
        brief = InvestigationBrief(
            deliverable="Analyze my spending patterns",
            context="I want to save more money this quarter",
            proposed_approach="Look at credit card transactions by category",
            tools_and_data="Plaid financial data for the last 3 months",
            exclusions="Ignore recurring subscriptions",
            precision="Within $50 accuracy is fine",
            intent="Decide whether to cut dining out or entertainment",
            conductor_context="malama",
        )
        assert brief.deliverable == "Analyze my spending patterns"
        assert brief.conductor_context == "malama"

    def test_deliverable_required(self):
        with pytest.raises(Exception):
            InvestigationBrief()


class TestLibrarianPlan:
    """Tests for LibrarianPlan model."""

    def test_minimal_plan(self):
        proposal = ArrangementProposal(
            type="single",
            rationale="Simple task",
            termination_criteria="Done",
            instrument="note",
        )
        plan = LibrarianPlan(proposal=proposal)
        assert plan.proposal.type == "single"
        assert plan.human_sketch_comparison is None
        assert plan.conductors_involved == []

    def test_full_plan(self):
        proposal = ArrangementProposal(
            type="sequential",
            rationale="Research then synthesize",
            termination_criteria="High confidence",
            steps=[
                ArrangementStep(instrument="research"),
                ArrangementStep(instrument="synthesis"),
            ],
        )
        plan = LibrarianPlan(
            proposal=proposal,
            human_sketch_comparison="Human suggested single research, but sequential is better",
            estimated_duration_seconds=120,
            conductors_involved=["malama", "lucid"],
        )
        assert plan.estimated_duration_seconds == 120
        assert len(plan.conductors_involved) == 2


# ── Catalog Tests ────────────────────────────────────────────────────────


class TestExpandedCatalog:
    """Tests for the expanded instrument catalog."""

    def test_has_core_instruments(self):
        for name in ["note", "research", "synthesis", "vision"]:
            assert name in INSTRUMENT_CATALOG
            assert INSTRUMENT_CATALOG[name].get("executable") is True

    def test_has_conductor_domain_instruments(self):
        for name in [
            "plaid_financial",
            "youtube_analytics",
            "health_correlation",
            "calendar_planning",
            "cross_domain",
        ]:
            assert name in INSTRUMENT_CATALOG
            assert INSTRUMENT_CATALOG[name].get("executable") is False
            assert "conductor" in INSTRUMENT_CATALOG[name]

    def test_all_instruments_have_required_fields(self):
        for name, info in INSTRUMENT_CATALOG.items():
            assert "description" in info, f"{name} missing description"
            assert "capabilities" in info, f"{name} missing capabilities"
            assert "max_iterations" in info, f"{name} missing max_iterations"
            assert "best_for" in info, f"{name} missing best_for"
            assert "executable" in info, f"{name} missing executable flag"


# ── Planner Tests ────────────────────────────────────────────────────────


class TestBuildCatalog:
    """Tests for catalog building."""

    def test_build_catalog_excludes_planned_by_default(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)
        catalog = planner._build_catalog(include_planned=False)
        assert "note" in catalog
        assert "research" in catalog
        assert "plaid_financial" not in catalog

    def test_build_catalog_includes_planned(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)
        catalog = planner._build_catalog(include_planned=True)
        assert "note" in catalog
        assert "plaid_financial" in catalog
        assert "PLANNED" in catalog


class TestValidateWithPlannedInstruments:
    """Tests for validation with non-executable instruments."""

    def test_planned_instrument_produces_warning_not_error(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="plaid_financial",
        )
        validation = planner.validate(proposal)
        assert validation.valid  # Should be valid (warning, not error)
        assert any("planned but not yet executable" in w for w in validation.warnings)

    def test_unknown_instrument_still_produces_error(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)

        proposal = ArrangementProposal(
            type="single",
            rationale="Test",
            termination_criteria="Done",
            instrument="totally_fake",
        )
        validation = planner.validate(proposal)
        assert not validation.valid
        assert any("totally_fake" in e for e in validation.errors)


class TestPlanFromBrief:
    """Tests for plan_from_brief()."""

    @pytest.mark.asyncio
    async def test_plan_from_brief_calls_claude(self):
        claude = AsyncMock()
        claude.complete = AsyncMock(return_value=json.dumps({
            "type": "sequential",
            "rationale": "Research spending then synthesize",
            "termination_criteria": "Analysis complete",
            "steps": [
                {"instrument": "research", "config": None},
                {"instrument": "synthesis", "config": None},
            ],
            "human_sketch_comparison": "Similar to human sketch",
            "estimated_duration_seconds": 90,
            "conductors_involved": ["malama"],
        }))
        planner = ArrangementPlanner(claude=claude)

        brief = InvestigationBrief(
            deliverable="Analyze my spending",
            proposed_approach="Check transactions by category",
        )

        plan = await planner.plan_from_brief(brief)

        claude.complete.assert_called_once()
        assert isinstance(plan, LibrarianPlan)
        assert plan.proposal.type == "sequential"
        assert plan.human_sketch_comparison == "Similar to human sketch"
        assert plan.estimated_duration_seconds == 90
        assert plan.conductors_involved == ["malama"]

    @pytest.mark.asyncio
    async def test_plan_from_brief_includes_all_categories_in_prompt(self):
        claude = AsyncMock()
        claude.complete = AsyncMock(return_value=json.dumps({
            "type": "single",
            "rationale": "Simple",
            "termination_criteria": "Done",
            "instrument": "note",
        }))
        planner = ArrangementPlanner(claude=claude)

        brief = InvestigationBrief(
            deliverable="Main goal",
            context="Urgent situation",
            proposed_approach="My idea",
            tools_and_data="Plaid data",
            exclusions="No credit cards",
            precision="Within $10",
            intent="Decide on budget cuts",
            conductor_context="malama",
        )

        await planner.plan_from_brief(brief)

        call_args = claude.complete.call_args
        prompt = call_args.kwargs["prompt"]
        assert "Main goal" in prompt
        assert "Urgent situation" in prompt
        assert "My idea" in prompt
        assert "Plaid data" in prompt
        assert "No credit cards" in prompt
        assert "Within $10" in prompt
        assert "Decide on budget cuts" in prompt

    @pytest.mark.asyncio
    async def test_plan_from_brief_fallback_on_parse_error(self):
        claude = AsyncMock()
        claude.complete = AsyncMock(return_value="not json at all")
        planner = ArrangementPlanner(claude=claude)

        brief = InvestigationBrief(deliverable="Test")
        plan = await planner.plan_from_brief(brief)

        assert plan.proposal.type == "single"
        assert plan.proposal.instrument == "note"
        assert "Fallback" in plan.proposal.rationale


class TestParseBriefResponse:
    """Tests for _parse_brief_response()."""

    def test_extracts_librarian_plan_fields(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)
        brief = InvestigationBrief(deliverable="Test")

        response = json.dumps({
            "type": "single",
            "rationale": "Quick answer",
            "termination_criteria": "Done",
            "instrument": "note",
            "human_sketch_comparison": None,
            "estimated_duration_seconds": 30,
            "conductors_involved": [],
        })

        plan = planner._parse_brief_response(response, brief)
        assert plan.proposal.type == "single"
        assert plan.estimated_duration_seconds == 30

    def test_handles_markdown_code_blocks(self):
        claude = MagicMock()
        planner = ArrangementPlanner(claude=claude)
        brief = InvestigationBrief(deliverable="Test")

        response = """```json
{
    "type": "single",
    "rationale": "Simple",
    "termination_criteria": "Done",
    "instrument": "note",
    "estimated_duration_seconds": 15
}
```"""

        plan = planner._parse_brief_response(response, brief)
        assert plan.proposal.instrument == "note"
        assert plan.estimated_duration_seconds == 15


# ── API Endpoint Tests ───────────────────────────────────────────────────


class TestLibrarianCatalogEndpoint:
    """Tests for GET /librarian/catalog."""

    @pytest.mark.asyncio
    async def test_catalog_returns_all_instruments(self):
        from fastapi.testclient import TestClient
        from loop_symphony.api.routes import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        response = client.get("/librarian/catalog")
        assert response.status_code == 200
        data = response.json()
        assert "note" in data
        assert "research" in data
        assert "plaid_financial" in data
        assert data["plaid_financial"]["executable"] is False
