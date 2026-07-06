"""Unit tests for parsing `/v1/execute` 200 bodies into DictRunResultExecute — both wire forms."""

from mthds.runners.api.models import DictConcept, DictRunResultExecute
from tests.unit.test_data import ExecuteWireResponses


class TestDictRunResultExecuteWireParsing:
    def test_hosted_full_dump_parses(self) -> None:
        """The hosted runner's enriched shape (full PipeOutput dump) validates:
        per-stuff and pipe-output extras ride model_extra instead of being
        rejected, and `concept` parses as the full object form.
        """
        result = DictRunResultExecute.model_validate(ExecuteWireResponses.HOSTED_FULL_DUMP)

        assert result.pipeline_run_id == "run_7f3a"
        main = result.pipe_output.working_memory.root["extracted_entities"]
        assert isinstance(main.concept, DictConcept)
        assert main.concept.code == "ExtractedEntities"
        assert main.concept_ref == "extract_entities.ExtractedEntities"
        assert main.content == {"entities": [{"name": "Marie Curie", "kind": "person"}]}

    def test_hosted_extras_ride_model_extra(self) -> None:
        """Extension fields land in model_extra at every level — top-level run
        state, pipe-output artifacts, per-stuff naming, and concept details.
        """
        result = DictRunResultExecute.model_validate(ExecuteWireResponses.HOSTED_FULL_DUMP)

        assert result.model_extra is not None
        assert result.model_extra["state"] == "COMPLETED"
        assert result.pipe_output.model_extra is not None
        assert result.pipe_output.model_extra["graph_spec"] == {"nodes": [], "edges": []}
        assert result.pipe_output.model_extra["tokens_usages"] == []
        main = result.pipe_output.working_memory.root["extracted_entities"]
        assert main.model_extra is not None
        assert main.model_extra["stuff_code"] == "e5f6a7b8"
        assert main.model_extra["stuff_name"] == "extracted_entities"
        assert isinstance(main.concept, DictConcept)
        assert main.concept.model_extra is not None
        assert main.concept.model_extra["structure_class_name"] == "extract_entities__ExtractedEntities"

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
        """The SDK's own reduced form (`concept` as the ref string) still
        validates, and `concept_ref` normalizes both wire forms to the same ref.
        """
        result = DictRunResultExecute.model_validate(ExecuteWireResponses.REDUCED)

        main = result.pipe_output.working_memory.root["extracted_entities"]
        assert main.concept == "extract_entities.ExtractedEntities"
        assert main.concept_ref == "extract_entities.ExtractedEntities"
