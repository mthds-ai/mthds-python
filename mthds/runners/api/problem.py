"""How `MthdsAPIClient` reads an httpx answer, or the lack of one, as a problem.

The reading of an answer is the protocol's and lives in `mthds.protocol.problem.answers`; this
module hands it an httpx response, and states the problem of a request that got no answer:

- **No request left** (no connection opened, a proxy refused it, or the request was refused locally):
  `client.unreachable`, naming the client's base URL, since the call created nothing. A base URL whose
  scheme the client does not send to is no transport failure but a setting: `MthdsAPIClient` raises
  it as `client.not_configured` before reading a failure here. A request that waited past the time limit for a free connection of the pool did
  not leave either, so it is `client.timeout`.
- **The request left and no answer came back** (the time limit passed, or the connection was lost):
  `client.outcome_unknown` on a route that creates a run, since the run may exist, and otherwise
  `client.timeout` naming the time limit, or `client.unreachable` for a lost connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from mthds.protocol.problem.answers import AnswerReading, read_answer
from mthds.protocol.problem.client_problems import make_client_problem
from mthds.protocol.problem.registry import CoreCode

if TYPE_CHECKING:
    from mthds.protocol.problem.models import Problem

# The failures httpx raises before any byte of the request left.
_NOTHING_SENT: tuple[type[httpx.TransportError], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ProxyError,
    httpx.LocalProtocolError,
)


# How much of an answer's body an error's message quotes; the error's `response_body` keeps it whole.
ANSWER_EXCERPT_LIMIT = 500

# The header a runner or a gateway in front of it names the request with, in lower case.
REQUEST_ID_HEADER = "x-request-id"


def lower_case_headers(headers: httpx.Headers) -> dict[str, str]:
    """An answer's headers as a plain mapping, names in lower case."""
    return {name.lower(): value for name, value in headers.items()}


def answer_excerpt(response: httpx.Response, *, problem_from_body: bool) -> str | None:
    """The start of an answer's body, for a person, when the body is not the problem an error carries.

    An answer that is no problem document, such as a gateway's `{"detail":"Not authenticated"}` or a
    proxy's HTML page, or a success whose body is not the route's answer, reads as a problem the client
    states in the registry's words; the body is what the server itself said, and an error's message
    quotes it so that a person sees it. The excerpt stays on one line, every run of whitespace written
    as one space, and a body longer than `ANSWER_EXCERPT_LIMIT` characters is cut there with an
    ellipsis. The problem itself is never changed: the excerpt belongs to the message alone.

    Args:
        response: The runner's answer.
        problem_from_body: Whether the problem the error carries is the body's own problem document,
            as the reading of the answer says (`mthds.protocol.problem.answers.AnswerReading.from_body`);
            the body is never read again to tell.

    Returns:
        The excerpt, or `None` when the body is empty or is the problem the error carries.
    """
    if problem_from_body:
        return None
    text = " ".join(response.text.split())
    if not text:
        return None
    if len(text) <= ANSWER_EXCERPT_LIMIT:
        return text
    return f"{text[:ANSWER_EXCERPT_LIMIT]}…"


def answer_request_id(response: httpx.Response, *, problem: Problem) -> str | None:
    """The id the runtime knows the request by, for support: the problem's own `request_id`, else the answer's `X-Request-ID`.

    A runner may name the request in its problem, as the undeclared member `request_id`, and a runner or
    a gateway in front of it may name it in the `X-Request-ID` header, the one place an answer that is
    no problem document names it. The header's id stays on the error and is never added to the
    problem, which stays what the runtime sent or what the client states.

    Args:
        response: The runner's answer.
        problem: The problem the error carries for it.

    Returns:
        The request's id, or `None` when neither the problem nor the header names one.
    """
    member = (problem.model_extra or {}).get("request_id")
    if isinstance(member, str) and member.strip():
        return member
    return response.headers.get(REQUEST_ID_HEADER, "").strip() or None


def read_error_answer(response: httpx.Response, *, creates_run: bool) -> AnswerReading:
    """Read an error answer as a problem, whatever its body, saying whether the problem is the body's own.

    Args:
        response: The runner's answer.
        creates_run: Whether the request may have created a run, as `POST /execute` and `POST /start` do.

    Returns:
        The runtime's problem document, else the problem the client reads from the answer's status,
        with `from_body` saying which.
    """
    return read_answer(
        status=response.status_code,
        body=response.text,
        headers=lower_case_headers(response.headers),
        creates_run=creates_run,
    )


def transport_failure_problem(failure: httpx.TransportError, *, creates_run: bool, base_url: str, timeout_seconds: float) -> Problem:
    """The problem of a request that got no answer.

    Args:
        failure: What httpx raised.
        creates_run: Whether the request may have created a run.
        base_url: The base URL the client is configured with.
        timeout_seconds: The client's time limit for the request.

    Returns:
        `client.unreachable`, `client.timeout` or `client.outcome_unknown`.
    """
    if isinstance(failure, _NOTHING_SENT):
        return make_client_problem(CoreCode.CLIENT_UNREACHABLE, params={"base_url": base_url})
    if isinstance(failure, httpx.PoolTimeout):
        return make_client_problem(CoreCode.CLIENT_TIMEOUT, params={"seconds": timeout_seconds})
    if creates_run:
        return make_client_problem(CoreCode.CLIENT_OUTCOME_UNKNOWN)
    if isinstance(failure, httpx.TimeoutException):
        return make_client_problem(CoreCode.CLIENT_TIMEOUT, params={"seconds": timeout_seconds})
    return make_client_problem(CoreCode.CLIENT_UNREACHABLE, params={"base_url": base_url})
