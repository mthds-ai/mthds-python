"""Unit tests for PipelexRunner (local CLI runner)."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic import BaseModel, ValidationError
from pytest_mock import MockerFixture

from mthds.runners.pipelex.runner import PipelexRunner, PipelexRunnerError
from tests.unit.test_data import CliWorkingMemoryDumps

if TYPE_CHECKING:
    from mthds.protocol.pipeline_inputs import PipelineInputs


class _PydanticInput(BaseModel):
    question: str
    score: float


class TestPipelexRunner:
    def test_validate_empty_contents_raises_without_invoking_cli(self, mocker: MockerFixture) -> None:
        """An empty `mthds_contents` must fail fast — validating an empty temp
        directory would otherwise return a passing `ValidationReport()` for a
        request that validated nothing (greptile P1 on PR #25; the API path
        treats empty input as a validation failure, so the local runner must
        match). The CLI is never invoked.
        """
        mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
        run_subprocess = mocker.patch("mthds.runners.pipelex.runner.run_subprocess")

        with pytest.raises(PipelexRunnerError, match="at least one bundle"):
            asyncio.run(PipelexRunner().validate(mthds_contents=[]))

        run_subprocess.assert_not_called()

    @pytest.mark.parametrize(
        ("kwargs", "expected_in_message"),
        [
            ({"output_name": "result"}, "output_name"),
            ({"output_multiplicity": 3}, "output_multiplicity"),
            ({"dynamic_output_concept_ref": "answer.Answer"}, "dynamic_output_concept_ref"),
        ],
    )
    def test_execute_rejects_unsupported_output_args(self, mocker: MockerFixture, kwargs: dict[str, Any], expected_in_message: str) -> None:
        """The CLI runner cannot honor protocol output args; it must fail fast
        instead of silently dropping them (greptile P1 on PR #26).
        """
        mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
        run_subprocess = mocker.patch("mthds.runners.pipelex.runner.run_subprocess")

        with pytest.raises(PipelexRunnerError, match=expected_in_message):
            asyncio.run(PipelexRunner().execute(pipe_code="answer", **kwargs))

        run_subprocess.assert_not_called()

    def test_execute_rejects_missing_target(self, mocker: MockerFixture) -> None:
        """With neither pipe_code nor mthds_contents the CLI invocation would
        be malformed; the runner must reject upfront for parity with the API
        runner (greptile P2 on PR #26).
        """
        mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
        run_subprocess = mocker.patch("mthds.runners.pipelex.runner.run_subprocess")

        with pytest.raises(PipelexRunnerError, match="pipe_code or mthds_contents"):
            asyncio.run(PipelexRunner().execute())

        run_subprocess.assert_not_called()

    def test_execute_serializes_pydantic_inputs(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Inputs may carry pydantic BaseModel values (StuffContent, etc.); a
        plain json.dumps would TypeError. The runner uses pydantic-aware
        serialization so the same protocol input that works through the API
        runner also works locally (greptile P1 on PR #26).
        """
        mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
        # Pin tempfile to a controllable directory we can read back from.
        mocker.patch("mthds.runners.pipelex.runner.tempfile.mkdtemp", return_value=str(tmp_path))
        captured: dict[str, list[str]] = {}

        def capture(cmd: list[str], **_kwargs: Any) -> Any:
            captured["cmd"] = cmd
            # Mock a working memory file so the post-call read succeeds.
            (tmp_path / "working_memory.json").write_text('{"root": {}, "aliases": {}}', encoding="utf-8")

            class _Result:
                returncode = 0
                stdout = b""
                stderr = b""

            return _Result()

        mocker.patch("mthds.runners.pipelex.runner.run_subprocess", side_effect=capture)
        # rmtree on a tmp_path under pytest's tmp is fine; the cleanup happens after we read the inputs file.
        mocker.patch("mthds.runners.pipelex.runner.shutil.rmtree")

        payload = _PydanticInput(question="why?", score=0.5)
        asyncio.run(PipelexRunner().execute(pipe_code="answer", inputs=cast("PipelineInputs", {"input": payload})))

        inputs_path = tmp_path / "inputs.json"
        assert inputs_path.exists()
        on_disk = json.loads(inputs_path.read_text(encoding="utf-8"))
        assert on_disk == {"input": {"question": "why?", "score": 0.5}}

    def test_execute_maps_the_cli_working_memory(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """The working memory the CLI writes maps onto the wire shape: each stuff keeps its
        concept ref and its content, and its runtime fields are dropped.
        """
        _patch_cli_writing_working_memory(mocker, tmp_path, CliWorkingMemoryDumps.REF_STRING)

        result = asyncio.run(PipelexRunner().execute(pipe_code="answer"))

        answer = result.pipe_output.working_memory.root["answer"]
        assert answer.concept == "answer.Answer"
        assert answer.content == {"text": "Because."}
        assert answer.model_extra == {}
        assert result.model_extra is not None
        assert result.model_extra["main_stuff_name"] == "answer"

    @pytest.mark.parametrize(
        ("topic", "malformed_stuff"),
        CliWorkingMemoryDumps.MALFORMED_CONCEPT_CASES,
    )
    def test_execute_refuses_a_stuff_without_a_concept_ref(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        topic: str,
        malformed_stuff: dict[str, Any],
    ) -> None:
        """A stuff whose concept is not its ref string fails validation at that stuff's `concept`,
        as on the API path, instead of reaching the caller under an invented ref.
        """
        working_memory = {"root": {"answer": malformed_stuff}, "aliases": {"main_stuff": "answer"}}
        _patch_cli_writing_working_memory(mocker, tmp_path, working_memory)

        with pytest.raises(ValidationError) as exc_info:
            asyncio.run(PipelexRunner().execute(pipe_code="answer"))

        errors = exc_info.value.errors()
        assert [(error["loc"], error["type"]) for error in errors] == [(("root", "answer", "concept"), "string_type")], topic


def _patch_cli_writing_working_memory(mocker: MockerFixture, tmp_path: Path, working_memory: dict[str, Any]) -> None:
    """Stand in for the `pipelex` CLI: a run that succeeds and writes `working_memory` where it was asked to."""
    mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
    mocker.patch("mthds.runners.pipelex.runner.tempfile.mkdtemp", return_value=str(tmp_path))
    mocker.patch("mthds.runners.pipelex.runner.shutil.rmtree")

    def write_working_memory(cmd: list[str], **_kwargs: Any) -> Any:
        working_memory_path = Path(cmd[cmd.index("--working-memory-path") + 1])
        working_memory_path.write_text(json.dumps(working_memory), encoding="utf-8")
        return mocker.Mock(returncode=0)

    mocker.patch("mthds.runners.pipelex.runner.run_subprocess", side_effect=write_working_memory)
