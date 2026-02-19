"""Magenta Loop instruments — 5-stage content analytics pipeline."""

from loop_symphony.instruments.magenta.composition import create_magenta_composition
from loop_symphony.instruments.magenta.diagnose import DiagnoseInstrument
from loop_symphony.instruments.magenta.ingest import IngestInstrument
from loop_symphony.instruments.magenta.prescribe import PrescribeInstrument
from loop_symphony.instruments.magenta.report import ReportInstrument
from loop_symphony.instruments.magenta.track import TrackInstrument

__all__ = [
    "IngestInstrument",
    "DiagnoseInstrument",
    "PrescribeInstrument",
    "TrackInstrument",
    "ReportInstrument",
    "create_magenta_composition",
]
