"""Tests for mthds.runners.registry — create_runner factory."""

import pytest
from pytest_mock import MockerFixture

from mthds.runners.api_runner import ApiRunner
from mthds.runners.pipelex_runner import PipelexRunner
from mthds.runners.registry import create_runner
from mthds.runners.types import RunnerType


class TestRunners:
    """Tests for the create_runner factory function."""

    def test_create_runner_api_explicit(self) -> None:
        """Passing RunnerType.API explicitly returns an ApiRunner."""
        runner = create_runner(RunnerType.API)
        assert isinstance(runner, ApiRunner)
        assert runner.runner_type == RunnerType.API

    def test_create_runner_pipelex_when_available(self, mocker: MockerFixture) -> None:
        """Passing RunnerType.PIPELEX returns PipelexRunner when pipelex is on PATH."""
        mocker.patch("mthds.runners.registry.shutil.which", return_value="/usr/local/bin/pipelex")

        runner = create_runner(RunnerType.PIPELEX)
        assert isinstance(runner, PipelexRunner)
        assert runner.runner_type == RunnerType.PIPELEX

    def test_create_runner_pipelex_falls_back_to_api(self, mocker: MockerFixture) -> None:
        """When pipelex is not on PATH, RunnerType.PIPELEX falls back to ApiRunner."""
        mocker.patch("mthds.runners.registry.shutil.which", return_value=None)

        runner = create_runner(RunnerType.PIPELEX)
        assert isinstance(runner, ApiRunner)
        assert runner.runner_type == RunnerType.API

    def test_create_runner_none_reads_credentials_api(self, mocker: MockerFixture) -> None:
        """When runner_type is None, reads from credentials; 'api' yields ApiRunner."""
        mocker.patch(
            "mthds.runners.registry.load_credentials",
            return_value={"runner": "api", "api_url": "", "api_key": "", "telemetry": "0"},
        )

        runner = create_runner(None)
        assert isinstance(runner, ApiRunner)

    def test_create_runner_none_reads_credentials_pipelex(self, mocker: MockerFixture) -> None:
        """When runner_type is None and credentials say 'pipelex', returns PipelexRunner if available."""
        mocker.patch(
            "mthds.runners.registry.load_credentials",
            return_value={"runner": "pipelex", "api_url": "", "api_key": "", "telemetry": "0"},
        )
        mocker.patch("mthds.runners.registry.shutil.which", return_value="/usr/local/bin/pipelex")

        runner = create_runner(None)
        assert isinstance(runner, PipelexRunner)

    def test_create_runner_none_invalid_configured_value_falls_back_to_api(self, mocker: MockerFixture) -> None:
        """When credentials contain an invalid runner value, fall back to ApiRunner."""
        mocker.patch(
            "mthds.runners.registry.load_credentials",
            return_value={"runner": "unknown_runner", "api_url": "", "api_key": "", "telemetry": "0"},
        )

        runner = create_runner(None)
        assert isinstance(runner, ApiRunner)

    @pytest.mark.parametrize(
        ("runner_type", "expected_class"),
        [
            (RunnerType.API, ApiRunner),
            (RunnerType.PIPELEX, ApiRunner),  # pipelex not on PATH -> fallback
        ],
    )
    def test_create_runner_explicit_types_no_pipelex(
        self,
        mocker: MockerFixture,
        runner_type: RunnerType,
        expected_class: type,
    ) -> None:
        """Both explicit types return ApiRunner when pipelex is not on PATH."""
        mocker.patch("mthds.runners.registry.shutil.which", return_value=None)

        runner = create_runner(runner_type)
        assert isinstance(runner, expected_class)
