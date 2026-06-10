import asyncio
import re
import time
from typing import Any, cast
from urllib.parse import quote

import httpx
from typing_extensions import override

from mthds.client.exceptions import (
    ClientAuthenticationError,
    PipelineRequestError,
    RunFailedError,
    RunLifecycleUnavailableError,
    RunTimeoutError,
)
from mthds.client.pipeline import DictPipelineExecuteResponse, DictPipelineStartResponse, PipelineRequest
from mthds.client.protocol import RunnerProtocol
from mthds.client.runs import (
    PollInfo,
    RunPublic,
    RunRead,
    RunResult,
    RunResultCompleted,
    RunResultFailed,
    RunResultRunning,
    RunResultState,
    RunStatus,
    StartRunRequest,
    WaitForResultOptions,
)
from mthds.config.credentials import load_credentials
from mthds.models.pipe_output import DictPipeOutputAbstract, VariableMultiplicity
from mthds.models.pipeline_inputs import PipelineInputs
from mthds.models.stuff import StuffType
from mthds.models.working_memory import WorkingMemoryAbstract

# The SDK derives both surfaces from one origin (MTHDS_API_URL). Self-host open question §7:
# default to the hosted runner prefix /runner/v1 (a bare pipelex-api serves /api/v1, no platform).
_RUNNER_PREFIX = "runner/v1"
_PLATFORM_PREFIX = "platform/v1"
_PLATFORM_RUNS = "runs"

_DEFAULT_REQUEST_TIMEOUT_SECONDS = 1200.0  # runner blocking-execute ceiling
_POLL_REQUEST_TIMEOUT_SECONDS = 30.0  # single status/result GETs; the hosted gateway caps responses at ~30s
_DEFAULT_DEGRADED_RETRY_SECONDS = 5  # matches the platform's _DEGRADE_RETRY_AFTER_SECONDS


