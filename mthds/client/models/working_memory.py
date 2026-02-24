from abc import ABC
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from mthds.client.models.stuff import DictStuffAbstract, StuffType

WorkingMemoryType = TypeVar("WorkingMemoryType", bound="WorkingMemoryAbstract[Any]")


class WorkingMemoryAbstract(BaseModel, ABC, Generic[StuffType]):
    model_config = ConfigDict(extra="forbid", strict=True)
    root: dict[str, StuffType] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)


class DictWorkingMemoryAbstract(BaseModel, ABC):
    model_config = ConfigDict(extra="forbid", strict=True)
    root: dict[str, DictStuffAbstract]
    aliases: dict[str, str]
