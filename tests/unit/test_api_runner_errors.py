"""Tests for how MthdsAPIClient reads every failure of every route as a problem, httpx's transport mocked."""

import asyncio
import json
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, NoReturn

import httpx
import pytest
from pytest_mock import MockerFixture
from typing_extensions import override

from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.models import ModelCategory
from mthds.protocol.problem.client_problems import make_client_problem
from mthds.protocol.problem.models import Problem, ProblemDomain, RemapValueOp
from mthds.protocol.problem.registry import CoreCode, ModelUnknownParams
from mthds.runners.api.client import MthdsAPIClient
from mthds.runners.api.exceptions import ApiResponseError, ApiTransportError, ClientNotConfiguredError, RunStillRunningError
from tests.unit.test_data import LegacyAnswerBodies, ProblemBodies

_BASE_URL = "http://localhost:8081"


def _execute(client: MthdsAPIClient) -> Coroutine[Any, Any, object]:
    """Call `execute()` with arguments that name something to run."""
    return client.execute(pipe_code="pitch_product", mthds_contents=['domain = "sales_copy"'])


# Each protocol route, called with arguments that name something to run: (route label, whether it creates a run, call).
_ROUTE_CALLS: list[tuple[str, bool, Callable[[MthdsAPIClient], Coroutine[Any, Any, object]]]] = [
    ("POST /v1/execute", True, _execute),
    ("POST /v1/start", True, lambda client: client.start(pipe_code="pitch_product", mthds_contents=['domain = "sales_copy"'])),
    ("POST /v1/validate", False, lambda client: client.validate(['domain = "sales_copy"'])),
    ("GET /v1/models", False, lambda client: client.models()),
    ("GET /v1/version", False, lambda client: client.version()),
]

Handler = Callable[[httpx.Request], httpx.Response]


def _answering(status_code: int, *, text: str = "", headers: Mapping[str, str] | Mapping[bytes, bytes] | None = None) -> Handler:
    """A transport handler answering every request with `status_code`, `text` as its body; header bytes carry a value that is not ASCII."""

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text, headers=headers or {}, request=request)

    return handle


def _failing(failure: type[httpx.TransportError]) -> Handler:
    """A transport handler that raises `failure` instead of answering."""

    def handle(request: httpx.Request) -> httpx.Response:
        msg = "the transport failed"
        raise failure(msg, request=request)

    return handle


