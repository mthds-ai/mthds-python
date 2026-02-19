# Changelog

## [v0.0.2] - 2026-02-19

- Fix StrEnum compatibility for Python 3.10: use `sys.version_info` guard instead of `try/except ImportError` in `_compat.py` so that mypy and pyright resolve the type correctly on all supported Python versions.

## [v0.0.1] - 2026-02-17

- Initial release: The Python interface for methods — base structures for structured outputs and the base runner for executing methods via API.