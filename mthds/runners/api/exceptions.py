"""The errors `MthdsAPIClient` raises, each a `PipelineRequestError` carrying the failure as a problem.

Every route raises only these, so `except PipelineRequestError` catches every failure of a call, and
`exc.problem` is always a problem document under a registered code:

- `ApiResponseError`: an answer came back and it is a failure, a non-2xx or a success the client
  cannot read. Its problem is the runtime's own problem document, or the problem the client reads
  from the answer when the body is none (see `mthds.protocol.problem.answers`); a success it cannot
  read on `execute` or `start` leaves the outcome unknown, `client.outcome_unknown`, since the
  runtime accepted the request.
- `ApiTransportError`: no usable answer came back. Its problem is `client.unreachable` when no request
  left, `client.timeout` when a call that creates nothing got no answer in time, and
  `client.outcome_unknown` when a request that creates a run left and no answer came back, so the
  run may exist. An answer whose body cannot be read, such as one whose content encoding cannot be
  decoded, is none either: `client.outcome_unknown` on a route that creates a run, and
  `client.unreachable` on any other.
- `RunStillRunningError`: `/execute` answered `202`, the protocol's optional degrade, so the run
  goes on on the runtime and the client does not follow it: `client.follow_failed`, naming the run.
- `ClientNotConfiguredError`: the client has no API key, no base URL, or a base URL it cannot send to: `client.not_configured`.
- `BlobUploadError`: an upload target named by `POST /blobs/missing` answered non-2xx. Its problem is
  the target's own problem document when it sent one, else the problem the answer's status names.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mthds.protocol.exceptions import PipelineRequestError

if TYPE_CHECKING:
    from mthds.protocol.problem.models import Problem


class ClientNotConfiguredError(PipelineRequestError):
    """The client is not configured to send: no API key or no base URL resolves, or the base URL makes no URL it sends to.

    Its problem is `client.not_configured` naming the setting, whose retry verdict is `no`: a repeat
    of the call cannot succeed until the setting is fixed.
    """


class ApiResponseError(PipelineRequestError):
    """An answer that DID come back from the runner and is a failure: a non-2xx, or a success the client cannot read.

    `problem` is what to branch on: the runtime's problem document as it sent it, undeclared members
    such as a `request_id` riding `problem.model_extra`, or the problem the client read from an
    answer that is no problem document (`client.response_unreadable`, or the one code its status
    names). `str(exc)` names the request and the status, gives the problem's `detail`, quotes on its
    own line the start of a body that is not the problem it carries, such as a gateway's HTML page,
    and gives on its own line the problem's next step.

    The transport's view rides beside it: `status` and `status_text`, `headers` (names in lower case,
    so `headers.get("retry-after")` reads the raw delay), `response_body` the raw text,
    `request_url` the URL requested and `api_url` the runner's base URL. `request_id` is the id to
    hand to support: the problem's own `request_id` member when the runtime sent one, else the
    answer's `X-Request-ID` header, which is never added to the problem. The error keeps this plain
    data and never the request itself, which carries the API key.
    """

    def __init__(
        self,
        message: str,
        *,
        problem: Problem,
        api_url: str,
        status: int,
        status_text: str,
        response_body: str,
        headers: dict[str, str] | None = None,
        request_url: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Build the error; its message is `message` followed by the problem's next step.

        Args:
            message: What failed and why, e.g. `API POST /v1/execute failed (422): <detail>`.
            problem: The failure as a problem document.
            api_url: The base URL of the runner that answered.
            status: The HTTP status code of the answer.
            status_text: The HTTP reason phrase of the answer.
            response_body: The answer's body, as text.
            headers: The answer's headers, names in lower case.
            request_url: The URL the request was sent to.
            request_id: The id the runtime knows the request by
                (`mthds.runners.api.problem.answer_request_id`).
        """
        super().__init__(message, problem=problem)
        self.api_url = api_url
        self.status = status
        self.status_text = status_text
        self.response_body = response_body
        self.headers: dict[str, str] = headers or {}
        self.request_url = request_url
        self.request_id = request_id


class ApiTransportError(PipelineRequestError):
    """No usable answer came back: the runtime was unreachable or did not answer in time, the connection was lost, or the body was unreadable.

    `problem` is `client.unreachable`, `client.timeout` or `client.outcome_unknown`. On
    `client.outcome_unknown` the request created a run or may have, so it is never repeated
    automatically: `problem.is_retryable` is false and `problem.outcome_is_unknown` true.
    """

    def __init__(self, message: str, *, problem: Problem, api_url: str, request_url: str) -> None:
        """Build the error; its message is `message` followed by the problem's next step.

        Args:
            message: What failed, e.g. `API GET /v1/models failed: <detail>`.
            problem: The failure as a problem document.
            api_url: The base URL of the runner the request was for.
            request_url: The URL the request was sent to.
        """
        super().__init__(message, problem=problem)
        self.api_url = api_url
        self.request_url = request_url


class RunStillRunningError(PipelineRequestError):
    """Raised when `execute()` receives a 202 instead of a final result: `client.follow_failed`, naming the run.

    The MTHDS Protocol permits an implementation to degrade a synchronous `/execute` into an
    accepted-async response (202 with a `Location` header) when it cannot hold the connection open.
    The run keeps executing server-side and this client does not follow it, so the call is never
    repeated, which would start the run twice: resume by `run_id` (the durable run lifecycle on a
    hosted deployment, or the `location` status resource when provided).
    """

    def __init__(
        self,
        message: str,
        *,
        problem: Problem,
        run_id: str,
        retry_after_seconds: int | None = None,
        location: str | None = None,
    ) -> None:
        """Build the error; its message is `message` followed by the problem's next step, which says not to start the run again.

        Args:
            message: What happened, for a person.
            problem: `client.follow_failed`, naming the run.
            run_id: The run the runner started.
            retry_after_seconds: The delay the `Retry-After` header asks for before reading the run.
            location: The run's status resource, from the `Location` header.
        """
        super().__init__(message, problem=problem)
        self.run_id = run_id
        self.retry_after_seconds = retry_after_seconds
        self.location = location


class BlobUploadError(PipelineRequestError):
    """An upload of one blob's bytes, to the target `POST /blobs/missing` named, answered non-2xx.

    The target is the runner's choice and may be another server than the runner, such as an
    object store behind a presigned URL, so its answer may be no problem document. `problem` reads
    it as any failed answer is read: the target's own problem document when it sent one, such as a
    runner's `PUT /blobs/{sha256}` refusal, else the problem its status names
    (`client.response_unreadable` naming the status, or the one code a status such as `503` names).
    The error keeps the status and the body as text beside it. `upload_url` is the target without
    its userinfo, its query and its fragment, since a presigned query carries a signature that
    grants the write and a `user:password@` is a credential; the full URL is never kept.
    """

    def __init__(
        self,
        message: str,
        *,
        problem: Problem,
        sha256: str,
        status: int,
        status_text: str,
        response_body: str,
        upload_url: str,
    ) -> None:
        """Build the error; its message is `message` followed by the problem's next step.

        Args:
            message: What failed and why, naming the blob and the status.
            problem: The failure as a problem document, as the target's answer reads.
            sha256: The SHA-256 of the blob whose upload failed, in lowercase hexadecimal.
            status: The HTTP status code of the answer.
            status_text: The HTTP reason phrase of the answer.
            response_body: The answer's body, as text.
            upload_url: The upload target's URL without its userinfo, its query or its fragment.
        """
        super().__init__(message, problem=problem)
        self.sha256 = sha256
        self.status = status
        self.status_text = status_text
        self.response_body = response_body
        self.upload_url = upload_url
