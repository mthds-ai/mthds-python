"""Reading a runtime's answer as a problem, whatever its body: the client side of the protocol's error contract.

Every error answer of the protocol is a problem document, but not every answer a client meets is one:
a proxy in front of the runtime answers with an HTML page, a server that is starting answers with an
empty body, and a framework's own refusal is JSON of another shape. `read_answer` reads each of them
as a problem under a registered code, so that a caller branches on one shape:

- **A problem document reads as received.** The body is decoded as JSON, refusing a body nested
  deeper than `MAX_BODY_NESTING`, the constants `NaN` and `Infinity` that JSON does not define and a
  number past the range of a double, which would read as an infinity, and it is a problem document
  when it validates as `Problem`. Its members are kept as sent, undeclared
  ones included; `status` is filled from the answer when the body leaves it out, and `retry_after`
  from the `Retry-After` header when the body gives none and its retry verdict is `yes`.
- **A status that names one code reads as that code.** When the body is no problem document, the
  answer's status is read by `STATUS_READINGS`, the statuses that exactly one core code carries and
  that a client can state from the answer alone (`405` and `503` in the core registry): the problem
  is that code with the answer's status. On a route that creates a run, a status whose code invites a
  retry is not read this way, since an answer that is no problem document never invites a repeat of
  a request that may have started a run.
- **Anything else reads as `client.response_unreadable`**, naming the answer's status.

`unreadable_answer` states the last case directly, for a success answer whose body is not the
route's answer.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, NamedTuple, NoReturn, cast

from pydantic import ValidationError

from mthds.protocol.problem.client_problems import make_client_problem
from mthds.protocol.problem.models import Problem
from mthds.protocol.problem.registry import CORE_CODE_SPECS, STATUS_READINGS, CoreCode, RetryVerdict

if TYPE_CHECKING:
    from collections.abc import Mapping

RETRY_AFTER_HEADER = "retry-after"

# A `Retry-After` delay in seconds, as HTTP writes it: ASCII digits only, never a Unicode digit such as `²`.
_DELAY_SECONDS = re.compile(r"[0-9]+")

# How much of a refused number literal the decoder's message quotes.
_NUMBER_EXCERPT_LENGTH = 40

MAX_BODY_NESTING = 512
"""The deepest nesting of arrays and objects a body may have and still be read, the limit the TypeScript client pins too.

No problem document comes near it. A body nested deeper is refused before it is parsed, so that every
reader draws the line at the same depth whatever its decoder's own limit, and so that neither the
decoder nor the validation that walks the decoded value can run out of stack.
"""

# A JSON string, its escapes included, whose brackets are text rather than nesting.
_JSON_STRING = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"')
_NOT_A_BRACKET = re.compile(r"[^\[\]{}]+")
_BRACKET_STEPS: dict[str, int] = {"[": 1, "{": 1, "]": -1, "}": -1}


class DecodedBody(NamedTuple):
    """A body decoded as JSON: `is_json` is false when it is not JSON, and `value` is then `None`."""

    is_json: bool
    value: Any


def _refuse_constant(name: str) -> Any:
    msg = f"JSON does not define the constant {name}."
    raise ValueError(msg)


def _refuse_non_finite(text: str) -> NoReturn:
    msg = f"The number {text[:_NUMBER_EXCERPT_LENGTH]} is past the range of a JSON reader's numbers, where it reads as an infinity."
    raise ValueError(msg)


def _parse_int(text: str) -> int:
    """A JSON integer, refused when it is past the range of a double, where a JavaScript reader reads it as an infinity.

    An integer too long for Python's bounded conversion raises `ValueError` from `int` itself, and is
    far past that range too.
    """
    value = int(text)
    try:
        float(value)
    except OverflowError:
        _refuse_non_finite(text)
    return value


def _parse_float(text: str) -> int | float:
    """A JSON number with a fraction or an exponent, an integral value reading as an integer, as a JavaScript reader sees it.

    A literal past the range of a double, such as `1e999`, which Python and a JavaScript reader both
    read as an infinity, is refused.
    """
    value = float(text)
    if not math.isfinite(value):
        _refuse_non_finite(text)
    if value.is_integer():
        return int(value)
    return value


def nests_deeper_than(text: str, *, limit: int) -> bool:
    """Whether a body nests arrays and objects deeper than `limit`, a bracket inside a string not counting.

    The brackets are counted without parsing, so that a body too deep to read is refused before any
    decoder walks it; a body with no more opening brackets than `limit` cannot pass it and is not scanned.
    """
    if text.count("[") + text.count("{") <= limit:
        return False
    brackets = _NOT_A_BRACKET.sub("", _JSON_STRING.sub("", text))
    return max(itertools.accumulate(map(_BRACKET_STEPS.__getitem__, brackets)), default=0) > limit


def decode_json(text: str) -> DecodedBody:
    """Decode a body as JSON, as every reader of the protocol does.

    A body nested deeper than `MAX_BODY_NESTING` is refused before it is parsed. The constants
    `NaN`, `Infinity` and `-Infinity`, which Python's decoder accepts and JSON does not define, are
    refused, and so is a number past the range of a double, such as `1e999`, which would read as an
    infinity. Numbers read as a JavaScript reader reads them: one with no fractional part reads as an
    integer, so that `2.0` reads as `2`.
    """
    if nests_deeper_than(text, limit=MAX_BODY_NESTING):
        return DecodedBody(is_json=False, value=None)
    try:
        value = json.loads(text, parse_constant=_refuse_constant, parse_float=_parse_float, parse_int=_parse_int)
    except (ValueError, RecursionError):
        return DecodedBody(is_json=False, value=None)
    return DecodedBody(is_json=True, value=value)


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> int | None:
    """The delay a `Retry-After` header asks for, in seconds.

    Args:
        value: The header's value: a number of seconds, or an HTTP date.
        now: The time to count an HTTP date from; the current time when not given.

    Returns:
        The delay in whole seconds, never negative, or `None` when the header is absent or unreadable:
        a number of seconds is ASCII digits only, as HTTP writes it, and one too long to convert reads
        as unreadable.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if _DELAY_SECONDS.fullmatch(text):
        try:
            return int(text)
        except ValueError:
            return None
    try:
        moment = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    delta = (moment - (now or datetime.now(tz=UTC))).total_seconds()
    return max(0, math.ceil(delta))


