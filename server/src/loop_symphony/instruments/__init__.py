"""Loop instruments for task execution."""

from loop_symphony.instruments.base import BaseInstrument, InstrumentResult
from loop_symphony.instruments.note import NoteInstrument
from loop_symphony.instruments.research import ResearchInstrument
from loop_symphony.instruments.synthesis import SynthesisInstrument
from loop_symphony.instruments.vision import VisionInstrument

__all__ = [
    "BaseInstrument",
    "InstrumentResult",
    "NoteInstrument",
    "ResearchInstrument",
    "SynthesisInstrument",
    "VisionInstrument",
]
