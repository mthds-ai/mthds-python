"""Tests for how MthdsAPIClient turns a non-2xx answer into ApiResponseError, on every route, httpx mocked."""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, NoReturn

import httpx
import pytest
from pytest_mock import MockerFixture
from typing_extensions import override

from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.models import ModelCategory, ValidationDiagnostic
from mthds.runners.api.client import MthdsAPIClient
from mthds.runners.api.exceptions import ApiResponseError, RunStillRunningError
from mthds.runners.api.problem import ProblemDocument
from tests.unit.test_data import RefusedRunBodies

_BASE_URL = "http://localhost:8081"

# Each protocol route, called with arguments that name something to run: (route label, call).
_ROUTE_CALLS: list[tuple[str, Callable[[MthdsAPIClient], Coroutine[Any, Any, object]]]] = [
    ("POST /v1/execute", lambda client: client.execute(pipe_code="pitch_product", mthds_contents=['domain = "sales_copy"'])),
    ("POST /v1/start", lambda client: client.start(pipe_code="pitch_product", mthds_contents=['domain = "sales_copy"'])),
    ("POST /v1/validate", lambda client: client.validate(['domain = "sales_copy"'])),
    ("GET /v1/models", lambda client: client.models()),
    ("GET /v1/version", lambda client: client.version()),
]


def _response(status_code: int, *, text: str = "", headers: dict[str, str] | None = None) -> httpx.Response:
    """Build a constructed httpx.Response carrying `text` as its body."""
    request = httpx.Request("POST", f"{_BASE_URL}/v1/x")
    return httpx.Response(status_code, text=text, headers=headers or {}, request=request)


class _NarrowedDiagnostic(ValidationDiagnostic):
    """A client's own narrowing of the diagnostic item, as pipelex-sdk narrows it."""

    pipe_code: str | None = None


