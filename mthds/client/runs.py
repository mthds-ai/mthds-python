"""Run-lifecycle models for the platform polling surface (`/platform/v1/runs`).

Long pipeline runs outlive the hosted gateway's ~30s synchronous cap, so the SDK
submits a run, then polls a self-healing endpoint by bare `pipeline_run_id` until
the run reaches a terminal state. All state lives behind the id (DynamoDB +
Temporal on the platform), so a caller can drop the poll loop and resume later
with just the id.

Wire contract mirrors `pipelex-platform` (`pipelex_shared.schemas.run` +
`routers/v1/runs.py`):
    POST /platform/v1/runs                       -> RunPublic        (start)
    GET  /platform/v1/runs/by-id/{run_id}        -> RunRead          (status, self-healing)
    GET  /platform/v1/runs/by-id/{run_id}/result -> 202 / 200 / 409  (result)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, Field

from mthds._compat import StrEnum
from mthds.models.pipe_output import VariableMultiplicity

if TYPE_CHECKING:
    from collections.abc import Callable


# ── Status ──────────────────────────────────────────────────────────


class RunStatus(StrEnum):
    """Run lifecycle status. Mirrors `pipelex_shared.schemas.run.RunStatus`.

    `STARTED` is deprecated server-side but kept here for historical rows.
    """

    PENDING = "PENDING"
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"
    TIMED_OUT = "TIMED_OUT"

    @property
    def is_terminal(self) -> bool:
        """True if the run has reached a terminal state (no further transitions)."""
        match self:
            case RunStatus.COMPLETED | RunStatus.FAILED | RunStatus.CANCELLED | RunStatus.TERMINATED | RunStatus.TIMED_OUT:
                return True
            case RunStatus.PENDING | RunStatus.STARTED | RunStatus.RUNNING:
                return False

    @property
    def is_success(self) -> bool:
        """True only for `COMPLETED`; every other terminal status is a failure."""
        match self:
            case RunStatus.COMPLETED:
                return True
            case (
                RunStatus.PENDING
                | RunStatus.STARTED
                | RunStatus.RUNNING
                | RunStatus.FAILED
                | RunStatus.CANCELLED
                | RunStatus.TERMINATED
                | RunStatus.TIMED_OUT
            ):
                return False


# ── Requests ────────────────────────────────────────────────────────


class StartRunRequest(BaseModel):
    """Body of `POST /platform/v1/runs`.

    Two run styles: a stored method (`method_id`) or an ad-hoc inline bundle
    (`mthds_contents` [+ optional `pipe_code`]). `method_id` is allowed on its
    own client-side — the SDK does not over-validate (D5); the platform is the
    source of truth for which combinations it accepts. The output controls mirror
    the runner's `PipelineRequest` and are forwarded verbatim to the runner.
    """

    # min_length=1 mirrors the platform's CreateRunRequest: an empty string is a caller
    # mistake, not "method_id-alone" (D5 allows method_id WITHOUT pipe_code/contents, not
    # an empty method_id). Rejecting it locally yields a clear error instead of a server 422.
    method_id: str | None = Field(default=None, min_length=1)
    pipe_code: str | None = Field(default=None, min_length=1)
    mthds_contents: list[str] | None = None
    inputs: dict[str, Any] | None = None
    output_name: str | None = None
    output_multiplicity: VariableMultiplicity | None = None
    dynamic_output_concept_ref: str | None = None


# ── Responses ───────────────────────────────────────────────────────


class RunPublic(BaseModel):
    """A run record. Mirrors `pipelex_shared.schemas.run.RunPublic`.

    The identity fields (`org_id`, `created_by_user_id`, `method_id`) are optional
    because the open-source runner serves the same lifecycle shape without them —
    only the hosted platform layers identity on. Tolerant of unknown fields so the
    server can evolve its payload (default `extra="ignore"`).
    """

    pipeline_run_id: str
    org_id: str | None = None
    created_by_user_id: str | None = None
    method_id: str | None = None
    pipe_code: str | None = None
    workflow_id: str | None = None
    status: RunStatus
    result_url: str | None = None
    created_at: str
    finished_at: str | None = None


class RunRead(RunPublic):
    """A run read through the self-healing path (`RunPublic` + `degraded`).

    When `degraded` is true, Temporal was unreachable and `status` is the
    last-known DB value, not a freshly-derived one — pair with
    `retry_after_seconds` (parsed from the `Retry-After` header by the client).
    """

    degraded: bool = False
    retry_after_seconds: int | None = None


class RunResult(BaseModel):
    """Result artifacts for a completed run — mirrors the platform's `RunResultsResponse`.

    `graph_spec` (`graphspec.json`) and `main_stuff` (`main_stuff.json`) are
    pipelex-produced S3 artifacts that the platform relays VERBATIM. `main_stuff`
    is polymorphic — a list output renders to a top-level array, a structured
    output to an object — so both are typed as opaque JSON (`Any`), never `dict`.
    Either may be `None` when the run is partial mid-write.
    """

    pipeline_run_id: str
    graph_spec: Any = None
    main_stuff: Any = None


# ── Single-shot result lookup outcome (discriminated on `state`) ─────


class RunResultRunning(BaseModel):
    """HTTP 202 — the run is in-flight; poll again after `retry_after_seconds`."""

    state: Literal["running"] = "running"
    pipeline_run_id: str
    retry_after_seconds: int | None = None


class RunResultCompleted(BaseModel):
    """HTTP 200 — the run is `COMPLETED`; `result` carries the artifacts."""

    state: Literal["completed"] = "completed"
    pipeline_run_id: str
    result: RunResult


class RunResultFailed(BaseModel):
    """HTTP 409 — the run reached a terminal non-`COMPLETED` status."""

    state: Literal["failed"] = "failed"
    pipeline_run_id: str
    status: RunStatus
    message: str


RunResultState: TypeAlias = Annotated[
    RunResultRunning | RunResultCompleted | RunResultFailed,
    Field(discriminator="state"),
]


# ── Polling options ─────────────────────────────────────────────────


@dataclass(frozen=True)
class PollInfo:
    """Progress info handed to a `WaitForResultOptions.on_poll` callback before each sleep."""

    attempt: int
    elapsed_seconds: float


@dataclass
class WaitForResultOptions:
    """Tuning for `wait_for_result`'s poll loop.

    The client is async-native: cancellation is via `asyncio.CancelledError`
    (the Python analog of mthds-js's `AbortSignal`), so there is no `signal`
    field — cancel the awaiting task instead.
    """

    interval_seconds: float = 2.0
    timeout_seconds: float = 1200.0
    on_poll: Callable[[PollInfo], None] | None = None
