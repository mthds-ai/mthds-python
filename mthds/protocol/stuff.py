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

        The dump is therefore one-way: these models are strict, so a stuff, a
        working memory or a pipe output cannot be validated back from its own
        dump. That is the point rather than an oversight — the definition the
        parse would need is not on the wire, and a reader resolves the ref
        through the concept library the method loads, the way the input side
        already does.

        A subclass that emits something else — the `<package_address>::<domain>.<Code>`
        crate key of a dependency-contributed concept, say — overrides this
        method **under this name**, decorated again or as a plain method.
        Declaring a second `field_serializer` for `concept` under any other name
        raises pydantic's `multiple-field-serializers` error at class definition;
        re-annotating the field with a serializer, or putting a `model_serializer`
        on the concept subclass, is ignored in favour of this one with no
        diagnostic at all.
        """
        return concept.concept_ref


class StuffContentAbstract(BaseModel, ABC):
    pass
