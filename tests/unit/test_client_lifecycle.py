"""Tests for MthdsAPIClient's durable run-lifecycle surface (start/get/result/wait), httpx mocked."""

import asyncio

import httpx
import pytest
from pytest_mock import MockerFixture

from mthds.client.client import MthdsAPIClient
from mthds.client.exceptions import RunFailedError, RunLifecycleUnavailableError, RunTimeoutError
from mthds.client.runs import (
    PollInfo,
    RunResult,
    RunResultCompleted,
    RunResultFailed,
    RunResultRunning,
    RunStatus,
    StartRunRequest,
    WaitForResultOptions,
)

_BASE_URL = "https://api.test.example"


def _response(status_code: int, *, json: object = None, headers: dict[str, str] | None = None) -> httpx.Response:
    """Build a constructed httpx.Response with a request attached (so raise_for_status works)."""
    request = httpx.Request("GET", f"{_BASE_URL}/x")
    if json is None:
        return httpx.Response(status_code, headers=headers or {}, request=request)
    return httpx.Response(status_code, json=json, headers=headers or {}, request=request)


class TestMthdsAPIClientLifecycle:
    """Tests for the platform run-lifecycle methods and their status mapping."""

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

    def test_start_run_targets_platform_v1_url(self, mocker: MockerFixture) -> None:
        """The platform surface is derived as <base>/platform/v1/runs; a trailing slash is stripped."""
        client = MthdsAPIClient(api_token="t", api_base_url=f"{_BASE_URL}/")
        body = {"pipeline_run_id": "run_1", "status": "RUNNING", "created_at": "2026-06-10T00:00:00Z"}
        send_mock = mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(201, json=body)))

        asyncio.run(client.start_run(StartRunRequest(method_id="mt_1")))
        assert client.api_base_url == _BASE_URL
        assert send_mock.call_args.args[1] == f"{_BASE_URL}/platform/v1/runs"

    def test_execute_pipeline_targets_runner_v1_url(self, mocker: MockerFixture) -> None:
        """The runner surface is derived as <base>/runner/v1/pipeline/execute (the version-prefix fix)."""
        client = self._client()
        captured: dict[str, str] = {}

        def capture(_method: str, url: str, **_kwargs: object) -> httpx.Response:
            captured["url"] = url
            return _response(500, json={})  # abort after the URL is built; derivation is what we assert

        mocker.patch.object(client, "_send", mocker.AsyncMock(side_effect=capture))
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.execute_pipeline(pipe_code="answer"))
        assert captured["url"] == f"{_BASE_URL}/runner/v1/pipeline/execute"

    # ── start_run ────────────────────────────────────────────────

    def test_start_run_returns_run_public(self, mocker: MockerFixture) -> None:
        """A 201 from POST /platform/v1/runs parses into a RunPublic."""
        client = self._client()
        body = {"pipeline_run_id": "run_1", "method_id": "mt_1", "status": "RUNNING", "created_at": "2026-06-10T00:00:00Z"}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(201, json=body)))

        run = asyncio.run(client.start_run(StartRunRequest(method_id="mt_1")))
        assert run.pipeline_run_id == "run_1"
        assert run.status == RunStatus.RUNNING

    def test_start_run_lifecycle_unavailable_on_missing_route(self, mocker: MockerFixture) -> None:
        """A bare-runner 404 with Starlette's default body (no error envelope) becomes RunLifecycleUnavailableError."""
        client = self._client()
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(404, json={"detail": "Not Found"})))

        with pytest.raises(RunLifecycleUnavailableError) as exc_info:
            asyncio.run(client.start_run(StartRunRequest(method_id="mt_1")))
        assert exc_info.value.api_url == _BASE_URL

    # ── get_run ──────────────────────────────────────────────────

    def test_get_run_populates_degraded_and_retry_after(self, mocker: MockerFixture) -> None:
        """get_run parses RunRead and lifts the Retry-After header onto retry_after_seconds."""
        client = self._client()
        body = {"pipeline_run_id": "run_1", "status": "RUNNING", "created_at": "2026-06-10T00:00:00Z", "degraded": True}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body, headers={"Retry-After": "7"})))

        run = asyncio.run(client.get_run("run_1"))
        assert run.degraded is True
        assert run.retry_after_seconds == 7

    def test_get_run_run_not_found_is_not_lifecycle_unavailable(self, mocker: MockerFixture) -> None:
        """A structured platform 404 (run not found, carries `code`) is a normal HTTP error, not unavailable."""
        client = self._client()
        body = {"code": "NOT_FOUND", "title": "Not found", "detail": "The requested resource does not exist."}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(404, json=body)))

        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(client.get_run("run_missing"))

    # ── get_result status mapping ────────────────────────────────

    def test_get_result_completed(self, mocker: MockerFixture) -> None:
        """A 200 maps to RunResultCompleted; a list main_stuff stays a top-level array."""
        client = self._client()
        body: dict[str, object] = {
            "pipeline_run_id": "run_1",
            "main_stuff": [{"color": "red"}, {"color": "blue"}],
            "graph_spec": {"nodes": []},
        }
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(200, json=body)))

        state = asyncio.run(client.get_result("run_1"))
        assert isinstance(state, RunResultCompleted)
        assert state.result.main_stuff == [{"color": "red"}, {"color": "blue"}]

    def test_get_result_running_honors_retry_after(self, mocker: MockerFixture) -> None:
        """A 202 maps to RunResultRunning with the server's Retry-After hint."""
        client = self._client()
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(202, headers={"Retry-After": "3"})))

        state = asyncio.run(client.get_result("run_1"))
        assert isinstance(state, RunResultRunning)
        assert state.retry_after_seconds == 3

    def test_get_result_degraded_503_defaults_retry(self, mocker: MockerFixture) -> None:
        """A 503 (DynamoDB/Temporal degraded) maps to running with the default retry, never a failure."""
        client = self._client()
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(503)))

        state = asyncio.run(client.get_result("run_1"))
        assert isinstance(state, RunResultRunning)
        assert state.retry_after_seconds == 5

    def test_get_result_failed_extracts_status(self, mocker: MockerFixture) -> None:
        """A 409 maps to RunResultFailed with the terminal status parsed from the detail message."""
        client = self._client()
        body = {"code": "CONFLICT", "detail": "Run finished with status TIMED_OUT; no result available"}
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(409, json=body)))

        state = asyncio.run(client.get_result("run_1"))
        assert isinstance(state, RunResultFailed)
        assert state.status == RunStatus.TIMED_OUT
        assert "TIMED_OUT" in state.message

    def test_get_result_lifecycle_unavailable_on_missing_route(self, mocker: MockerFixture) -> None:
        """A bare-runner 404 on the result route becomes RunLifecycleUnavailableError."""
        client = self._client()
        mocker.patch.object(client, "_send", mocker.AsyncMock(return_value=_response(404, json={"detail": "Not Found"})))

        with pytest.raises(RunLifecycleUnavailableError):
            asyncio.run(client.get_result("run_1"))

    # ── wait_for_result poll loop ────────────────────────────────

    def test_wait_for_result_polls_until_completed(self, mocker: MockerFixture) -> None:
        """The loop polls past a running state and returns the completed result; on_poll fires per wait."""
        client = self._client()
        result = RunResult(pipeline_run_id="run_1", main_stuff={"answer": "42"})
        mocker.patch.object(
            client,
            "get_result",
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
            "get_result",
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
            "get_result",
            mocker.AsyncMock(return_value=RunResultRunning(pipeline_run_id="run_1", retry_after_seconds=0)),
        )

        with pytest.raises(RunTimeoutError) as exc_info:
            asyncio.run(client.wait_for_result("run_1", WaitForResultOptions(timeout_seconds=0.0)))
        assert exc_info.value.run_id == "run_1"
        assert exc_info.value.timeout_seconds == 0.0

    def test_wait_for_result_propagates_cancellation(self, mocker: MockerFixture) -> None:
        """Cancellation surfaces as asyncio.CancelledError (the loop never swallows it; run stays resumable)."""
        client = self._client()
        mocker.patch.object(client, "get_result", mocker.AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            asyncio.run(client.wait_for_result("run_1"))
