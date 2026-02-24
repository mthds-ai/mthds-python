from abc import ABC
from typing import Generic

from pydantic import BaseModel, ConfigDict

from mthds.client.models.working_memory import DictWorkingMemoryAbstract, WorkingMemoryType

VariableMultiplicity = bool | int


class PipeOutputAbstract(BaseModel, ABC, Generic[WorkingMemoryType]):
    model_config = ConfigDict(extra="forbid", strict=True)
    working_memory: WorkingMemoryType
    pipeline_run_id: str


class DictPipeOutputAbstract(BaseModel, ABC):
    model_config = ConfigDict(extra="forbid", strict=True)
    working_memory: DictWorkingMemoryAbstract
    pipeline_run_id: str
