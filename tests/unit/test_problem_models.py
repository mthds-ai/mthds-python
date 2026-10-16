import copy
from typing import Any

import pytest
from pydantic import ValidationError

from mthds.protocol.problem.models import FixSafety, Problem, ProblemItem, RemapValueOp, SuggestedFix, UnknownFixOp
from mthds.protocol.problem.registry import MethodConceptUnresolvedParams, ProblemDomain, RetryVerdict, StepKind
from tests.unit.test_data import ProblemBodies


def _problem(**members: Any) -> dict[str, Any]:
    """The rate-limited problem with `members` replaced, a member given as `...` removed."""
    body = copy.deepcopy(ProblemBodies.RATE_LIMITED)
    for name, value in members.items():
        if value is ...:
            body.pop(name, None)
        else:
            body[name] = value
    return body


class TestProblemModels:
    def test_a_problem_reads_as_received_with_its_extra_members(self) -> None:
        """A problem keeps every member as sent, an undeclared one on `model_extra`, and gives them back from `as_wire()`."""
        problem = Problem.model_validate(ProblemBodies.MODEL_UNKNOWN)

        assert problem.as_wire() == ProblemBodies.MODEL_UNKNOWN
        assert problem.model_extra == {"request_id": "req_b7d2c66f-b2d5-4dc7-bd4f-6cf98abfbdc0"}
        assert problem.domain is ProblemDomain.METHOD
        assert problem.retry is RetryVerdict.NO
        assert problem.next_step.kind is StepKind.CONTACT_OWNER
        assert problem.family == "model"
        assert problem.code_spec is not None
        assert problem.code_spec.status == 422

    @pytest.mark.parametrize(
        ("topic", "members"),
        [
            ("a status written as a string", {"status": "422"}),
            ("a status outside the HTTP range", {"status": 99}),
            ("a boolean where a number belongs", {"retry_after": True}),
            ("a negative delay", {"retry_after": -1}),
            ("a null member", {"params": None}),
            ("a code outside the code pattern", {"code": "Account.RateLimited"}),
            ("a code with no family", {"code": "rate_limited"}),
            ("no next step", {"next_step": ...}),
            ("a next step without its sentence", {"next_step": {"kind": "wait"}}),
            ("no detail", {"detail": ...}),
            ("an empty list of faults", {"errors": []}),
            ("a location counted from zero where it counts from one", {"location": {"line": 0}}),
            ("a blob hash that is not one", {"params": {"missing_blobs": ["abc"]}}),
        ],
    )
    def test_a_mistyped_member_makes_the_document_no_problem(self, topic: str, members: dict[str, Any]) -> None:
        """A declared member of the wrong type, or missing where required, fails validation, so the reader treats the body as unreadable."""
        with pytest.raises(ValidationError):
            Problem.model_validate(_problem(**members))
        assert topic

    @pytest.mark.parametrize(
        ("topic", "members", "domain", "retry", "step_kind"),
        [
            ("every value known", {}, ProblemDomain.ACCOUNT, RetryVerdict.YES, StepKind.WAIT),
            (
                "unknown values in a family whose codes agree",
                {"code": "auth.passkey_expired", "domain": "steward", "retry": "later", "next_step": {"kind": "escalate", "detail": "Escalate."}},
                ProblemDomain.ACCOUNT,
                RetryVerdict.NO,
                StepKind.CONTACT_OWNER,
            ),
            (
                "unknown values in a family the reader does not know",
                {"code": "quorum.lost", "domain": "steward", "retry": "later", "next_step": {"kind": "escalate", "detail": "Escalate."}},
                ProblemDomain.RUNTIME,
                RetryVerdict.NO,
                StepKind.REPORT,
            ),
            (
                "a known domain is read as sent whatever the family",
                {"code": "quorum.lost", "domain": "operator"},
                ProblemDomain.OPERATOR,
                RetryVerdict.YES,
                StepKind.WAIT,
            ),
        ],
    )
    def test_a_reader_falls_back_on_the_family(
        self, topic: str, members: dict[str, Any], domain: ProblemDomain, retry: RetryVerdict, step_kind: StepKind
    ) -> None:
        """An unknown domain or step kind reads as its family's, then `runtime` and `report`; an unknown retry reads as `no`."""
        problem = Problem.model_validate(_problem(**members))

        assert problem.effective_domain is domain, topic
        assert problem.effective_retry is retry, topic
        assert problem.effective_step_kind is step_kind, topic
        # An unknown value is kept as received, not replaced by its reading.
        assert problem.as_wire()["domain"] == _problem(**members)["domain"]

    @pytest.mark.parametrize(
        ("retry", "is_retryable", "outcome_is_unknown"),
        [("yes", True, False), ("no", False, False), ("outcome_unknown", False, True), ("later", False, False)],
    )
    def test_only_a_retry_of_yes_invites_a_repeat(self, retry: str, is_retryable: bool, outcome_is_unknown: bool) -> None:
        """`is_retryable` is true for `yes` alone, so an unknown outcome or an unknown verdict is never repeated on a guess."""
        problem = Problem.model_validate(_problem(retry=retry))

        assert problem.is_retryable is is_retryable
        assert problem.outcome_is_unknown is outcome_is_unknown

    def test_an_item_reads_its_domain_from_its_code(self) -> None:
        """An item carries no verdict: its domain is its code's, else its family's, else `runtime`."""
        known = ProblemItem.model_validate({"code": "input.missing", "detail": "The input 'contract' is missing."})
        family_known = ProblemItem.model_validate({"code": "input.too_vague", "detail": "The input is vague."})
        unknown = ProblemItem.model_validate({"code": "quorum.lost", "detail": "The quorum is lost."})

        assert known.effective_domain is ProblemDomain.INPUT
        assert family_known.effective_domain is ProblemDomain.INPUT
        assert unknown.effective_domain is ProblemDomain.RUNTIME

    def test_an_items_params_validate_into_its_codes_model(self) -> None:
        """`params_as` reads an item's parameters as the generated model of its code."""
        problem = Problem.model_validate(ProblemBodies.METHOD_INVALID)
        assert problem.errors is not None

        params = problem.errors[0].params_as(MethodConceptUnresolvedParams)
        assert params.concept == "legal.Clausee"
        assert params.suggestions == ["legal.Clause"]

    def test_a_fix_with_an_unknown_operation_is_never_applicable(self) -> None:
        """An operation of a kind the protocol does not list reads as `UnknownFixOp`, which makes the whole fix inapplicable."""
        fix = SuggestedFix.model_validate(
            {
                "fix_code": "rename-concept-reference",
                "description": "Rename the concept.",
                "safety": "reviewed",
                "ops": [
                    {"kind": "remap_value", "table_path": ["pipe", "x"], "key": "output", "mapping": {"a.B": "a.C"}},
                    {"kind": "rewrite_reference", "from": "a.B", "to": "a.C"},
                ],
            }
        )

        assert isinstance(fix.ops[0], RemapValueOp)
        assert isinstance(fix.ops[1], UnknownFixOp)
        assert (fix.ops[1].model_extra or {}) == {"from": "a.B", "to": "a.C"}
        assert not fix.is_applicable
        # A safety the reader does not know reads as unsafe, and stays as received.
        assert fix.effective_safety is FixSafety.UNSAFE
        assert fix.safety == "reviewed"

    @pytest.mark.parametrize(
        ("topic", "operation"),
        [
            ("a known kind missing a member", {"kind": "set_key", "table_path": [], "key": "x"}),
            ("an ensure_table of the root", {"kind": "ensure_table", "table_path": []}),
            ("an empty mapping", {"kind": "remap_value", "table_path": [], "key": "x", "mapping": {}}),
            ("a kind that is not a string", {"kind": 7}),
        ],
    )
    def test_a_malformed_operation_is_refused(self, topic: str, operation: dict[str, Any]) -> None:
        """A listed kind is held to its variant's shape, and the catch-all still needs a string kind."""
        with pytest.raises(ValidationError):
            SuggestedFix.model_validate({"fix_code": "a-fix", "description": "A fix.", "safety": "safe", "ops": [operation]})
        assert topic

    def test_with_members_adds_members_that_count_as_read(self) -> None:
        """A member added by `with_members` is validated and given back by `as_wire()`."""
        problem = Problem.model_validate(_problem(status=...)).with_members(status=429, retry_after=17)

        assert problem.status == 429
        assert problem.retry_after == 17
        assert problem.as_wire() == {**ProblemBodies.RATE_LIMITED, "retry_after": 17}

    def test_an_integral_number_reads_as_an_integer(self) -> None:
        """A JSON integer written with a fraction of zero reads as an integer, as a JavaScript reader sees it."""
        problem = Problem.model_validate(_problem(status=429.0, retry_after=2.0))

        assert problem.as_wire()["status"] == 429
        assert isinstance(problem.as_wire()["retry_after"], int)
        assert Problem.model_validate(_problem(retry_after=2.5)).retry_after == 2.5
