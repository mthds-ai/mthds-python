"""Unit tests for PipelexRunner (local CLI runner)."""

import asyncio

import pytest
from pytest_mock import MockerFixture

from mthds.runners.pipelex.runner import PipelexRunner, PipelexRunnerError


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
