"""Composition patterns for orchestrating instrument pipelines."""

from loop_library.compositions.sequential import SequentialComposition
from loop_library.compositions.parallel import ParallelComposition
from loop_library.compositions.helpers import (
    _apply_config,
    _build_step_context,
    _restore_config,
    _serialize_result,
)

__all__ = [
    "ParallelComposition",
    "SequentialComposition",
    "_apply_config",
    "_build_step_context",
    "_restore_config",
    "_serialize_result",
]
