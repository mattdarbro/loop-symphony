"""Models for conductor invocations."""

from pydantic import BaseModel, Field

from loop_library.models.process import ProcessType


class ConductorConfig(BaseModel):
    """Configuration for a conductor."""

    name: str
    description: str = ""
    default_trust_level: int = Field(default=0, ge=0, le=3)
    max_depth: int = Field(default=3, ge=1, le=10)
    enabled_instruments: list[str] = Field(default_factory=list)
    enabled_symphonies: list[str] = Field(default_factory=list)


class LoopInvocation(BaseModel):
    """What a conductor passes to the loop library for execution."""

    instrument_name: str
    query: str
    context: dict = Field(default_factory=dict)
    process_type: ProcessType = ProcessType.SEMI_AUTONOMIC
