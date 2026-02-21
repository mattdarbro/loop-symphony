"""Loop instruments for task execution."""

from loop_library.instruments.base import BaseInstrument, InstrumentResult
from loop_library.instruments.falcon import FalconInstrument
from loop_library.instruments.note import NoteInstrument
from loop_library.instruments.research import ResearchInstrument
from loop_library.instruments.synthesis import SynthesisInstrument
from loop_library.instruments.vision import VisionInstrument

__all__ = [
    "BaseInstrument",
    "FalconInstrument",
    "InstrumentResult",
    "NoteInstrument",
    "ResearchInstrument",
    "SynthesisInstrument",
    "VisionInstrument",
]
