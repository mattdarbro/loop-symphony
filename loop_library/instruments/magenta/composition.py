"""Magenta composition — factory for the 5-stage pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from loop_library.compositions.sequential import SequentialComposition


def create_magenta_composition() -> SequentialComposition:
    """Create the Magenta Loop as a SequentialComposition.

    Pipeline: ingest -> diagnose -> prescribe -> track -> report

    Returns:
        SequentialComposition configured for the full Magenta Loop
    """
    from loop_library.compositions.sequential import SequentialComposition

    return SequentialComposition(
        steps=[
            ("magenta_ingest", None),
            ("magenta_diagnose", None),
            ("magenta_prescribe", None),
            ("magenta_track", None),
            ("magenta_report", None),
        ]
    )