class _NarrowedApiResponseError(ApiResponseError[_NarrowedDiagnostic]):
    """A client's own error, carrying a member the base does not name."""

    def __init__(self, message: str, *, category: str | None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.category = category


class _NarrowingClient(MthdsAPIClient):
    """A client built on the base that raises its own error subclass through the protected seam."""

    @override
    def _raise_api_response_error(self, *, method: str, endpoint: str, response: httpx.Response) -> NoReturn:
        document = ProblemDocument.make_from_response(response)
        members = document.members or {}
        raw_items: list[dict[str, Any]] = members.get("validation_errors", [])
        category = members.get("error_category")
        msg = f"API {method} /v1/{endpoint} failed ({response.status_code})"
        raise _NarrowedApiResponseError(
            msg,
            category=category if isinstance(category, str) else None,
            api_url=self.base_url,
            status=response.status_code,
            status_text=response.reason_phrase,
            response_body=response.text,
            validation_errors=[_NarrowedDiagnostic.model_validate(item) for item in raw_items],
            user_action=document.user_action,
        )


class TestMthdsAPIClientErrors:
    """Every route raises ApiResponseError on a non-2xx answer, its problem members typed and its message readable."""

    @pytest.fixture(autouse=True)
    def _mock_config(self, mocker: MockerFixture) -> None:
        """Keep construction hermetic — never touch the real config file/env."""
        mocker.patch(
            "mthds.runners.api.client.load_config",
            return_value={"api_key": "", "base_url": "", "runner": "api"},
        )

    def _client(self) -> MthdsAPIClient:
        return MthdsAPIClient(api_key="test-token", base_url=_BASE_URL)

    def _raised(
        self, client: MthdsAPIClient, mocker: MockerFixture, response: httpx.Response, call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]]
    ) -> ApiResponseError:
        """Answer every request with `response`, make the call, and return the ApiResponseError it raised."""
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=response))
        with pytest.raises(ApiResponseError) as exc_info:
            asyncio.run(call(client))
        return exc_info.value

    @pytest.mark.parametrize(("route", "call"), _ROUTE_CALLS)
    def test_every_route_raises_the_typed_error_with_the_problem_members(
        self, route: str, call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]], mocker: MockerFixture
    ) -> None:
        """A refusal on any route arrives as ApiResponseError, never as httpx's HTTPStatusError, its members parsed."""
        exc = self._raised(self._client(), mocker, _response(422, text=RefusedRunBodies.UNSERVED_MODEL_AT_RUN), call)

        assert not isinstance(exc, httpx.HTTPStatusError)
        assert isinstance(exc, PipelineRequestError)
        assert exc.status == 422
        assert exc.status_text == "Unprocessable Entity"
        assert exc.api_url == _BASE_URL
        assert exc.error_type == "ModelNotFoundError"
        assert exc.server_message == RefusedRunBodies.UNSERVED_MODEL_DETAIL
        assert exc.user_action is not None
        assert exc.user_action.detail == RefusedRunBodies.UNSERVED_MODEL_NEXT_STEP
        assert str(exc) == (
            f"API {route} failed (422): {RefusedRunBodies.UNSERVED_MODEL_DETAIL}\nNext step: {RefusedRunBodies.UNSERVED_MODEL_NEXT_STEP}"
        )

    def test_a_bundle_refused_at_load_carries_every_member(self, mocker: MockerFixture) -> None:
        """The dev plane's refusal of a bundle naming an unknown model: every member, and the itemized diagnostic."""
        exc = self._raised(self._client(), mocker, _response(422, text=RefusedRunBodies.UNKNOWN_MODEL_AT_LOAD), _ROUTE_CALLS[0][1])

        assert exc.type_uri == "https://docs.pipelex.com/latest/errors/validate-bundle-error/"
        assert exc.title == "Validate bundle"
        assert exc.instance == "/v1/execute"
        assert exc.request_id == "req_a3dd6900-7909-48d3-b551-0140e73ac7fc"
        assert exc.error_type == "ValidateBundleError"
        assert exc.error_domain == "input"
        assert exc.retryable is False
        assert exc.server_message == RefusedRunBodies.UNKNOWN_MODEL_DETAIL
        assert exc.user_action is not None
        assert exc.user_action.kind == "change_input"
        assert exc.user_action.detail == RefusedRunBodies.UNKNOWN_MODEL_NEXT_STEP
        assert exc.validation_errors is not None
        assert len(exc.validation_errors) == 1
        item = exc.validation_errors[0]
        assert item.category == "pipe_validation"
        assert item.message == RefusedRunBodies.UNKNOWN_MODEL_DETAIL
        # The protocol's neutral item: the runner's locators ride model_extra until a client narrows them.
        assert (item.model_extra or {})["pipe_code"] == "draft_pitch"
        assert (item.model_extra or {})["suggestions"] == ["gpt-5.5", "gpt-5.4", "gpt-5.6-sol", "gpt-5.4-pro", "gpt-5.6-luna"]
        # A member this package does not name stays reachable on the decoded document.
        assert exc.problem is not None
        assert exc.problem["error_category"] == "configuration"
        assert exc.response_body == RefusedRunBodies.UNKNOWN_MODEL_AT_LOAD
        # The message names the failing pipe and the model, then the next step.
        assert str(exc) == (
            f"API POST /v1/execute failed (422): {RefusedRunBodies.UNKNOWN_MODEL_DETAIL}\nNext step: {RefusedRunBodies.UNKNOWN_MODEL_NEXT_STEP}"
        )

    def test_a_run_failed_at_a_pipe_states_its_reason_once(self, mocker: MockerFixture) -> None:
        """When the reason already says the next step, the message does not repeat it."""
        exc = self._raised(self._client(), mocker, _response(422, text=RefusedRunBodies.COMBINE_FAILURE_AT_RUN), _ROUTE_CALLS[0][1])

        assert exc.type_uri == "https://docs.pipelex.com/latest/errors/stuff-factory-error/"
        assert exc.title == "Stuff factory"
        assert exc.request_id == "req_d4212542-63a6-4ddb-87c9-4b968785c8c5"
        assert exc.error_type == "StuffFactoryError"
        assert exc.error_domain == "input"
        # The runner did not say whether a retry helps: unknown, not False.
        assert exc.retryable is None
        assert exc.validation_errors is None
        assert exc.user_action is not None
        assert exc.user_action.kind == "change_input"
        assert exc.user_action.detail == RefusedRunBodies.COMBINE_FAILURE_NEXT_STEP
        assert exc.server_message is not None
        assert str(exc) == f"API POST /v1/execute failed (422): {exc.server_message}"
        assert "Next step:" not in str(exc)

    @pytest.mark.parametrize(
        ("topic", "status", "body", "expected_message", "expected_server_message", "expected_error_type"),
        [
            (
                "legacy detail object",
                500,
                RefusedRunBodies.LEGACY_DETAIL_OBJECT,
                "API POST /v1/execute failed (500): Pipe 'summarize' failed: the input is empty",
                "Pipe 'summarize' failed: the input is empty",
                "PipeRunError",
            ),
            ("plain detail string", 404, RefusedRunBodies.PLAIN_DETAIL_STRING, "API POST /v1/execute failed (404): Not Found", "Not Found", None),
            ("title only", 422, RefusedRunBodies.TITLE_ONLY, "API POST /v1/execute failed (422): Malformed request", None, None),
            (
                "gateway html page",
                502,
                RefusedRunBodies.GATEWAY_HTML,
                f"API POST /v1/execute failed (502): {RefusedRunBodies.GATEWAY_HTML}",
                None,
                None,
            ),
            ("empty body", 503, "", "API POST /v1/execute failed (503): Service Unavailable", None, None),
        ],
    )
    def test_an_answer_that_is_no_problem_document_still_raises_the_typed_error(
        self,
        topic: str,
        status: int,
        body: str,
        expected_message: str,
        expected_server_message: str | None,
        expected_error_type: str | None,
        mocker: MockerFixture,
    ) -> None:
        """Whatever the body, the error carries the status and the raw text, and its message the best reason there is."""
        exc = self._raised(self._client(), mocker, _response(status, text=body), _ROUTE_CALLS[0][1])

        assert exc.status == status, topic
        assert exc.response_body == body
        assert str(exc) == expected_message
        assert exc.server_message == expected_server_message
        assert exc.error_type == expected_error_type
        assert exc.user_action is None
        assert exc.validation_errors is None

    def test_a_long_raw_body_is_cut_short_in_the_message_and_kept_whole_on_the_error(self, mocker: MockerFixture) -> None:
        """A page of text is quoted up to a limit in the message; `response_body` holds all of it."""
        body = "x" * 2000
        exc = self._raised(self._client(), mocker, _response(502, text=body), _ROUTE_CALLS[0][1])

        assert str(exc) == f"API POST /v1/execute failed (502): {'x' * 500}…"
        assert exc.response_body == body

    def test_a_filtered_models_read_names_its_query_in_the_message(self, mocker: MockerFixture) -> None:
        """The endpoint in the message is the one requested, query string included."""
        exc = self._raised(
            self._client(), mocker, _response(401, text='{"detail":"Invalid API key"}'), lambda client: client.models(ModelCategory.LLM)
        )

        assert str(exc) == "API GET /v1/models?type=llm failed (401): Invalid API key"

    def test_a_202_on_execute_still_raises_run_still_running(self, mocker: MockerFixture) -> None:
        """The protocol's async degrade keeps its own error, ahead of the non-2xx handling."""
        client = self._client()
        response = _response(202, text='{"pipeline_run_id":"run_7f3a"}', headers={"Location": "/v1/runs/run_7f3a", "Retry-After": "5"})
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=response))

        with pytest.raises(RunStillRunningError) as exc_info:
            asyncio.run(client.execute(pipe_code="answer"))
        assert not isinstance(exc_info.value, ApiResponseError)
        assert exc_info.value.run_id == "run_7f3a"
        assert exc_info.value.location == "/v1/runs/run_7f3a"
        assert exc_info.value.retry_after_seconds == 5

    @pytest.mark.parametrize(("route", "call"), _ROUTE_CALLS)
    def test_a_client_built_on_this_one_raises_its_own_subclass_from_every_route(
        self, route: str, call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]], mocker: MockerFixture
    ) -> None:
        """Overriding the protected seam re-types every inherited route's error, which base handlers still catch."""
        client = _NarrowingClient(api_key="test-token", base_url=_BASE_URL)
        exc = self._raised(client, mocker, _response(422, text=RefusedRunBodies.UNKNOWN_MODEL_AT_LOAD), call)

        assert isinstance(exc, _NarrowedApiResponseError)
        assert exc.category == "configuration"
        assert exc.validation_errors is not None
        assert exc.validation_errors[0].pipe_code == "draft_pitch"
        assert str(exc) == f"API {route} failed (422)\nNext step: {RefusedRunBodies.UNKNOWN_MODEL_NEXT_STEP}"
