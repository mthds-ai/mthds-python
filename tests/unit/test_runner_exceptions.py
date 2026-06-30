"""Tests for the protocol + runner error hierarchy (`mthds.protocol.exceptions`, `mthds.runners.api.exceptions`)."""

import pytest

from mthds.protocol.exceptions import PipelineRequestError
from mthds.runners.api.exceptions import ClientAuthenticationError, RunStillRunningError


class TestClientExceptions:
    """Tests for the client exception hierarchy and the protocol 202-degrade error."""

    def test_run_still_running_error_attributes(self) -> None:
        """RunStillRunningError carries the run id and the 202 hints (Retry-After + Location)."""
        msg = "execute() was accepted asynchronously (202): run run_1 is still running server-side."
        exc = RunStillRunningError(msg, run_id="run_1", retry_after_seconds=10, location="/v1/runs/run_1/results")
        assert exc.run_id == "run_1"
        assert exc.retry_after_seconds == 10
        assert exc.location == "/v1/runs/run_1/results"
        assert str(exc) == msg

    def test_run_still_running_error_subclasses_pipeline_request_error(self) -> None:
        """RunStillRunningError is a PipelineRequestError subclass so `except PipelineRequestError` catches it."""
        assert issubclass(RunStillRunningError, PipelineRequestError)

    def test_catching_pipeline_request_error_catches_run_still_running(self) -> None:
        """A RunStillRunningError is caught by an `except PipelineRequestError` handler."""
        msg = "boom"
        with pytest.raises(PipelineRequestError):
            raise RunStillRunningError(msg, run_id="run_1")

    def test_client_authentication_error_is_distinct(self) -> None:
        """ClientAuthenticationError is not part of the PipelineRequestError tree."""
        assert not issubclass(ClientAuthenticationError, PipelineRequestError)
