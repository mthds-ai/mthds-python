"""Tests for ProblemDocument, the lenient read of a refused request's problem members."""

from typing import Any

import httpx
import pytest

from mthds.runners.api.problem import ProblemDocument, UserAction
from tests.unit.test_data import RefusedRunBodies


def _response(body: str, *, headers: dict[str, str] | None = None) -> httpx.Response:
    request = httpx.Request("POST", "http://localhost:8081/v1/execute")
    return httpx.Response(422, text=body, headers=headers or {}, request=request)


class TestProblemDocument:
    """Each member is read from the body when it has the type the document gives it, and reads as absent otherwise."""

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("type_uri", "https://docs.pipelex.com/latest/errors/model-not-found-error/"),
            ("title", "Model not found"),
            ("instance", "/v1/execute"),
            ("server_message", RefusedRunBodies.UNSERVED_MODEL_DETAIL),
            ("error_type", "ModelNotFoundError"),
            ("request_id", "req_b7d2c66f-b2d5-4dc7-bd4f-6cf98abfbdc0"),
            ("error_domain", "input"),
            ("retryable", False),
            ("user_action", UserAction(kind="change_model", detail=RefusedRunBodies.UNSERVED_MODEL_NEXT_STEP)),
            ("validation_errors", None),
        ],
    )
    def test_each_member_of_a_real_refusal(self, field: str, expected: Any) -> None:
        """Every member of the dev plane's refusal of a run on a model the deck does not serve."""
        document = ProblemDocument.make_from_body(RefusedRunBodies.UNSERVED_MODEL_AT_RUN)
        assert getattr(document, field) == expected

    @pytest.mark.parametrize(
        "field",
        ["type_uri", "title", "instance", "request_id", "error_domain", "retryable", "user_action", "validation_errors"],
    )
    def test_a_malformed_member_reads_as_absent(self, field: str) -> None:
        """A member of the wrong type, an empty string, a next step with no words, or a list with one bad item reads as `None`."""
        document = ProblemDocument.make_from_body(RefusedRunBodies.MALFORMED_MEMBERS)
        assert getattr(document, field) is None
        # The well-formed member beside them is still read.
        assert document.server_message == "The input is empty"

    @pytest.mark.parametrize(
        ("topic", "body"),
        [
            ("empty body", ""),
            ("html page", RefusedRunBodies.GATEWAY_HTML),
            ("json array", "[1, 2]"),
            ("json string", '"refused"'),
            ("truncated json", '{"detail": "refu'),
        ],
    )
    def test_a_body_that_is_no_json_object_carries_no_member(self, topic: str, body: str) -> None:
        """Anything but a JSON object reads as a document with no members at all."""
        assert ProblemDocument.make_from_body(body) == ProblemDocument(), topic

    def test_the_legacy_detail_object_gives_the_reason_and_the_class(self) -> None:
        """`{"detail": {"error_type": ..., "message": ...}}` is read as the class and the reason."""
        document = ProblemDocument.make_from_body(RefusedRunBodies.LEGACY_DETAIL_OBJECT)
        assert document.error_type == "PipeRunError"
        assert document.server_message == "Pipe 'summarize' failed: the input is empty"
        assert document.type_uri is None

    def test_top_level_error_type_and_message_are_the_fallbacks(self) -> None:
        """A detail object missing a member falls back to the top-level `error_type` and `message`."""
        document = ProblemDocument.make_from_body('{"detail": {}, "error_type": "RunnerError", "message": "The runner is shutting down"}')
        assert document.error_type == "RunnerError"
        assert document.server_message == "The runner is shutting down"

    @pytest.mark.parametrize(
        ("topic", "body"),
        [
            ("empty detail string", '{"detail": "", "message": "The runner is shutting down", "error_type": "RunnerError"}'),
            (
                "empty detail object members",
                '{"detail": {"error_type": "", "message": ""}, "message": "The runner is shutting down", "error_type": "RunnerError"}',
            ),
        ],
    )
    def test_an_empty_detail_gives_no_reason_and_falls_back(self, topic: str, body: str) -> None:
        """An empty `detail` is no reason: the top-level `message` and `error_type` stand in."""
        document = ProblemDocument.make_from_body(body)
        assert document.server_message == "The runner is shutting down", topic
        assert document.error_type == "RunnerError", topic

    def test_the_validation_items_keep_their_locators(self) -> None:
        """A refusal's items are the protocol's neutral diagnostics, the runner's locators on model_extra."""
        document = ProblemDocument.make_from_body(RefusedRunBodies.UNKNOWN_MODEL_AT_LOAD)
        assert document.validation_errors is not None
        item = document.validation_errors[0]
        assert item.category == "pipe_validation"
        assert (item.model_extra or {})["error_type"] == "unknown_model"
        assert (item.model_extra or {})["field_path"] == "pipe.draft_pitch.model"
        assert (item.model_extra or {})["model_reference"] == "gpt-5.1"

    def test_an_empty_validation_list_is_kept(self) -> None:
        """An empty list is the runner's list, not an absent one."""
        assert ProblemDocument.make_from_body('{"validation_errors": []}').validation_errors == []

    def test_a_user_action_keeps_the_members_a_runner_adds(self) -> None:
        """The next step's extra members ride model_extra."""
        document = ProblemDocument.make_from_body(
            '{"user_action": {"kind": "check_billing", "detail": "Top up the account", "url": "https://app.example/billing"}}'
        )
        assert document.user_action is not None
        assert document.user_action.kind == "check_billing"
        assert document.user_action.detail == "Top up the account"
        assert (document.user_action.model_extra or {})["url"] == "https://app.example/billing"

    def test_members_holds_the_decoded_document_whole(self) -> None:
        """A member this package does not name is kept on `members`."""
        document = ProblemDocument.make_from_body(RefusedRunBodies.UNKNOWN_MODEL_AT_LOAD)
        assert document.members is not None
        assert document.members["error_category"] == "configuration"
        assert document.members["status"] == 422

    @pytest.mark.parametrize(
        ("topic", "body", "headers", "expected"),
        [
            (
                "body wins over header",
                RefusedRunBodies.UNSERVED_MODEL_AT_RUN,
                {"X-Request-ID": "req_header"},
                "req_b7d2c66f-b2d5-4dc7-bd4f-6cf98abfbdc0",
            ),
            ("header when the body has none", RefusedRunBodies.PLAIN_DETAIL_STRING, {"X-Request-ID": "  req_header  "}, "req_header"),
            ("header when the body is no json", RefusedRunBodies.GATEWAY_HTML, {"x-request-id": "req_gateway"}, "req_gateway"),
            ("a blank header is no id", RefusedRunBodies.PLAIN_DETAIL_STRING, {"X-Request-ID": "   "}, None),
            ("neither", RefusedRunBodies.PLAIN_DETAIL_STRING, {}, None),
        ],
    )
    def test_the_request_id_falls_back_to_the_response_header(self, topic: str, body: str, headers: dict[str, str], expected: str | None) -> None:
        """The body's `request_id` wins; the `X-Request-ID` header stands in when the body names none."""
        assert ProblemDocument.make_from_response(_response(body, headers=headers)).request_id == expected, topic
