"""Unit tests for mthds.runners.api.models — the SDK's dict-serialized wire models."""

from typing import Any

from mthds.protocol.concept import ConceptAbstract
from mthds.protocol.pipe_output import PipeOutputAbstract
from mthds.protocol.stuff import StuffAbstract, StuffContentAbstract
from mthds.protocol.working_memory import WorkingMemoryAbstract
from mthds.runners.api.models import MAIN_STUFF_NAME, DictRunResultExecute


class _StubContent(StuffContentAbstract):
    value: str


class _StubConcept(ConceptAbstract):
    pass


class _StubStuff(StuffAbstract[_StubConcept, _StubContent]):
    pass


class _StubWorkingMemory(WorkingMemoryAbstract[_StubStuff]):
    pass


class _StubPipeOutput(PipeOutputAbstract[_StubWorkingMemory]):
    pass


def _pipe_output_with_run_id(run_id: str) -> Any:
    """A minimal pipe-output stub carrying a non-empty pipeline_run_id."""
    return _StubPipeOutput(
        working_memory=_StubWorkingMemory(
            root={
                "main": _StubStuff(
                    stuff_code="stuff_1",
                    concept=_StubConcept(code="Answer", domain_code="answer"),
                    content=_StubContent(value="42"),
                )
            },
            aliases={MAIN_STUFF_NAME: "main"},
        ),
        pipeline_run_id=run_id,
    )


class TestDictRunResultExecuteFromPipeOutput:
    def test_top_level_run_id_falls_back_to_pipe_output_run_id(self) -> None:
        """When the optional `pipeline_run_id` arg is omitted (default ""),
        the top-level field falls back to `pipe_output.pipeline_run_id` —
        otherwise the SDK would drop a real run id that lives on the nested
        object (greptile P2 / cubic P2 on PR #26).
        """
        pipe_output = _pipe_output_with_run_id("run_42")

        result = DictRunResultExecute.from_pipe_output(pipe_output=pipe_output)

        assert result.pipeline_run_id == "run_42"
        assert result.pipe_output.pipeline_run_id == "run_42"

    def test_explicit_run_id_arg_takes_precedence(self) -> None:
        """An explicit `pipeline_run_id` arg overrides whatever the pipe
        output carries — the caller is the authority.
        """
        pipe_output = _pipe_output_with_run_id("run_old")

        result = DictRunResultExecute.from_pipe_output(pipe_output=pipe_output, pipeline_run_id="run_new")

        assert result.pipeline_run_id == "run_new"
        # The nested object is preserved verbatim — only the top-level field is the authoritative one.
        assert result.pipe_output.pipeline_run_id == "run_old"

    def test_main_stuff_name_extension_passes_through(self) -> None:
        """`main_stuff_name` rides the protocol's extension-open response via
        model_extra (it is not a typed protocol field).
        """
        pipe_output = _pipe_output_with_run_id("run_1")

        result = DictRunResultExecute.from_pipe_output(pipe_output=pipe_output)

        assert result.model_extra is not None
        assert result.model_extra["main_stuff_name"] == "main"

    def test_concept_is_reduced_to_its_ref_string(self) -> None:
        """The wire model carries the concept as `<domain>.<Code>` — the reduction this path
        performs is `concept_ref`, the same property the protocol's field serializer delegates to.
        """
        result = DictRunResultExecute.from_pipe_output(pipe_output=_pipe_output_with_run_id("run_1"))

        assert result.pipe_output.working_memory.root["main"].concept == "answer.Answer"
