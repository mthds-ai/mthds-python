"""Tests for mthds.runners.runs — run-lifecycle models for the hosted polling surface."""

import pytest
from pydantic import TypeAdapter

from mthds.runners.runs import (
    RunStatus,
)


class TestRuns:
    """Tests for the run-lifecycle models."""

    # ── RunStatus ────────────────────────────────────────────────

    @pytest.mark.parametrize(
        ("status", "is_terminal", "is_success"),
        [
            (RunStatus.PENDING, False, False),
            (RunStatus.STARTED, False, False),
            (RunStatus.RUNNING, False, False),
            (RunStatus.COMPLETED, True, True),
            (RunStatus.FAILED, True, False),
            (RunStatus.CANCELLED, True, False),
            (RunStatus.TERMINATED, True, False),
            (RunStatus.TIMED_OUT, True, False),
        ],
    )
    def test_run_status_predicates(self, status: RunStatus, is_terminal: bool, is_success: bool) -> None:
        """is_terminal / is_success classify every status correctly."""
        assert status.is_terminal is is_terminal
        assert status.is_success is is_success

    def test_run_status_parses_from_string(self) -> None:
        """A wire string parses into the enum."""
        adapter = TypeAdapter(RunStatus)
        assert adapter.validate_python("TIMED_OUT") == RunStatus.TIMED_OUT