def _retries(code: CoreCode) -> bool:
    match CORE_CODE_SPECS[code].retry:
        case RetryVerdict.YES:
            return True
        case RetryVerdict.NO | RetryVerdict.OUTCOME_UNKNOWN:
            return False


def read_problem_document(body: str, *, status: int, headers: Mapping[str, str]) -> Problem | None:
    """Read a body as a problem document, filling what the answer around it says.

    Args:
        body: The answer's body, as text.
        status: The answer's HTTP status, which a body that leaves `status` out takes.
        headers: The answer's headers, names in lower case; `retry-after` fills a missing `retry_after`
            beside a retry verdict of `yes`.

    Returns:
        The problem, or `None` when the body is no problem document.
    """
    decoded = decode_json(body)
    value: object = decoded.value
    if not decoded.is_json or not isinstance(value, dict):
        return None
    members = cast("dict[str, Any]", value)
    try:
        problem = Problem.model_validate(members)
    except ValidationError:
        return None
    filled: dict[str, Any] = {}
    if "status" not in members:
        filled["status"] = status
    if "retry_after" not in members and problem.is_retryable:
        delay = parse_retry_after(headers.get(RETRY_AFTER_HEADER))
        if delay is not None:
            filled["retry_after"] = delay
    if not filled:
        return problem
    return problem.with_members(**filled)


def unreadable_answer(status: int) -> Problem:
    """The problem of an answer whose body the client cannot read: `client.response_unreadable` naming its status."""
    return make_client_problem(CoreCode.CLIENT_RESPONSE_UNREADABLE, params={"status": status})


def read_answer(*, status: int, body: str, headers: Mapping[str, str], creates_run: bool) -> Problem:
    """Read an error answer as a problem, whatever its body.

    Args:
        status: The answer's HTTP status.
        body: The answer's body, as text.
        headers: The answer's headers, names in lower case.
        creates_run: Whether the request may have created a run, as `POST /execute` and `POST /start` do.

    Returns:
        The runtime's problem when the body is one, else the code the status names, else
        `client.response_unreadable`.
    """
    problem = read_problem_document(body, status=status, headers=headers)
    if problem is not None:
        return problem
    code = STATUS_READINGS.get(status)
    if code is None or (creates_run and _retries(code)):
        return unreadable_answer(status)
    retry_after = parse_retry_after(headers.get(RETRY_AFTER_HEADER)) if _retries(code) else None
    return make_client_problem(code, status=status, retry_after=retry_after)
