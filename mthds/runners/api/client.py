from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

import httpx
from pydantic_core import to_json
from typing_extensions import override

from mthds.config.credentials import load_credentials
from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.models import ModelCategory, ModelDeck, RunResultStart, ValidationReport, VersionInfo
from mthds.protocol.protocol import MTHDSProtocol
from mthds.runners.api.exceptions import (
    ClientAuthenticationError,
    RunFailedError,
    RunLifecycleUnavailableError,
    RunStillRunningError,
    RunTimeoutError,
)
from mthds.runners.api.models import DictPipeOutputAbstract, DictRunResultExecute
from mthds.runners.api.runs import (
    PollInfo,
    RunRead,
    RunResultCompleted,
    RunResultFailed,
    RunResultRunning,
    RunResults,
    RunResultState,
    RunStatus,
    WaitForResultOptions,
)
from mthds.runners.types import RunnerType

if TYPE_CHECKING:
    from typing_extensions import Self

    from mthds.protocol.pipe_output import VariableMultiplicity
    from mthds.protocol.pipeline_inputs import PipelineInputs
    from mthds.protocol.stuff import StuffType
    from mthds.protocol.working_memory import WorkingMemoryAbstract

# The SDK composes every endpoint from one origin (MTHDS_API_URL): `{base}/v1/{endpoint}`.
# The same paths are served by the hosted MTHDS API (api.pipelex.com/v1) and by a bare
# pipelex-api runner (localhost:8081/v1) — the protocol surface is identical; only the
# hosted extensions (e.g. run polling) differ, detectable via GET /version.
_API_PREFIX = "v1"
_RUNS = "runs"

_DEFAULT_REQUEST_TIMEOUT_SECONDS = 1200.0  # runner blocking-execute ceiling
_POLL_REQUEST_TIMEOUT_SECONDS = 30.0  # single status/result GETs; the hosted gateway caps responses at ~30s
_DEFAULT_DEGRADED_RETRY_SECONDS = 5  # matches the platform's _DEGRADE_RETRY_AFTER_SECONDS


