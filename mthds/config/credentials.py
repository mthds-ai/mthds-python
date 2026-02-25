"""Unified credentials management for the MTHDS CLI.

Reads and writes ``~/.mthds/credentials`` using a dotenv-style format
(``KEY=VALUE``, ``#`` comments, blank lines allowed).

Resolution order: environment variables > credentials file > defaults.
"""

from __future__ import annotations

import json
import os
from enum import unique
from pathlib import Path
from typing import NamedTuple

from mthds._compat import StrEnum

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
CREDENTIALS_PATH = CONFIG_DIR / "credentials"

# Legacy paths (for auto-migration from JS config)
_LEGACY_CONFIG_PATH = CONFIG_DIR / "config.json"
_LEGACY_ENV_LOCAL_PATH = CONFIG_DIR / ".env.local"

# ── Credential keys ────────────────────────────────────────────────

# Map from internal key to credential key (env var name and file key share the same names)
_CREDENTIAL_KEYS: dict[str, str] = {
    "api_url": "PIPELEX_API_URL",
    "api_key": "PIPELEX_API_KEY",
    "runner": "MTHDS_RUNNER",
    "telemetry": "DISABLE_TELEMETRY",
}

# Defaults
_DEFAULTS: dict[str, str] = {
    "runner": "api",
    "api_url": "https://api.pipelex.com",
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
    """Read the credentials file, running migration if needed."""
    _migrate_if_needed()
    if not CREDENTIALS_PATH.is_file():
        return {}
    try:
        return _parse_dotenv(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except OSError:
        return {}


def _write_credentials_file(entries: dict[str, str]) -> None:
    """Write the credentials file with restricted permissions (owner-only)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(_serialize_dotenv(entries), encoding="utf-8")
    CREDENTIALS_PATH.chmod(0o600)


# ── Migration ──────────────────────────────────────────────────────

_migration_done = False


def _migrate_if_needed() -> None:
    """Silently migrate from legacy config.json / .env.local if they exist."""
    global _migration_done  # noqa: PLW0603
    if _migration_done:
        return
    _migration_done = True

    if CREDENTIALS_PATH.is_file():
        return

    migrated: dict[str, str] = {}
    did_migrate = False

    # Migrate from config.json
    if _LEGACY_CONFIG_PATH.is_file():
        try:
            raw = _LEGACY_CONFIG_PATH.read_text(encoding="utf-8")
            config: dict[str, object] = json.loads(raw)

            if isinstance(config.get("runner"), str):
                migrated["MTHDS_RUNNER"] = str(config["runner"])
            if isinstance(config.get("apiUrl"), str):
                migrated["PIPELEX_API_URL"] = str(config["apiUrl"])
            if isinstance(config.get("apiKey"), str):
                migrated["PIPELEX_API_KEY"] = str(config["apiKey"])
            if isinstance(config.get("telemetry"), bool):
                migrated["DISABLE_TELEMETRY"] = "0" if config["telemetry"] else "1"

            did_migrate = True
        except (OSError, json.JSONDecodeError):
            pass

    # Migrate from .env.local (telemetry flag)
    if _LEGACY_ENV_LOCAL_PATH.is_file():
        try:
            env_entries = _parse_dotenv(_LEGACY_ENV_LOCAL_PATH.read_text(encoding="utf-8"))
            if "DISABLE_TELEMETRY" in env_entries:
                migrated["DISABLE_TELEMETRY"] = env_entries["DISABLE_TELEMETRY"]
            did_migrate = True
        except OSError:
            pass

    if did_migrate:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_PATH.write_text(_serialize_dotenv(migrated), encoding="utf-8")

        # Remove legacy files
        for legacy_path in (_LEGACY_CONFIG_PATH, _LEGACY_ENV_LOCAL_PATH):
            try:
                if legacy_path.is_file():
                    legacy_path.unlink()
            except OSError:
                pass


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
    for internal_key, file_key in _CREDENTIAL_KEYS.items():
        if file_key in file_entries:
            merged[internal_key] = file_entries[file_key]

    # Env vars take precedence
    for internal_key, env_name in _CREDENTIAL_KEYS.items():
        env_val = os.environ.get(env_name)
        if env_val is not None:
            merged[internal_key] = env_val

    return merged


def _cli_key_for(internal_key: str) -> str:
    """Reverse-lookup the CLI flag name for an internal key."""
    return next(cli_k for cli_k, int_k in _KEY_ALIASES.items() if int_k == internal_key)


def get_credential_value(key: str) -> CredentialEntry:
    """Get a single credential value with its source.

    Args:
        key: Internal key (e.g. "runner", "api_url").

    Returns:
        A CredentialEntry with the value and its source.
    """
    cli_key = _cli_key_for(key)

    env_name = _CREDENTIAL_KEYS[key]
    env_val = os.environ.get(env_name)
    if env_val is not None:
        return CredentialEntry(key=key, cli_key=cli_key, value=env_val, source=CredentialSource.ENV)

    file_entries = _read_credentials_file()
    file_key = _CREDENTIAL_KEYS[key]
    if file_key in file_entries:
        return CredentialEntry(key=key, cli_key=cli_key, value=file_entries[file_key], source=CredentialSource.FILE)

    return CredentialEntry(key=key, cli_key=cli_key, value=_DEFAULTS[key], source=CredentialSource.DEFAULT)


def set_credential_value(key: str, value: str) -> None:
    """Set a credential value in the credentials file.

    Args:
        key: Internal key (e.g. "runner", "api_url").
        value: The value to set.
    """
    file_entries = _read_credentials_file()
    file_key = _CREDENTIAL_KEYS[key]
    file_entries[file_key] = value
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
