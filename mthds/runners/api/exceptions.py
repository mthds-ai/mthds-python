from __future__ import annotations

from typing import TYPE_CHECKING, Any, Generic

from typing_extensions import TypeVar

from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.models import ValidationDiagnostic

if TYPE_CHECKING:
    from mthds.runners.api.problem import UserAction


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


# The item type of `ApiResponseError.validation_errors`. It defaults to the protocol's neutral
# diagnostic, so a bare `except ApiResponseError` reads the items as `ValidationDiagnostic`, and it is
# covariant, so a client narrowing the items (`ApiResponseError[ItsItem]`) still raises an error a
# handler typed with the base accepts.
ProblemDiagnosticT = TypeVar("ProblemDiagnosticT", bound=ValidationDiagnostic, covariant=True, default=ValidationDiagnostic)


class ApiResponseError(PipelineRequestError, Generic[ProblemDiagnosticT]):
    """A non-2xx answer that DID come back from the runner, with its problem document's members typed.

    `MthdsAPIClient` raises it from every route when the runner answers non-2xx, whatever the body:
    a body that is not a problem document still raises it, with the status and the raw text. Each
    member below is `None` when the answer did not carry it.

    - **What happened, for a person.** `str(exc)` names the request and the status, gives the
      reason — the problem's `detail`, else its `title`, else the raw body, else the status text —
      and, when the runner advised one, the next step on its own line. `server_message` is the
      `detail` alone, `title` the stable label of the error class, `user_action` the advised next
      step (`kind` and `detail`).
    - **What to branch on, for a program.** `type_uri` (the problem's `type`) is the stable URI of
      the error class. `error_domain` says who can fix it: `input` (the caller — a malformed bundle,
      a bad argument, a missing input), `config` (the runner's operator — a missing secret, a
      misconfigured backend) or `runtime` (nobody beforehand — a provider outage during execution);
      the runner owns that vocabulary, so it is an open string. `retryable` says whether the same
      request can succeed later, `None` meaning unknown. `error_type` is the runner's exception class,
      finer and specific to the runner. Branch on these, never on the wording of a message; the
      HTTP `status` is transport.
    - **For support.** `request_id` finds the runner's log lines for this request; `instance` names
      the occurrence.
    - **Per-item failures.** `validation_errors` holds the diagnostics of a run route's refusal to
      run an invalid method (a `422` from `/execute` or `/start`). `/validate` never routes an
      invalid bundle here: that is its `200` invalid verdict. A refusal whose diagnostics are not
      itemized carries `None`, so fall back to `server_message`.
    - **Everything else.** `problem` is the decoded document whole, so a member not named here stays
      reachable; `response_body` is the raw text, `status` / `status_text` the transport's,
      `headers` the answer's headers (lower-case names, so `headers.get("retry-after")` reads the
      delay a `429` or a `503` asks for), `request_url` the URL requested, and `api_url` the
      runner's base URL. The error keeps this plain data and never the request itself, which
      carries the API key.

    The class is generic over the item type of `validation_errors` (`ValidationDiagnostic` unless
    stated), so a client that narrows the items to its own diagnostic subclass raises
    `ApiResponseError[ItsItem]`, which every handler of this class still catches.
    """

    def __init__(
        self,
        message: str,
        *,
        api_url: str,
        status: int,
        status_text: str,
        response_body: str,
        headers: dict[str, str] | None = None,
        request_url: str | None = None,
        error_type: str | None = None,
        server_message: str | None = None,
        validation_errors: list[ProblemDiagnosticT] | None = None,
        type_uri: str | None = None,
        title: str | None = None,
        instance: str | None = None,
        request_id: str | None = None,
        error_domain: str | None = None,
        retryable: bool | None = None,
        user_action: UserAction | None = None,
        problem: dict[str, Any] | None = None,
    ) -> None:
        """Build the error; its message is `message` followed by the next step, when there is one.

        Args:
            message: What failed and why, e.g. `API POST /v1/execute failed (422): <reason>`. The
                next step is appended on its own line unless `message` already ends with it.
            api_url: The base URL of the runner that answered.
            status: The HTTP status code of the answer.
            status_text: The HTTP reason phrase of the answer.
            response_body: The answer's body, as text.
            headers: The answer's headers, names in lower case.
            request_url: The URL the request was sent to.
            error_type: The runner's exception class name.
            server_message: The problem's `detail`, the reason for this occurrence.
            validation_errors: The per-error diagnostics of a refused run.
            type_uri: The problem's `type`, the stable URI of the error class.
            title: The problem's `title`, the stable label of the error class.
            instance: The problem's `instance`, the occurrence.
            request_id: The request's correlation id.
            error_domain: Who can fix the failure: `input`, `config` or `runtime`.
            retryable: Whether the same request can succeed later; `None` when unknown.
            user_action: The next step the runner advises.
            problem: The decoded problem document whole.
        """
        super().__init__(_with_next_step(message, user_action))
        self.api_url = api_url
        self.status = status
        self.status_text = status_text
        self.response_body = response_body
        self.headers: dict[str, str] = headers or {}
        self.request_url = request_url
        self.error_type = error_type
        self.server_message = server_message
        self.validation_errors = validation_errors
        self.type_uri = type_uri
        self.title = title
        self.instance = instance
        self.request_id = request_id
        self.error_domain = error_domain
        self.retryable = retryable
        self.user_action = user_action
        self.problem = problem


def _with_next_step(message: str, user_action: UserAction | None) -> str:
    """Append the advised next step to a message, unless there is none or the message already ends with it."""
    if user_action is None or message.rstrip().endswith(user_action.detail.strip()):
        return message
    return f"{message}\nNext step: {user_action.detail}"