class MthdsAPIClient(MTHDSProtocol[DictPipeOutputAbstract]):
    """Client for any MTHDS runner — protocol surface + hosted run-lifecycle extension.

    One base URL (`MTHDS_API_URL`); every endpoint is `<base>/v1/<endpoint>`:
    - **protocol** (`execute` / `start` / `validate` / `models` / `version`) — works against
      any MTHDS-compliant runner, hosted or bare.
    - **run lifecycle** (`get_run_status` / `get_run_result` / `wait_for_result`) — the durable
      polling extension that survives long runs and lets a caller resume by id. Served only by
      a deployment that includes the platform block (the hosted MTHDS API); a bare `pipelex-api`
      runner 404s those routes, which the lifecycle methods translate into a clear
      `RunLifecycleUnavailableError`.
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

    @property
    def runner_type(self) -> RunnerType:
        """Return the runner type (the API client IS the API runner — parity D8)."""
        return RunnerType.API

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start_client(self) -> MthdsAPIClient:
        """Initialize the HTTP client for API calls."""
        self.client = httpx.AsyncClient(headers={"Authorization": f"Bearer {self.api_token}"})
        return self

    async def close(self) -> None:
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
            self.client = None

    async def __aenter__(self) -> Self:
        self.start_client()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # ── URL resolution ─────────────────────────────────────────────────

    def _url(self, endpoint: str) -> str:
        """Build an API URL: `<base>/v1/<endpoint>`."""
        return f"{self.api_base_url}/{_API_PREFIX}/{endpoint}"

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

    def _raise_if_lifecycle_unavailable(self, response: httpx.Response, url: str) -> None:
        """Translate a "route absent" 404 (a bare pipelex-api with no platform block) into a clear
        `RunLifecycleUnavailableError`. The platform's own 404s (run not found / cross-org) carry a
        structured problem+json envelope (a `code` field) and are left for normal handling.
        """
        if response.status_code != 404:
            return
        if _is_missing_route_404(response):
            msg = (
                f"The durable run lifecycle is not available: {url} returned 404. Run polling is a "
                f"hosted-API extension (/{_API_PREFIX}/{_RUNS}/*), not part of the MTHDS Protocol; "
                "MTHDS_API_URL points at a bare runner that does not serve it."
            )
            raise RunLifecycleUnavailableError(msg, api_url=self.api_base_url)

    # ── Protocol surface ─────────────────────────────────────────────────

    @override
    async def execute(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> DictRunResultExecute:
        """Execute a method synchronously and wait for its completion — `POST /v1/execute`.

        Args:
            pipe_code: The code identifying the pipe to execute
            mthds_contents: List of MTHDS bundle contents to load
            inputs: Inputs passed to the method
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for the dynamic output concept ref
            extra: Server-specific extension args, merged into the request body
                as top-level properties — the server you call defines and handles
                them; this SDK only passes them through. Protocol args must be
                passed as named parameters, not through `extra` (raises
                `PipelineRequestError`).

        Returns:
            Complete execution results including run state and output

        Raises:
            RunStillRunningError: If the server answers 202 (the protocol's optional
                async degrade) — the run continues server-side; resume by `run_id`.
        """
        if not pipe_code and not mthds_contents and not extra:
            msg = "Either pipe_code, mthds_contents or a server-specific extension arg (extra) must be provided to the API execute."
            raise PipelineRequestError(msg)

        body = _build_run_body(
            pipe_code=pipe_code,
            mthds_contents=mthds_contents,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_ref=dynamic_output_concept_ref,
            extra=extra,
            exclude_none=True,
        )
        content = to_json(body)
        response = await self._send("POST", self._url("execute"), content=content, request_timeout=_DEFAULT_REQUEST_TIMEOUT_SECONDS)
        self._raise_if_execute_degraded(response)
        response.raise_for_status()
        return DictRunResultExecute.model_validate(response.json())

    @override
    async def start(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RunResultStart:
        """Start a method asynchronously — `POST /v1/start` (202: `pipeline_run_id` only).

        Args:
            pipe_code: The code identifying the pipe to execute
            mthds_contents: List of MTHDS bundle contents to load
            inputs: Inputs passed to the method
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for the dynamic output concept ref
            extra: Server-specific extension args, merged into the request body
                as top-level properties — the server you call defines and handles
                them; this SDK only passes them through. Protocol args must be
                passed as named parameters, not through `extra` (raises
                `PipelineRequestError`).

        Returns:
            RunResultStart — the authoritative server-generated `pipeline_run_id`
            (no output yet). On a hosted deployment the id is durable — poll
            `get_run_status` / `get_run_result`.
        """
        if not pipe_code and not mthds_contents and not extra:
            msg = "Either pipe_code, mthds_contents or a server-specific extension arg (extra) must be provided to the API start."
            raise PipelineRequestError(msg)

        body = _build_run_body(
            pipe_code=pipe_code,
            mthds_contents=mthds_contents,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_ref=dynamic_output_concept_ref,
            extra=extra,
            exclude_none=True,
        )
        content = to_json(body)
        response = await self._send("POST", self._url("start"), content=content, request_timeout=_POLL_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return RunResultStart.model_validate(response.json())

    @override
    async def validate(
        self,
        mthds_contents: list[str],
        allow_signatures: bool = False,
    ) -> ValidationReport:
        """Parse, validate, and dry-run an MTHDS bundle — `POST /v1/validate`.

        Args:
            mthds_contents: MTHDS contents to load (always a list, even for one file)
            allow_signatures: Tolerate unimplemented pipe signatures (strict by default)

        Returns:
            ValidationReport with the structural artifacts of a valid bundle.

        Raises:
            httpx.HTTPStatusError: 422 when the bundle is invalid (RFC 7807 problem body).
        """
        body = {"mthds_contents": mthds_contents, "allow_signatures": allow_signatures}
        response = await self._send(
            "POST",
            self._url("validate"),
            content=json.dumps(body).encode("utf-8"),
            request_timeout=_DEFAULT_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return ValidationReport.model_validate(response.json())

    @override
    async def models(self, category: ModelCategory | None = None) -> ModelDeck:
        """The model deck the runner can route to — `GET /v1/models[?type=]`.

        Args:
            category: Optional filter (`llm`, `extract`, `img_gen`, `search`).

        Returns:
            ModelDeck with the models this runner can route to (base fields
            + any implementation extensions).
        """
        endpoint = f"models?type={quote(category, safe='')}" if category is not None else "models"
        response = await self._send("GET", self._url(endpoint), content=None, request_timeout=_POLL_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return ModelDeck.model_validate(response.json())

    @override
    async def version(self) -> VersionInfo:
        """Protocol + runner versions — `GET /v1/version` (public).

        Returns:
            VersionInfo — the handshake for feature detection (hosted extensions or not).
        """
        response = await self._send("GET", self._url("version"), content=None, request_timeout=_POLL_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return VersionInfo.model_validate(response.json())

    def _raise_if_execute_degraded(self, response: httpx.Response) -> None:
        """Map the protocol's optional 202 execute degrade to a typed error.

        Hosted does not emit 202 today, but the protocol permits it; raising a typed
        error (with the `run_id` + `Location` + `Retry-After` hints) beats a generic
        validation failure on an unexpected body shape.
        """
        if response.status_code != 202:
            return
        body: dict[str, Any] = {}
        try:
            raw = response.json()
            if isinstance(raw, dict):
                body = cast("dict[str, Any]", raw)
        except ValueError:
            body = {}
        started_run_id = body.get("pipeline_run_id")
        run_id = started_run_id if isinstance(started_run_id, str) else ""
        msg = (
            f"execute() was accepted asynchronously (202): run {run_id or '<unknown>'} is still "
            "running server-side. Poll its results (hosted) or use start()."
        )
        raise RunStillRunningError(
            msg,
            run_id=run_id,
            retry_after_seconds=_parse_retry_after(response.headers),
            location=response.headers.get("location"),
        )

    # ── Hosted extension: durable run lifecycle (NOT part of the protocol) ──

    async def get_run_status(self, run_id: str) -> RunRead:
        """Fetch a run's status by bare id — `GET /v1/runs/{run_id}/status`.

        Self-healing: a finished-but-unrecorded run resolves to its true terminal status on read.
        `degraded=True` means Temporal was unreachable and `status` is the last-known value;
        `retry_after_seconds` carries the server's `Retry-After` hint when present.

        Raises:
            RunLifecycleUnavailableError: If the lifecycle routes are absent (a bare runner).
            httpx.HTTPStatusError: For a genuine run-not-found 404 or any other non-2xx response.
        """
        url = self._url(f"{_RUNS}/{quote(run_id, safe='')}/status")
        response = await self._send("GET", url, content=None, request_timeout=_POLL_REQUEST_TIMEOUT_SECONDS)
        self._raise_if_lifecycle_unavailable(response, url)
        response.raise_for_status()
        run = RunRead.model_validate(response.json())
        retry_after = _parse_retry_after(response.headers)
        if retry_after is not None:
            run = run.model_copy(update={"retry_after_seconds": retry_after})
        return run

    async def get_run_result(self, run_id: str) -> RunResultState:
        """Single-shot result lookup — `GET /v1/runs/{run_id}/results`.

        Maps the platform's poll semantics to a discriminated union:
        - HTTP 202 → `running` (in-flight, with the `Retry-After` hint)
        - HTTP 503 → `running` (DynamoDB/Temporal degraded — retry, never fail a poller)
        - HTTP 200 → `completed` (with the result artifacts)
        - HTTP 409 → `failed` (terminal non-`COMPLETED`)

        Raises:
            RunLifecycleUnavailableError: If the lifecycle routes are absent (a bare runner).
            httpx.HTTPStatusError: For a genuine run-not-found 404 or any other non-2xx response.
        """
        url = self._url(f"{_RUNS}/{quote(run_id, safe='')}/results")
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
        result = RunResults.model_validate(response.json())
        return RunResultCompleted(pipeline_run_id=run_id, result=result)

    async def wait_for_result(self, run_id: str, options: WaitForResultOptions | None = None) -> RunResults:
        """Poll a run to a terminal state and return its result.

        Resolves on `COMPLETED`, raises `RunFailedError` on any other terminal status, and raises
        `RunTimeoutError` if `timeout_seconds` elapses first (the run keeps executing server-side —
        resume later by `run_id`). Honors the server's `Retry-After`. Async-native: cancelling the
        awaiting task raises `asyncio.CancelledError` out of this loop, leaving the run resumable.

        Args:
            run_id: The `pipeline_run_id` returned by `start`.
            options: Poll-loop tuning (interval, timeout, on_poll callback).

        Returns:
            The result artifacts of the completed run.
        """
        opts = options or WaitForResultOptions()
        started_at = time.monotonic()
        attempt = 0

        while True:
            elapsed = time.monotonic() - started_at
            remaining = opts.timeout_seconds - elapsed
            if remaining <= 0:
                msg = (
                    f"Run {run_id} did not reach a terminal state within {opts.timeout_seconds}s; "
                    "it is still executing server-side and can be resumed by id."
                )
                raise RunTimeoutError(msg, run_id=run_id, timeout_seconds=opts.timeout_seconds)

            try:
                state = await asyncio.wait_for(self.get_run_result(run_id), timeout=remaining)
            except asyncio.TimeoutError as exc:  # noqa: UP041 — on Python 3.10 asyncio.TimeoutError is its own class, distinct from builtin TimeoutError.
                msg = (
                    f"Run {run_id} did not reach a terminal state within {opts.timeout_seconds}s; "
                    "it is still executing server-side and can be resumed by id."
                )
                raise RunTimeoutError(msg, run_id=run_id, timeout_seconds=opts.timeout_seconds) from exc

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

    async def start_and_wait(
        self,
        pipe_code: str | None = None,
        mthds_contents: list[str] | None = None,
        inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
        extra: dict[str, Any] | None = None,
        wait_options: WaitForResultOptions | None = None,
    ) -> RunResults:
        """Start a run and poll it to completion — the whole async lifecycle in one call.

        Convenience wrapper: `start` (the 202 start result) followed by `wait_for_result`
        on the returned `pipeline_run_id`. This is the durable way to run long
        methods on the hosted API (the run survives client disconnects and the
        gateway's synchronous cap). All `start` args apply, including the generic
        `extra` extension passthrough.

        Args:
            pipe_code: The code identifying the pipe to execute
            mthds_contents: List of MTHDS bundle contents to load
            inputs: Inputs passed to the method
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for the dynamic output concept ref
            extra: Server-specific extension args, merged into the request body
            wait_options: Poll-loop tuning (interval, timeout, on_poll callback)

        Returns:
            The result artifacts of the completed run.

        Raises:
            RunFailedError: If the run reaches a terminal status other than COMPLETED.
            RunTimeoutError: If the poll budget elapses (the run keeps executing —
                resume later by id via `wait_for_result`).
            RunLifecycleUnavailableError: If the server has no run store (a bare runner).
        """
        started = await self.start(
            pipe_code=pipe_code,
            mthds_contents=mthds_contents,
            inputs=inputs,
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_ref=dynamic_output_concept_ref,
            extra=extra,
        )
        return await self.wait_for_result(started.pipeline_run_id, options=wait_options)


# ── Module helpers ──────────────────────────────────────────────────────

_KNOWN_RUN_STATUS_NAMES: frozenset[str] = frozenset(RunStatus.__members__)


# The protocol's basic request args — the named parameters of execute()/start().
# Anything else a caller passes is an extension arg: it rides `extra` and merges
# into the body as a top-level property. A protocol arg smuggled through `extra`
# is rejected (it must be passed as a named parameter).
_PROTOCOL_REQUEST_ARGS: frozenset[str] = frozenset(
    {"pipe_code", "mthds_contents", "inputs", "output_name", "output_multiplicity", "dynamic_output_concept_ref"}
)


def _build_run_body(
    *,
    pipe_code: str | None,
    mthds_contents: list[str] | None,
    inputs: PipelineInputs | WorkingMemoryAbstract[StuffType] | None,
    output_name: str | None,
    output_multiplicity: VariableMultiplicity | None,
    dynamic_output_concept_ref: str | None,
    extra: dict[str, Any] | None,
    exclude_none: bool = False,
) -> dict[str, Any]:
    """Assemble the `/execute` | `/start` request body — the protocol has no request model.

    The body is a plain mapping of the protocol's basic args plus any
    server-specific extension args (merged as top-level properties). `inputs`
    may carry pydantic objects (StuffContent, working memory), so the caller
    serializes the returned mapping with `pydantic_core.to_json`, which handles
    them. With `exclude_none`, absent fields are pruned from the wire body.

    Raises:
        PipelineRequestError: If `extra` carries a protocol arg.
    """
    extensions = _build_extensions(extra)
    body: dict[str, Any] = {
        "pipe_code": pipe_code,
        "mthds_contents": mthds_contents,
        "inputs": inputs,
        "output_name": output_name,
        "output_multiplicity": output_multiplicity,
        "dynamic_output_concept_ref": dynamic_output_concept_ref,
        **extensions,
    }
    if exclude_none:
        body = {key: value for key, value in body.items() if value is not None}
    return body


def _build_extensions(extra: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and copy the generic `extra` passthrough.

    Extension args ride the request body as top-level properties; the protocol's
    own args must be passed as named parameters, never smuggled through `extra`.

    Args:
        extra: Server-specific extension args from the caller, or None.

    Returns:
        A mutable copy of `extra` safe to merge into the body.

    Raises:
        PipelineRequestError: If `extra` carries a protocol arg.
    """
    extensions: dict[str, Any] = dict(extra or {})
    protocol_overlap = extensions.keys() & _PROTOCOL_REQUEST_ARGS
    if protocol_overlap:
        msg = f"extra carries protocol args {sorted(protocol_overlap)} — pass them as named parameters instead."
        raise PipelineRequestError(msg)
    return extensions


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
