# Changelog

## [v0.8.1] - 2026-07-06

### Changed

- **Dev tooling: upgraded pytest to `>=9.0.3` and adopted the pytest-9 config norm.** The dev dependency moves from `pytest>=8.0.0,<9.0.0` to `pytest>=9.0.3`, and the pytest settings switch from the legacy `[tool.pytest.ini_options]` table to the native `[tool.pytest]` table with `minversion = "9.0"`, matching the `pipelex` repo. No change to the shipped package.

## [v0.8.0] - 2026-07-06

### Fixed

- **Blocking `execute()` no longer rejects the hosted runner's enriched `/v1/execute` response.** The Dict wire models (`DictStuffAbstract`, `DictWorkingMemoryAbstract`, `DictPipeOutputAbstract`) were `extra="forbid"`, contradicting the protocol's extension-openness — parsing a hosted `pipelex-api` response (which dumps the full `PipeOutput`: per-stuff `stuff_code` / `stuff_name`, pipe-output `graph_spec` / `tokens_usages` / `working_memory_raw` / assembly errors) raised a pydantic `ValidationError` after the run had succeeded server-side. They are now `extra="allow"` like every other protocol response model; extension fields ride `model_extra`.

### Changed

- **Breaking: dropped Python 3.10 support — `requires-python` is now `>=3.11,<3.15`.** The 3.10 compatibility bridges are gone: `StrEnum` and `Self` are imported directly from the stdlib (`enum` / `typing`, the `mthds._compat` shim is removed), `tomllib` replaces the `tomli` fallback, and the `backports.strenum` / `tomli` conditional dependencies are dropped. Install on Python 3.11 or newer.
- **Breaking: `DictStuffAbstract.concept` is now `str | DictConcept`** — a stuff's `concept` arrives on the wire either as the reduced namespaced ref string (what this SDK's own serialization emits) or as the full concept object the hosted runner dumps, now modeled by the new extension-open `DictConcept` (`code` + `domain_code` typed, the rest in `model_extra`). Use the new `DictStuffAbstract.concept_ref` property to get the ref string regardless of wire form.

## [v0.7.1] - 2026-07-02

### Fixed

- **`MthdsAPIClient(request_timeout_seconds=0.0)` is now honored** as the per-request ceiling instead of silently falling back to the default. The resolution tests presence (`is not None`).

## [v0.7.0] - 2026-07-02

`mthds` is now positioned as the client for the open-source `pipelex-api` runner rather than the hosted MTHDS API: it defaults to a local runner, and `MthdsAPIClient` construction speaks the runner's vocabulary.

### Breaking Changes

