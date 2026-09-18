from abc import ABC
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, field_serializer

from mthds.protocol.concept import ConceptType

StuffContentType = TypeVar("StuffContentType", bound="StuffContentAbstract")
StuffType = TypeVar("StuffType", bound="StuffAbstract[Any, Any]")


class StuffAbstract(BaseModel, ABC, Generic[ConceptType, StuffContentType]):
    model_config = ConfigDict(extra="forbid", strict=True)

    stuff_code: str
    stuff_name: str | None = None
    concept: ConceptType
    content: StuffContentType

    @field_serializer("concept")
    def serialize_concept(self, concept: ConceptType) -> str:
        """Emit the concept as its reference string.

        A stuff names its concept and never carries its definition, so every
        dump of a stuff — whatever a runtime keeps on its own concept subclass —
        is the standard's wire form.
        """
        return concept.concept_ref


class StuffContentAbstract(BaseModel, ABC):
    pass
