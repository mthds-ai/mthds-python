"""Integration tests for mthds.cli.commands.build_cmd — build subcommands with mocked subprocess."""

import pytest
import typer
from pytest_mock import MockerFixture

from mthds.cli.commands.build_cmd import (
    do_build_inputs,
    do_build_output,
    do_build_pipe,
    do_build_runner,
)


class TestBuildCmd:
    """Integration tests for build command functions with mocked pipelex subprocess."""

    def test_build_pipe_delegates_to_pipelex(self, mocker: MockerFixture) -> None:
        """do_build_pipe calls run_subprocess with correct pipelex build pipe args."""
        mocker.patch("mthds.cli.commands.build_cmd.shutil.which", return_value="/usr/local/bin/pipelex")
        mock_run = mocker.patch("mthds.cli.commands.build_cmd.run_subprocess")

        do_build_pipe(brief="generate a summary report")

        mock_run.assert_called_once_with(["pipelex", "build", "pipe", "generate a summary report"])

    def test_build_pipe_no_pipelex_exits(self, mocker: MockerFixture) -> None:
        """do_build_pipe exits when pipelex is not on PATH."""
        mocker.patch("mthds.cli.commands.build_cmd.shutil.which", return_value=None)

        with pytest.raises(typer.Exit) as exc_info:
            do_build_pipe(brief="anything")

        assert exc_info.value.exit_code == 1

    def test_build_runner_with_pipe_code(self, mocker: MockerFixture) -> None:
        """do_build_runner includes --pipe flag when pipe_code is provided."""
        mocker.patch("mthds.cli.commands.build_cmd.shutil.which", return_value="/usr/local/bin/pipelex")
        mock_run = mocker.patch("mthds.cli.commands.build_cmd.run_subprocess")

        do_build_runner(target="bundle.mthds", pipe_code="my.pipe")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["pipelex", "build", "runner", "bundle.mthds", "--pipe", "my.pipe"]

    def test_build_runner_without_pipe_code(self, mocker: MockerFixture) -> None:
        """do_build_runner omits --pipe flag when pipe_code is None."""
        mocker.patch("mthds.cli.commands.build_cmd.shutil.which", return_value="/usr/local/bin/pipelex")
        mock_run = mocker.patch("mthds.cli.commands.build_cmd.run_subprocess")

        do_build_runner(target="bundle.mthds")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["pipelex", "build", "runner", "bundle.mthds"]
        assert "--pipe" not in cmd

    def test_build_inputs_delegates_correctly(self, mocker: MockerFixture) -> None:
        """do_build_inputs passes correct args including --pipe flag."""
        mocker.patch("mthds.cli.commands.build_cmd.shutil.which", return_value="/usr/local/bin/pipelex")
        mock_run = mocker.patch("mthds.cli.commands.build_cmd.run_subprocess")

        do_build_inputs(target="bundle.mthds", pipe_code="my.pipe")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["pipelex", "build", "inputs", "bundle.mthds", "--pipe", "my.pipe"]

    def test_build_output_with_format(self, mocker: MockerFixture) -> None:
        """do_build_output includes --format flag in the command."""
        mocker.patch("mthds.cli.commands.build_cmd.shutil.which", return_value="/usr/local/bin/pipelex")
        mock_run = mocker.patch("mthds.cli.commands.build_cmd.run_subprocess")

        do_build_output(target="bundle.mthds", pipe_code="my.pipe", fmt="json")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd == ["pipelex", "build", "output", "bundle.mthds", "--pipe", "my.pipe", "--format", "json"]

    def test_build_output_default_format(self, mocker: MockerFixture) -> None:
        """do_build_output defaults to 'schema' format when not specified."""
        mocker.patch("mthds.cli.commands.build_cmd.shutil.which", return_value="/usr/local/bin/pipelex")
        mock_run = mocker.patch("mthds.cli.commands.build_cmd.run_subprocess")

        do_build_output(target="bundle.mthds", pipe_code="my.pipe")

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--format" in cmd
        format_index = cmd.index("--format")
        assert cmd[format_index + 1] == "schema"

    def test_resolve_runner_api_not_supported(self, mocker: MockerFixture) -> None:
        """runner='api' for build operations exits with exit code 1."""
        mocker.patch("mthds.cli.commands.build_cmd.shutil.which", return_value="/usr/local/bin/pipelex")

        with pytest.raises(typer.Exit) as exc_info:
            do_build_pipe(brief="anything", runner="api")

        assert exc_info.value.exit_code == 1

    def test_resolve_runner_unknown_exits(self, mocker: MockerFixture) -> None:
        """An unknown runner name for build operations exits with exit code 1."""
        mocker.patch("mthds.cli.commands.build_cmd.shutil.which", return_value="/usr/local/bin/pipelex")

        with pytest.raises(typer.Exit) as exc_info:
            do_build_pipe(brief="anything", runner="nonexistent")

        assert exc_info.value.exit_code == 1
