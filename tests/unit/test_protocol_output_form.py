"""Parity and strictness tests for `mthds.protocol.output_form` against the engine-produced fixture.

The fixture `tests/fixtures/protocol/output_form.json` is the reference engine's own emission,
committed byte-for-byte here and in `mthds-js` alongside its two siblings (the directory's README
carries the provenance). It is parsed the way the artifact actually arrives: as a typed field
declared on a model narrowing the validate report.

What is worth testing here is narrower than the input side, and deliberately so. The node union is
the SAME one — an output is a concept ref exactly like an input is, so its kinds, its nesting and
its constraints are already covered by `test_protocol_input_form.py`, and re-asserting them here
would be asserting the reuse rather than the artifact. What is new is only what this artifact adds:
the single `field`, the ABSENCE of the two pipe-slot facts, and the plural wrap — the one place
producing this artifact is real work rather than reuse, and the one that fails silently.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from mthds.protocol.output_form import OutputForm, PipeOutputFormDescriptor
from mthds.protocol.pipe_io_contracts import IOMultiplicity, PipeIOContracts


class NarrowedValidateReport(BaseModel):
    """How the artifact arrives: a typed field on a model narrowing the validate report."""

    model_config = ConfigDict(extra="forbid")

    output_form: OutputForm
    pipe_io_contracts: PipeIOContracts


_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "protocol"
_RAW_OUTPUT_FORM: dict[str, Any] = json.loads((_FIXTURES / "output_form.json").read_text(encoding="utf-8"))
_RAW_CONTRACTS: dict[str, Any] = json.loads((_FIXTURES / "pipe_io_contracts.json").read_text(encoding="utf-8"))
_REPORT = NarrowedValidateReport.model_validate({"output_form": _RAW_OUTPUT_FORM, "pipe_io_contracts": _RAW_CONTRACTS})
_OUTPUT_FORM = _REPORT.output_form
_CONTRACTS = _REPORT.pipe_io_contracts


class TestOutputFormProtocolModels:
    @pytest.mark.parametrize("pipe_ref", [pytest.param(pipe_ref, id=pipe_ref) for pipe_ref in _RAW_OUTPUT_FORM])
    def test_fixture_entry_parses_strictly_and_round_trips(self, pipe_ref: str) -> None:
        """Each per-pipe descriptor parses under the closed shapes and dumps back to the exact input.

        `exclude_none` is the dump mode, matching the input form's: a slot that does not apply to a
        node is ABSENT on this wire, never `null`.
        """
        descriptor = PipeOutputFormDescriptor.model_validate(_RAW_OUTPUT_FORM[pipe_ref])
        assert descriptor.model_dump(mode="json", exclude_none=True) == _RAW_OUTPUT_FORM[pipe_ref]

    def test_shares_one_key_set_with_the_contracts(self) -> None:
        """All three validate artifacts are keyed by the same `pipe_ref` set — they iterate one pipe sequence."""
        assert sorted(_OUTPUT_FORM) == sorted(_CONTRACTS)

    @pytest.mark.parametrize("pipe_ref", [pytest.param(pipe_ref, id=pipe_ref) for pipe_ref in _RAW_OUTPUT_FORM])
    def test_output_node_states_no_pipe_slot_facts(self, pipe_ref: str) -> None:
        """`presence` and `gating` are facts of an INPUT slot, and an output has none.

        Both are optional on the node so a slotless node can exist at all — not so a producer may
        fill them in with something plausible.
        """
        node = _OUTPUT_FORM[pipe_ref].field
        assert node.presence is None
        assert node.gating is None

    @pytest.mark.parametrize("pipe_ref", [pytest.param(pipe_ref, id=pipe_ref) for pipe_ref in _RAW_OUTPUT_FORM])
    def test_plurality_is_carried_by_the_descriptor(self, pipe_ref: str) -> None:
        """THE producer obligation, and the one that fails silently.

        `concept_ref` is the element with the multiplicity suffix stripped on both sides of the
        contract, so a producer that does not read `multiplicity` describes ONE item where a run
        returns many — and every renderer then shows one. A consumer never re-derives this: it
        reads `kind` and never touches the contract for plurality.
        """
        node = _OUTPUT_FORM[pipe_ref].field
        if _CONTRACTS[pipe_ref].output.multiplicity.is_plural:
            assert node.kind == "list"
        else:
            assert node.kind != "list"

    def test_the_corpus_reaches_both_plural_arms(self) -> None:
        """A corpus with no plural output could not have caught the wrap being skipped at all."""
        multiplicities = {contract.output.multiplicity for contract in _CONTRACTS.values()}
        assert IOMultiplicity.VARIABLE in multiplicities
        assert IOMultiplicity.FIXED in multiplicities

    def test_rejects_an_output_node_carrying_a_slot_fact(self) -> None:
        """Stating the absence is a parse rule, not a convention a producer may quietly break."""
        node = {"name": "output", "kind": "prose", "concept_ref": "native.Text", "required": True}
        with pytest.raises(ValidationError):
            PipeOutputFormDescriptor.model_validate({"field": {**node, "presence": "plain"}})
        with pytest.raises(ValidationError):
            PipeOutputFormDescriptor.model_validate({"field": {**node, "gating": True}})

    def test_rejects_an_unknown_member_and_an_input_form_shape(self) -> None:
        """Closed shape, and `fields` is the input form's shape: a pipe has exactly one output."""
        node = {"name": "output", "kind": "prose", "concept_ref": "native.Text", "required": True}
        with pytest.raises(ValidationError):
            PipeOutputFormDescriptor.model_validate({"field": node, "fields": []})
        with pytest.raises(ValidationError):
            PipeOutputFormDescriptor.model_validate({"fields": [node]})

    def test_rejects_an_explicit_wire_null(self) -> None:
        """A wire payload never spells absence as `null` — the same rule the input descriptor states."""
        with pytest.raises(ValidationError):
            PipeOutputFormDescriptor.model_validate(
                {"field": {"name": "output", "kind": "prose", "concept_ref": "native.Text", "required": True, "title": None}}
            )


