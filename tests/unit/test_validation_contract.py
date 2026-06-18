"""Contract round-trip tests for the 200-diagnostic `/validate` union.

Pins the Pipelex validation wire models against the canonical example bodies from
the protocol spec (`docs/specs/pipelex-mthds-protocol.md`, `## Validation report
union`). Mirrors `mthds-js/tests/unit/protocol/validation-contract.test.ts`: parse a
wire body at the boundary, discriminate on `is_valid`, and assert the narrowed arm.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from mthds.runners.api.models import (
    DryRunStatus,
    PipelexInvalidReport,
    PipelexValidationReport,
    PipelexValidationResult,
    PipelexValidationResultAdapter,
    ValidationErrorCategory,
)

# ── Canonical example bodies (verbatim shapes from the protocol spec) ─────────

VALID_BODY: dict[str, Any] = {
    "is_valid": True,
    "bundle_blueprint": {"source": "contracts.mthds", "domain": "legal_contracts"},
    "pipe_io_contracts": {
        "legal_contracts.summarize": {
            "inputs": {"contract": {"concept_ref": "legal_contracts.Contract", "json_schema": {}}},
            "output": {"concept_ref": "legal_contracts.Summary", "multiplicity": "single"},
        }
    },
    "validated_pipes": [{"pipe_ref": "legal_contracts.summarize", "status": "SUCCESS"}],
    "pending_signatures": [],
    "is_runnable": True,
    "graph_spec": {"nodes": [], "edges": []},
    "mthds_contents": ["<verbatim submitted source>"],
    "message": "Validation succeeded.",
}

INVALID_BODY: dict[str, Any] = {
    "is_valid": False,
    "validation_errors": [
        {
            "category": "pipe_validation",
            "error_type": "PipeValidationError",
            "message": "Pipe references an unknown concept.",
            "pipe_code": "summarize",
            "concept_code": "Contractt",
            "field_name": "output",
            "source": "contracts.mthds",
        }
    ],
    "pending_signatures": [],
    "is_runnable": False,
    "message": "Validation found errors.",
}

DRY_RUN_BODY: dict[str, Any] = {
    "is_valid": False,
    "validation_errors": [{"category": "dry_run", "error_type": "DryRunError", "message": "Dry run failed: residual."}],
    "pending_signatures": [],
    "is_runnable": False,
    "message": "Validation found errors.",
}

BLUEPRINT_RESIDUAL_BODY: dict[str, Any] = {
    "is_valid": False,
    "validation_errors": [{"category": "blueprint_validation", "error_type": "TOMLDecodeError", "message": "Invalid TOML."}],
    "pending_signatures": [],
    "is_runnable": False,
    "message": "Validation found errors.",
}

PENDING_SIGNATURE_BODY: dict[str, Any] = {
    "is_valid": True,
    "bundle_blueprint": {"source": "draft.mthds"},
    "pipe_io_contracts": {},
    "validated_pipes": [],
    "pending_signatures": ["pending_sig.draft_step"],
    "is_runnable": False,
    "graph_spec": None,
    "message": "Validation succeeded.",
}


def _parse(body: dict[str, Any]) -> PipelexValidationResult:
    """Parse a wire body through the real discriminated-union adapter — the exact parse path the API client uses."""
    return PipelexValidationResultAdapter.validate_python(body)


class TestValidationContract:
    def test_valid_arm_carries_typed_artifacts(self) -> None:
        """The valid arm parses to a typed report with structural artifacts."""
        report = _parse(VALID_BODY)
        assert isinstance(report, PipelexValidationReport)
        assert report.is_valid is True
        assert report.is_runnable is True
        assert report.bundle_blueprint["source"] == "contracts.mthds"
        assert "legal_contracts.summarize" in report.pipe_io_contracts
        assert report.validated_pipes[0].pipe_ref == "legal_contracts.summarize"
        assert report.validated_pipes[0].status is DryRunStatus.SUCCESS
        assert report.mthds_contents == ["<verbatim submitted source>"]

    def test_invalid_arm_carries_structured_errors_without_artifacts(self) -> None:
        """The invalid arm carries typed `validation_errors[]` and no structural artifacts."""
        report = _parse(INVALID_BODY)
        assert isinstance(report, PipelexInvalidReport)
        assert report.is_valid is False
        assert report.is_runnable is False
        item = report.validation_errors[0]
        assert item.category is ValidationErrorCategory.PIPE_VALIDATION
        assert item.pipe_code == "summarize"
        assert item.concept_code == "Contractt"
        assert item.field_name == "output"
        assert item.source == "contracts.mthds"
        # Structural artifacts do not exist on the invalid arm — not a field, not an extra.
        assert "bundle_blueprint" not in (report.model_extra or {})
        assert "graph_spec" not in (report.model_extra or {})

    def test_dry_run_residual_is_graph_level(self) -> None:
        """A dry-run residual is one `dry_run` item with no `source` (graph-level)."""
        report = _parse(DRY_RUN_BODY)
        assert isinstance(report, PipelexInvalidReport)
        item = report.validation_errors[0]
        assert item.category is ValidationErrorCategory.DRY_RUN
        assert item.error_type == "DryRunError"
        assert item.source is None

    def test_blueprint_residual_has_no_source(self) -> None:
        """A parse-level residual is one `blueprint_validation` item with no `source`."""
        report = _parse(BLUEPRINT_RESIDUAL_BODY)
        assert isinstance(report, PipelexInvalidReport)
        assert report.validation_errors[0].category is ValidationErrorCategory.BLUEPRINT_VALIDATION
        assert report.validation_errors[0].source is None

    def test_pending_signatures_is_valid_but_not_runnable(self) -> None:
        """Pending signatures ride a runnability fact on a VALID arm, never an error item."""
        report = _parse(PENDING_SIGNATURE_BODY)
        assert isinstance(report, PipelexValidationReport)
        assert report.is_valid is True
        assert report.is_runnable is False
        assert report.pending_signatures == ["pending_sig.draft_step"]

    def test_rendered_markdown_is_typed_on_both_arms_when_present(self) -> None:
        """The opt-in `rendered_markdown` extra parses to a typed field on both verdict arms."""
        valid = _parse({**VALID_BODY, "rendered_markdown": "# Validation passed"})
        assert isinstance(valid, PipelexValidationReport)
        assert valid.rendered_markdown == "# Validation passed"
        invalid = _parse({**INVALID_BODY, "rendered_markdown": "# Validation failed"})
        assert isinstance(invalid, PipelexInvalidReport)
        assert invalid.rendered_markdown == "# Validation failed"

    def test_rendered_markdown_is_none_when_absent(self) -> None:
        """Default responses omit `rendered_markdown` — the typed field defaults to None on both arms."""
        valid = _parse(VALID_BODY)
        assert isinstance(valid, PipelexValidationReport)
        assert valid.rendered_markdown is None
        invalid = _parse(INVALID_BODY)
        assert isinstance(invalid, PipelexInvalidReport)
        assert invalid.rendered_markdown is None

    def test_category_vocabulary_is_the_locked_set(self) -> None:
        """The closed category set mirrors `conformance/.../validation_contract.py` (drift guard)."""
        assert {category.value for category in ValidationErrorCategory} == {
            "blueprint_validation",
            "pipe_factory",
            "pipe_validation",
            "dry_run",
        }

    def test_unknown_category_is_rejected(self) -> None:
        """An out-of-vocabulary category fails validation — the enum is a closed set."""
        bad_body = {**INVALID_BODY, "validation_errors": [{"category": "made_up", "message": "x"}]}
        with pytest.raises(ValidationError, match="made_up"):
            PipelexValidationResultAdapter.validate_python(bad_body)

    @pytest.mark.parametrize(
        "malformed_body",
        [
            {},  # no discriminant at all
            {"message": "x"},  # still no discriminant — must NOT be read as a valid verdict
            {"is_valid": None},  # null discriminant cannot be tagged
            {"is_valid": "false"},  # non-boolean discriminant cannot be tagged
            {"is_valid": False, "message": "x"},  # invalid arm tagged, but required validation_errors missing
        ],
    )
    def test_malformed_200_body_raises_no_silent_valid(self, malformed_body: dict[str, Any]) -> None:
        """A 200 body that can't be discriminated, or whose tagged arm misses a required field, raises.

        Regression guard for the silent-valid hole: the old hand-rolled `is_valid is False` check
        treated any non-`False` discriminant (missing, null, anything) as valid. Routing through the
        discriminated-union adapter makes a missing/bad discriminant a loud `ValidationError` instead.
        """
        with pytest.raises(ValidationError):
            PipelexValidationResultAdapter.validate_python(malformed_body)
