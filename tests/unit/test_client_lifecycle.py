"""Tests for MthdsAPIClient's durable run-lifecycle surface (start/status/results/wait), httpx mocked."""

import asyncio

import httpx
import pytest
from pytest_mock import MockerFixture

from mthds.client.client import MthdsAPIClient
from mthds.client.exceptions import (
    PipelineRequestError,
    RunFailedError,
    RunLifecycleUnavailableError,
    RunStillRunningError,
    RunTimeoutError,
)
from mthds.client.runs import (
    PollInfo,
    RunResultCompleted,
    RunResultFailed,
    RunResultRunning,
    RunResults,
    RunStatus,
    WaitForResultOptions,
)

# A bare-runner-shaped base: the SDK composes {base}/v1/... against any MTHDS runner
# (hosted or self-hosted) — valid against localhost:8081 after the pipelex-api /v1 re-mount.
_BASE_URL = "http://localhost:8081"


def _response(status_code: int, *, json: object = None, headers: dict[str, str] | None = None) -> httpx.Response:
    """Build a constructed httpx.Response with a request attached (so raise_for_status works)."""
    request = httpx.Request("GET", f"{_BASE_URL}/x")
    if json is None:
        return httpx.Response(status_code, headers=headers or {}, request=request)
    return httpx.Response(status_code, json=json, headers=headers or {}, request=request)


