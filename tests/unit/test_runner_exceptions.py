"""Tests for the protocol + runner error hierarchy (`mthds.protocol.exceptions`, `mthds.runners.api.exceptions`)."""

import httpx
import pytest

from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.models import ValidationDiagnostic
from mthds.runners.api.exceptions import ApiResponseError, ClientAuthenticationError, RunStillRunningError
from mthds.runners.api.problem import UserAction


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

    def test_api_response_error_is_a_pipeline_request_error_and_not_httpx(self) -> None:
        """A non-2xx answer is caught by `except PipelineRequestError`, and no longer by httpx's HTTPStatusError."""
        assert issubclass(ApiResponseError, PipelineRequestError)
        assert not issubclass(ApiResponseError, httpx.HTTPStatusError)

    @pytest.mark.parametrize(
        ("topic", "message", "user_action", "expected"),
        [
            ("no next step", "API POST /v1/start failed (401): Invalid API key", None, "API POST /v1/start failed (401): Invalid API key"),
            (
                "next step on its own line",
                "API POST /v1/start failed (422): Model handle 'gpt-5.1' was not found",
                UserAction(kind="change_model", detail="Change the model 'gpt-5.1'."),
                "API POST /v1/start failed (422): Model handle 'gpt-5.1' was not found\nNext step: Change the model 'gpt-5.1'.",
            ),
            (
                "next step already said",
                "API POST /v1/start failed (422): The field is single. Declare it as a list.",
                UserAction(kind="change_input", detail="Declare it as a list."),
                "API POST /v1/start failed (422): The field is single. Declare it as a list.",
            ),
        ],
    )
    def test_api_response_error_message_ends_with_the_next_step(
        self, topic: str, message: str, user_action: UserAction | None, expected: str
    ) -> None:
        """`str()` is the message, then the advised next step unless the message already carries it."""
        exc = ApiResponseError(
            message, api_url="http://localhost:8081", status=422, status_text="Unprocessable Entity", response_body="", user_action=user_action
        )
        assert str(exc) == expected, topic

    def test_api_response_error_attributes(self) -> None:
        """Every member passed at construction is kept as given, and an unstated one is None."""
        items = [ValidationDiagnostic(category="pipe_validation", message="bad model")]
        exc = ApiResponseError(
            "API POST /v1/execute failed (422): bad model",
            api_url="http://localhost:8081",
            status=422,
            status_text="Unprocessable Entity",
            response_body='{"detail":"bad model"}',
            error_type="ValidateBundleError",
            server_message="bad model",
            validation_errors=items,
            type_uri="https://docs.example/errors/validate-bundle-error/",
            title="Validate bundle",
            instance="/v1/execute",
            request_id="req_1",
            error_domain="input",
            retryable=False,
            problem={"detail": "bad model"},
        )
        assert (exc.api_url, exc.status, exc.status_text) == ("http://localhost:8081", 422, "Unprocessable Entity")
        assert exc.response_body == '{"detail":"bad model"}'
        assert (exc.error_type, exc.server_message) == ("ValidateBundleError", "bad model")
        assert exc.validation_errors == items
        assert (exc.type_uri, exc.title, exc.instance) == ("https://docs.example/errors/validate-bundle-error/", "Validate bundle", "/v1/execute")
        assert (exc.request_id, exc.error_domain, exc.retryable) == ("req_1", "input", False)
        assert exc.problem == {"detail": "bad model"}
        assert exc.user_action is None
