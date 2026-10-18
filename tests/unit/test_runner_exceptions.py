"""Tests for the protocol + runner error hierarchy (`mthds.protocol.exceptions`, `mthds.runners.api.exceptions`)."""

import copy
import inspect
import pickle  # ruff: ignore[suspicious-pickle-import]  # the test round-trips its own errors, never untrusted bytes
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # the test imports this package's own modules in a fresh interpreter
import sys
from typing import Any

import httpx
import pytest
from pytest_mock import MockerFixture

from mthds.protocol.exceptions import PipelineRequestError, make_argument_invalid_error
from mthds.protocol.problem.client_problems import make_client_problem
from mthds.protocol.problem.models import Problem
from mthds.protocol.problem.registry import CoreCode
from mthds.runners.api.client import MthdsAPIClient
from mthds.runners.api.exceptions import ApiResponseError, ApiTransportError, BlobUploadError, ClientNotConfiguredError, RunStillRunningError
from tests.unit.test_data import ProblemBodies

_FOLLOW_FAILED = make_client_problem(CoreCode.CLIENT_FOLLOW_FAILED, params={"pipeline_run_id": "run_1"})
_UNREACHABLE = make_client_problem(CoreCode.CLIENT_UNREACHABLE, params={"base_url": "http://localhost:8081"})
_MODEL_UNKNOWN = Problem.model_validate(ProblemBodies.MODEL_UNKNOWN)
_UPLOAD_REFUSED = make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": 403})


