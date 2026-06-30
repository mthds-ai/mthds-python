from mthds.protocol.exceptions import PipelineRequestError


class ClientAuthenticationError(Exception):
    pass


class RunStillRunningError(PipelineRequestError):
    """Raised when `execute()` receives a 202 instead of a final result.

    The MTHDS Protocol permits an implementation to degrade a synchronous
    `/execute` into an accepted-async response (202 with a `Location` header)
    when it cannot hold the connection open. The run keeps executing
    server-side — resume by `run_id` (the durable run lifecycle on a hosted
    deployment, or the `location` status resource when provided).
    """

    def __init__(self, message: str, run_id: str, retry_after_seconds: int | None = None, location: str | None = None) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.retry_after_seconds = retry_after_seconds
        self.location = location
