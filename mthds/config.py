"""Unified credentials management for the MTHDS client.

Reads and writes ``~/.mthds/config`` using a dotenv-style format — the SAME
file, format, and key names the ``mthds`` CLI (mthds-js) uses, so a single
``mthds config set …`` configures both the TypeScript and Python clients.
Only the canonical ``MTHDS_*`` keys are recognized; there is no legacy
fallback and no migration.
(``KEY=VALUE``, ``#`` comments, blank lines allowed).

Resolution order: environment variables > config file > defaults.
"""

from __future__ import annotations

import os
from enum import unique
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from mthds._compat import StrEnum

if TYPE_CHECKING:
    from collections.abc import Mapping

# ── Types ───────────────────────────────────────────────────────────


@unique
class CredentialSource(StrEnum):
    ENV = "env"
    FILE = "file"
    DEFAULT = "default"


class CredentialEntry(NamedTuple):
    key: str
    cli_key: str
    value: str
    source: CredentialSource


# ── Paths ───────────────────────────────────────────────────────────

CONFIG_DIR = Path.home() / ".mthds"
# Canonical file, shared with the mthds CLI (mthds-js reads/writes the same path).
CONFIG_PATH = CONFIG_DIR / "config"

# ── Credential keys ────────────────────────────────────────────────

# Map from internal key to the canonical credential key (env var name and file key share the same names).
# The package is vendor-neutral ``mthds``, so the public keys use the ``MTHDS_`` prefix.
_CREDENTIAL_KEYS: dict[str, str] = {
    "api_url": "MTHDS_API_URL",
    "api_key": "MTHDS_API_KEY",
    "runner": "MTHDS_RUNNER",
    "telemetry": "DISABLE_TELEMETRY",
}

# Defaults
_DEFAULTS: dict[str, str] = {
    "runner": "api",
    # This client targets the open-source pipelex-api runner; default to a local instance
    # (pipelex-api's default port). Point MTHDS_API_URL at any MTHDS-Protocol server to override.
    "api_url": "http://localhost:8081",
    "api_key": "",
    "telemetry": "0",  # DISABLE_TELEMETRY=0 means enabled
}

# Map from CLI flag names (kebab-case) to internal keys
_KEY_ALIASES: dict[str, str] = {
    "runner": "runner",
    "api-url": "api_url",
    "api-key": "api_key",
    "telemetry": "telemetry",
}

VALID_KEYS: list[str] = list(_KEY_ALIASES.keys())


def resolve_key(cli_key: str) -> str | None:
    """Resolve a CLI flag name to an internal credential key."""
    return _KEY_ALIASES.get(cli_key)


def _lookup_in_store(internal_key: str, store: Mapping[str, str]) -> str | None:
    """Look up the value for an internal key in a storage mapping (file entries or environ).

    Args:
        internal_key: The internal credential key (e.g. "api_url").
        store: A mapping keyed by storage/env names (e.g. parsed config file or os.environ).

    Returns:
        The value for the canonical ``MTHDS_`` key, or None when it is absent.
    """
    return store.get(_CREDENTIAL_KEYS[internal_key])


# ── Dotenv parser / serializer ─────────────────────────────────────


def _parse_dotenv(content: str) -> dict[str, str]:
    """Parse a dotenv-style string into a dict."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        eq_index = trimmed.find("=")
        if eq_index == -1:
            continue
        key = trimmed[:eq_index].strip()
        value = trimmed[eq_index + 1 :].strip()
        result[key] = value
    return result


def _serialize_dotenv(entries: dict[str, str]) -> str:
    """Serialize a dict into dotenv format."""
    lines: list[str] = []
    for key, value in entries.items():
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


# ── File I/O ───────────────────────────────────────────────────────


def _read_credentials_file() -> dict[str, str]:
    """Read the config file."""
    if not CONFIG_PATH.is_file():
        return {}
    try:
        return _parse_dotenv(CONFIG_PATH.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _write_credentials_file(entries: dict[str, str]) -> None:
    """Write the config file with restricted permissions (owner-only)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(_serialize_dotenv(entries), encoding="utf-8")
    CONFIG_PATH.chmod(0o600)


# ── Public API ─────────────────────────────────────────────────────


def load_credentials() -> dict[str, str]:
    """Load all credentials with resolution: env > file > defaults.

    Returns:
        A dict with keys: runner, api_url, api_key, telemetry.
        The telemetry value is the raw DISABLE_TELEMETRY value ("0" or "1").
    """
    file_entries = _read_credentials_file()
    merged = dict(_DEFAULTS)

    # Apply file values
    for internal_key in _CREDENTIAL_KEYS:
        file_val = _lookup_in_store(internal_key, file_entries)
        if file_val is not None:
            merged[internal_key] = file_val

    # Env vars take precedence over file and defaults
    for internal_key in _CREDENTIAL_KEYS:
        env_val = _lookup_in_store(internal_key, os.environ)
        if env_val is not None:
            merged[internal_key] = env_val

    return merged


def _cli_key_for(internal_key: str) -> str:
    """Reverse-lookup the CLI flag name for an internal key."""
    for cli_k, int_k in _KEY_ALIASES.items():
        if int_k == internal_key:
            return cli_k
    msg = f"No CLI key alias found for internal key '{internal_key}'"
    raise KeyError(msg)


def get_credential_value(key: str) -> CredentialEntry:
    """Get a single credential value with its source.

    Args:
        key: Internal key (e.g. "runner", "api_url").

    Returns:
        A CredentialEntry with the value and its source.
    """
    cli_key = _cli_key_for(key)

    env_val = _lookup_in_store(key, os.environ)
    if env_val is not None:
        return CredentialEntry(key=key, cli_key=cli_key, value=env_val, source=CredentialSource.ENV)

    file_entries = _read_credentials_file()
    file_val = _lookup_in_store(key, file_entries)
    if file_val is not None:
        return CredentialEntry(key=key, cli_key=cli_key, value=file_val, source=CredentialSource.FILE)

    return CredentialEntry(key=key, cli_key=cli_key, value=_DEFAULTS[key], source=CredentialSource.DEFAULT)


def set_credential_value(key: str, value: str) -> None:
    """Set a credential value in the config file.

    Args:
        key: Internal key (e.g. "runner", "api_url").
        value: The value to set.
    """
    file_entries = _read_credentials_file()
    file_entries[_CREDENTIAL_KEYS[key]] = value
    _write_credentials_file(file_entries)


def list_credentials() -> list[CredentialEntry]:
    """List all credential values with their sources."""
    result: list[CredentialEntry] = []
    for cli_key, internal_key in _KEY_ALIASES.items():
        entry = get_credential_value(internal_key)
        result.append(CredentialEntry(key=internal_key, cli_key=cli_key, value=entry.value, source=entry.source))
    return result


def is_telemetry_enabled() -> bool:
    """Check if telemetry is enabled (DISABLE_TELEMETRY != "1")."""
    creds = load_credentials()
    return creds["telemetry"] != "1"