- **Default `MTHDS_BASE_URL` is now `http://localhost:8081`** (a local `pipelex-api` runner, using `pipelex-api`'s default port), was `https://api.pipelex.com`. The hosted API is no longer the default target — point `MTHDS_BASE_URL` at any MTHDS-Protocol server to use another. A caller that relied on the implicit hosted default must now set `MTHDS_BASE_URL` explicitly.
- **`MthdsAPIClient.__init__` renamed its arguments** — `api_token` → `api_key` and `api_base_url` → `base_url` — to match the `MTHDS_API_KEY` / `MTHDS_BASE_URL` config keys. Update keyword call sites.
- **Renamed the config surface `mthds.config.credentials` → `mthds.config`.** The credential-flavored names become config-flavored: `load_credentials` → `load_config`, `get_credential_value` → `get_config_value`, `set_credential_value` → `set_config_value`, `list_credentials` → `list_config`, `CredentialSource` → `ConfigSource`, `CredentialEntry` → `ConfigEntry`. Update imports and call sites (`from mthds.config import load_config`).
- **Renamed the `api_url` internal key and `api-url` CLI flag to `base_url` / `base-url`, and the shared env/file key `MTHDS_API_URL` to `MTHDS_BASE_URL`.** All three naming layers now align (`base_url` internal, `base-url` CLI flag, `MTHDS_BASE_URL` env/file). The wire-key rename is coordinated with the `mthds` npm CLI, which makes the same change. Migration: an `MTHDS_API_URL=…` line in an existing `~/.mthds/config` is now an unknown key — ignored on read, preserved on write — so re-set it with `mthds config set base-url <url>` (or rename the key in the file), and update any `MTHDS_API_URL` environment variables.
- **Removed telemetry handling from the Python client.** `is_telemetry_enabled()` and the `telemetry` / `DISABLE_TELEMETRY` key are gone — telemetry lives only in the `mthds` npm client. A `DISABLE_TELEMETRY` line written into the shared config file by that client is harmlessly ignored on the Python side.

### Added

- **`MthdsAPIClient(request_timeout_seconds=…)`** — the per-request timeout is now an overridable constructor argument (default `1200.0`, the runner blocking-execute ceiling).
- **Shared config-dialect conformance fixture.** The `~/.mthds/config` dotenv dialect is now pinned by a spec (workspace `docs/specs/mthds-config-file.md`) and a shared case fixture whose canonical copy lives in the `conformance` repo; this package vendors a byte-identical copy (`tests/fixtures/config_dialect_cases.json`, drift-gated by conformance) and runs every case in its own unit suite (`tests/unit/test_config_dialect.py`), so the Python and TypeScript parsers cannot silently diverge.

### Changed

- **Config-file parsing splits lines on `\n` only**, per the config-file spec. Previously `splitlines()` also treated a lone `\r` (and other Unicode line boundaries) as line separators, diverging from the `mthds` npm client; a lone `\r` now stays inside the surrounding value. Files using `\n` or `\r\n` line endings parse exactly as before.

## [v0.6.1] - 2026-06-30

### Fixed

- **`guard-branches.yml`: the `protect-workflows` job no longer silently passes.** Under `pull_request_target` the `actions/checkout` default is the BASE branch, so `git diff FETCH_HEAD HEAD` was comparing base-against-base and never saw a fork's workflow edits. The checkout now pins `ref: github.event.pull_request.head.sha` (safe here — the job only fetches/diffs/greps, it never executes the untrusted tree).
- **`guard-branches.yml`: the `protect-workflows` association gate now blocks all external authors.** The previous `author_association == 'CONTRIBUTOR'` check skipped `FIRST_TIME_CONTRIBUTOR` / `FIRST_TIMER` / `NONE`, letting first-time external authors modify workflow files unguarded. Inverted to a maintainer allow-list (`OWNER` / `MEMBER` / `COLLABORATOR`).
- **`tests-check.yml`: dropped `id-token: write` from the `matrix-test` job.** The job runs untrusted PR code but no step uses OIDC, so the unused permission only created a path to mint a repo OIDC token. Reduced to `contents: read` (least privilege).

## [v0.6.0] - 2026-06-30

`mthds` becomes **protocol-only and brand-neutral**: it now mirrors the MTHDS Protocol's five routes and nothing more, and its `/validate` surface carries only the standard's neutral verdict shapes. Two hosted-API / Pipelex-branded extensions move out of `mthds` into `pipelex-sdk` (`PipelexAPIClient`), which builds on this base — the durable run lifecycle (polling a started run to completion by id) and the Pipelex narrowing of the validation verdict union. This completes the MTHDS-vs-Pipelex brand boundary on these surfaces and mirrors the `mthds-js` / `@pipelex/sdk` split on the TypeScript side.

### Breaking Changes

- **Removed the durable run lifecycle from `MthdsAPIClient`.** The `get_run_status`, `get_run_result`, `wait_for_result`, and `start_and_wait` methods are gone. They live in `pipelex-sdk`'s `PipelexAPIClient` now (which adds a bare-runner blocking-execute fallback on top). `execute`, `start`, `validate`, `models`, and `version` — the protocol routes — are unchanged.
- **Removed the run-lifecycle models module `mthds.runners.api.runs`.** `RunStatus`, `RunPublic`, `RunRead`, `RunResults`, the `RunResultRunning` / `RunResultCompleted` / `RunResultFailed` discriminated union (`RunResultState`), `PollInfo`, and `WaitForResultOptions` are no longer part of this package; they live in `pipelex-sdk` (`pipelex_sdk.runs`).
- **Removed the lifecycle errors from `mthds.runners.api.exceptions`.** `RunFailedError`, `RunTimeoutError`, and `RunLifecycleUnavailableError` are gone (they now live in `pipelex-sdk`). `ClientAuthenticationError` and `RunStillRunningError` — the latter being the protocol's optional 202-degrade signal raised by `execute` — remain.
- **Removed the Pipelex validation narrowing from `mthds.runners.api.models`.** `PipelexValidationReport`, `PipelexInvalidReport`, `PipelexValidationResult`, `PipelexValidationResultAdapter`, `ValidationErrorItem`, `ValidationErrorCategory`, `ValidatedPipeEntry`, and `DryRunStatus` are gone from this package; they are Pipelex-branded implementation envelopes and now live in `pipelex-sdk` (`pipelex_sdk.validation_models`). The neutral protocol bases they narrowed — `ValidationReport`, `InvalidValidationReport`, `ValidationResult`, `ValidationDiagnostic` (in `mthds.protocol.models`) — are unchanged.
- **`MthdsAPIClient.validate()` now returns the protocol-neutral `ValidationResult`** (`ValidationReport | InvalidValidationReport`), not the Pipelex narrowing. Implementation-specific artifacts (structural blueprints, `rendered_markdown`, etc.) ride `model_extra`; a consumer that wants them typed uses `pipelex-sdk`'s `PipelexAPIClient`, whose `validate()` narrows the same 200 body to `PipelexValidationReport` / `PipelexInvalidReport`.

### Added

- **`MthdsAPIClient._post_validate(...)`** — a protected transport seam (alongside `_send` / `_url` / `_build_run_body`) that builds + sends the `/validate` request and returns the raw 200-diagnostic response, leaving the verdict-union parse to the caller. The `pipelex-sdk` subclass reuses it to parse the same body into its Pipelex-branded narrowing without re-implementing the wire call.

### Unchanged

- The `Dict*` wire models (`DictStuffAbstract`, `DictWorkingMemoryAbstract`, `DictPipeOutputAbstract`, `DictRunResultExecute`, `MAIN_STUFF_NAME`) stay in `mthds.runners.api.models`. They are brand-neutral and a shared wire contract — the in-process `PipelexRunner`, the API client, and the `pipelex` runtime all build on them.

## [v0.5.0] - 2026-06-18

The 200-diagnostic `/validate` contract: a produced verdict — valid or invalid — rides a 200 body discriminated on `is_valid`; non-2xx is reserved for "no verdict could be produced". Brings `mthds-python` in line with the MTHDS Protocol (`mthds-protocol.openapi.yaml`) and its `mthds-js` twin.

### Breaking Changes

- **`ValidationReport` is now the VALID arm of a discriminated union.** It carries the `is_valid: Literal[True]` discriminant; an invalid bundle is the sibling `InvalidValidationReport` (`is_valid: false`, with `validation_errors[]`) returned at **200**, not a 422 RFC 7807 problem. `POST /validate` is 200-diagnostic.
- **`MthdsAPIClient.validate()` returns `PipelexValidationResult` and no longer raises on an invalid bundle.** It reads the verdict from the 200 body discriminant; `httpx.HTTPStatusError` now surfaces only for no-verdict responses (request-shape 422, 401/403, 5xx). Previously an invalid bundle (then a 422) raised — under the new server contract that 422 became a 200, which the old `raise_for_status()`-then-parse path would have silently mistaken for valid.
- **`MTHDSProtocol.validate()` and `PipelexRunner.validate()` return `ValidationResult`.** The local CLI runner keeps surfacing an invalid bundle as a raised `PipelexRunnerError` (the CLI's exit code) — a documented divergence from the wire's 200 invalid arm.

### Added

- Protocol wire models: `ValidationDiagnostic` (neutral `category` + `message` base — named to stay distinct from `pydantic.ValidationError`), generic `InvalidValidationReport`, and the `ValidationResult` discriminated union.
- Pipelex narrowing (`mthds.runners.api.models`): `ValidationErrorItem`, `ValidationErrorCategory` (closed set incl. `dry_run`), `ValidatedPipeEntry`, `DryRunStatus`, `PipelexValidationReport`, `PipelexInvalidReport`, `PipelexValidationResult`.
- Generic `extra` passthrough on `validate()` (mirrors `execute`/`start`) — server-specific extension args merge into the request body as top-level properties; protocol args (`mthds_contents`, `allow_signatures`) inside `extra` are rejected client-side with `PipelineRequestError`. Server extensions like `mthds_sources` (per-content source names threaded onto each diagnostic's `source`) ride it. The local `PipelexRunner.validate()` rejects any `extra` (the CLI runner defines no extension args).
- Typed `rendered_markdown: str | None` on both `PipelexValidationReport` and `PipelexInvalidReport` — the opt-in Pipelex-API presentation extra (the server-rendered Markdown view of the verdict, present only when the request asked for it via `render: ["markdown"]`) is now a first-class field on both verdict arms instead of riding `model_extra`. SDK peer of the `mthds-js` parity change.

### Changed

- The validate consumer reads the body discriminant instead of `raise_for_status`-on-invalid; the abstract interface, the local runner, and the docs are aligned to the contract.

## [v0.4.1] - 2026-06-11

### Fixed

- Fixed protocol version (0.1.0 -> 0.6.0)

## [v0.4.0] - 2026-06-11

The MTHDS Protocol release: `mthds-python` is reorganized around the [MTHDS Protocol](https://mthds.ai) standard — one `/v1` HTTP surface, a slim `mthds.protocol` package, and per-runner implementations under `mthds.runners`.

### Breaking Changes

- **`RunnerProtocol` → `MTHDSProtocol`.** The runner abstraction now mirrors the protocol's five routes: `execute` (was `execute_pipeline`), `start` (was `start_pipeline`), plus the new `validate`, `models`, `version`. `execute`/`start` carry the protocol's basic args only — `pipe_code`, `mthds_contents`, `inputs`, `output_name`, `output_multiplicity`, `dynamic_output_concept_ref` — plus a generic `extra` mapping for server-specific extension args (protocol args inside `extra` are rejected client-side).
- **Package restructure — `mthds.client` is gone.** The protocol lives in `mthds.protocol`: `protocol.py` (`MTHDSProtocol`), `models.py` (the wire models), `exceptions.py` (`PipelineRequestError`), and the domain shapes `concept` / `stuff` / `working_memory` / `pipe_output` / `pipeline_inputs`. Implementations live in `mthds.runners`: `api.client` (`MthdsAPIClient`), `api.models` (Dict wire models + `DictRunResult`), `api.runs` (hosted polling), `api.exceptions`, and `pipelex.runner` (`PipelexRunner`). The `mthds.models` package, the `create_runner` factory (`registry.py`), and `ApiRunner` are removed — construct the runner you need directly. Layering is strict: `mthds.protocol` depends on nothing under `mthds.runners`.
- **Single `/v1` base path.** `MthdsAPIClient` composes every endpoint as `{MTHDS_API_URL}/v1/{endpoint}`; the old `runner/v1` / `platform/v1` prefixes are gone. Requires the hosted MTHDS API after the `/v1` cutover, or a `pipelex-api` image that mounts at `/v1`.
- **No request model.** There is no `RunRequest` class; the runner assembles the request body from the basic args + the `extra` passthrough and serializes it with `pydantic_core.to_json` (which handles pydantic `inputs`). A server that wants a typed request model (e.g. pipelex-api) defines its own.
- **Two run responses, one per route.** `execute` answers with `RunResultExecute{pipeline_run_id, pipe_output}` (both required — a completed run always has output); `start` answers with `RunResultStart{pipeline_run_id}` (just the authoritative id; the output is delivered later, out of band). Both are extension-open (`extra="allow"`): run states, timestamps, output naming, workflow ids ride `model_extra`, never named by the SDK. There is no `StartAck` / `RunState`, and the request side carries no `pipeline_run_id` (a client-supplied run id is an extension arg via `extra`).
- **Discovery/validation response models slimmed, extension-open.** `VersionInfo` = `{protocol_version, runner_version?}` (runner_version optional); `ValidationReport` declares no body fields (the 200 IS the verdict); `ModelDeck` = `models[{name, type}]`. Everything else a server returns rides `model_extra` — the response-side mirror of the request-side `extra`.
- **Config unified to `~/.mthds/config`.** The client reads/writes the same dotenv file and `MTHDS_*` keys as the `mthds` CLI (mthds-js). Legacy support is dropped: `~/.mthds/credentials`, `config.json`, `.env.local`, and the `PIPELEX_API_URL` / `PIPELEX_API_KEY` read aliases.

### Added

- `validate(mthds_contents, allow_signatures)` → `ValidationReport`; `models(category)` → `ModelDeck`; `version()` → `VersionInfo` — on both `MthdsAPIClient` and `PipelexRunner` (the local CLI runner implements `validate` + `version`; `models` / `start` raise `NotImplementedError`).
- The hosted run-lifecycle extension on `MthdsAPIClient`: `start` (202), `get_run_status`, `get_run_result`, `wait_for_result`, and `start_and_wait(...)` — the whole async lifecycle in one call. Bare runners (no run store) raise `RunLifecycleUnavailableError`.
- Typed errors `RunStillRunningError` (a `202` degrade on `execute`) and `RunLifecycleUnavailableError`.

### Docs

- Library-first README — `mthds-python` has no CLI (the `mthds` CLI ships as the npm package); `CLI.md` removed. Protocol + runners reference in `docs/runners.md`.

## [v0.3.0] - 2026-04-29

### Breaking Changes

- **`dynamic_output_concept_code` → `dynamic_output_concept_ref`** — Renamed across `RunnerProtocol`, `MthdsAPIClient`, `ApiRunner`, `PipelexRunner`, and `PipelineRequest`. The HTTP request body key consumed by `PipelineRequest.from_body()` is also renamed; API callers must update their payloads accordingly. Aligns the parameter name with pipelex core, where this value is a concept ref (e.g. `document_qa.ReferenceCount`), not a bare code.

## [v0.2.0] - 2026-03-19

### Breaking Changes

- **`mthds_content` → `mthds_contents`** — All runner protocol methods (`execute_pipeline`, `start_pipeline`) and `PipelineRequest` now use `mthds_contents: list[str] | None` instead of `mthds_content: str | None`. This applies to `RunnerProtocol`, `MthdsAPIClient`, `ApiRunner`, and `PipelexRunner`. Callers passing a single bundle content string should wrap it in a list: `mthds_contents=[content]`.
- **`PipelineRequest.from_body()` legacy compat** — `from_body()` still accepts `mthds_content` (singular) in request bodies for backward compatibility, wrapping it into a single-element list.

## [v0.1.1] - 2026-03-12

### Changed

- **Cross-package reference validation deferred to runtime** — `PackageVisibilityChecker.validate_cross_package_references()` is now a no-op. Cross-package refs (the `->` syntax) are resolved at runtime by the consuming runtime (e.g., Pipelex's address-based dependency loading), which has visibility into installed method packages. The base `mthds` layer only sees manifest and bundle metadata and cannot determine whether a referenced package is installed.

## [v0.1.0] - 2026-03-02

### Breaking Changes

- **Method names: strict snake_case** — `METHOD_NAME_PATTERN` now enforces snake_case only (pattern `[a-z][a-z0-9_]{1,24}`). Hyphens are no longer allowed — names like `my-method` must become `my_method`.

## [v0.0.7] - 2026-03-01

### Added

- Added `clone_default_branch()` to `mthds/package/vcs_resolver.py` — shallow-clones a git repository's default branch (`git clone --depth 1`), alongside the existing `clone_at_version()`. Same error handling pattern (catches `FileNotFoundError`, `CalledProcessError`, `TimeoutExpired` → raises `VCSFetchError`).
- **`main_pipe` must be in exports** — added `validate_main_pipe_in_exports` model validator to `MethodsManifest`. When `main_pipe` is set, it must appear in at least one domain's exported pipes, otherwise a `ManifestValidationError` is raised.

### Changed

- **Moved models from `mthds.client.models` to `mthds.models`** — `concept`, `pipe_output`, `pipeline_inputs`, `stuff`, and `working_memory` modules relocated to a top-level `mthds/models/` package. All internal imports (`client`, `pipeline`, `protocol`, `runners`) updated accordingly. The old `mthds/client/models/` directory has been removed.

## [v0.0.6] - 2026-02-25

### Breaking Changes

- **`[dependencies]` removed from METHODS.toml** — the `dependencies` field has been removed from `MethodsManifest`. A `[dependencies]` section in METHODS.toml now raises a `ManifestValidationError`. The `PackageDependency` class has been moved internally to `dependency_resolver.py` for backward compatibility with the resolver and lock file modules.

### Added

- **`name` field on `MethodsManifest`** — optional method identifier (2-25 lowercase chars, regex `^[a-z][a-z0-9_-]{1,24}$`).
- **`main_pipe` field on `MethodsManifest`** — optional default pipe code to execute (must be valid snake_case pipe code).
- **Method discovery module (`installed_methods.py`)** — `discover_installed_methods()` scans `~/.mthds/methods/` (global) and `./.mthds/methods/` (project-local) for installed methods with METHODS.toml manifests. Includes `find_method_by_name()` and `find_method_by_exported_pipe()` lookup functions.
- **New exceptions** — `MethodNotFoundError`, `DuplicateMethodNameError`, `AmbiguousPipeCodeError`, `PipeCodeNotFoundError` for method discovery error handling.

## [v0.0.5] - 2026-02-24

- bump to redeploy

## [v0.0.4] - 2026-02-24

- pytest and vscode settings
- removed CLI

## [v0.0.3] - 2026-02-23

### Changed

- Move all METHODS.toml validation logic into the `MthdsPackageManifest` Pydantic model via a `model_validator(mode="before")`, so the model can be constructed directly from a raw TOML dict (`MthdsPackageManifest.model_validate(raw)`). Simplify `manifest_parser.py` from ~155 lines of manual validation to a thin TOML-parse + `model_validate` wrapper.

### Added

- Add `bundle_scanner` module (`mthds/packages/bundle_scanner.py`) with `scan_bundles_for_domain_info()` and `build_domain_exports_from_scan()` for scanning `.mthds` files and building `DomainExports` from scan results.
- Add `bundle_metadata` module (`mthds/packages/bundle_metadata.py`) with minimal `BundleMetadata` model for visibility checking.
- Add `visibility` module (`mthds/packages/visibility.py`) with `PackageVisibilityChecker` enforcing MTHDS visibility rules: pipes default to private, only exported or `main_pipe` pipes are public across domains, and cross-package references must use declared dependency aliases.
- Add full unit test suite for METHODS.toml parsing and validation (`tests/test_manifest.py`, 62 tests).
- Add pytest configuration in `pyproject.toml` and Makefile targets: `test`, `test-with-prints`, `t`, `tp`, `gha-tests`, `agent-test`.

## [v0.0.2] - 2026-02-19

- Fix StrEnum compatibility for Python 3.10: use `sys.version_info` guard instead of `try/except ImportError` in `_compat.py` so that mypy and pyright resolve the type correctly on all supported Python versions.

## [v0.0.1] - 2026-02-17

- Initial release: The Python interface for methods — base structures for structured outputs and the base runner for executing methods via API.
