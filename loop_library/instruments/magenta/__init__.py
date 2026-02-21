"""Magenta Loop instruments — 5-stage content analytics pipeline."""

from loop_library.instruments.magenta.composition import create_magenta_composition
from loop_library.instruments.magenta.diagnose import DiagnoseInstrument
from loop_library.instruments.magenta.ingest import IngestInstrument
from loop_library.instruments.magenta.prescribe import PrescribeInstrument
from loop_library.instruments.magenta.report import ReportInstrument
from loop_library.instruments.magenta.track import TrackInstrument

__all__ = [
    "IngestInstrument",
    "DiagnoseInstrument",
    "PrescribeInstrument",
    "TrackInstrument",
    "ReportInstrument",
    "create_magenta_composition",
]
