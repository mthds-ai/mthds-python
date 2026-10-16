"""Reading a runtime's answer as a problem, whatever its body: the client side of the protocol's error contract.

Every error answer of the protocol is a problem document, but not every answer a client meets is one:
a proxy in front of the runtime answers with an HTML page, a server that is starting answers with an
empty body, and a framework's own refusal is JSON of another shape. `read_answer` reads each of them
as a problem under a registered code, so that a caller branches on one shape:

- **A problem document reads as received.** The body is decoded as JSON, refusing a body nested
  deeper than `MAX_BODY_NESTING`, the constants `NaN` and `Infinity` that JSON does not define and a
  number past the range of a double, which would read as an infinity, and it is a problem document
  when it validates as `Problem`. Its members are kept as sent, undeclared
  ones included; `status` is filled from the answer when the body leaves it out and the answer's
  status is one HTTP defines, `100` to `599`, and `retry_after`
  from the `Retry-After` header when the body gives none and its retry verdict is `yes`.
- **A server error on a route that creates a run leaves the outcome unknown.** When the body is no
  problem document and the status is a `5xx`, such as a gateway's `504` after its own time limit or
  a proxy's `502`, on a route that creates a run, something other than the runtime answered and the
  run may have started behind it: the problem is `client.outcome_unknown`, which no caller repeats
  automatically.
- **A status that names one code reads as that code.** Otherwise, when the body is no problem
  document, the answer's status is read by `STATUS_READINGS`, the statuses that exactly one core
  code carries and that a client can state from the answer alone (`405` and `503` in the core
  registry): the problem is that code with the answer's status. On a route that creates a run, a
  status whose code invites a retry is not read this way, since an answer that is no problem
  document never invites a repeat of a request that may have started a run.
- **Anything else reads as `client.response_unreadable`**, naming the answer's status.

`unreadable_answer` states the last case directly, for a success answer whose body is not the
route's answer.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from datetime import UTC, datetime, timedelta
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

# The largest delay a JavaScript reader holds exactly, `Number.MAX_SAFE_INTEGER`; a larger one is unreadable to both twins.
_MAX_EXACT_SECONDS = 2**53 - 1

# The three forms of an HTTP date a recipient accepts (RFC 9110, section 5.6.7), names case-sensitive.
_MONTHS: tuple[str, ...] = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTH = "(?P<month>" + "|".join(_MONTHS) + ")"
_DAY_NAME = "(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"
_DAY_NAME_LONG = "(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
_TIME_OF_DAY = "(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
_IMF_FIXDATE = re.compile(f"{_DAY_NAME}, (?P<day>[0-9]{{2}}) {_MONTH} (?P<year>[0-9]{{4}}) {_TIME_OF_DAY} GMT")
_RFC850_DATE = re.compile(f"{_DAY_NAME_LONG}, (?P<day>[0-9]{{2}})-{_MONTH}-(?P<year>[0-9]{{2}}) {_TIME_OF_DAY} GMT")
_ASCTIME_DATE = re.compile(f"{_DAY_NAME} {_MONTH} (?P<day>[0-9]{{2}}| [0-9]) {_TIME_OF_DAY} (?P<year>[0-9]{{4}})")
_LEAP_SECOND = 60

# How much of a refused number literal the decoder's message quotes.
_NUMBER_EXCERPT_LENGTH = 40

MAX_BODY_NESTING = 512
"""The deepest nesting of arrays and objects a body may have and still be read, the limit the TypeScript client pins too.

