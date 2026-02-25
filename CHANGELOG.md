# Changelog

## [Unreleased]

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