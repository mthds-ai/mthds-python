from mthds.protocol.exceptions import PipelineRequestError
from mthds.runners.api.runs import RunStatus


class ClientAuthenticationError(Exception):
    pass


class RunFailedError(PipelineRequestError):
    """Raised when a run reaches a terminal state that is not `COMPLETED`.

    Surfaced from `wait_for_result` / `get_run_result` when the platform answers a
    result lookup with HTTP 409 (`FAILED`, `CANCELLED`, `TERMINATED`,
    `TIMED_OUT`). `run_id` and `status` let callers report the outcome precisely;
    `status` stays the typed `RunStatus` enum so callers can match/case on it.
    """

    def __init__(self, message: str, run_id: str, status: RunStatus) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.status = status


class RunTimeoutError(PipelineRequestError):
    """Raised when `wait_for_result` exceeds its timeout before the run is terminal.

    The run is NOT cancelled — it keeps executing server-side and can be resumed
    later by `run_id` (the poll loop just stopped waiting).
    """

    def __init__(self, message: str, run_id: str, timeout_seconds: float) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.timeout_seconds = timeout_seconds


class RunStillRunningError(PipelineRequestError):
    """Raised when `execute()` receives a 202 instead of a final result.

    The MTHDS Protocol permits an implementation to degrade a synchronous
    `/execute` into an accepted-async response (202 with a `Location` header)
    when it cannot hold the connection open. The run keeps executing
    server-side — resume by `run_id` (`get_run_result` / `wait_for_result` on
    a hosted deployment, or the `location` status resource when provided).
    """

    def __init__(self, message: str, run_id: str, retry_after_seconds: int | None = None, location: str | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.retry_after_seconds = retry_after_seconds
        self.location = location


class RunLifecycleUnavailableError(PipelineRequestError):
    """Raised when the durable run lifecycle (`/v1/runs/*`) is not served by the
    configured `MTHDS_API_URL`.

    Run polling is a hosted-API extension, not part of the MTHDS Protocol: the
    open-source `pipelex-api` runner executes methods but has no run store, so it
    404s those routes; only a deployment that includes the platform block (the
    hosted MTHDS API) serves status/results. Distinguished from a genuine
    run-not-found 404, which carries the platform's structured error envelope.
    """

    def __init__(self, message: str, api_url: str) -> None:
        super().__init__(message)
        self.api_url = api_url