class TestMthdsAPIClientLifecycle:
    """Tests for the hosted run-lifecycle methods and their status mapping."""

    @pytest.fixture(autouse=True)
    def _mock_credentials(self, mocker: MockerFixture) -> None:
        """Keep construction hermetic — never touch the real credentials file/env."""
        mocker.patch(
            "mthds.client.client.load_credentials",
            return_value={"api_key": "", "api_url": "", "runner": "api", "telemetry": "0"},
        )

    def _client(self) -> MthdsAPIClient:
        return MthdsAPIClient(api_token="test-token", api_base_url=_BASE_URL)

    # ── URL derivation (asserted via the URL each surface sends to) ──

    def test_start_targets_v1_url(self, mocker: MockerFixture) -> None:
        """Start posts to <base>/v1/start; a trailing slash on the base is stripped."""
        client = MthdsAPIClient(api_token="t", api_base_url=f"{_BASE_URL}/")
        body = {"pipeline_run_id": "run_1", "state": "RUNNING", "created_at": "2026-06-10T00:00:00Z"}
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(202, json=body)))

        asyncio.run(client.start(method_id="mt_1"))
        assert client.api_base_url == _BASE_URL
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/start"

    def test_execute_targets_v1_url(self, mocker: MockerFixture) -> None:
        """Execute posts to <base>/v1/execute — one base URL, protocol path."""
        client = self._client()
        captured: dict[str, str] = {}

        def capture(_method: str, url: str, **_kwargs: object) -> httpx.Response:
            captured["url"] = url
            return _response(500, json={})  # abort after the URL is built; derivation is what we assert

        mocker.patch.object(client, "_send", mocker.AsyncMock(side_effect=capture))
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.execute(pipe_code="answer"))
        assert captured["url"] == f"{_BASE_URL}/v1/execute"

    # ── start ────────────────────────────────────────────────────

    def test_start_returns_start_ack(self, mocker: MockerFixture) -> None:
        """A 202 from POST /v1/start parses into a StartAck with the authoritative run_id."""
        client = self._client()
        body = {"pipeline_run_id": "run_1", "state": "RUNNING", "created_at": "2026-06-10T00:00:00Z"}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(202, json=body)))

        ack = asyncio.run(client.start(method_id="mt_1"))
        assert ack.pipeline_run_id == "run_1"
        assert ack.created_at == "2026-06-10T00:00:00Z"

    def test_start_request_shape_with_method_id(self, mocker: MockerFixture) -> None:
        """The named pipelex extensions (method_id, callback_urls) ride the body; absent fields are pruned (exclude_none)."""
        client = self._client()
        body = {"pipeline_run_id": "run_1", "state": "RUNNING", "created_at": "2026-06-10T00:00:00Z"}
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(202, json=body)))

        asyncio.run(client.start(method_id="mt_1", callback_urls=["https://example.com/done"]))
        sent = send_mock.call_args.kwargs["content"].decode("utf-8")
        assert '"method_id":"mt_1"' in sent
        assert '"callback_urls":["https://example.com/done"]' in sent
        assert "pipe_code" not in sent
        assert "pipeline_run_id" not in sent

    def test_start_extra_passthrough_rides_body(self, mocker: MockerFixture) -> None:
        """Arbitrary extension args given via `extra` reach the wire as top-level body properties."""
        client = self._client()
        body = {"pipeline_run_id": "run_1", "state": "RUNNING", "created_at": "2026-06-10T00:00:00Z"}
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(202, json=body)))

        asyncio.run(client.start(pipe_code="answer", extra={"some_vendor_arg": {"nested": True}, "priority": 3}))
        sent = send_mock.call_args.kwargs["content"].decode("utf-8")
        assert '"some_vendor_arg":{"nested":true}' in sent
        assert '"priority":3' in sent
        assert '"pipe_code":"answer"' in sent

    def test_start_extra_rejects_protocol_args(self) -> None:
        """`extra` is for extension args only — a protocol arg inside it raises a clear client-side error."""
        client = self._client()
        with pytest.raises(PipelineRequestError, match="pipe_code"):
            asyncio.run(client.start(method_id="mt_1", extra={"pipe_code": "smuggled"}))

    def test_execute_extension_args_ride_body(self, mocker: MockerFixture) -> None:
        """execute() carries the method_id pipelex extension and the generic extra passthrough too."""
        client = self._client()
        body: dict[str, object] = {
            "pipeline_run_id": "run_1",
            "state": "COMPLETED",
            "created_at": "2026-06-10T00:00:00Z",
            "pipe_output": {"working_memory": {"root": {}, "aliases": {}}, "pipeline_run_id": "run_1"},
        }
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        asyncio.run(client.execute(method_id="mt_1", extra={"some_vendor_arg": "yes"}))
        sent = send_mock.call_args.kwargs["content"].decode("utf-8")
        assert '"method_id":"mt_1"' in sent
        assert '"some_vendor_arg":"yes"' in sent

    # ── get_run_status ───────────────────────────────────────────

    def test_get_run_status_populates_degraded_and_retry_after(self, mocker: MockerFixture) -> None:
        """get_run_status hits /v1/runs/{id}/status, parses RunRead, and lifts Retry-After."""
        client = self._client()
        body = {"pipeline_run_id": "run_1", "status": "RUNNING", "created_at": "2026-06-10T00:00:00Z", "degraded": True}
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body, headers={"Retry-After": "7"})))

        run = asyncio.run(client.get_run_status("run_1"))
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/runs/run_1/status"
        assert run.degraded is True
        assert run.retry_after_seconds == 7

    def test_get_run_status_run_not_found_is_not_lifecycle_unavailable(self, mocker: MockerFixture) -> None:
        """A structured platform 404 (run not found, carries `code`) is a normal HTTP error, not unavailable."""
        client = self._client()
        body = {"code": "NOT_FOUND", "title": "Not found", "detail": "The requested resource does not exist."}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(404, json=body)))

        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.get_run_status("run_missing"))

    def test_get_run_status_lifecycle_unavailable_on_missing_route(self, mocker: MockerFixture) -> None:
        """A bare-runner 404 with Starlette's default body (no error envelope) becomes RunLifecycleUnavailableError."""
        client = self._client()
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(404, json={"detail": "Not Found"})))

        with pytest.raises(RunLifecycleUnavailableError) as exc_info:
            asyncio.run(client.get_run_status("run_1"))
        assert exc_info.value.api_url == _BASE_URL

    # ── get_run_result status mapping ────────────────────────────

    def test_get_run_result_completed(self, mocker: MockerFixture) -> None:
        """A 200 on /v1/runs/{id}/results maps to RunResultCompleted; a list main_stuff stays a top-level array."""
        client = self._client()
        body: dict[str, object] = {
            "pipeline_run_id": "run_1",
            "main_stuff": [{"color": "red"}, {"color": "blue"}],
            "graph_spec": {"nodes": []},
        }
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        state = asyncio.run(client.get_run_result("run_1"))
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/v1/runs/run_1/results"
        assert isinstance(state, RunResultCompleted)
        assert state.result.main_stuff == [{"color": "red"}, {"color": "blue"}]

    def test_get_run_result_running_honors_retry_after(self, mocker: MockerFixture) -> None:
        """A 202 maps to RunResultRunning with the server's Retry-After hint."""
        client = self._client()
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(202, headers={"Retry-After": "3"})))

        state = asyncio.run(client.get_run_result("run_1"))
        assert isinstance(state, RunResultRunning)
        assert state.retry_after_seconds == 3

    def test_get_run_result_degraded_503_defaults_retry(self, mocker: MockerFixture) -> None:
        """A 503 (DynamoDB/Temporal degraded) maps to running with the default retry, never a failure."""
        client = self._client()
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(503)))

        state = asyncio.run(client.get_run_result("run_1"))
        assert isinstance(state, RunResultRunning)
        assert state.retry_after_seconds == 5

    def test_get_run_result_failed_extracts_status(self, mocker: MockerFixture) -> None:
        """A 409 maps to RunResultFailed with the terminal status parsed from the detail message."""
        client = self._client()
        body = {"code": "CONFLICT", "detail": "Run finished with status TIMED_OUT; no result available"}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(409, json=body)))

        state = asyncio.run(client.get_run_result("run_1"))
        assert isinstance(state, RunResultFailed)
        assert state.status == RunStatus.TIMED_OUT
        assert "TIMED_OUT" in state.message

    def test_get_run_result_lifecycle_unavailable_on_missing_route(self, mocker: MockerFixture) -> None:
        """A bare-runner 404 on the results route becomes RunLifecycleUnavailableError."""
        client = self._client()
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(404, json={"detail": "Not Found"})))

        with pytest.raises(RunLifecycleUnavailableError):
            asyncio.run(client.get_run_result("run_1"))

    # ── execute 202 degrade (protocol MAY; eng-review 3B) ────────

    def test_execute_202_raises_typed_still_running(self, mocker: MockerFixture) -> None:
        """A 202 + StartAck on execute raises RunStillRunningError carrying run_id + hints."""
        client = self._client()
        body = {"pipeline_run_id": "run_1", "state": "RUNNING", "created_at": "2026-06-10T00:00:00Z"}
        headers = {"Retry-After": "10", "Location": "/v1/runs/run_1/results"}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(202, json=body, headers=headers)))

        with pytest.raises(RunStillRunningError) as exc_info:
            asyncio.run(client.execute(pipe_code="answer"))
        assert exc_info.value.run_id == "run_1"
        assert exc_info.value.retry_after_seconds == 10
        assert exc_info.value.location == "/v1/runs/run_1/results"

    # ── wait_for_result poll loop ────────────────────────────────

    def test_wait_for_result_polls_until_completed(self, mocker: MockerFixture) -> None:
        """The loop polls past a running state and returns the completed result; on_poll fires per wait."""
        client = self._client()
        result = RunResults(pipeline_run_id="run_1", main_stuff={"answer": "42"})
        mocker.patch.object(
            client,
            "get_run_result",
            mocker.AsyncMock(
                side_effect=[
                    RunResultRunning(pipeline_run_id="run_1", retry_after_seconds=0),
                    RunResultCompleted(pipeline_run_id="run_1", result=result),
                ]
            ),
        )
        mocker.patch("mthds.client.client.asyncio.sleep", mocker.AsyncMock())
        polls: list[PollInfo] = []

        returned = asyncio.run(client.wait_for_result("run_1", WaitForResultOptions(interval_seconds=0.0, on_poll=polls.append)))
        assert returned.main_stuff == {"answer": "42"}
        assert len(polls) == 1
        assert polls[0].attempt == 1

    def test_wait_for_result_raises_run_failed(self, mocker: MockerFixture) -> None:
        """A terminal non-COMPLETED state raises RunFailedError carrying the typed status."""
        client = self._client()
        mocker.patch.object(
            client,
            "get_run_result",
            mocker.AsyncMock(return_value=RunResultFailed(pipeline_run_id="run_1", status=RunStatus.CANCELLED, message="cancelled")),
        )

        with pytest.raises(RunFailedError) as exc_info:
            asyncio.run(client.wait_for_result("run_1"))
        assert exc_info.value.run_id == "run_1"
        assert exc_info.value.status == RunStatus.CANCELLED

    def test_wait_for_result_times_out(self, mocker: MockerFixture) -> None:
        """When the run never terminates and the timeout elapses, RunTimeoutError is raised (run survives).

        timeout_seconds=0.0 makes the first running poll exceed the budget immediately, so the loop
        raises before sleeping — no wall-clock wait and no time patching (which would feed asyncio).
        """
        client = self._client()
        mocker.patch.object(
            client,
            "get_run_result",
            mocker.AsyncMock(return_value=RunResultRunning(pipeline_run_id="run_1", retry_after_seconds=0)),
        )

        with pytest.raises(RunTimeoutError) as exc_info:
            asyncio.run(client.wait_for_result("run_1", WaitForResultOptions(timeout_seconds=0.0)))
        assert exc_info.value.run_id == "run_1"
        assert exc_info.value.timeout_seconds == 0.0

    def test_wait_for_result_propagates_cancellation(self, mocker: MockerFixture) -> None:
        """Cancellation surfaces as asyncio.CancelledError (the loop never swallows it; run stays resumable)."""
        client = self._client()
        mocker.patch.object(client, "get_run_result", mocker.AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(client.wait_for_result("run_1"))
