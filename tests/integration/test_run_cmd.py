"""Integration tests for mthds.cli.commands.run_cmd — do_run with mocked runners."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import typer
from pytest_mock import MockerFixture

from mthds.cli.commands.run_cmd import do_run
from mthds.runners.pipelex_runner import PipelexRunnerError


class _FakePipeOutput:
    """Minimal fake pipe output for DictPipelineExecuteResponse."""

    def __init__(self) -> None:
        self.working_memory = {"root": {}, "aliases": {}}
        self.pipeline_run_id = "run-001"


class _FakeExecuteResponse:
    """Minimal fake for DictPipelineExecuteResponse returned by runner.execute_pipeline."""

    def __init__(self) -> None:
        self.pipeline_run_id = "run-001"
        self.created_at = "2026-01-01T00:00:00Z"
        self.pipeline_state = "COMPLETED"
        self.finished_at = "2026-01-01T00:01:00Z"
        self.pipe_output = _FakePipeOutput()
        self.main_stuff_name = "main_stuff"

    def model_dump(self) -> dict[str, Any]:
        return {
            "pipeline_run_id": self.pipeline_run_id,
            "created_at": self.created_at,
            "pipeline_state": self.pipeline_state,
            "finished_at": self.finished_at,
            "pipe_output": {
                "working_memory": self.pipe_output.working_memory,
                "pipeline_run_id": self.pipe_output.pipeline_run_id,
            },
            "main_stuff_name": self.main_stuff_name,
        }


class TestRunCmd:
    """Integration tests for do_run() with mocked runners."""

    @pytest.fixture
    def mock_runner(self) -> AsyncMock:
        """Create a mock runner with an async execute_pipeline method."""
        runner = AsyncMock()
        runner.execute_pipeline.return_value = _FakeExecuteResponse()
        return runner

    @pytest.fixture
    def _patch_create_runner(self, mocker: MockerFixture, mock_runner: AsyncMock) -> None:
        """Patch create_runner to return the mock runner."""
        mocker.patch("mthds.cli.commands.run_cmd.create_runner", return_value=mock_runner)

    @pytest.mark.usefixtures("_patch_create_runner")
    def test_do_run_with_pipe_code(self, mock_runner: AsyncMock) -> None:
        """Providing a pipe code string passes it directly to execute_pipeline."""
        do_run(target="my.domain.pipe_code")

        mock_runner.execute_pipeline.assert_awaited_once_with(
            pipe_code="my.domain.pipe_code",
            mthds_content=None,
            inputs=None,
        )

    @pytest.mark.usefixtures("_patch_create_runner")
    def test_do_run_with_mthds_file(self, tmp_path: Path, mock_runner: AsyncMock) -> None:
        """Providing a .mthds file reads its content and passes mthds_content."""
        mthds_file = tmp_path / "bundle.mthds"
        mthds_file.write_text("pipe_code: test\nsteps:\n  - name: step1", encoding="utf-8")

        do_run(target=str(mthds_file))

        mock_runner.execute_pipeline.assert_awaited_once()
        call_kwargs = mock_runner.execute_pipeline.call_args.kwargs
        assert call_kwargs["pipe_code"] is None
        assert call_kwargs["mthds_content"] == "pipe_code: test\nsteps:\n  - name: step1"
        assert call_kwargs["inputs"] is None

    @pytest.mark.usefixtures("_patch_create_runner")
    def test_do_run_with_inputs_json(self, mock_runner: AsyncMock) -> None:
        """Providing inline JSON inputs parses them and passes to execute_pipeline."""
        do_run(target="some.pipe", inputs_json='{"topic": "AI", "count": 3}')

        mock_runner.execute_pipeline.assert_awaited_once()
        call_kwargs = mock_runner.execute_pipeline.call_args.kwargs
        assert call_kwargs["pipe_code"] == "some.pipe"
        assert call_kwargs["inputs"] == {"topic": "AI", "count": 3}

    @pytest.mark.usefixtures("_patch_create_runner")
    def test_do_run_with_inputs_file(self, tmp_path: Path, mock_runner: AsyncMock) -> None:
        """Providing a JSON inputs file reads it and passes parsed dict to execute_pipeline."""
        inputs_file = tmp_path / "inputs.json"
        inputs_data = {"language": "python", "version": "3.10"}
        inputs_file.write_text(json.dumps(inputs_data), encoding="utf-8")

        do_run(target="some.pipe", inputs_file=str(inputs_file))

        mock_runner.execute_pipeline.assert_awaited_once()
        call_kwargs = mock_runner.execute_pipeline.call_args.kwargs
        assert call_kwargs["inputs"] == {"language": "python", "version": "3.10"}

    def test_do_run_unknown_runner_exits(self, mocker: MockerFixture) -> None:
        """Providing an invalid runner name raises typer.Exit."""
        mocker.patch("mthds.cli.commands.run_cmd.create_runner")

        with pytest.raises(typer.Exit) as exc_info:
            do_run(target="some.pipe", runner="nonexistent")

        assert exc_info.value.exit_code == 1

    @pytest.mark.usefixtures("_patch_create_runner")
    def test_do_run_runner_error_exits(self, mock_runner: AsyncMock) -> None:
        """When the runner raises PipelexRunnerError, do_run catches it and exits."""
        mock_runner.execute_pipeline.side_effect = PipelexRunnerError("pipelex crashed")

        with pytest.raises(typer.Exit) as exc_info:
            do_run(target="some.pipe")

        assert exc_info.value.exit_code == 1