class MthdsAPIClient(RunnerProtocol[DictPipeOutputAbstract]):
    """Client for the MTHDS API — runner (execution) + platform (durable run lifecycle).

    One base URL (`MTHDS_API_URL`); the SDK derives both surfaces under it:
    - **runner** (`<base>/runner/v1/*`) — blocking `execute_pipeline` / fire-and-forget `start_pipeline`.
    - **platform** (`<base>/platform/v1/runs*`) — the durable run lifecycle (`start_run` / `get_run` /
      `get_result` / `wait_for_result`) that survives long runs and lets a caller resume by id.

    The platform surface is served only by a deployment that includes the pipelex-platform block
    (the hosted MTHDS API); a bare `pipelex-api` runner 404s those routes, which the lifecycle
    methods translate into a clear `RunLifecycleUnavailableError`.
    """

    def __init__(
        self,
        api_token: str | None = None,
        api_base_url: str | None = None,
    ):
        credentials = load_credentials()

        resolved_api_token = api_token or credentials["api_key"]
        if not resolved_api_token:
            msg = "API token is required for API execution. Set MTHDS_API_KEY or run: mthds config set api-key <key>"
            raise ClientAuthenticationError(msg)
        self.api_token = resolved_api_token

        resolved_api_base_url = api_base_url or credentials["api_url"]
        if not resolved_api_base_url:
            msg = "API base URL is required for API execution. Set MTHDS_API_URL or run: mthds config set api-url <url>"
            raise ClientAuthenticationError(msg)
        self.api_base_url = resolved_api_base_url.rstrip("/")

        self.client: httpx.AsyncClient | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start_client(self) -> "MthdsAPIClient":
        """Initialize the HTTP client for API calls."""
        self.client = httpx.AsyncClient(headers={"Authorization": f"Bearer {self.api_token}"})
        return self

    async def close(self) -> None:
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def __aenter__(self) -> "MthdsAPIClient":
        self.start_client()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # ── URL resolution ─────────────────────────────────────────────────

    def _runner_url(self, endpoint: str) -> str:
        """Build a runner URL: `<base>/runner/v1/<endpoint>`."""
        return f"{self.api_base_url}/{_RUNNER_PREFIX}/{endpoint}"

    def _platform_url(self, endpoint: str) -> str:
        """Build a platform (run-lifecycle) URL: `<base>/platform/v1/<endpoint>`."""
        return f"{self.api_base_url}/{_PLATFORM_PREFIX}/{endpoint}"

    # ── Transport ──────────────────────────────────────────────────────

    async def _send(self, method: str, url: str, *, content: bytes | None, request_timeout: float) -> httpx.Response:
        """Issue one HTTP request and return the raw response (status interpretation is the caller's).

        Args:
            method: HTTP method ("GET" or "POST").
            url: Fully-resolved absolute URL.
            content: JSON-encoded request body, or None for a bodyless request.
            request_timeout: Per-request timeout in seconds.

        Returns:
            The httpx.Response, without status-code interpretation.
        """
        if not self.client:
            self.start_client()
            assert self.client is not None

        headers = {"Accept": "application/json"}
        if content is not None:
            headers["Content-Type"] = "application/json"
        return await self.client.request(method, url, content=content, headers=headers, timeout=request_timeout)

    async def _make_api_call(self, endpoint: str, pipeline_request: PipelineRequest | None = None) -> dict[str, Any]:
        """POST a pipeline request to a runner endpoint and return the parsed body.

        Args:
            endpoint: Runner endpoint relative to `/runner/v1` (e.g. "pipeline/execute").
            pipeline_request: Request body to send, or None for a bodyless call.

        Returns:
            The JSON-decoded response from the runner.

        Raises:
            httpx.HTTPStatusError: If the runner returns a non-2xx status.
        """
        content = pipeline_request.model_dump_json().encode("utf-8") if pipeline_request is not None else None
        response = await self._send("POST", self._runner_url(endpoint), content=content, request_timeout=_DEFAULT_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        response_data: dict[str, Any] = response.json()
        return response_data

    def _raise_if_lifecycle_unavailable(self, response: httpx.Response, url: str) -> None:
        """Translate a "route absent" 404 (a bare pipelex-api with no platform block) into a clear
        `RunLifecycleUnavailableError`. The platform's own 404s (run not found / cross-org) carry a
        structured problem+json envelope (a `code` field) and are left for normal handling.
        """
        if response.status_code != 404:
            return
        if _is_missing_route_404(response):
            msg = (
                f"The durable run lifecycle is not available: {url} returned 404. The platform routes "
                f"(/{_PLATFORM_PREFIX}/{_PLATFORM_RUNS}*) are served only by a deployment that includes the "
                "platform block (the hosted MTHDS API); MTHDS_API_URL points at a bare pipelex-api runner."
            )
            raise RunLifecycleUnavailableError(msg, api_url=self.api_base_url)

    # ── Runner surface (blocking execution) ─────────────────────────────

    @override
    async def execute_pipeline(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
    ) -> DictPipelineExecuteResponse:
        """Execute a pipeline synchronously and wait for its completion.

        Args:
            pipe_code: The code identifying the pipeline to execute
            mthds_contents: List of MTHDS bundle contents to load
            inputs: Inputs passed to the pipeline
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for the dynamic output concept ref

        Returns:
            Complete execution results including pipeline state and output
        """
        if not pipe_code and not mthds_contents:
            msg = "Either pipe_code or mthds_contents must be provided to the API execute_pipeline."
            raise PipelineRequestError(msg)

        pipeline_request = PipelineRequest(
            pipe_code=pipe_code,
            mthds_contents=mthds_contents,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_ref=dynamic_output_concept_ref,
        )
        response = await self._make_api_call("pipeline/execute", pipeline_request=pipeline_request)
        return DictPipelineExecuteResponse.from_api_response(response)

    @override
    async def start_pipeline(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
    ) -> DictPipelineStartResponse:
        """Start a pipeline execution asynchronously without waiting for completion.

        Args:
            pipe_code: The code identifying the pipeline to execute
            mthds_contents: List of MTHDS bundle contents to load
            inputs: Inputs passed to the pipeline
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for the dynamic output concept ref

        Returns:
            Initial response with pipeline_run_id and created_at timestamp
        """
        if not pipe_code and not mthds_contents:
            msg = "Either pipe_code or mthds_contents must be provided to the API start_pipeline."
            raise PipelineRequestError(msg)

        pipeline_request = PipelineRequest(
            pipe_code=pipe_code,
            mthds_contents=mthds_contents,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_ref=dynamic_output_concept_ref,
        )
        response = await self._make_api_call("pipeline/start", pipeline_request=pipeline_request)
        return DictPipelineStartResponse.from_api_response(response)

    # ── Platform surface (durable run lifecycle) ────────────────────────

    async def start_run(self, request: StartRunRequest) -> RunPublic:
        """Start a run — `POST /platform/v1/runs`. Returns the created run record; the run executes
        asynchronously. Poll `get_result` / `wait_for_result` (or `get_run` for status) by the
        returned `pipeline_run_id`.

        Raises:
            RunLifecycleUnavailableError: If the platform routes are absent (a bare runner).
            httpx.HTTPStatusError: For any other non-2xx response.
        """
        url = self._platform_url(_PLATFORM_RUNS)
        content = request.model_dump_json(exclude_none=True).encode("utf-8")
        response = await self._send("POST", url, content=content, request_timeout=_POLL_REQUEST_TIMEOUT_SECONDS)
        self._raise_if_lifecycle_unavailable(response, url)
        response.raise_for_status()
        return RunPublic.model_validate(response.json())

    async def get_run(self, run_id: str) -> RunRead:
        """Fetch a run's status by bare id — `GET /platform/v1/runs/by-id/{run_id}`.

        Self-healing: a finished-but-unrecorded run resolves to its true terminal status on read.
        `degraded=True` means Temporal was unreachable and `status` is the last-known value;
        `retry_after_seconds` carries the server's `Retry-After` hint when present.

        Raises:
            RunLifecycleUnavailableError: If the platform routes are absent (a bare runner).
            httpx.HTTPStatusError: For a genuine run-not-found 404 or any other non-2xx response.
        """
        url = self._platform_url(f"{_PLATFORM_RUNS}/by-id/{quote(run_id, safe='')}")
        response = await self._send("GET", url, content=None, request_timeout=_POLL_REQUEST_TIMEOUT_SECONDS)
        self._raise_if_lifecycle_unavailable(response, url)
        response.raise_for_status()
        run = RunRead.model_validate(response.json())
        retry_after = _parse_retry_after(response.headers)
        if retry_after is not None:
            run = run.model_copy(update={"retry_after_seconds": retry_after})
        return run

    async def get_result(self, run_id: str) -> RunResultState:
        """Single-shot result lookup — `GET /platform/v1/runs/by-id/{run_id}/result`.

        Maps the platform's poll semantics to a discriminated union:
        - HTTP 202 → `running` (in-flight, with the `Retry-After` hint)
        - HTTP 503 → `running` (DynamoDB/Temporal degraded — retry, never fail a poller)
        - HTTP 200 → `completed` (with the result artifacts)
        - HTTP 409 → `failed` (terminal non-`COMPLETED`)

        Raises:
            RunLifecycleUnavailableError: If the platform routes are absent (a bare runner).
            httpx.HTTPStatusError: For a genuine run-not-found 404 or any other non-2xx response.
        """
        url = self._platform_url(f"{_PLATFORM_RUNS}/by-id/{quote(run_id, safe='')}/result")
        response = await self._send("GET", url, content=None, request_timeout=_POLL_REQUEST_TIMEOUT_SECONDS)
        status_code = response.status_code

        if status_code in {202, 503}:
            retry_after = _parse_retry_after(response.headers)
            return RunResultRunning(
                pipeline_run_id=run_id,
                retry_after_seconds=retry_after if retry_after is not None else _DEFAULT_DEGRADED_RETRY_SECONDS,
            )
        if status_code == 409:
            message = _parse_error_message(response) or "Run finished without a result."
            return RunResultFailed(
                pipeline_run_id=run_id,
                status=_extract_run_status_from_message(message),
                message=message,
            )

        self._raise_if_lifecycle_unavailable(response, url)
        response.raise_for_status()
        result = RunResult.model_validate(response.json())
        return RunResultCompleted(pipeline_run_id=run_id, result=result)

    async def wait_for_result(self, run_id: str, options: WaitForResultOptions | None = None) -> RunResult:
        """Poll a run to a terminal state and return its result.

        Resolves on `COMPLETED`, raises `RunFailedError` on any other terminal status, and raises
        `RunTimeoutError` if `timeout_seconds` elapses first (the run keeps executing server-side —
        resume later by `run_id`). Honors the server's `Retry-After`. Async-native: cancelling the
        awaiting task raises `asyncio.CancelledError` out of this loop, leaving the run resumable.

        Args:
            run_id: The `pipeline_run_id` returned by `start_run`.
            options: Poll-loop tuning (interval, timeout, on_poll callback).

        Returns:
            The result artifacts of the completed run.
        """
        opts = options or WaitForResultOptions()
        started_at = time.monotonic()
        attempt = 0

        while True:
            state = await self.get_result(run_id)
            if isinstance(state, RunResultCompleted):
                return state.result
            if isinstance(state, RunResultFailed):
                msg = state.message
                raise RunFailedError(msg, run_id=run_id, status=state.status)

            # state is RunResultRunning — decide whether to keep waiting.
            attempt += 1
            elapsed = time.monotonic() - started_at
            if elapsed >= opts.timeout_seconds:
                msg = (
                    f"Run {run_id} did not reach a terminal state within {opts.timeout_seconds}s; "
                    "it is still executing server-side and can be resumed by id."
                )
                raise RunTimeoutError(msg, run_id=run_id, timeout_seconds=opts.timeout_seconds)
            if opts.on_poll is not None:
                opts.on_poll(PollInfo(attempt=attempt, elapsed_seconds=elapsed))

            retry_seconds = state.retry_after_seconds if state.retry_after_seconds is not None else 0
            wait_seconds = min(max(opts.interval_seconds, retry_seconds), opts.timeout_seconds - elapsed)
            await asyncio.sleep(wait_seconds)


# ── Module helpers ──────────────────────────────────────────────────────

_KNOWN_RUN_STATUS_NAMES: frozenset[str] = frozenset(RunStatus.__members__)


def _is_missing_route_404(response: httpx.Response) -> bool:
    """Whether a 404 is an unmatched-route 404 (no platform deployed) rather than the platform's
    structured run-not-found 404. The platform wraps its 404s in RFC 7807 problem+json with a stable
    `code`; a bare runner returns Starlette's default `{"detail": "Not Found"}` (no `code`).
    """
    try:
        body = response.json()
    except ValueError:
        return True
    if not isinstance(body, dict):
        return True
    return "code" not in body


def _parse_retry_after(headers: httpx.Headers) -> int | None:
    """Parse the `Retry-After` header (integer-seconds form, which the platform uses)."""
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        seconds = int(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def _parse_error_message(response: httpx.Response) -> str | None:
    """Extract a human message from an error body — handles the platform's problem+json (`detail`
    string) and the runner's `{"detail": {"message": ...}}` / `{"message": ...}` shapes.
    """
    try:
        raw = response.json()
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    body = cast("dict[str, Any]", raw)
    detail = body.get("detail")
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        message = cast("dict[str, Any]", detail).get("message")
        if isinstance(message, str):
            return message
    top_message = body.get("message")
    return top_message if isinstance(top_message, str) else None


def _extract_run_status_from_message(message: str) -> RunStatus:
    """Pull the status word out of a 409 detail ("Run finished with status FAILED; ..."), defaulting
    to FAILED if the shape ever changes.
    """
    match = re.search(r"status\s+([A-Z_]+)", message)
    if match and match.group(1) in _KNOWN_RUN_STATUS_NAMES:
        return RunStatus(match.group(1))
    return RunStatus.FAILED
