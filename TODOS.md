# TODOS — harden the 200-diagnostic `/validate` contract

Follow-up fixes from the code review of the staged `200-diagnostic /validate` change (branch `feature/200-diagnostic-validate`, unreleased `v0.5.0`). This plan makes the discriminated union the single parse path, fixes the broken docs example, and replaces the bespoke `mthds_sources` param with the generic `extra` passthrough.

All changes are part of the **same unreleased `v0.5.0`** — amend the existing changelog entry, do **not** add a new version or bump `pyproject.toml`.

## Context for a cold start

The change under review reframes `POST /validate` as **200-diagnostic**: a produced verdict (valid or invalid) rides an HTTP 200 body discriminated on `is_valid`; non-2xx is reserved for "no verdict could be produced". The wire models are a pydantic discriminated union:

- Protocol-neutral base: `mthds/protocol/models.py` → `ValidationReport` (`is_valid: Literal[True]`), `ValidationDiagnostic`, `InvalidValidationReport[ValidationDiagnosticT]` (`is_valid: Literal[False]`), and the `ValidationResult` TypeAlias (`Annotated[..., Field(discriminator="is_valid")]`).
- Pipelex narrowing: `mthds/runners/api/models.py` → `PipelexValidationReport`, `PipelexInvalidReport`, `ValidationErrorItem`, `ValidationErrorCategory`, `DryRunStatus`, `ValidatedPipeEntry`, and the `PipelexValidationResult` TypeAlias.
- Consumers: `MthdsAPIClient.validate` (`mthds/runners/api/client.py`), `PipelexRunner.validate` (`mthds/runners/pipelex/runner.py`), the abstract `MTHDSProtocol.validate` (`mthds/protocol/protocol.py`), docs (`docs/runners.md`), and tests (`tests/unit/test_api_runner_protocol.py`, `tests/unit/test_validation_contract.py`).

### Decisions taken

- **`mthds_sources` → generic `extra` passthrough (user-chosen).** Drop the bespoke `mthds_sources` param from `MthdsAPIClient.validate`. Add `extra: dict[str, Any] | None = None` to `validate` on the interface and both runners, mirroring `execute`/`start`. Server extensions (e.g. `mthds_sources`) ride `extra` and merge into the request body as top-level properties. `extra` carrying a protocol arg (`mthds_contents`, `allow_signatures`) is rejected with `PipelineRequestError`, exactly like `execute`/`start`. The local `PipelexRunner.validate` **rejects** any `extra` (raises `PipelexRunnerError`) — same as `PipelexRunner.execute` (the CLI defines no extension args).
- **Parse through the discriminated union.** Replace the hand-rolled `if payload.get("is_valid") is False:` with one `TypeAdapter(PipelexValidationResult)` call, built once at module scope. This makes the declared return type honest, removes duplication, and **closes the silent-valid hole**: a 200 body missing/with-a-bad `is_valid` now raises loudly instead of being mistaken for valid.
- **Malformed 200 body raises `pydantic.ValidationError`.** Acceptable and desired (loud failure). It matches the pre-existing behavior (the old code already called `model_validate`, which can raise). Document it in the `validate` `Raises:` section; do **not** wrap it in a custom exception (out of scope, and a malformed 200 is a server bug worth surfacing raw).
- **Docs consumer pattern uses `if report.is_valid is True:`.** Verified to narrow under strict pyright; bare `if report.is_valid:` and `if not report.is_valid:` do **not** narrow.

### Verified facts (don't re-derive)

Established by running the repo's own `pyright==1.1.408` / `mypy==1.19.1` and live pydantic probes:

