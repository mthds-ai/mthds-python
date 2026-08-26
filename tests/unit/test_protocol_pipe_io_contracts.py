"""Parity and strictness tests for `mthds.protocol.pipe_io_contracts` against the engine-produced fixture.

The fixture `tests/fixtures/protocol/pipe_io_contracts.json` is the reference engine's own emission,
committed byte-for-byte here and in `mthds-js` (its README carries the provenance). It is parsed the
way the artifact actually arrives: as a typed field declared on a model narrowing the validate
report — pydantic parses the whole map from the plain annotation, no adapter machinery involved.
Every entry must parse under the closed shapes — `extra="forbid"` on every model is what makes the
parse a real check — and dump back to exactly the input: on this artifact `item_count` is always on
the wire, `null` off the fixed arm, and a plain dump keeps it there.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from mthds.protocol.pipe_io_contracts import IOMultiplicity, PipeInputContract, PipeIOContract, PipeIOContracts, PipeOutputContract, PresenceMarker
from tests.unit.test_data import PipeIOContractWireNodes


class NarrowedValidateReport(BaseModel):
    """How the artifact arrives: a typed field on a model narrowing the validate report.

    `pipelex-sdk-python` declares exactly this field (as `PipeIOContracts | None`) on its own report
    narrowing at Stage 3.4; a plain field annotation is the whole parse path.
    """

    model_config = ConfigDict(extra="forbid")

    pipe_io_contracts: PipeIOContracts


_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "protocol" / "pipe_io_contracts.json"
_RAW: dict[str, Any] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
_REPORT = NarrowedValidateReport.model_validate({"pipe_io_contracts": _RAW})
_CONTRACTS = _REPORT.pipe_io_contracts


class TestPipeIOContractsProtocolModels:
    @pytest.mark.parametrize("pipe_ref", [pytest.param(pipe_ref, id=pipe_ref) for pipe_ref in _RAW])
    def test_fixture_entry_parses_strictly_and_round_trips(self, pipe_ref: str) -> None:
        """Each per-pipe contract parses under the closed shapes and dumps back to the exact input."""
        contract = PipeIOContract.model_validate(_RAW[pipe_ref])
        assert contract.model_dump(mode="json") == _RAW[pipe_ref]
        assert json.loads(contract.model_dump_json()) == _RAW[pipe_ref]

    def test_whole_artifact_round_trips(self) -> None:
        """Parsed as the typed field it rides in on, the whole payload dumps back unchanged."""
        assert list(_CONTRACTS) == list(_RAW)
        assert _REPORT.model_dump(mode="json") == {"pipe_io_contracts": _RAW}
        assert json.loads(_REPORT.model_dump_json()) == {"pipe_io_contracts": _RAW}

    def test_item_count_is_always_on_the_wire(self) -> None:
        """`item_count` rides every input and output contract, `null` off the fixed arm, even through a plain dump."""
        dumped = _REPORT.model_dump(mode="json")["pipe_io_contracts"]
        for pipe_ref, entry in dumped.items():
            assert "item_count" in entry["output"], pipe_ref
            for input_name, input_contract in entry["inputs"].items():
                assert "item_count" in input_contract, f"{pipe_ref}.{input_name}"
        opt = dumped["input_semantics_probe.probe_markers"]["inputs"]["opt"]
        assert opt["item_count"] is None
        assert dumped["input_semantics_probe.probe_markers"]["output"]["item_count"] is None

    def test_presence_and_multiplicity_are_read_together(self) -> None:
        """The three presence values, the three multiplicities, and the item-count pair are stated as authored."""
        markers = _CONTRACTS["input_semantics_probe.probe_markers"]
        assert list(markers.inputs) == ["opt", "many", "two", "forced"]

        opt = markers.inputs["opt"]
        assert opt.concept_ref == "input_semantics_probe.Widget"
        assert opt.presence is PresenceMarker.OPTIONAL
        assert opt.presence.is_optional is True
        assert opt.multiplicity is IOMultiplicity.SINGLE
        assert opt.item_count is None
        assert opt.json_schema["type"] == "object"

        many = markers.inputs["many"]
        assert many.presence is PresenceMarker.PLAIN
        assert many.multiplicity is IOMultiplicity.VARIABLE
        assert many.multiplicity.is_plural is True
        assert many.item_count is None
        assert many.json_schema["type"] == "array"
        assert "minItems" not in many.json_schema

        two = markers.inputs["two"]
        assert two.concept_ref == "input_semantics_probe.Gadget"
        assert two.multiplicity is IOMultiplicity.FIXED
        assert two.item_count == 2
        assert two.json_schema["type"] == "array"
        assert two.json_schema["minItems"] == 2
        assert two.json_schema["maxItems"] == 2

        forced = markers.inputs["forced"]
        assert forced.concept_ref == "native.Text"
        assert forced.presence is PresenceMarker.FORCE
        assert forced.presence.is_optional is False

        output = markers.output
        assert output.concept_ref == "native.Text"
        assert output.multiplicity is IOMultiplicity.SINGLE
        assert output.item_count is None
        assert output.optional is False

    def test_every_pipe_has_an_entry_with_both_members(self) -> None:
        """Keys are namespaced pipe refs, and every entry states `inputs` and `output`."""
        for pipe_ref, contract in _CONTRACTS.items():
            domain, pipe_code = pipe_ref.rsplit(".", 1)
            assert domain
            assert pipe_code
            assert isinstance(contract.output, PipeOutputContract)
            for input_contract in contract.inputs.values():
                assert isinstance(input_contract, PipeInputContract)
                assert "." in input_contract.concept_ref
        natives = _CONTRACTS["input_semantics_probe.probe_native_inputs"].inputs
        assert list(natives) == ["text_in", "image_in", "document_in", "page_in", "number_in", "date_in", "time_in", "html_in", "yesno_in"]
        assert natives["document_in"].concept_ref == "native.Document"

    @pytest.mark.parametrize(
        "node",
        [
            pytest.param(PipeIOContractWireNodes.INPUT_UNKNOWN_MEMBER, id="unknown member on an input"),
            pytest.param(PipeIOContractWireNodes.INPUT_ITEM_COUNT_MISSING, id="item_count omitted"),
            pytest.param(PipeIOContractWireNodes.INPUT_FIXED_WITHOUT_COUNT, id="fixed without a count"),
            pytest.param(PipeIOContractWireNodes.INPUT_SINGLE_WITH_COUNT, id="single with a count"),
            pytest.param(PipeIOContractWireNodes.INPUT_FIXED_COUNT_OF_ONE, id="fixed with a count of one"),
            pytest.param(PipeIOContractWireNodes.INPUT_UNKNOWN_PRESENCE, id="presence outside the vocabulary"),
            pytest.param(PipeIOContractWireNodes.INPUT_VARIABLE_OPTIONAL, id="variable marked optional"),
            pytest.param(PipeIOContractWireNodes.INPUT_FIXED_FORCED, id="fixed marked forced"),
        ],
    )
    def test_input_contract_is_a_closed_shape(self, node: dict[str, Any]) -> None:
        """A member the standard does not define, an omitted member, or a broken pair rule fails the parse."""
        with pytest.raises(ValidationError):
            PipeInputContract.model_validate(node)

    @pytest.mark.parametrize(
        "node",
        [
            pytest.param(PipeIOContractWireNodes.OUTPUT_UNKNOWN_MEMBER, id="schema on an output"),
            pytest.param(PipeIOContractWireNodes.OUTPUT_FIXED_WITHOUT_COUNT, id="fixed without a count"),
            pytest.param(PipeIOContractWireNodes.OUTPUT_FIXED_OPTIONAL, id="fixed marked optional"),
        ],
    )
    def test_output_contract_is_a_closed_shape(self, node: dict[str, Any]) -> None:
        """An output carries no schema, obeys the same item-count pair rule as an input, and is plural or optional but never both."""
        with pytest.raises(ValidationError):
            PipeOutputContract.model_validate(node)

    @pytest.mark.parametrize(
        "node",
        [
            pytest.param(PipeIOContractWireNodes.ENTRY_WITHOUT_INPUTS, id="inputs omitted"),
            pytest.param(PipeIOContractWireNodes.ENTRY_UNKNOWN_MEMBER, id="unknown member on an entry"),
        ],
    )
    def test_entry_is_a_closed_shape_with_both_members(self, node: dict[str, Any]) -> None:
        """An entry names both `inputs` and `output` and nothing else."""
        with pytest.raises(ValidationError):
            PipeIOContract.model_validate(node)

    def test_accepted_edges(self) -> None:
        """An empty input map is a stated fact, and a single optional output carries its flag with a null count."""
        entry = PipeIOContract.model_validate(PipeIOContractWireNodes.ENTRY_WITHOUT_DECLARED_INPUTS)
        assert entry.inputs == {}
        assert entry.model_dump()["inputs"] == {}
        output = PipeOutputContract.model_validate(PipeIOContractWireNodes.OUTPUT_SINGLE_OPTIONAL)
        assert output.multiplicity is IOMultiplicity.SINGLE
        assert output.item_count is None
        assert output.optional is True