class TestOutputPayloadSchema:
    """The contract's half of the pair — tested here because it is only useful beside the descriptor."""

    @pytest.mark.parametrize("pipe_ref", [pytest.param(pipe_ref, id=pipe_ref) for pipe_ref in _RAW_CONTRACTS])
    def test_payload_schema_is_a_content_model_never_a_bare_array(self, pipe_ref: str) -> None:
        """Where the output side departs from the input side, asserted rather than only documented.

        An input's schema describes what a caller SENDS, so a plural slot's is a bare array. An
        output's describes what COMES BACK, which is a content model — an object — whatever the
        multiplicity. A bare array here would state a shape no runtime produces.
        """
        schema = _CONTRACTS[pipe_ref].output.json_schema
        assert schema.get("type") == "object"
        assert isinstance(schema.get("properties"), dict)

    @pytest.mark.parametrize("pipe_ref", [pytest.param(pipe_ref, id=pipe_ref) for pipe_ref in _RAW_CONTRACTS])
    def test_fixed_output_bounds_its_element_array(self, pipe_ref: str) -> None:
        """On the fixed arm the element array carries `minItems`/`maxItems` equal to `item_count`.

        Without them a `Concept[N]` output would be indistinguishable from a `Concept[]` one by
        schema alone — the list content model states no bounds of its own.
        """
        output = _CONTRACTS[pipe_ref].output
        if output.multiplicity is not IOMultiplicity.FIXED:
            pytest.skip("not the fixed arm")
        properties: dict[str, Any] = output.json_schema["properties"]
        elements = next(iter(properties.values()))
        assert elements["minItems"] == output.item_count
        assert elements["maxItems"] == output.item_count