No problem document comes near it. A body nested deeper is refused before it is parsed, so that every
reader draws the line at the same depth whatever its decoder's own limit, and so that neither the
decoder nor the validation that walks the decoded value can run out of stack.
"""

# A JSON string, its escapes included, whose brackets are text rather than nesting, read from its opening
# quote in one pass: a backslash escapes whatever character follows it, a line break included, and a string
# never closed runs to the end of the body. Matching every string once from the left keeps the scan linear,
# where requiring the closing quote would scan again from every quote of a string never closed.
_JSON_STRING = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"?', re.DOTALL)
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
    The scan reads the body once from the left, in time linear in its length, as the TypeScript client's
    does: a quote opens a string, a backslash inside it escapes the next character, whether or not JSON
    defines that escape, and a string never closed runs to the end. The depth is exact for every JSON
    body; a body that is no JSON, such as one with an escape JSON does not define, may count otherwise,
    and the decoder refuses it whatever the count.
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
        value: The header's value: a number of seconds, or an HTTP date in one of the three forms
            `parse_http_date` reads.
        now: The time to count an HTTP date from; the current time when not given.

    Returns:
        The delay in whole seconds, never negative, or `None` when the header is absent or unreadable:
        a number of seconds is ASCII digits only, as HTTP writes it, and one larger than a double
        holds exactly, past `2**53 - 1`, reads as unreadable, as a JavaScript reader reads it.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if _DELAY_SECONDS.fullmatch(text):
        try:
            seconds = int(text)
        except ValueError:
            return None
        return seconds if seconds <= _MAX_EXACT_SECONDS else None
    current = now or datetime.now(tz=UTC)
    moment = parse_http_date(text, now=current)
    if moment is None:
        return None
    delta = (moment - current).total_seconds()
    return max(0, math.ceil(delta))


def parse_http_date(text: str, *, now: datetime) -> datetime | None:
    """An HTTP date, in exactly the three forms a recipient must accept (RFC 9110, section 5.6.7), and no other.

    The forms are the IMF-fixdate `Sun, 06 Nov 1994 08:49:37 GMT`, the obsolete RFC 850 form
    `Sunday, 06-Nov-94 08:49:37 GMT` and the asctime form `Sun Nov  6 08:49:37 1994`, every name
    case-sensitive as the grammar writes it. The day name is part of the form but not checked against
    the date. The RFC 850 form's two-digit year reads as the year ending in those digits from 49 years
    before `now` to 50 years after it, so that a date that would be more than 50 years ahead reads as
    the most recent past year with those digits, as the RFC requires. A second of `60`, a leap
    second, counts as the next minute.

    Args:
        text: The date, with no surrounding whitespace.
        now: The time the two-digit year of the RFC 850 form is read against.

    Returns:
        The moment in UTC, or `None` when `text` is in none of the three forms, names no real moment,
        or names a leap second that carries it past the end of the year 9999.
    """
    year: int
    match_found = _IMF_FIXDATE.fullmatch(text) or _ASCTIME_DATE.fullmatch(text)
    if match_found is not None:
        year = int(match_found["year"])
    else:
        match_found = _RFC850_DATE.fullmatch(text)
        if match_found is None:
            return None
        year = _rfc850_year(int(match_found["year"]), now=now)
    second = int(match_found["second"])
    if second > _LEAP_SECOND:
        return None
    try:
        minute_start = datetime(
            year,
            _MONTHS.index(match_found["month"]) + 1,
            int(match_found["day"]),
            int(match_found["hour"]),
            int(match_found["minute"]),
            tzinfo=UTC,
        )
        return minute_start + timedelta(seconds=second)
    except ValueError:
        # A day the month does not have, or an hour or a minute the day does not have.
        return None
    except OverflowError:
        # A leap second in the last minute of the year 9999 carries the moment past the last one a date holds.
        return None


def _rfc850_year(two_digits: int, *, now: datetime) -> int:
    """The year ending in `two_digits` that lies from 49 years before `now` to 50 years after it."""
    year = now.year - now.year % 100 + two_digits
    if year > now.year + 50:
        return year - 100
    if year <= now.year - 50:
        return year + 100
    return year


def _is_problem_status(status: int) -> bool:
    """Whether a status is one a problem's `status` may hold, `100` to `599`, as HTTP defines them."""
    return 100 <= status <= 599


def _is_server_error(status: int) -> bool:
    """Whether a status is a server error, `500` to `599`."""
    return 500 <= status <= 599


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
        status: The answer's HTTP status, which a body that leaves `status` out takes when it is one HTTP
            defines, `100` to `599`; a body answered with another status keeps no `status`.
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
    # An HTTP parser may hand over a status HTTP does not define, such as `999`, which no problem's `status` holds.
    if "status" not in members and _is_problem_status(status):
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
        The runtime's problem when the body is one, else `client.outcome_unknown` for a server error
        on a route that creates a run, else the code the status names, else `client.response_unreadable`.
    """
    problem = read_problem_document(body, status=status, headers=headers)
    if problem is not None:
        return problem
    if creates_run and _is_server_error(status):
        return make_client_problem(CoreCode.CLIENT_OUTCOME_UNKNOWN)
    code = STATUS_READINGS.get(status)
    if code is None or (creates_run and _retries(code)):
        return unreadable_answer(status)
    retry_after = parse_retry_after(headers.get(RETRY_AFTER_HEADER)) if _retries(code) else None
    return make_client_problem(code, status=status, retry_after=retry_after)