class _NarrowedApiResponseError(ApiResponseError):
    """A client's own error, carrying a member the base does not name."""

    def __init__(self, message: str, *, request_id: str | None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.request_id = request_id


class _NarrowingClient(MthdsAPIClient):
    """A client built on the base that raises its own error subclass through the protected seam."""

    @override
    def _raise_api_response_error(self, *, method: str, endpoint: str, response: httpx.Response, problem: Problem) -> NoReturn:
        request_id = (problem.model_extra or {}).get("request_id")
        msg = f"API {method} /v1/{endpoint} failed ({response.status_code})"
        raise _NarrowedApiResponseError(
            msg,
            request_id=request_id if isinstance(request_id, str) else None,
            problem=problem,
            api_url=self.base_url,
            status=response.status_code,
            status_text=response.reason_phrase,
            response_body=response.text,
        )


class TestMthdsAPIClientErrors:
    """Every route raises a PipelineRequestError carrying a problem: the runtime's, or the one the client reads from what it met."""

    @pytest.fixture(autouse=True)
    def _mock_config(self, mocker: MockerFixture) -> None:
        """Keep construction hermetic — never touch the real config file/env."""
        mocker.patch(
            "mthds.runners.api.client.load_config",
            return_value={"api_key": "", "base_url": "", "runner": "api"},
        )

    def _client(self, handler: Handler, *, client_class: type[MthdsAPIClient] = MthdsAPIClient) -> MthdsAPIClient:
        client = client_class(api_key="test-token", base_url=_BASE_URL, request_timeout_seconds=30.0)
        client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return client

    def _raised(self, client: MthdsAPIClient, call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]]) -> PipelineRequestError:
        """Make the call and return the PipelineRequestError it raised."""

        async def scenario() -> None:
            try:
                await call(client)
            finally:
                await client.close()

        with pytest.raises(PipelineRequestError) as exc_info:
            asyncio.run(scenario())
        return exc_info.value

    def _response_error(self, client: MthdsAPIClient, call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]]) -> ApiResponseError:
        exc = self._raised(client, call)
        assert isinstance(exc, ApiResponseError), repr(exc)
        return exc

    @pytest.mark.parametrize(("route", "creates_run", "call"), _ROUTE_CALLS)
    def test_every_route_raises_the_runtimes_problem(
        self, route: str, creates_run: bool, call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]]
    ) -> None:
        """A refusal on any route arrives as ApiResponseError carrying the problem as the runtime sent it, its extra member kept."""
        exc = self._response_error(self._client(_answering(422, text=ProblemBodies.MODEL_UNKNOWN_BODY)), call)

        assert not isinstance(exc, httpx.HTTPStatusError)
        assert exc.problem.as_wire() == ProblemBodies.MODEL_UNKNOWN, f"{route} creates a run: {creates_run}"
        assert (exc.problem.model_extra or {})["request_id"] == "req_b7d2c66f-b2d5-4dc7-bd4f-6cf98abfbdc0"
        assert exc.problem.effective_domain is ProblemDomain.METHOD
        assert not exc.problem.is_retryable
        assert exc.problem.params_as(ModelUnknownParams).model == "gpt-5.1"
        assert exc.status == 422
        assert exc.status_text == "Unprocessable Entity"
        assert exc.api_url == _BASE_URL
        assert exc.response_body == ProblemBodies.MODEL_UNKNOWN_BODY
        assert str(exc) == (
            f"API {route} failed (422): The method names the llm model 'gpt-5.1', which no catalog knows.\n"
            "Next step: Ask the method's owner to name a model that exists in place of 'gpt-5.1'."
        )

    def test_a_method_that_does_not_validate_carries_its_faults_as_items(self) -> None:
        """A run route's refusal of an invalid method keeps one typed item per fault, with its fix."""
        exc = self._response_error(self._client(_answering(422, text=ProblemBodies.METHOD_INVALID_BODY)), _execute)

        assert exc.problem.code == "method.invalid"
        assert exc.problem.errors is not None
        item = exc.problem.errors[0]
        assert item.code == "method.concept_unresolved"
        assert item.effective_domain is ProblemDomain.METHOD
        assert item.suggestions == ["legal.Clause"]
        assert item.location is not None
        assert (item.location.pipe, item.location.line) == ("extract_clauses", 30)
        assert item.suggested_fix is not None
        assert item.suggested_fix.is_applicable
        assert isinstance(item.suggested_fix.ops[0], RemapValueOp)
        assert item.suggested_fix.ops[0].mapping == {"legal.Clausee": "legal.Clause"}

    @pytest.mark.parametrize(
        ("topic", "status", "body", "expected_code"),
        [
            ("an answer written before the protocol's core members", 422, LegacyAnswerBodies.UNKNOWN_MODEL_AT_LOAD, "client.response_unreadable"),
            ("a legacy detail object", 500, LegacyAnswerBodies.LEGACY_DETAIL_OBJECT, "client.response_unreadable"),
            ("a framework's unmatched route", 404, LegacyAnswerBodies.PLAIN_DETAIL_STRING, "client.response_unreadable"),
            ("a gateway's html page", 502, LegacyAnswerBodies.GATEWAY_HTML, "client.response_unreadable"),
            ("an empty 503 on a route that creates a run", 503, "", "client.response_unreadable"),
            ("a framework's refusal of the method", 405, '{"detail":"Method Not Allowed"}', "request.method_not_allowed"),
        ],
    )
    def test_an_answer_that_is_no_problem_document_reads_as_a_registered_code(self, topic: str, status: int, body: str, expected_code: str) -> None:
        """Whatever the body, the error carries a problem under a registered code, the status and the raw text."""
        exc = self._response_error(self._client(_answering(status, text=body)), _execute)

        assert exc.problem.code == expected_code, topic
        assert exc.status == status
        assert exc.response_body == body
        lines = str(exc).split("\n")
        assert lines[0] == f"API POST /v1/execute failed ({status}): {exc.problem.detail}", topic
        assert lines[-1] == f"Next step: {exc.problem.next_step.detail}", topic
        if body:
            assert len(lines) == 3, topic
            assert lines[1].startswith("The server answered: "), topic
        else:
            assert len(lines) == 2, topic

    def test_the_message_quotes_what_the_server_said_and_the_problem_keeps_the_registrys_words(self) -> None:
        """A body that is no problem document is quoted on its own line of the message, never in the problem, which stays the client's."""
        exc = self._response_error(self._client(_answering(401, text='{"detail":"Not authenticated"}')), lambda client: client.models())

        assert str(exc) == (
            "API GET /v1/models failed (401): "
            "The runtime answered with the HTTP status 401 and a body that is not a problem document the client can read.\n"
            'The server answered: {"detail":"Not authenticated"}\n'
            f"Next step: {exc.problem.next_step.detail}"
        )
        assert exc.problem.as_wire() == make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": 401}).as_wire()
        assert "Not authenticated" not in json.dumps(exc.problem.as_wire())

    @pytest.mark.parametrize(
        ("topic", "status", "body", "expected_line"),
        [
            ("a success that is not the route's answer", 200, "OK", "The server answered: OK"),
            (
                "a page on several lines reads on one",
                502,
                "<html>\n  <body>\n    <h1>502 Bad Gateway</h1>\n  </body>\n</html>\n",
                "The server answered: <html> <body> <h1>502 Bad Gateway</h1> </body> </html>",
            ),
            ("a long page is cut", 502, "<p>" + "x" * 600 + "</p>", "The server answered: <p>" + "x" * 497 + "…"),
        ],
    )
    def test_the_quote_of_the_body_is_one_bounded_line(self, topic: str, status: int, body: str, expected_line: str) -> None:
        exc = self._response_error(self._client(_answering(status, text=body)), lambda client: client.version())

        assert str(exc).split("\n")[1] == expected_line, topic
        assert exc.response_body == body, topic

    def test_an_empty_503_on_a_read_says_the_runtime_is_unavailable_with_the_delay_it_asks_for(self) -> None:
        """A read creates nothing, so a 503 with no problem document reads as runtime.unavailable, retry_after from the header."""
        exc = self._response_error(self._client(_answering(503, headers={"Retry-After": "5"})), lambda client: client.models())

        assert exc.problem.code == "runtime.unavailable"
        assert exc.problem.status == 503
        assert exc.problem.retry_after == 5
        assert exc.problem.is_retryable

    def test_a_retryable_problem_takes_its_delay_from_the_header(self) -> None:
        """A problem with a retry of yes and no retry_after takes the `Retry-After` header's; the raw header stays on the error."""
        exc = self._response_error(
            self._client(_answering(429, text=ProblemBodies.RATE_LIMITED_BODY, headers={"Retry-After": "17", "X-Request-ID": "req_rate"})),
            _ROUTE_CALLS[1][2],
        )

        assert exc.problem.code == "account.rate_limited"
        assert exc.problem.retry_after == 17
        assert exc.problem.is_retryable
        assert exc.headers["retry-after"] == "17"
        assert exc.headers["x-request-id"] == "req_rate"
        assert exc.request_url == f"{_BASE_URL}/v1/start"
        for value in vars(exc).values():
            assert not isinstance(value, (httpx.Request, httpx.Response))
        assert "test-token" not in repr(vars(exc))

    @pytest.mark.parametrize(
        ("topic", "literal"), [("a delay past a double's range", '"retry_after":1e999'), ("an extra member past it", '"load":-1e999')]
    )
    def test_a_problem_holding_a_number_json_readers_read_as_infinite_is_unreadable(self, topic: str, literal: str) -> None:
        """A number that reads as an infinity makes the body no JSON a reader can read, as the constant `Infinity` does, so no problem carries it."""
        body = ProblemBodies.RATE_LIMITED_BODY[:-1] + "," + literal + "}"
        exc = self._response_error(self._client(_answering(429, text=body)), lambda client: client.models())

        assert exc.problem.code == "client.response_unreadable", topic
        assert exc.problem.as_wire()["params"] == {"status": 429}, topic
        assert exc.response_body == body, topic

    @pytest.mark.parametrize(
        ("topic", "header"),
        [("a superscript digit", "²"), ("arabic-indic digits", "١٢"), ("digits too many to convert", "9" * 5000)],
    )
    def test_a_retry_after_header_the_client_cannot_read_gives_no_delay(self, topic: str, header: str) -> None:
        """A `Retry-After` that is not ASCII digits, or too long to convert, is unreadable: the call still raises the typed error, with no delay."""
        headers = {b"Retry-After": header.encode()}
        rate_limited = self._response_error(
            self._client(_answering(429, text=ProblemBodies.RATE_LIMITED_BODY, headers=headers)), lambda client: client.models()
        )
        unavailable = self._response_error(self._client(_answering(503, headers=headers)), lambda client: client.models())
        degraded = self._raised(
            self._client(_answering(202, text='{"pipeline_run_id":"run_7f3a"}', headers=headers)), lambda client: client.execute(pipe_code="answer")
        )

        assert (rate_limited.problem.code, rate_limited.problem.retry_after) == ("account.rate_limited", None), topic
        assert "retry_after" not in rate_limited.problem.as_wire(), topic
        assert (unavailable.problem.code, unavailable.problem.retry_after) == ("runtime.unavailable", None), topic
        assert isinstance(degraded, RunStillRunningError), topic
        assert degraded.retry_after_seconds is None, topic

    def test_a_filtered_models_read_names_its_query_in_the_message(self) -> None:
        """The endpoint in the message is the one requested, query string included."""
        exc = self._response_error(
            self._client(_answering(401, text='{"detail":"Invalid API key"}')), lambda client: client.models(ModelCategory.LLM)
        )

        assert str(exc).startswith("API GET /v1/models?type=llm failed (401): ")
        assert exc.request_url == f"{_BASE_URL}/v1/models?type=llm"

    @pytest.mark.parametrize(("route", "creates_run", "call"), _ROUTE_CALLS)
    @pytest.mark.parametrize(
        ("topic", "body"), [("a body that is not json", "OK"), ("json that is not the route's answer", '["not", "an", "answer"]')]
    )
    def test_a_success_the_client_cannot_read_is_an_unreadable_answer(
        self, route: str, creates_run: bool, call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]], topic: str, body: str
    ) -> None:
        """A 2xx whose body is not the route's answer raises `client.response_unreadable` naming the status, never a pydantic error."""
        status = 202 if route == "POST /v1/start" else 200
        exc = self._response_error(self._client(_answering(status, text=body)), call)

        assert exc.problem.code == "client.response_unreadable", f"{route}, {topic}, creates a run: {creates_run}"
        assert exc.problem.as_wire()["params"] == {"status": status}
        assert exc.status == status

    @pytest.mark.parametrize(("route", "creates_run", "call"), _ROUTE_CALLS)
    @pytest.mark.parametrize(
        ("topic", "failure", "code_on_a_read", "code_on_a_run"),
        [
            ("no connection opened", httpx.ConnectError, "client.unreachable", "client.unreachable"),
            ("the connection attempt timed out", httpx.ConnectTimeout, "client.unreachable", "client.unreachable"),
            ("no free connection in the pool", httpx.PoolTimeout, "client.timeout", "client.timeout"),
            ("no answer in time", httpx.ReadTimeout, "client.timeout", "client.outcome_unknown"),
            ("the connection dropped mid-answer", httpx.ReadError, "client.unreachable", "client.outcome_unknown"),
            ("the server closed without an answer", httpx.RemoteProtocolError, "client.unreachable", "client.outcome_unknown"),
        ],
    )
    def test_a_request_that_got_no_answer_is_a_transport_error(
        self,
        route: str,
        creates_run: bool,
        call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]],
        topic: str,
        failure: type[httpx.TransportError],
        code_on_a_read: str,
        code_on_a_run: str,
    ) -> None:
        """No answer raises ApiTransportError on every route, and a request that may have created a run is never offered for a retry."""
        exc = self._raised(self._client(_failing(failure)), call)

        assert isinstance(exc, ApiTransportError), topic
        expected_code = code_on_a_run if creates_run else code_on_a_read
        assert exc.problem.code == expected_code, f"{route}: {topic}"
        assert isinstance(exc.__cause__, httpx.TransportError)
        assert exc.api_url == _BASE_URL
        assert str(exc).startswith(f"API {route} failed: {exc.problem.detail}\nNext step: ")
        if expected_code == "client.outcome_unknown":
            assert exc.problem.outcome_is_unknown
            assert not exc.problem.is_retryable
        if expected_code == "client.timeout":
            assert exc.problem.as_wire()["params"] == {"seconds": 30}

    @pytest.mark.parametrize(("route", "creates_run", "call"), _ROUTE_CALLS)
    @pytest.mark.parametrize(
        ("topic", "base_url"), [("no scheme", "api.example.com"), ("a host read as a scheme", "localhost:8081"), ("a scheme not sent to", "ftp://example.com")]
    )
    def test_a_base_url_the_client_cannot_send_to_is_a_setting_to_fix(
        self, route: str, creates_run: bool, call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]], topic: str, base_url: str
    ) -> None:
        """httpx's real transport refuses the scheme before connecting, and the call reads as `client.not_configured`, never as a runtime to retry."""
        client = MthdsAPIClient(api_key="test-token", base_url=base_url, request_timeout_seconds=30.0)
        exc = self._raised(client, call)

        assert isinstance(exc, ClientNotConfiguredError), f"{route}, {topic}: {exc!r}"
        assert isinstance(exc.__cause__, httpx.UnsupportedProtocol)
        assert exc.problem.code == "client.not_configured", f"{route} creates a run: {creates_run}"
        assert exc.problem.as_wire()["params"] == {"setting": "base_url"}
        assert not exc.problem.is_retryable
        assert not exc.problem.outcome_is_unknown

    def test_a_202_on_execute_raises_run_still_running(self) -> None:
        """The protocol's async degrade reads as `client.follow_failed` naming the run, with the 202's hints on the error."""
        handler = _answering(202, text='{"pipeline_run_id":"run_7f3a"}', headers={"Location": "/v1/runs/run_7f3a", "Retry-After": "5"})
        exc = self._raised(self._client(handler), lambda client: client.execute(pipe_code="answer"))

        assert isinstance(exc, RunStillRunningError)
        assert not isinstance(exc, ApiResponseError)
        assert exc.run_id == "run_7f3a"
        assert exc.location == "/v1/runs/run_7f3a"
        assert exc.retry_after_seconds == 5
        assert exc.problem.code == "client.follow_failed"
        assert exc.problem.as_wire()["params"] == {"pipeline_run_id": "run_7f3a"}
        assert exc.problem.outcome_is_unknown

    def test_a_202_on_execute_naming_no_run_is_an_unreadable_answer(self) -> None:
        """A 202 that names no run gives the client nothing to follow: `client.response_unreadable`."""
        exc = self._response_error(self._client(_answering(202, text="{}")), lambda client: client.execute(pipe_code="answer"))

        assert exc.problem.code == "client.response_unreadable"
        assert exc.problem.as_wire()["params"] == {"status": 202}

    def test_a_body_whose_encoding_cannot_be_decoded_reads_by_its_status(self) -> None:
        """A broken gzip stream is read as an empty body, so the answer's status still decides how it reads."""
        broken = b"this was never gzip"

        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, stream=httpx.ByteStream(broken), headers={"Content-Encoding": "gzip", "Retry-After": "3"}, request=request)

        exc = self._response_error(self._client(handle), lambda client: client.models())

        assert exc.problem.code == "runtime.unavailable"
        assert exc.problem.retry_after == 3
        assert exc.response_body == ""

    @pytest.mark.parametrize(("route", "creates_run", "call"), _ROUTE_CALLS)
    def test_a_client_built_on_this_one_raises_its_own_subclass_from_every_route(
        self, route: str, creates_run: bool, call: Callable[[MthdsAPIClient], Coroutine[Any, Any, object]]
    ) -> None:
        """Overriding the protected seam re-types every inherited route's error, which base handlers still catch."""
        client = self._client(_answering(422, text=ProblemBodies.MODEL_UNKNOWN_BODY), client_class=_NarrowingClient)
        exc = self._response_error(client, call)

        assert isinstance(exc, _NarrowedApiResponseError), f"{route} creates a run: {creates_run}"
        assert exc.request_id == "req_b7d2c66f-b2d5-4dc7-bd4f-6cf98abfbdc0"
        assert exc.problem.code == "model.unknown"
        assert str(exc) == f"API {route} failed (422)\nNext step: Ask the method's owner to name a model that exists in place of 'gpt-5.1'."
