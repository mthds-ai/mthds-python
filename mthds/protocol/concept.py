from abc import ABC
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

ConceptType = TypeVar("ConceptType", bound="ConceptAbstract")


class ConceptAbstract(BaseModel, ABC):
    model_config = ConfigDict(extra="forbid", strict=True)

    code: str
    domain_code: str
    description: str
    structure_class_name: str
    refines: str | None = None

    @property
    def concept_ref(self) -> str:
        return f"{self.domain_code}.{self.code}"
