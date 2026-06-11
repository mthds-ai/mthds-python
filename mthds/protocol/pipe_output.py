from abc import ABC
from typing import Generic

from pydantic import BaseModel, ConfigDict

from mthds.protocol.working_memory import WorkingMemoryType

VariableMultiplicity = bool | int


class PipeOutputAbstract(BaseModel, ABC, Generic[WorkingMemoryType]):
    model_config = ConfigDict(extra="forbid", strict=True)
    working_memory: WorkingMemoryType
    pipeline_run_id: str
