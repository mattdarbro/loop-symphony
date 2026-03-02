"""Models for the Librarian's investigation brief and plan.

Re-exports from librarian.catalog.planner for use in API routes.
"""

from pydantic import BaseModel

from librarian.catalog.planner import InvestigationBrief, LibrarianPlan

__all__ = ["InvestigationBrief", "LibrarianPlan", "LibrarianExecuteRequest"]


class LibrarianExecuteRequest(BaseModel):
    """Request to execute an approved Librarian plan."""

    brief_id: str
    plan: LibrarianPlan
