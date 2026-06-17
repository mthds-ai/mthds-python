"""Contract round-trip tests for the 200-diagnostic `/validate` union.

Pins the Pipelex validation wire models against the canonical example bodies from
the protocol spec (`docs/specs/pipelex-mthds-protocol.md`, `## Validation report
union`). Mirrors `mthds-js/tests/unit/protocol/validation-contract.test.ts`: parse a
wire body at the boundary, discriminate on `is_valid`, and assert the narrowed arm.
"""

from __future__ import annotations

from typing import Any

import pytest

from mthds.runners.api.models import (
    DryRunStatus,
    PipelexInvalidReport,
    PipelexValidationReport,
    PipelexValidationResult,
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
    """Discriminate on `is_valid` exactly as the API client does."""
    if body.get("is_valid") is False:
        return PipelexInvalidReport.model_validate(body)
    return PipelexValidationReport.model_validate(body)


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
        with pytest.raises(ValueError, match="made_up"):
            PipelexInvalidReport.model_validate(bad_body)
