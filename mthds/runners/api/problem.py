"""How `MthdsAPIClient` reads an httpx answer, or the lack of one, as a problem.

The reading of an answer is the protocol's and lives in `mthds.protocol.problem.answers`; this
module hands it an httpx response, and states the problem of a request that got no answer:

- **No request left** (no connection opened, a proxy refused it, the URL's scheme is unsupported, or
  the request was refused locally): `client.unreachable`, naming the client's base URL, since the call
  created nothing. A request that waited past the time limit for a free connection of the pool did
  not leave either, so it is `client.timeout`.
- **The request left and no answer came back** (the time limit passed, or the connection was lost):
  `client.outcome_unknown` on a route that creates a run, since the run may exist, and otherwise
  `client.timeout` naming the time limit, or `client.unreachable` for a lost connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from mthds.protocol.problem.answers import read_answer
from mthds.protocol.problem.client_problems import make_client_problem
from mthds.protocol.problem.registry import CoreCode

if TYPE_CHECKING:
    from mthds.protocol.problem.models import Problem

# The failures httpx raises before any byte of the request left.
_NOTHING_SENT: tuple[type[httpx.TransportError], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ProxyError,
    httpx.UnsupportedProtocol,
    httpx.LocalProtocolError,
)


def lower_case_headers(headers: httpx.Headers) -> dict[str, str]:
    """An answer's headers as a plain mapping, names in lower case."""
    return {name.lower(): value for name, value in headers.items()}


def read_response_problem(response: httpx.Response, *, creates_run: bool) -> Problem:
    """Read an error answer as a problem, whatever its body.

    Args:
        response: The runner's answer.
        creates_run: Whether the request may have created a run, as `POST /execute` and `POST /start` do.

    Returns:
        The runtime's problem document, else the problem the client reads from the answer's status.
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
