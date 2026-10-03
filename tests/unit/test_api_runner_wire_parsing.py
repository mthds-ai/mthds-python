"""Unit tests for parsing `/v1/execute` 200 bodies and hosted working memories into the Dict wire models."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mthds.runners.api.models import DictRunResultExecute, DictWorkingMemoryAbstract
from tests.unit.test_data import ExecuteWireResponses, HostedRunCapture

_CAPTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "hosted_run" / HostedRunCapture.FILE_NAME


def _load_hosted_capture() -> dict[str, Any]:
    with _CAPTURE_PATH.open(encoding="utf-8") as capture_file:
        capture: dict[str, Any] = json.load(capture_file)
    return capture


class TestDictRunResultExecuteWireParsing:
    def test_hosted_capture_names_every_concept_by_its_ref(self) -> None:
        """A working memory the hosted plane really delivered parses, and every stuff in it
        carries its concept as the ref string — native, refining and structured concepts alike.
        """
        working_memory = DictWorkingMemoryAbstract.model_validate(_load_hosted_capture())

        concept_refs = {slot_name: stuff.concept for slot_name, stuff in working_memory.root.items()}
        assert concept_refs == HostedRunCapture.EXPECTED_CONCEPT_REFS
        for stuff in working_memory.root.values():
            assert stuff.concept_ref == stuff.concept
            assert stuff.model_extra is not None
            assert set(stuff.model_extra) == HostedRunCapture.EXTENSION_FIELDS
        assert working_memory.aliases == {"main_stuff": HostedRunCapture.MAIN_STUFF_SLOT}
        assert working_memory.model_extra == {"absences": {}}

    def test_hosted_full_dump_parses(self) -> None:
        """The hosted runner's enriched shape (full PipeOutput dump) validates, with `concept`
        as the ref string.
        """
        result = DictRunResultExecute.model_validate(ExecuteWireResponses.HOSTED_FULL_DUMP)

        assert result.pipeline_run_id == "run_7f3a"
        main = result.pipe_output.working_memory.root["extracted_entities"]
        assert main.concept == "extract_entities.ExtractedEntities"
        assert main.concept_ref == "extract_entities.ExtractedEntities"
        assert main.content == {"entities": [{"name": "Marie Curie", "kind": "person"}]}

    def test_hosted_extras_ride_model_extra(self) -> None:
        """Extension fields land in model_extra at every level — top-level run state,
        pipe-output artifacts, the working memory's absences and per-stuff naming.
        """
        result = DictRunResultExecute.model_validate(ExecuteWireResponses.HOSTED_FULL_DUMP)

        assert result.model_extra is not None
        assert result.model_extra["state"] == "COMPLETED"
        assert result.pipe_output.model_extra is not None
        assert result.pipe_output.model_extra["graph_spec"] == {"nodes": [], "edges": []}
        assert result.pipe_output.model_extra["tokens_usages"] == []
        assert result.pipe_output.working_memory.model_extra == {"absences": {}}
        main = result.pipe_output.working_memory.root["extracted_entities"]
        assert main.model_extra == {"stuff_code": "e5f6a7b8", "stuff_name": "extracted_entities"}

    def test_hosted_dump_keeps_content_reachable(self) -> None:
        """`pipe_output.model_dump()` keeps the consumer path
        `["working_memory"]["root"][*]["content"]` reachable (the shape
        `pipelex-sdk`'s RunResults mapping and its consumers depend on).
        """
        result = DictRunResultExecute.model_validate(ExecuteWireResponses.HOSTED_FULL_DUMP)

        dumped = result.pipe_output.model_dump()
        content = dumped["working_memory"]["root"]["extracted_entities"]["content"]
        assert content == {"entities": [{"name": "Marie Curie", "kind": "person"}]}
        # Extras survive the dump too.
        assert dumped["working_memory"]["root"]["extracted_entities"]["stuff_code"] == "e5f6a7b8"
        assert dumped["graph_spec"] == {"nodes": [], "edges": []}

    def test_reduced_form_parses(self) -> None:
        """The SDK's own reduced form (base fields only) validates."""
        result = DictRunResultExecute.model_validate(ExecuteWireResponses.REDUCED)

        main = result.pipe_output.working_memory.root["extracted_entities"]
        assert main.concept == "extract_entities.ExtractedEntities"
        assert main.concept_ref == "extract_entities.ExtractedEntities"
        assert main.model_extra == {}

    def test_concept_object_is_refused(self) -> None:
        """A stuff carrying the concept's definition in place of its ref is refused, and the
        error names the `concept` of that stuff rather than the body as a whole.
        """
        with pytest.raises(ValidationError) as exc_info:
            DictRunResultExecute.model_validate(ExecuteWireResponses.CONCEPT_OBJECT)

        errors = exc_info.value.errors()
        assert [(error["loc"], error["type"]) for error in errors] == [
            (("pipe_output", "working_memory", "root", "extracted_entities", "concept"), "string_type"),
        ]
