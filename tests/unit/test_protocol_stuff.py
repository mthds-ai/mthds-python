"""Unit tests for the protocol's stuff and concept shapes — what a stuff says about its concept."""

import json

import pytest
from pydantic import ValidationError

from mthds.protocol.concept import ConceptAbstract
from mthds.protocol.stuff import StuffAbstract, StuffContentAbstract


class _StubConcept(ConceptAbstract):
    """A runtime's concept: the protocol's two fields, plus whatever the runtime needs in memory."""

    structure_class_name: str


class _StubContent(StuffContentAbstract):
    value: str


class _StubStuff(StuffAbstract[_StubConcept, _StubContent]):
    pass


def _stub_stuff() -> _StubStuff:
    return _StubStuff(
        stuff_code="stuff_1",
        stuff_name="analysis",
        concept=_StubConcept(code="ContractAnalysis", domain_code="legal", structure_class_name="ContractAnalysis"),
        content=_StubContent(value="high"),
    )


class TestStuffConceptSerialization:
    def test_concept_abstract_carries_the_reference_only(self) -> None:
        """A concept's definition belongs to the library, so the protocol model holds the two fields
        that name it and nothing else.
        """
        assert set(ConceptAbstract.model_fields) == {"code", "domain_code"}

    def test_definition_fields_are_refused(self) -> None:
        """The trimmed fields are not silently tolerated: the model is closed, so a payload
        carrying a definition fails the parse rather than smuggling it beside a stuff.
        """
        with pytest.raises(ValidationError, match="description"):
            ConceptAbstract.model_validate({"code": "ContractAnalysis", "domain_code": "legal", "description": "A contract analysis"})

    def test_concept_ref_is_the_domain_qualified_reference(self) -> None:
        assert _stub_stuff().concept.concept_ref == "legal.ContractAnalysis"

    def test_dump_emits_the_concept_as_its_reference(self) -> None:
        """`model_dump()` gives the ref string, not the concept object — including what the
        runtime's own subclass carries beside the two protocol fields.
        """
        dumped = _stub_stuff().model_dump()

        assert dumped["concept"] == "legal.ContractAnalysis"
        assert dumped["content"] == {"value": "high"}
        assert dumped["stuff_code"] == "stuff_1"
        assert dumped["stuff_name"] == "analysis"

    def test_json_dump_emits_the_concept_as_its_reference(self) -> None:
        """JSON mode agrees with python mode — the wire form is the protocol's on both."""
        assert json.loads(_stub_stuff().model_dump_json())["concept"] == "legal.ContractAnalysis"

    def test_serialization_schema_declares_the_concept_a_string(self) -> None:
        """A server embedding a stuff in a response publishes `concept` as a string, so the
        generated OpenAPI says what the wire actually carries.
        """
        schema = _StubStuff.model_json_schema(mode="serialization")

        assert schema["properties"]["concept"] == {"type": "string"}
