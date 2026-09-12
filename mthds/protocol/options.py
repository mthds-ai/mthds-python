"""The MTHDS Protocol's run-source argument surface — which combinations of the `execute` /
`start` arguments name something to run, and which are illegal.

The protocol has no request *model*: a runner takes the request's basic arguments as named
parameters and serializes the wire body directly, merging any server-specific extension args
(`extra`) into the body as top-level properties. The Python expression of that argument surface
is therefore not a class but this set of predicates over the arguments themselves — each taking
plain values, so a caller passes them from wherever its own signature keeps them (a named
parameter, or a key it pulled out of `extra`).

They travel with the request rather than with any one runner: which source combinations are
legal is an invariant of the request itself, so every Python client that builds one — the
`MthdsAPIClient` here, `PipelexAPIClient` in `pipelex-sdk` — enforces it from this single
definition instead of re-deriving it and drifting. This module is the Python twin of
`mthds-js/src/protocol/options.ts`, and the error wording mirrors the server's own validator so
a client-side rejection reads like the 422 it pre-empts.

Three layers of argument meet here, and each predicate's docstring says which layer it is about:

- **the protocol's own run source** — `pipe_code`, `mthds_contents`;
- **the pipelex-api extensions** that carry a whole method bundle (`files`, `bundle_b64`) or its
  published address (`method_ref`);
- **the hosted platform's** catalog id (`method_id`).

Only the first layer is a named parameter of `MTHDSProtocol.execute` / `start`; the other two
reach the wire through the generic `extra` passthrough, or as named parameters of a client that
types its own stack's arguments. Keeping all three here is deliberate — a rule split across the
packages that enforce it is a rule that drifts, which is the situation this module ends.

The `pipe-selector` campaign will change this surface (a `pipe_ref` beside `pipe_code`, and
which of the two may be combined with what). When it does, it changes it here.
"""

from collections.abc import Mapping, Sequence
from typing import Final

from mthds.protocol.exceptions import PipelineRequestError

RUN_ARG_FILES: Final[str] = "files"
"""Wire key of the pipelex-api `files` extension — a whole method bundle as a path-to-text map."""

RUN_ARG_BUNDLE_B64: Final[str] = "bundle_b64"
"""Wire key of the pipelex-api `bundle_b64` extension — the same bundle as a base64 zip."""

RUN_ARG_METHOD_REF: Final[str] = "method_ref"
"""Wire key of the pipelex-api `method_ref` extension — a published method's address."""

RUN_ARG_METHOD_ID: Final[str] = "method_id"
"""Wire key of the hosted platform's `method_id` run arg — a stored method's catalog id."""


