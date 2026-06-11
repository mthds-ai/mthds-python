"""Tests for mthds.runners.runs — run-lifecycle models for the hosted polling surface."""

from dataclasses import FrozenInstanceError

import pytest
from pydantic import TypeAdapter

from mthds.protocol.models import RunRequest
from mthds.runners.runs import (
    PollInfo,
    RunPublic,
    RunRead,
    RunResultCompleted,
    RunResultFailed,
    RunResultRunning,
    RunResults,
    RunResultState,
    RunStatus,
    WaitForResultOptions,
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

    # ── RunRequest (the /execute and /start body) ─────────────

    def test_start_run_request_extension_alone_is_valid(self) -> None:
        """A body with only an extension arg is accepted client-side (the server is the source of truth)."""
        request = RunRequest.model_validate({"some_vendor_selector": "sel_123"})
        assert request.pipe_code is None
        assert request.mthds_contents is None
        assert request.model_dump(exclude_none=True) == {"some_vendor_selector": "sel_123"}

    def test_start_run_request_serializes_only_set_fields(self) -> None:
        """Extension-alone serializes to a minimal body (exclude_none)."""
        request = RunRequest.model_validate({"some_vendor_selector": "sel_123"})
        assert request.model_dump(exclude_none=True) == {"some_vendor_selector": "sel_123"}

    def test_run_request_keeps_arbitrary_extension_args(self) -> None:
        """The request models are extension-open: unknown args are kept and serialized, never silently dropped."""
        request = RunRequest.model_validate({"pipe_code": "answer", "some_vendor_arg": {"nested": True}})
        dumped = request.model_dump(exclude_none=True)
        assert dumped == {"pipe_code": "answer", "some_vendor_arg": {"nested": True}}

    @pytest.mark.parametrize("multiplicity", [True, False, 3])
    def test_start_run_request_output_multiplicity(self, multiplicity: bool | int) -> None:
        """output_multiplicity accepts bool or int (VariableMultiplicity)."""
        request = RunRequest(pipe_code="answer", output_multiplicity=multiplicity)
        assert request.output_multiplicity == multiplicity

    def test_start_run_request_full_inline_bundle(self) -> None:
        """An ad-hoc inline bundle carries contents + output controls."""
        request = RunRequest(
            mthds_contents=["domain answer\npipe answer ..."],
            pipe_code="answer",
            inputs={"question": "why?"},
            output_name="result",
            dynamic_output_concept_ref="answer.Answer",
        )
        assert request.mthds_contents == ["domain answer\npipe answer ..."]
        assert request.inputs == {"question": "why?"}
        assert request.output_name == "result"
        assert request.dynamic_output_concept_ref == "answer.Answer"

    # ── RunPublic / RunRead ──────────────────────────────────────

    def test_run_public_runner_tier_without_identity(self) -> None:
        """Identity fields are optional so a runner-tier run (no org) still parses."""
        run = RunPublic(pipeline_run_id="run_1", status=RunStatus.RUNNING, created_at="2026-06-10T00:00:00Z")
        assert run.pipeline_run_id == "run_1"
        assert run.status == RunStatus.RUNNING
        assert run.model_extra == {}
        assert run.finished_at is None

    def test_run_public_keeps_server_specific_response_fields(self) -> None:
        """Server-specific response fields are preserved (extra=allow) and accessible, never named by the SDK."""
        run = RunPublic.model_validate(
            {
                "pipeline_run_id": "run_2",
                "pipe_code": "answer",
                "status": "COMPLETED",
                "created_at": "2026-06-10T00:00:00Z",
                "finished_at": "2026-06-10T00:00:10Z",
                "some_vendor_field": "vendor_value",
                "another_one": {"nested": True},
            }
        )
        assert run.status == RunStatus.COMPLETED
        assert run.model_extra == {"some_vendor_field": "vendor_value", "another_one": {"nested": True}}
        assert run.some_vendor_field == "vendor_value"  # type: ignore[attr-defined] # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType]

    def test_run_read_defaults(self) -> None:
        """RunRead defaults degraded=False and retry_after_seconds=None."""
        run = RunRead(pipeline_run_id="run_1", status=RunStatus.RUNNING, created_at="2026-06-10T00:00:00Z")
        assert run.degraded is False
        assert run.retry_after_seconds is None

    def test_run_read_degraded(self) -> None:
        """A degraded read carries the last-known status + a retry hint."""
        run = RunRead(
            pipeline_run_id="run_1",
            status=RunStatus.RUNNING,
            created_at="2026-06-10T00:00:00Z",
            degraded=True,
            retry_after_seconds=5,
        )
        assert run.degraded is True
        assert run.retry_after_seconds == 5

    # ── RunResults (opaque Any payloads) ─────────────────────────

    def test_run_result_main_stuff_list_stays_list(self) -> None:
        """A list output stays a top-level array — main_stuff is Any, not dict (avoid mthds-js bug)."""
        result = RunResults(pipeline_run_id="run_1", main_stuff=[{"color": "red"}, {"color": "blue"}])
        assert result.main_stuff == [{"color": "red"}, {"color": "blue"}]
        assert isinstance(result.main_stuff, list)

    def test_run_result_main_stuff_object_and_defaults(self) -> None:
        """A structured output is an object; both artifacts default to None when absent."""
        result = RunResults(pipeline_run_id="run_1", main_stuff={"answer": "42"})
        assert result.main_stuff == {"answer": "42"}
        assert result.model_extra == {}

    # ── RunResultState discriminated union ───────────────────────

    def test_run_result_state_running(self) -> None:
        """A `running` payload discriminates to RunResultRunning."""
        adapter: TypeAdapter[RunResultState] = TypeAdapter(RunResultState)
        state = adapter.validate_python({"state": "running", "pipeline_run_id": "run_1", "retry_after_seconds": 3})
        assert isinstance(state, RunResultRunning)
        assert state.retry_after_seconds == 3

    def test_run_result_state_completed(self) -> None:
        """A `completed` payload carries the RunResult artifacts."""
        adapter: TypeAdapter[RunResultState] = TypeAdapter(RunResultState)
        state = adapter.validate_python(
            {"state": "completed", "pipeline_run_id": "run_1", "result": {"pipeline_run_id": "run_1", "main_stuff": [1, 2]}}
        )
        assert isinstance(state, RunResultCompleted)
        assert state.result.main_stuff == [1, 2]

    def test_run_result_state_failed(self) -> None:
        """A `failed` payload carries the terminal status + message."""
        adapter: TypeAdapter[RunResultState] = TypeAdapter(RunResultState)
        state = adapter.validate_python({"state": "failed", "pipeline_run_id": "run_1", "status": "FAILED", "message": "boom"})
        assert isinstance(state, RunResultFailed)
        assert state.status == RunStatus.FAILED
        assert state.message == "boom"

    # ── PollInfo / WaitForResultOptions ──────────────────────────

    def test_wait_for_result_options_defaults(self) -> None:
        """Defaults match the polling contract (2s interval, 20min timeout, no callback)."""
        options = WaitForResultOptions()
        assert options.interval_seconds == 2.0
        assert options.timeout_seconds == 1200.0
        assert options.on_poll is None

    def test_wait_for_result_options_on_poll_callback(self) -> None:
        """on_poll holds a callable invoked with a PollInfo."""
        seen: list[PollInfo] = []

        def record(info: PollInfo) -> None:
            seen.append(info)

        options = WaitForResultOptions(interval_seconds=0.5, timeout_seconds=30.0, on_poll=record)
        assert options.on_poll is not None
        options.on_poll(PollInfo(attempt=1, elapsed_seconds=0.5))
        assert seen[0].attempt == 1
        assert seen[0].elapsed_seconds == 0.5

    def test_poll_info_is_frozen(self) -> None:
        """PollInfo is an immutable value object."""
        info = PollInfo(attempt=2, elapsed_seconds=4.0)
        with pytest.raises(FrozenInstanceError):
            info.attempt = 3  # type: ignore[misc]