- The shipped source files already pass pyright and mypy with 0 errors; the new tests pass (16/16). These fixes must keep that green.
- `TypeAdapter(PipelexValidationResult).validate_python(...)` **builds and works** despite the covariant `ValidationDiagnosticT` TypeVar. It routes `{"is_valid": True, ...}` → `PipelexValidationReport`, `{"is_valid": False, ...}` → `PipelexInvalidReport`, and **raises `ValidationError` on `{}` / missing `is_valid` / `is_valid: null` / `is_valid: "false"`** ("Unable to extract tag"). This is strictly safer than the hand-rolled `is False` check, which silently treats a missing discriminant as valid.
- pyright narrowing of the `PipelexValidationReport | PipelexInvalidReport` union: `if report.is_valid is True:` narrows **both** branches correctly; bare `if report.is_valid:` and `if not report.is_valid:` leave the **full union** in both branches (→ `reportAttributeAccessIssue` on arm-specific fields). `isinstance(report, PipelexInvalidReport)` also narrows cleanly and yields `list[ValidationErrorItem]` (the covariant TypeVar does **not** degrade member types once narrowed — the reviewer's "Unknown member type" concern was an un-narrowed-union artifact, **refuted**, no fix needed).
- `pydantic_core.to_json(body)` emits **compact** JSON (no space after `:`/`,`), unlike `json.dumps` (which defaults to `": "`). Switching `validate` to `to_json` (for consistency with `execute`/`start`, and because `extra` may carry pydantic values) **requires updating the request-body string assertions** in `test_api_runner_protocol.py` to the compact form.
- `ValidationErrorCategory` / `DryRunStatus` already match the conformance source of truth `/Users/lchoquel/repos/Pipelex/conformance/conformance/validation_contract.py` exactly — no drift; leave them alone.

---

## Tier 1 — Make the discriminated union the single parse path (review #2 + #3)

- [ ] **Add a module-level adapter in `mthds/runners/api/models.py`.** After the `PipelexValidationResult` TypeAlias, add `PipelexValidationResultAdapter = TypeAdapter(PipelexValidationResult)` (import `TypeAdapter` from `pydantic`). Built once at import time (don't construct per-call — `TypeAdapter` is expensive). Annotate if pyright wants it; otherwise let it infer.
- [ ] **Rewrite `MthdsAPIClient.validate` parsing** (`mthds/runners/api/client.py`, currently ~L312-316). Replace the `response.raise_for_status(); payload = response.json(); if payload.get("is_valid") is False: ...` block with:
  ```python
  response.raise_for_status()
  return PipelexValidationResultAdapter.validate_python(response.json())
  ```
  Import `PipelexValidationResultAdapter`; drop now-unused `PipelexInvalidReport` / `PipelexValidationReport` imports (let `make fui` prune). Keep the return annotation `PipelexValidationResult`.
- [ ] **Update the `validate` docstring `Raises:`** to add: a malformed 200 body (missing/invalid `is_valid`, or missing required fields) raises `pydantic.ValidationError`; non-2xx still raises `httpx.HTTPStatusError`.
- [ ] **Route the contract test through the same adapter** (`tests/unit/test_validation_contract.py`). Change `_parse` to `return PipelexValidationResultAdapter.validate_python(body)` (import it). This makes the test pin the **real** union instead of a hand-rolled copy. Update `test_unknown_category_is_rejected` to validate via the adapter too (still expect `ValidationError` matching `made_up`).
- [ ] **Add a regression test** (in `tests/unit/test_validation_contract.py` or `test_api_runner_protocol.py`): a 200 body missing `is_valid` (e.g. `{}` or `{"message": "x"}`) now raises (no silent-valid). Optionally assert `is_valid: false` with a missing required `message`/`validation_errors` raises too.

## Tier 2 — Fix the broken docs example (review #1)

- [ ] **`docs/runners.md`** — change the validate example so it narrows under strict pyright. Use `if report.is_valid is True:` for the valid arm and `else:` for the invalid arm. Confirm the surrounding prose still matches. Target shape:
  ```python
  report = await client.validate([bundle_text])
  if report.is_valid is True:
      ...                                          # PipelexValidationReport — structural artifacts
  else:
      for item in report.validation_errors:        # PipelexInvalidReport — typed diagnostics
          print(item.category, item.message, item.source)
  ```
- [ ] **Verify** the snippet typechecks: drop it into a scratch `.py` importing `PipelexValidationResult`, run `uv run pyright scratch.py`, expect 0 errors. Delete the scratch file.

## Tier 3 — `mthds_sources` → generic `extra` passthrough (review #4, folds in #6 + #8)

- [ ] **Generalize the extension helper** (`mthds/runners/api/client.py`, module helpers ~L552-614). Make `_build_extensions` accept a keyword-only protected set: `def _build_extensions(extra, *, protocol_args=_PROTOCOL_REQUEST_ARGS)` and check overlap against `protocol_args`. Add `_VALIDATE_REQUEST_ARGS: frozenset[str] = frozenset({"mthds_contents", "allow_signatures"})`.
- [ ] **`MthdsAPIClient.validate`** — drop the `mthds_sources` param; add `extra: dict[str, Any] | None = None`. Build the body and merge extensions, then serialize with `to_json` (replaces `json.dumps(...).encode(...)`, review #6):
  ```python
  body: dict[str, Any] = {"mthds_contents": mthds_contents, "allow_signatures": allow_signatures}
  body.update(_build_extensions(extra, protocol_args=_VALIDATE_REQUEST_ARGS))
  content = to_json(body)
  ```
  Update the `Args:` docstring: replace `mthds_sources` with `extra` (mirror the `execute`/`start` wording — server-specific args merged as top-level body properties; protocol args rejected). Mention `mthds_sources` as an example server extension passed via `extra`.
- [ ] **`MTHDSProtocol.validate`** (`mthds/protocol/protocol.py`) — add `extra: dict[str, Any] | None = None` to the interface signature + docstring (mirror `execute`/`start`).
- [ ] **`PipelexRunner.validate`** (`mthds/runners/pipelex/runner.py`) — add `extra: dict[str, Any] | None = None`; reject it exactly like `PipelexRunner.execute`:
  ```python
  if extra:
      msg = f"The pipelex CLI runner defines no extension args; got {sorted(extra)}."
      raise PipelexRunnerError(msg)
  ```
  Docstring `Args:` → `extra: Rejected — the CLI runner defines no extension args.`
- [ ] **Update tests** (`tests/unit/test_api_runner_protocol.py`):
  - `test_validate_posts_contents_and_parses_valid_report` → switch body-string assertions to **compact** JSON (`'"mthds_contents":["domain = \\"answer\\""]'`, `'"allow_signatures":true'`); keep `"mthds_sources" not in sent`.
  - `test_validate_threads_mthds_sources` → call `client.validate([...], extra={"mthds_sources": ["answer.mthds"]})`; assert `'"mthds_sources":["answer.mthds"]' in sent` (compact).
  - `test_validate_no_verdict_response_raises_http_error` → drop the misleading mismatched `mthds_sources=[...]` arg (review #8); fix the docstring so it no longer implies a local length-mismatch check (there is none — mismatch detection is server-side).
  - **New** `test_validate_extra_rejects_protocol_arg` → `client.validate([...], extra={"mthds_contents": [...]})` raises `PipelineRequestError` (mirrors the `execute`/`start` guard).
- [ ] **CHANGELOG.md** — in the unreleased `v0.5.0` entry, reword the `mthds_sources` "Added" bullet to describe the generic `extra` passthrough on `validate()` (mirrors `execute`/`start`); note server extensions like `mthds_sources` ride it.
- [ ] **docs/runners.md** — update any `mthds_sources=[...]` usage in the validate prose/example to `extra={"mthds_sources": [...]}`.

## Considered — not changing (rationale recorded)

- **#5 `PipelexRunner.validate` returns `ValidationResult` but only ever yields the valid arm / raises.** Intentional, documented divergence (CLI exit-code semantics). Leave as-is; the docstring + changelog already call it out.
- **#7 `ValidationErrorItem` inherits `extra="allow"`.** Correct for a **wire-consumer** model: a newer server may add locator fields this client version doesn't know, and `extra="allow"` keeps it forward-compatible. The "builder typo" risk lives in the server-side builder (a different repo), not here. Do **not** switch to `extra="forbid"`.
- **#9 `message` requiredness asymmetry (optional on valid arm, required on invalid).** Minor. Leave `message: str = ""` on the valid arm — the server always sends it, and tightening risks rejecting a lean/non-pipelex valid body. Revisit only if a real consumer depends on it.
- **Covariant `ValidationDiagnosticT` → "Unknown member type" (reviewer #2).** Refuted — narrowed access yields clean `list[ValidationErrorItem]`. No change.

## Final verification

- [ ] `make fui && make cc` passes (ruff fix-unused-imports, format, lint, pyright + mypy — 0 errors).
- [ ] `python -m pytest tests/unit/test_validation_contract.py tests/unit/test_api_runner_protocol.py tests/unit/test_pipelex_runner.py -q` passes.
- [ ] `make agent-test` passes (silent on success).
- [ ] Re-confirm the `docs/runners.md` example typechecks (Tier 2 scratch-file check).
- [ ] Re-read the diff end-to-end; confirm no stray `mthds_sources` param or `json.dumps` remains in `validate`, and the changelog/docs read consistently.
