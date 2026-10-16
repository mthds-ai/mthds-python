import json
from datetime import UTC, datetime

import pytest

from mthds.protocol.problem.answers import decode_json, parse_retry_after, read_answer, read_problem_document, unreadable_answer
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
        ],
    )
    def test_decode_json_reads_as_every_reader_of_the_protocol_does(self, topic: str, text: str, is_json: bool, value: object) -> None:
        """The constants JSON does not define and a body too deep to decode are not JSON; numbers read as a JavaScript reader reads them."""
        decoded = decode_json(text)

        assert decoded.is_json is is_json, topic
        assert decoded.value == value, topic

    def test_a_body_nested_past_the_decoders_limit_is_not_json(self) -> None:
        """A body that exhausts the decoder reads as not JSON rather than raising `RecursionError`.

        The depth that trips it is an interpreter build constant, which rose by an order of
        magnitude in CPython 3.14, so the depth is discovered rather than pinned.
        """
        for depth in (10_000, 200_000, 2_000_000):
            text = "[" * depth + "]" * depth
            try:
                json.loads(text)
            except RecursionError:
                assert decode_json(text) == (False, None)
                return
        pytest.skip("no tried nesting depth exhausts this interpreter's JSON decoder")

    def test_an_integer_too_long_for_python_reads_as_a_number(self) -> None:
        """An integer past Python's conversion limit is still JSON, as it is for a JavaScript reader."""
        decoded = decode_json("[" + "1" * 5000 + "]")

        assert decoded.is_json
        assert decoded.value == [float("inf")]

    @pytest.mark.parametrize(
        ("topic", "value", "expected"),
        [
            ("seconds", "17", 17),
            ("seconds with spaces", " 5 ", 5),
            ("an http date ahead", "Fri, 16 Oct 2026 12:00:30 GMT", 30),
            ("an http date past", "Fri, 16 Oct 2026 11:59:00 GMT", 0),
            ("absent", None, None),
            ("empty", "", None),
            ("negative", "-5", None),
            ("a fraction", "1.5", None),
            ("garbage", "soon", None),
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
            ("a 503 on a run route, which never invites a repeat", 503, True, "client.response_unreadable"),
            ("a 405 on a run route, which invites none", 405, True, "request.method_not_allowed"),
            ("a 404, which several codes answer", 404, False, "client.response_unreadable"),
            ("a 500", 500, False, "client.response_unreadable"),
            ("a redirect the client does not follow", 302, False, "client.response_unreadable"),
        ],
    )
    def test_an_answer_that_is_no_problem_document_reads_by_its_status(self, topic: str, status: int, creates_run: bool, expected_code: str) -> None:
        problem = read_answer(status=status, body=LegacyAnswerBodies.PLAIN_DETAIL_STRING, headers={}, creates_run=creates_run)

        assert problem.code == expected_code, topic
        if expected_code == "client.response_unreadable":
            assert problem.as_wire()["params"] == {"status": status}
            assert problem.status is None
        else:
            assert problem.status == status

    def test_unreadable_answer_names_the_status(self) -> None:
        problem = unreadable_answer(200)

        assert problem.code == "client.response_unreadable"
        assert problem.detail == "The runtime answered with the HTTP status 200 and a body that is not a problem document the client can read."
