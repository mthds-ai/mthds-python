"""Unit tests for the run-source argument surface — the predicates every Python client shares."""

import pytest

from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.options import (
    RUN_ARG_BUNDLE_B64,
    RUN_ARG_FILES,
    RUN_ARG_METHOD_ID,
    RUN_ARG_METHOD_REF,
    assert_exclusive_run_sources,
    assert_method_ref_pairs_with_nothing,
    has_bundle_payload,
    normalized_selector,
    run_selector_extensions,
)

_ADDRESS = "github.com/Pipelex/methods/documents@v0.1.0"


class TestRunSourceOptions:
    """The run-source predicates and the selector normalization that goes with them."""

    # ── wire keys ────────────────────────────────────────────────

    def test_keys_match_the_wire(self) -> None:
        """The constants are the request's own property names — the runners read `extra` by them."""
        assert (RUN_ARG_FILES, RUN_ARG_BUNDLE_B64, RUN_ARG_METHOD_REF, RUN_ARG_METHOD_ID) == (
            "files",
            "bundle_b64",
            "method_ref",
            "method_id",
        )

    # ── normalized_selector ──────────────────────────────────────

    def test_absent_selector_is_none(self) -> None:
        """An absent selector normalizes to None."""
        assert normalized_selector(name=RUN_ARG_METHOD_REF, value=None) is None

    def test_empty_selector_is_none(self) -> None:
        """An empty selector selects nothing, so it normalizes to None rather than riding the wire."""
        assert normalized_selector(name=RUN_ARG_METHOD_REF, value="") is None

    def test_present_selector_passes_through(self) -> None:
        """A non-empty string is returned unchanged."""
        assert normalized_selector(name=RUN_ARG_METHOD_REF, value=_ADDRESS) == _ADDRESS

    @pytest.mark.parametrize("wrong_value", [123, ["mt_1"], 0, [], {}, True])
    def test_non_string_selector_is_refused(self, wrong_value: object) -> None:
        """A non-string is refused rather than dropped (falsy) or forwarded (truthy) — one answer
        for every wrong type.

        This DIVERGES from the JS lineage rather than matching it: `nonEmptyString` in
        `pipelex-sdk-js` never throws, so it drops most of these silently and forwards
        `["mt_1"]`, whose `length` happens to be non-zero. Refusing is the better behaviour;
        the two sides do not agree on it yet.
        """
        with pytest.raises(PipelineRequestError, match="must be a string, received"):
            normalized_selector(name=RUN_ARG_METHOD_REF, value=wrong_value)

    def test_selector_error_names_the_argument_and_the_type(self) -> None:
        """The message names the argument the caller passed and the type they passed for it."""
        with pytest.raises(PipelineRequestError, match=r"method_id must be a string, received int\."):
            normalized_selector(name=RUN_ARG_METHOD_ID, value=7)

    # ── run_selector_extensions ──────────────────────────────────

    def test_no_selector_contributes_nothing(self) -> None:
        """Neither selector present: the contribution is empty, so the caller's `extra` is untouched."""
        assert run_selector_extensions() == {}

    def test_both_selectors_ride_under_their_wire_keys(self) -> None:
        """Each selector reaches the mapping under its own wire key."""
        assert run_selector_extensions(method_ref=_ADDRESS, method_id="mt_abc") == {
            RUN_ARG_METHOD_REF: _ADDRESS,
            RUN_ARG_METHOD_ID: "mt_abc",
        }

    def test_empty_selectors_are_dropped(self) -> None:
        """An empty selector contributes nothing (presence is decided after normalization)."""
        assert run_selector_extensions(method_ref="", method_id="") == {}

    def test_extensions_refuse_a_non_string_selector(self) -> None:
        """The normalization is the same one `normalized_selector` applies."""
        with pytest.raises(PipelineRequestError, match="method_id must be a string"):
            run_selector_extensions(method_id=42)

    # ── has_bundle_payload ───────────────────────────────────────

    def test_no_bundle(self) -> None:
        """Neither encoding present: nothing to run from a bundle."""
        assert has_bundle_payload() is False

    def test_files_payload(self) -> None:
        """A non-empty file map carries a method."""
        assert has_bundle_payload(files={"main.mthds": 'domain = "answer"'}) is True

    def test_zip_payload(self) -> None:
        """A non-empty base64 zip carries a method."""
        assert has_bundle_payload(bundle_b64="UEsDBA==") is True

    def test_empty_encodings_carry_no_method(self) -> None:
        """Unlike exclusivity, this keys off a RUNNABLE payload: empty encodings carry nothing."""
        assert has_bundle_payload(files={}, bundle_b64="") is False

    # ── assert_exclusive_run_sources ─────────────────────────────

    def test_nothing_present_is_legal(self) -> None:
        """Exclusivity says nothing about an absent source — the precondition is a separate check."""
        assert_exclusive_run_sources()

    def test_contents_alone_is_legal(self) -> None:
        """Inline contents alone is the protocol's own run source."""
        assert_exclusive_run_sources(mthds_contents=['domain = "answer"'])

    def test_files_alone_is_legal(self) -> None:
        """One bundle encoding alone is legal."""
        assert_exclusive_run_sources(files={"main.mthds": 'domain = "answer"'})

    def test_two_encodings_are_refused(self) -> None:
        """`files` and `bundle_b64` are two encodings of one bundle."""
        with pytest.raises(PipelineRequestError, match="two encodings of the same bundle"):
            assert_exclusive_run_sources(files={"main.mthds": "x"}, bundle_b64="UEsDBA==")

    def test_two_encodings_key_off_presence_not_emptiness(self) -> None:
        """An empty `files` map beside a zip still expressed two encodings."""
        with pytest.raises(PipelineRequestError, match="two encodings of the same bundle"):
            assert_exclusive_run_sources(files={}, bundle_b64="UEsDBA==")

    def test_bundle_with_contents_is_refused(self) -> None:
        """A bundle carries its own `.mthds`, so it cannot be combined with inline contents."""
        with pytest.raises(PipelineRequestError, match="self-contained"):
            assert_exclusive_run_sources(mthds_contents=['domain = "answer"'], files={"main.mthds": "x"})

    def test_zip_with_contents_is_refused(self) -> None:
        """The same rule holds for the zip encoding."""
        with pytest.raises(PipelineRequestError, match="self-contained"):
            assert_exclusive_run_sources(mthds_contents=['domain = "answer"'], bundle_b64="UEsDBA==")

    def test_empty_contents_beside_a_bundle_is_legal(self) -> None:
        """An empty contents list is "no contents", so it does not collide with a bundle."""
        assert_exclusive_run_sources(mthds_contents=[], files={"main.mthds": "x"})

    def test_bundle_with_contents_keys_off_presence_not_emptiness(self) -> None:
        """An empty `files` map beside inline contents is still two run sources.

        This arm and `has_bundle_payload` deliberately read the same value differently: an empty
        encoding is PRESENT for exclusivity and RUNNABLE for neither. Pinning both sides of that
        disagreement is what stops a later refactor from routing exclusivity through
        `has_bundle_payload` and turning this refusal into an accepted request.
        """
        assert has_bundle_payload(files={}) is False
        with pytest.raises(PipelineRequestError, match="self-contained"):
            assert_exclusive_run_sources(mthds_contents=['domain = "answer"'], files={})

    # ── assert_method_ref_pairs_with_nothing ─────────────────────

    def test_absent_method_ref_checks_nothing(self) -> None:
        """With no address, every other combination is somebody else's rule."""
        assert_method_ref_pairs_with_nothing(mthds_contents=['domain = "answer"'], method_id="mt_abc")

    def test_empty_method_ref_checks_nothing(self) -> None:
        """An empty address selects nothing, so it is not an address run."""
        assert_method_ref_pairs_with_nothing(method_ref="", mthds_contents=['domain = "answer"'], method_id="mt_abc")

    def test_method_ref_alone_is_legal(self) -> None:
        """The address alone is a complete run source."""
        assert_method_ref_pairs_with_nothing(method_ref=_ADDRESS)

    def test_method_ref_with_contents_is_refused(self) -> None:
        """An address and inline contents are two run sources."""
        with pytest.raises(PipelineRequestError, match="inline mthds_contents are mutually exclusive"):
            assert_method_ref_pairs_with_nothing(method_ref=_ADDRESS, mthds_contents=['domain = "answer"'])

    def test_method_ref_with_files_is_refused(self) -> None:
        """An address and a bundle are two run sources — the arm the private SDK copy lacked."""
        with pytest.raises(PipelineRequestError, match=r"a method bundle \(bundle_b64 / files\) are mutually exclusive"):
            assert_method_ref_pairs_with_nothing(method_ref=_ADDRESS, files={"main.mthds": "x"})

    def test_method_ref_with_zip_is_refused(self) -> None:
        """The bundle arm keys off presence, so the zip encoding is refused too."""
        with pytest.raises(PipelineRequestError, match=r"a method bundle \(bundle_b64 / files\) are mutually exclusive"):
            assert_method_ref_pairs_with_nothing(method_ref=_ADDRESS, bundle_b64="UEsDBA==")

    def test_method_ref_with_method_id_is_refused(self) -> None:
        """An address run has its own provenance and takes no run-history linkage id."""
        with pytest.raises(PipelineRequestError, match="takes no run-history linkage id"):
            assert_method_ref_pairs_with_nothing(method_ref=_ADDRESS, method_id="mt_abc")

    def test_method_ref_with_empty_method_id_is_legal(self) -> None:
        """An empty id selects nothing, so it is not a second selector."""
        assert_method_ref_pairs_with_nothing(method_ref=_ADDRESS, method_id="")

    def test_empty_contents_beside_method_ref_is_legal(self) -> None:
        """An empty contents list is "no contents" — the presence semantics the server uses."""
        assert_method_ref_pairs_with_nothing(method_ref=_ADDRESS, mthds_contents=[])

    def test_non_string_method_ref_is_refused(self) -> None:
        """The address goes through the same boundary normalization as any selector."""
        with pytest.raises(PipelineRequestError, match="method_ref must be a string"):
            assert_method_ref_pairs_with_nothing(method_ref=["github.com/Pipelex/methods"])

    def test_non_string_method_id_is_refused_without_an_address(self) -> None:
        """The selector type refusal does not depend on an unrelated argument.

        `method_id` is normalized before the no-address early return, so one wrong value gets one
        answer whether or not a `method_ref` accompanies it — the unconditional guarantee
        `docs/runners.md` advertises for a selector at this boundary.
        """
        with pytest.raises(PipelineRequestError, match=r"method_id must be a string, received int\."):
            assert_method_ref_pairs_with_nothing(method_id=42)
