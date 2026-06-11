"""Tests for the protocol + runner error hierarchy (`mthds.protocol.exceptions`, `mthds.runners.exceptions`)."""

import pytest

from mthds.protocol.exceptions import PipelineRequestError
from mthds.runners.exceptions import (
    ClientAuthenticationError,
    RunFailedError,
    RunStillRunningError,
    RunTimeoutError,
)
from mthds.runners.runs import RunStatus


class TestClientExceptions:
    """Tests for the client exception hierarchy and the run-lifecycle errors."""

    def test_run_failed_error_attributes(self) -> None:
        """RunFailedError carries the run id, terminal status (typed RunStatus), and message."""
        msg = "Run finished with status FAILED; no result available"
        exc = RunFailedError(msg, run_id="run_1", status=RunStatus.FAILED)
        assert exc.run_id == "run_1"
        assert exc.status == RunStatus.FAILED
        assert str(exc) == msg

    def test_run_timeout_error_attributes(self) -> None:
        """RunTimeoutError carries the run id and the timeout it exceeded."""
        msg = "Timed out waiting for run run_1 after 1200.0s; the run is still executing and can be resumed by id"
        exc = RunTimeoutError(msg, run_id="run_1", timeout_seconds=1200.0)
        assert exc.run_id == "run_1"
        assert exc.timeout_seconds == 1200.0
        assert str(exc) == msg

    def test_run_still_running_error_attributes(self) -> None:
        """RunStillRunningError carries the run id and the 202 hints (Retry-After + Location)."""
        msg = "execute() was accepted asynchronously (202): run run_1 is still running server-side."
        exc = RunStillRunningError(msg, run_id="run_1", retry_after_seconds=10, location="/v1/runs/run_1/results")
        assert exc.run_id == "run_1"
        assert exc.retry_after_seconds == 10
        assert exc.location == "/v1/runs/run_1/results"
        assert str(exc) == msg

    @pytest.mark.parametrize(
        ("child_cls", "parent_cls"),
        [
            (RunFailedError, PipelineRequestError),
            (RunTimeoutError, PipelineRequestError),
            (RunStillRunningError, PipelineRequestError),
        ],
    )
    def test_run_errors_subclass_pipeline_request_error(self, child_cls: type, parent_cls: type) -> None:
        """The run-lifecycle errors are PipelineRequestError subclasses so `except PipelineRequestError` catches them."""
        assert issubclass(child_cls, parent_cls)

    def test_catching_pipeline_request_error_catches_run_failed(self) -> None:
        """A RunFailedError is caught by an `except PipelineRequestError` handler."""
        msg = "boom"
        with pytest.raises(PipelineRequestError):
            raise RunFailedError(msg, run_id="run_1", status=RunStatus.CANCELLED)

    def test_client_authentication_error_is_distinct(self) -> None:
        """ClientAuthenticationError is not part of the PipelineRequestError tree."""
        assert not issubclass(ClientAuthenticationError, PipelineRequestError)
