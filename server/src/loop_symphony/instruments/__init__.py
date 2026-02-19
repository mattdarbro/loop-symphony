"""Loop instruments for task execution."""

from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.instruments.falcon import FalconInstrument
from loop_symphony.instruments.magenta import (
    DiagnoseInstrument,
    IngestInstrument,
    PrescribeInstrument,
    ReportInstrument,
    TrackInstrument,
    create_magenta_composition,
)
from loop_symphony.instruments.note import NoteInstrument
from loop_symphony.instruments.research import ResearchInstrument
from loop_symphony.instruments.synthesis import SynthesisInstrument
from loop_symphony.instruments.vision import VisionInstrument

__all__ = [
    "BaseInstrument",
    "DiagnoseInstrument",
    "FalconInstrument",
    "IngestInstrument",
    "InstrumentResult",
    "NoteInstrument",
    "PrescribeInstrument",
    "ReportInstrument",
    "ResearchInstrument",
    "SynthesisInstrument",
    "TrackInstrument",
    "VisionInstrument",
    "create_magenta_composition",
]
