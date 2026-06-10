from mthds.client.runs import RunStatus


class ClientAuthenticationError(Exception):
    pass


class PipelineRequestError(Exception):
    pass


class RunFailedError(PipelineRequestError):
    """Raised when a run reaches a terminal state that is not `COMPLETED`.

    Surfaced from `wait_for_result` / `get_result` when the platform answers a
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


class RunLifecycleUnavailableError(PipelineRequestError):
    """Raised when the durable run lifecycle (`/platform/v1/runs*`) is not served by the
    configured `MTHDS_API_URL`.

    The open-source `pipelex-api` runner executes pipelines but has no run store, so it 404s
    those routes; only a deployment that includes the platform block (the hosted MTHDS API)
    serves start/poll/result. Distinguished from a genuine run-not-found 404, which carries the
    platform's structured error envelope.
    """

    def __init__(self, message: str, api_url: str) -> None:
        super().__init__(message)
        self.api_url = api_url
