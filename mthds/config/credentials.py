"""Unified credentials management for the MTHDS client.

Reads and writes ``~/.mthds/config`` using a dotenv-style format — the SAME
file, format, and key names the ``mthds`` CLI (mthds-js) uses, so a single
``mthds config set …`` configures both the TypeScript and Python clients.
(``KEY=VALUE``, ``#`` comments, blank lines allowed).

Resolution order: environment variables > config file > defaults.
"""

from __future__ import annotations

import json
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
# Canonical file, shared with the mthds CLI (mthds-js writes the same path).
CONFIG_PATH = CONFIG_DIR / "config"

# Legacy paths, auto-migrated forward into CONFIG_PATH when it does not yet
# exist (an existing CONFIG_PATH always wins — the CLI is the source of truth):
#   - ``credentials``  : the dotenv file earlier Python clients wrote.
#   - ``config.json``  : the very first JS client format.
#   - ``.env.local``   : early telemetry flag store.
_LEGACY_CREDENTIALS_PATH = CONFIG_DIR / "credentials"
_LEGACY_CONFIG_JSON_PATH = CONFIG_DIR / "config.json"
_LEGACY_ENV_LOCAL_PATH = CONFIG_DIR / ".env.local"

# ── Credential keys ────────────────────────────────────────────────

# Map from internal key to the canonical credential key (env var name and file key share the same names).
# The package is vendor-neutral ``mthds``, so the public keys use the ``MTHDS_`` prefix.
_CREDENTIAL_KEYS: dict[str, str] = {
    "api_url": "MTHDS_API_URL",
    "api_key": "MTHDS_API_KEY",
    "runner": "MTHDS_RUNNER",
    "telemetry": "DISABLE_TELEMETRY",
}

# Legacy credential keys, still honored on read (env var or credentials file) and transparently
# migrated to the canonical ``MTHDS_`` keys. Maps internal key to its old storage key.
_LEGACY_CREDENTIAL_KEYS: dict[str, str] = {
    "api_url": "PIPELEX_API_URL",
    "api_key": "PIPELEX_API_KEY",
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


def _lookup_in_store(internal_key: str, store: Mapping[str, str]) -> str | None:
    """Look up the value for an internal key in a storage mapping (file entries or environ).

    The canonical ``MTHDS_`` key takes precedence; a legacy ``PIPELEX_`` key is honored as a
    fallback so older credentials files and environments keep working without a manual rewrite.
    An empty canonical value is treated as absent for the purpose of choosing between the two,
    so a real (non-empty) legacy value is never shadowed by a stray empty canonical entry.

    Args:
        internal_key: The internal credential key (e.g. "api_url").
        store: A mapping keyed by storage/env names (e.g. parsed credentials file or os.environ).

    Returns:
        The first non-empty value among the canonical then legacy keys; an empty string if only
        empty values are present (preserving "explicitly set" semantics); None when neither key
        is present.
    """
    canonical_key = _CREDENTIAL_KEYS[internal_key]
    legacy_key = _LEGACY_CREDENTIAL_KEYS.get(internal_key)
    candidate_keys = [canonical_key] if legacy_key is None else [canonical_key, legacy_key]

    found_empty = False
    for store_key in candidate_keys:
        if store_key in store:
            value = store[store_key]
            if value:
                return value
            found_empty = True
    return "" if found_empty else None


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
    """Read the config file, running migration if needed."""
    _migrate_if_needed()
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


# ── Migration ──────────────────────────────────────────────────────

_migration_done = False


def _migrate_if_needed() -> None:
    """Silently migrate legacy files forward into ``~/.mthds/config``.

    No-op when ``config`` already exists — the CLI owns that file, so we never
    clobber a current config with a stale legacy one. Sources, lowest to
    highest precedence: ``config.json`` → ``.env.local`` → ``credentials``
    (the dotenv file earlier Python clients wrote wins, being the most recent
    Python format).
    """
    global _migration_done  # noqa: PLW0603
    if _migration_done:
        return
    _migration_done = True

    if CONFIG_PATH.is_file():
        return

    migrated: dict[str, str] = {}
    did_migrate = False

    # Migrate from config.json (oldest JS format)
    if _LEGACY_CONFIG_JSON_PATH.is_file():
        try:
            raw = _LEGACY_CONFIG_JSON_PATH.read_text(encoding="utf-8")
            config: dict[str, object] = json.loads(raw)

            if isinstance(config.get("runner"), str):
                migrated["MTHDS_RUNNER"] = str(config["runner"])
            if isinstance(config.get("apiUrl"), str):
                migrated["MTHDS_API_URL"] = str(config["apiUrl"])
            if isinstance(config.get("apiKey"), str):
                migrated["MTHDS_API_KEY"] = str(config["apiKey"])
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

    # Migrate from the old ``credentials`` dotenv file (earlier Python clients).
    # Highest precedence: it is the most recent Python format and already uses
    # the canonical MTHDS_/legacy PIPELEX_ keys, so copy every entry verbatim.
    if _LEGACY_CREDENTIALS_PATH.is_file():
        try:
            migrated.update(_parse_dotenv(_LEGACY_CREDENTIALS_PATH.read_text(encoding="utf-8")))
            did_migrate = True
        except OSError:
            pass

    if did_migrate:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(_serialize_dotenv(migrated), encoding="utf-8")

        # Remove legacy files
        for legacy_path in (_LEGACY_CONFIG_JSON_PATH, _LEGACY_ENV_LOCAL_PATH, _LEGACY_CREDENTIALS_PATH):
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

    # Apply file values (canonical key wins over legacy alias)
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
    file_key = _CREDENTIAL_KEYS[key]
    file_entries[file_key] = value
    # Drop any stale legacy alias so the file converges on the canonical key.
    legacy_key = _LEGACY_CREDENTIAL_KEYS.get(key)
    if legacy_key is not None:
        file_entries.pop(legacy_key, None)
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
