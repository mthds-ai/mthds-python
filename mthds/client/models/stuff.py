from abc import ABC
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from mthds.client.models.concept import ConceptType

StuffContentType = TypeVar("StuffContentType", bound="StuffContentAbstract")
StuffType = TypeVar("StuffType", bound="StuffAbstract[Any, Any]")


class StuffAbstract(BaseModel, ABC, Generic[ConceptType, StuffContentType]):
    model_config = ConfigDict(extra="forbid", strict=True)

    stuff_code: str
    stuff_name: str | None = None
    concept: ConceptType
    content: StuffContentType


class StuffContentAbstract(BaseModel, ABC):
    pass


class DictStuffAbstract(BaseModel, ABC):
    model_config = ConfigDict(extra="forbid", strict=True)
    concept: str
    content: Any