class TestClientExceptions:
    """Every error of the client is a PipelineRequestError carrying its failure as a problem, and crosses a process boundary as itself."""

    @pytest.mark.parametrize(
        "error_class",
        [ApiResponseError, ApiTransportError, RunStillRunningError, ClientNotConfiguredError, BlobUploadError],
    )
    def test_every_client_error_is_a_pipeline_request_error_and_not_httpx(self, error_class: type[Exception]) -> None:
        """`except PipelineRequestError` catches every error the client raises, and httpx's own errors never escape it."""
        assert issubclass(error_class, PipelineRequestError)
        assert not issubclass(error_class, httpx.HTTPError)

    def test_run_still_running_error_attributes(self) -> None:
        """RunStillRunningError carries the run id, the 202 hints (Retry-After + Location) and `client.follow_failed`."""
        msg = "execute() was accepted asynchronously (202): run run_1 is still running server-side."
        exc = RunStillRunningError(msg, problem=_FOLLOW_FAILED, run_id="run_1", retry_after_seconds=10, location="/v1/runs/run_1/results")
        assert exc.run_id == "run_1"
        assert exc.retry_after_seconds == 10
        assert exc.location == "/v1/runs/run_1/results"
        assert str(exc) == f"{msg}\nNext step: Read the run 'run_1' by its id rather than start it again."
        assert exc.problem.code == "client.follow_failed"
        assert exc.problem.outcome_is_unknown
        assert not exc.problem.is_retryable

    def test_a_request_error_is_never_built_without_its_problem(self) -> None:
        """`problem` is a required keyword, so no request error exists without one, a refused argument's included."""
        problem_parameter = inspect.signature(PipelineRequestError.__init__).parameters["problem"]
        assert problem_parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert problem_parameter.default is inspect.Parameter.empty

    def test_a_bare_request_error_is_an_argument_refused_before_sending(self) -> None:
        """The client's own refusal of an argument carries `client.argument_invalid`, naming the argument and the reason."""
        exc = make_argument_invalid_error("pipe_code must be a string, received int.", argument="pipe_code", reason="not_a_string")
        assert type(exc) is PipelineRequestError
        assert str(exc) == "pipe_code must be a string, received int.\nNext step: Correct the argument 'pipe_code', then try again."
        assert exc.problem.as_wire() == {
            "type": "https://mthds.ai/errors/client.argument_invalid",
            "title": "An argument was refused before sending",
            "detail": "The argument 'pipe_code' was refused before any request left (reason: not_a_string).",
            "code": "client.argument_invalid",
            "domain": "input",
            "retry": "no",
            "next_step": {"kind": "change_input", "detail": "Correct the argument 'pipe_code', then try again."},
            "params": {"argument": "pipe_code", "reason": "not_a_string"},
        }

    @pytest.mark.parametrize("module", ["mthds.protocol.exceptions", "mthds.protocol.options", "mthds.protocol.method_files"])
    def test_a_light_protocol_module_loads_no_registry(self, module: str) -> None:
        """A module that only refuses arguments loads the generated registry when it refuses one, never when it is imported."""
        probe = f"import sys, {module}; print('mthds.protocol.problem.registry' in sys.modules)"
        completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, check=True, text=True)  # ruff: ignore[subprocess-without-shell-equals-true]

        assert completed.stdout.strip() == "False", module

    @pytest.mark.parametrize(
        ("topic", "api_key", "base_url", "setting"),
        [
            ("no api key", "", "http://localhost:8081", "api_key"),
            ("no base url", "test-token", "", "base_url"),
        ],
    )
    def test_a_client_without_configuration_is_refused_with_the_setting_named(
        self, topic: str, api_key: str, base_url: str, setting: str, mocker: MockerFixture
    ) -> None:
        """A client that resolves no key or no base URL raises `client.not_configured`, naming the setting."""
        mocker.patch("mthds.runners.api.client.load_config", return_value={"api_key": "", "base_url": "", "runner": "api"})
        with pytest.raises(ClientNotConfiguredError) as exc_info:
            MthdsAPIClient(api_key=api_key, base_url=base_url)
        assert exc_info.value.problem.code == "client.not_configured", topic
        assert exc_info.value.problem.as_wire()["params"] == {"setting": setting}
        assert str(exc_info.value).endswith(f"\nNext step: Set '{setting}' in the client's configuration."), topic

    @pytest.mark.parametrize(
        ("topic", "api_key"),
        [
            ("a line break at its end", "sk-secret-key\n"),
            ("a carriage return and a line break", "sk-secret-key\r\n"),
            ("a space at its end", "sk-secret-key "),
            ("a line break inside", "sk-secret\nkey"),
            ("a null character", "sk-secret-key\x00"),
            ("a character past ASCII", "sk-secret-kéy"),
        ],
    )
    def test_an_api_key_no_header_can_carry_is_a_setting_to_fix(self, topic: str, api_key: str, mocker: MockerFixture) -> None:
        """A key HTTP cannot send is refused at construction as `client.not_configured`, never as an unreachable runtime, and never quoted."""
        mocker.patch("mthds.runners.api.client.load_config", return_value={"api_key": "", "base_url": "", "runner": "api"})
        with pytest.raises(ClientNotConfiguredError) as exc_info:
            MthdsAPIClient(api_key=api_key, base_url="http://localhost:8081")
        assert exc_info.value.problem.as_wire()["params"] == {"setting": "api_key"}, topic
        assert not exc_info.value.problem.is_retryable, topic
        assert "secret" not in str(exc_info.value), topic

    def test_api_response_error_message_ends_with_the_next_step(self) -> None:
        """`str()` is the message, then the problem's next step on its own line."""
        exc = ApiResponseError(
            f"API POST /v1/start failed (422): {_MODEL_UNKNOWN.detail}",
            problem=_MODEL_UNKNOWN,
            api_url="http://localhost:8081",
            status=422,
            status_text="Unprocessable Entity",
            response_body=ProblemBodies.MODEL_UNKNOWN_BODY,
        )
        assert str(exc) == (
            "API POST /v1/start failed (422): The method names the llm model 'gpt-5.1', which no catalog knows.\n"
            "Next step: Ask the method's owner to name a model that exists in place of 'gpt-5.1'."
        )
        assert (exc.api_url, exc.status, exc.status_text) == ("http://localhost:8081", 422, "Unprocessable Entity")
        assert exc.headers == {}
        assert exc.request_url is None

    @pytest.mark.parametrize(
        ("topic", "error"),
        [
            (
                "api response error",
                ApiResponseError(
                    "API POST /v1/execute failed (422): The method names the llm model 'gpt-5.1', which no catalog knows.",
                    problem=_MODEL_UNKNOWN,
                    api_url="http://localhost:8081",
                    status=422,
                    status_text="Unprocessable Entity",
                    response_body=ProblemBodies.MODEL_UNKNOWN_BODY,
                    headers={"retry-after": "17"},
                    request_url="http://localhost:8081/v1/execute",
                ),
            ),
            (
                "api transport error",
                ApiTransportError(
                    "API GET /v1/models failed: The client could not connect to the runtime at http://localhost:8081.",
                    problem=_UNREACHABLE,
                    api_url="http://localhost:8081",
                    request_url="http://localhost:8081/v1/models",
                ),
            ),
            (
                "run still running",
                RunStillRunningError("still running", problem=_FOLLOW_FAILED, run_id="run_1", retry_after_seconds=10, location="/v1/runs/run_1"),
            ),
            (
                "client not configured",
                ClientNotConfiguredError("no key", problem=make_client_problem(CoreCode.CLIENT_NOT_CONFIGURED, params={"setting": "api_key"})),
            ),
            (
                "blob upload error",
                BlobUploadError(
                    "Uploading blob 3e9b failed (403): AccessDenied",
                    problem=_UPLOAD_REFUSED,
                    sha256="3e9b68b71cc667168399f0bccfb64b2d16314cdc0ed78fac4819aba0dda121a0",
                    status=403,
                    status_text="Forbidden",
                    response_body="<Error><Code>AccessDenied</Code></Error>",
                    upload_url="https://bucket.example/blobs/3e9b",
                ),
            ),
            ("plain request error", make_argument_invalid_error("nothing to run", argument="pipe_code", reason="nothing_to_run")),
        ],
    )
    def test_request_errors_survive_pickling_and_copying(self, topic: str, error: PipelineRequestError) -> None:
        """A request error crosses a process boundary, or a deep copy, as itself: same class, same message, same members, same problem."""
        unpickled: Any = pickle.loads(pickle.dumps(error))  # ruff: ignore[suspicious-pickle-usage]
        rebuilt_errors: list[Any] = [unpickled, copy.deepcopy(error), copy.copy(error)]
        for rebuilt in rebuilt_errors:
            assert type(rebuilt) is type(error), topic
            assert str(rebuilt) == str(error), topic
            assert rebuilt.args == error.args, topic
            assert vars(rebuilt) == vars(error), topic
            assert rebuilt.problem.as_wire() == error.problem.as_wire(), topic