def normalized_selector(*, name: str, value: object) -> str | None:
    """Normalize one method-selector argument at a client's boundary.

    A **non-string** value is refused rather than dropped or forwarded. A published client
    validates its request-option types at its own boundary, so that one wrong value gets one
    answer: a bare truthiness check would silently drop the falsy wrong types (`0`, `[]`) and
    forward the truthy ones (`123`, `["mt_1"]`) to a server `422` — a different partition of
    wrong values than the JS client makes for the same argument on the same wire. `value` is
    typed `object` rather than `str | None` deliberately — this helper *is* the runtime
    boundary, and the callers it guards against are the untyped ones a type checker never sees.

    An absent or **empty** value normalizes to `None`: an empty selector selects nothing, so it
    is not sent and does not satisfy a client's "something to run" precondition.

    Args:
        name: The argument's name, as it appears in the error message and on the wire.
        value: The caller-supplied value, of any type.

    Returns:
        The selector string, or None when it is absent or empty.

    Raises:
        PipelineRequestError: If the value is present and is not a string.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{name} must be a string, received {type(value).__name__}."
        raise PipelineRequestError(msg)
    return value or None


def run_selector_extensions(*, method_ref: object = None, method_id: object = None) -> dict[str, str]:
    """Normalize the method selectors a client names into the extension mapping they ride to the
    wire.

    The layering seam: `method_ref` (layer 2 — the Pipelex API's run source, resolved by the
    runner) and `method_id` (layer 3 — the hosted platform's run arg) are named parameters on
    the client that types its own stack's arguments, and each reaches the wire as a top-level
    body property through the protocol client's generic extension mechanism, which merges it
    without knowing what it means.

    Both go through `normalized_selector`, so a non-string is refused and an absent or empty
    value contributes nothing. Rejecting the caller's own reserved argument names inside `extra`
    is the calling client's business — it owns that list — and merging is left to the caller too,
    so this returns only what the selectors contribute.

    Args:
        method_ref: The published method's address, or None.
        method_id: The hosted catalog id, or None.

    Returns:
        The selector contribution to the extension mapping — empty when neither is present.

    Raises:
        PipelineRequestError: If a selector is present and is not a string.
    """
    extensions: dict[str, str] = {}
    selected_method_ref = normalized_selector(name=RUN_ARG_METHOD_REF, value=method_ref)
    if selected_method_ref is not None:
        extensions[RUN_ARG_METHOD_REF] = selected_method_ref
    selected_method_id = normalized_selector(name=RUN_ARG_METHOD_ID, value=method_id)
    if selected_method_id is not None:
        extensions[RUN_ARG_METHOD_ID] = selected_method_id
    return extensions


def has_bundle_payload(*, files: Mapping[str, str] | None = None, bundle_b64: str | None = None) -> bool:
    """Does the request carry a method bundle (the pipelex-api `files` / `bundle_b64` extension)?

    A bundle satisfies the "something to run" precondition on its own — it carries its own
    `.mthds`, so neither `pipe_code` nor `mthds_contents` is required alongside it. Unlike
    `assert_exclusive_run_sources`, this keys off a RUNNABLE payload: an empty map or string
    carries no method, so it does not satisfy the precondition (and must not be sent — the
    runner rejects a zero-file bundle).

    Args:
        files: The bundle as a path-to-text map, or None.
        bundle_b64: The bundle as a base64-encoded zip, or None.

    Returns:
        True when either encoding carries a method.
    """
    return bool(files) or bool(bundle_b64)


def assert_exclusive_run_sources(
    *,
    mthds_contents: Sequence[str] | None = None,
    files: Mapping[str, str] | None = None,
    bundle_b64: str | None = None,
) -> None:
    """Enforce the run-source exclusivity contract shared by every client: a method bundle is
    self-contained (`files` / `bundle_b64` carry their own `.mthds`), so it cannot be combined
    with `mthds_contents`, and `files` / `bundle_b64` are two encodings of one bundle.

    Exclusivity keys off PRESENCE, not emptiness — a caller who supplies `files={}` alongside
    `bundle_b64` still expressed two encodings — while `mthds_contents` counts only when
    non-empty (an empty list is "no contents"). The wording mirrors the server's validator.

    Args:
        mthds_contents: Inline MTHDS bundle contents, or None.
        files: The bundle as a path-to-text map, or None.
        bundle_b64: The bundle as a base64-encoded zip, or None.

    Raises:
        PipelineRequestError: If two run sources that exclude each other are both present.
    """
    has_files = files is not None
    has_zip = bundle_b64 is not None
    has_contents = bool(mthds_contents)
    if has_files and has_zip:
        msg = "files and bundle_b64 are two encodings of the same bundle and are mutually exclusive; provide one."
        raise PipelineRequestError(msg)
    if (has_files or has_zip) and has_contents:
        msg = "A method bundle (files/bundle_b64) is self-contained; it cannot be combined with mthds_contents."
        raise PipelineRequestError(msg)


def assert_method_ref_pairs_with_nothing(
    *,
    method_ref: object = None,
    mthds_contents: Sequence[str] | None = None,
    files: Mapping[str, str] | None = None,
    bundle_b64: str | None = None,
    method_id: object = None,
) -> None:
    """Enforce the run routes' `method_ref` exclusivity, mirroring the server's own 422s so an
    illegal pairing fails before anything hits the wire.

    A `method_ref` is a complete run source (the fetched package carries its `.mthds` and its
    entry pipe), so it pairs with NOTHING: not with inline `mthds_contents`, not with a bundle
    encoding, and not with the hosted `method_id` — an address run has its own provenance and
    needs no linkage id.

    The one documented run-route exception is deliberately NOT here: inline source + `method_id`
    stays legal (the inline source runs; the id demotes to run-history linkage). `pipe_code`
    beside a `method_ref` is legal too — it overrides the fetched manifest's `main_pipe`.
    Presence semantics match the server's: `mthds_contents` counts when non-empty, a bundle
    encoding counts when the key is present, a selector counts when non-empty.

    Args:
        method_ref: The published method's address, or None — when absent or empty, nothing is
            checked.
        mthds_contents: Inline MTHDS bundle contents, or None.
        files: The bundle as a path-to-text map, or None.
        bundle_b64: The bundle as a base64-encoded zip, or None.
        method_id: The hosted catalog id, or None.

    Raises:
        PipelineRequestError: If a `method_ref` is paired with any other run source, or if a
            selector is present and is not a string.
    """
    if normalized_selector(name=RUN_ARG_METHOD_REF, value=method_ref) is None:
        return
    if mthds_contents:
        msg = "method_ref and inline mthds_contents are mutually exclusive; send one or the other."
        raise PipelineRequestError(msg)
    if files is not None or bundle_b64 is not None:
        msg = "method_ref and a method bundle (bundle_b64 / files) are mutually exclusive; send one or the other."
        raise PipelineRequestError(msg)
    if normalized_selector(name=RUN_ARG_METHOD_ID, value=method_id) is not None:
        msg = (
            "method_ref and method_id are mutually exclusive: an address run carries its own provenance "
            "and takes no run-history linkage id. Send exactly one method selector."
        )
        raise PipelineRequestError(msg)
