from abc import ABC
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

ConceptType = TypeVar("ConceptType", bound="ConceptAbstract")


class ConceptAbstract(BaseModel, ABC):
    """A concept as a stuff names it — a reference, and nothing more.

    The standard puts a concept's definition — its description, its structure,
    what it refines, and anything an implementation attaches to it such as the
    name of a runtime class — in the library the method loads, never beside a
    stuff (see the "Stuffs on the Wire" section of the
    [CLI I/O contract](https://mthds.ai/latest/spec/cli-io-contract/)). A runtime
    that needs more of the definition in memory declares it on its own subclass.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str
    domain_code: str

    @property
    def concept_ref(self) -> str:
        """The domain-qualified reference, `<domain>.<Code>`.

        This is the crate key for a concept the method's own package declares and
        for a native one. A concept a dependency contributes is keyed
        `<package_address>::<domain>.<Code>`, and this model holds no declaring
        package address, so that form is a subclass's to produce.
        """
        return f"{self.domain_code}.{self.code}"
