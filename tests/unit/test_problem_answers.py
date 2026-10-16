import json
import time
from datetime import UTC, datetime

import pytest

from mthds.protocol.problem.answers import (
    MAX_BODY_NESTING,
    decode_json,
    nests_deeper_than,
    parse_retry_after,
    read_answer,
    read_problem_document,
    unreadable_answer,
)
from mthds.protocol.problem.registry import STATUS_READINGS, CoreCode
from tests.unit.test_data import LegacyAnswerBodies, ProblemBodies

_NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)


class TestProblemAnswers:
    @pytest.mark.parametrize(
        ("topic", "text", "is_json", "value"),
        [
            ("an object", '{"a": 1}', True, {"a": 1}),
            ("an integral float reads as an integer", "[2.0, 2.5, 1e2]", True, [2, 2.5, 100]),
            ("null is JSON", "null", True, None),
            ("NaN is not JSON", '{"a": NaN}', False, None),
            ("Infinity is not JSON", "[-Infinity]", False, None),
            ("an html page", LegacyAnswerBodies.GATEWAY_HTML, False, None),
            ("an empty body", "", False, None),
            ("a truncated object", '{"detail": "refu', False, None),
            ("an exponent past a double's range, which reads as an infinity", '{"retry_after": 1e999}', False, None),
            ("a negative one", "[-1e999]", False, None),
            ("an integer past a double's range", "[" + "9" * 400 + "]", False, None),
            ("the largest double", "[1.7976931348623157e308]", True, [int(1.7976931348623157e308)]),
        ],
    )
    def test_decode_json_reads_as_every_reader_of_the_protocol_does(self, topic: str, text: str, is_json: bool, value: object) -> None:
        """The constants JSON does not define and a body too deep to decode are not JSON; numbers read as a JavaScript reader reads them."""
        decoded = decode_json(text)

        assert decoded.is_json is is_json, topic
        assert decoded.value == value, topic

    @pytest.mark.parametrize(
        ("topic", "text", "is_json"),
        [
            ("arrays at the limit", "[" * MAX_BODY_NESTING + "]" * MAX_BODY_NESTING, True),
            ("arrays past it", "[" * (MAX_BODY_NESTING + 1) + "]" * (MAX_BODY_NESTING + 1), False),
            ("objects at the limit", '{"a":' * MAX_BODY_NESTING + "1" + "}" * MAX_BODY_NESTING, True),
            ("objects past it", '{"a":' * (MAX_BODY_NESTING + 1) + "1" + "}" * (MAX_BODY_NESTING + 1), False),
            ("brackets inside a string are text", '["' + "[{" * MAX_BODY_NESTING + '"]', True),
            ("an escaped quote keeps the string open", '["\\"' + "[" * (MAX_BODY_NESTING + 1) + '"]', True),
            (
                "an escaped backslash leaves the next quote to close the string",
                '["\\\\",' + "[" * MAX_BODY_NESTING + "]" * (MAX_BODY_NESTING + 1),
                False,
            ),
            ("far past any decoder's own limit", "[" * 200_000 + "]" * 200_000, False),
        ],
    )
    def test_a_body_nested_past_the_limit_is_not_json(self, topic: str, text: str, is_json: bool) -> None:
        """Every reader refuses a body nested deeper than the one limit the twins pin, before parsing it, and a bracket in a string never counts."""
        assert decode_json(text).is_json is is_json, topic
        assert nests_deeper_than(text, limit=MAX_BODY_NESTING) is not is_json, topic

    @pytest.mark.parametrize(
        ("topic", "text"),
        [
            ("a string never closed, full of escaped quotes", '"' + '\\"' * 40_000 + "[" * (MAX_BODY_NESTING + 1)),
            ("an escaped line break, which keeps the string open", '["\\\n' + "[" * (MAX_BODY_NESTING + 1) + '"]'),
        ],
    )
    def test_the_nesting_scan_reads_a_string_in_one_pass(self, topic: str, text: str) -> None:
        """Brackets in a string never count, however the string is written, and the scan is linear rather than repeated from every quote."""
        started = time.perf_counter()

        nests = nests_deeper_than(text, limit=MAX_BODY_NESTING)

        assert time.perf_counter() - started < 1.0, topic
        assert nests is False, topic
        assert decode_json(text).is_json is False, topic

    def test_an_integer_too_long_for_python_is_not_json(self) -> None:
        """An integer past Python's conversion limit is far past a double's range, where a JavaScript reader reads an infinity, so it is refused."""
        assert decode_json("[" + "1" * 5000 + "]") == (False, None)

    @pytest.mark.parametrize(
        ("topic", "value", "expected"),
        [
            ("seconds", "17", 17),
            ("seconds with spaces", " 5 ", 5),
            ("an http date ahead", "Fri, 16 Oct 2026 12:00:30 GMT", 30),
            ("an http date past", "Fri, 16 Oct 2026 11:59:00 GMT", 0),
            ("the obsolete rfc 850 form", "Friday, 16-Oct-26 12:00:30 GMT", 30),
            ("the asctime form", "Fri Oct 16 12:00:30 2026", 30),
            ("the asctime form with a one-digit day", "Fri Nov  6 12:00:00 2026", 21 * 24 * 3600),
            ("an rfc 850 year more than 50 years ahead reads as the past", "Sunday, 06-Nov-94 08:49:37 GMT", 0),
            (
                "an rfc 850 year within 50 years ahead",
                "Friday, 16-Oct-76 12:00:00 GMT",
                int((datetime(2076, 10, 16, 12, tzinfo=UTC) - _NOW).total_seconds()),
            ),
            ("a leap second", "Fri, 16 Oct 2026 12:00:60 GMT", 60),
            ("no day name", "16 Oct 2026 12:00:30 GMT", None),
            ("a numeric zone", "Fri, 16 Oct 2026 12:00:30 +0000", None),
            ("a zone other than GMT", "Fri, 16 Oct 2026 12:00:30 UTC", None),
            ("a day name in lower case", "fri, 16 Oct 2026 12:00:30 GMT", None),
            ("a month in upper case", "Fri, 16 OCT 2026 12:00:30 GMT", None),
            ("a one-digit day in the fixdate form", "Fri, 6 Nov 2026 12:00:30 GMT", None),
            ("a two-digit year in the fixdate form", "Fri, 16 Oct 26 12:00:30 GMT", None),
            ("a short day name in the rfc 850 form", "Fri, 16-Oct-26 12:00:30 GMT", None),
            ("a four-digit year in the rfc 850 form", "Friday, 16-Oct-2026 12:00:30 GMT", None),
            ("the asctime form with a zone", "Fri Oct 16 12:00:30 2026 GMT", None),
            ("an iso 8601 date", "2026-10-16T12:00:30Z", None),
            ("a day the month does not have", "Fri, 31 Feb 2026 12:00:30 GMT", None),
            ("an hour the day does not have", "Fri, 16 Oct 2026 24:00:00 GMT", None),
            ("a second past a leap second", "Fri, 16 Oct 2026 12:00:61 GMT", None),
            ("a leap second carrying the moment past the year 9999", "Fri, 31 Dec 9999 23:59:60 GMT", None),
            ("the last second of the year 9999", "Fri, 31 Dec 9999 23:59:59 GMT", int((datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC) - _NOW).total_seconds())),
            ("absent", None, None),
            ("empty", "", None),
            ("negative", "-5", None),
            ("a fraction", "1.5", None),
            ("garbage", "soon", None),
            ("a superscript digit, which is no ASCII digit", "²", None),
            ("arabic-indic digits, which are no ASCII digits", "١٢", None),
            ("digits too many to convert", "9" * 5000, None),
            ("the largest delay a double holds exactly", str(2**53 - 1), 2**53 - 1),
            ("a delay past it", str(2**53), None),
        ],
    )
    def test_parse_retry_after_reads_seconds_and_http_dates(self, topic: str, value: str | None, expected: int | None) -> None:
        assert parse_retry_after(value, now=_NOW) == expected, topic

    def test_a_problem_document_takes_its_status_and_delay_from_the_answer(self) -> None:
        """A body that leaves `status` out takes the answer's, and a retryable one without `retry_after` takes the header's."""
        body = {member: value for member, value in ProblemBodies.RATE_LIMITED.items() if member != "status"}

        problem = read_problem_document(json.dumps(body), status=429, headers={"retry-after": "9"})

        assert problem is not None
        assert problem.as_wire() == {**ProblemBodies.RATE_LIMITED, "retry_after": 9}

    def test_a_problem_document_keeps_its_own_status_and_delay(self) -> None:
        body = {**ProblemBodies.RATE_LIMITED, "retry_after": 3}

        problem = read_problem_document(json.dumps(body), status=503, headers={"retry-after": "9"})

        assert problem is not None
        assert (problem.status, problem.retry_after) == (429, 3)

    def test_a_problem_that_invites_no_retry_takes_no_delay(self) -> None:
        problem = read_problem_document(ProblemBodies.MODEL_UNKNOWN_BODY, status=422, headers={"retry-after": "9"})

        assert problem is not None
        assert problem.retry_after is None
        assert "retry_after" not in problem.as_wire()

    @pytest.mark.parametrize(
        ("topic", "body"),
        [
            ("an answer written before the protocol's core members", LegacyAnswerBodies.UNKNOWN_MODEL_AT_LOAD),
            ("a json array", "[1, 2]"),
            ("a json string", '"refused"'),
            ("an html page", LegacyAnswerBodies.GATEWAY_HTML),
        ],
    )
    def test_a_body_that_is_no_problem_document_reads_as_none(self, topic: str, body: str) -> None:
        assert read_problem_document(body, status=500, headers={}) is None, topic

    def test_the_status_readings_are_the_ones_a_caller_can_state(self) -> None:
        """The core registry names two statuses a client can read without a problem document."""
        assert STATUS_READINGS == {405: CoreCode.REQUEST_METHOD_NOT_ALLOWED, 503: CoreCode.RUNTIME_UNAVAILABLE}

    @pytest.mark.parametrize(
        ("topic", "status", "creates_run", "expected_code"),
        [
            ("a 503 on a read", 503, False, "runtime.unavailable"),
            ("a 503 on a run route, where the run may have started", 503, True, "client.outcome_unknown"),
            ("a gateway's 504 on a run route", 504, True, "client.outcome_unknown"),
            ("a 500 on a run route", 500, True, "client.outcome_unknown"),
            ("a 504 on a read", 504, False, "client.response_unreadable"),
            ("a 404 on a run route, which no server error is", 404, True, "client.response_unreadable"),
            ("a 405 on a run route, which invites none", 405, True, "request.method_not_allowed"),
            ("a 404, which several codes answer", 404, False, "client.response_unreadable"),
            ("a 500", 500, False, "client.response_unreadable"),
            ("a redirect the client does not follow", 302, False, "client.response_unreadable"),
        ],
    )
    def test_an_answer_that_is_no_problem_document_reads_by_its_status(self, topic: str, status: int, creates_run: bool, expected_code: str) -> None:
        reading = read_answer(status=status, body=LegacyAnswerBodies.PLAIN_DETAIL_STRING, headers={}, creates_run=creates_run)
        problem = reading.problem

        assert reading.from_body is False, topic
        assert problem.code == expected_code, topic
        if expected_code == "client.response_unreadable":
            assert problem.as_wire()["params"] == {"status": status}
            assert problem.status is None
        elif expected_code == "client.outcome_unknown":
            assert problem.outcome_is_unknown, topic
            assert problem.status is None, topic
        else:
            assert problem.status == status

    def test_a_problem_document_reads_as_the_bodys_own(self) -> None:
        """The reading says the problem is the body's, so that a caller never reads the body again to tell."""
        reading = read_answer(status=422, body=ProblemBodies.MODEL_UNKNOWN_BODY, headers={}, creates_run=True)

        assert reading.from_body is True
        assert reading.problem.as_wire() == ProblemBodies.MODEL_UNKNOWN

    def test_unreadable_answer_names_the_status(self) -> None:
        problem = unreadable_answer(200)

        assert problem.code == "client.response_unreadable"
        assert problem.detail == "The runtime answered with the HTTP status 200 and a body that is not a problem document the client can read."
