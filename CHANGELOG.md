# Changelog

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