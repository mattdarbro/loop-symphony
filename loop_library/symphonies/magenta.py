"""Magenta symphony — 5-stage content analytics pipeline factory."""

from loop_library.compositions.sequential import SequentialComposition


def create_magenta_symphony() -> SequentialComposition:
    """Create the Magenta Loop as a named symphony.

    Pipeline: ingest -> diagnose -> prescribe -> track -> report

    Returns:
        SequentialComposition configured for the full Magenta Loop
    """
    return SequentialComposition(
        steps=[
            ("magenta_ingest", None),
            ("magenta_diagnose", None),
            ("magenta_prescribe", None),
            ("magenta_track", None),
            ("magenta_report", None),
        ]
    )
