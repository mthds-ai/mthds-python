"""Vendor the MTHDS core error registry from an `mthds` checkout, byte for byte, at a ref or a tag.

Usage: `make vendor-error-registry MTHDS=<path to an mthds checkout> REF=<ref or tag>`, then
`make generate-error-registry` to regenerate the module the vendored files describe.
`make check-error-registry-upstream MTHDS=<path> REF=<tag>` runs it with `--check`, which writes
nothing and fails when the vendored files differ from those the ref publishes; that check needs
the checkout to hold the ref, so no gate requires it.

The registry's JSON snapshot and its JSON Schema are copied unchanged from the ref given into
`vendor/mthds-error-registry/`, never from the checkout's working copy, so that the commit the
sidecar names holds exactly the bytes vendored. The sidecar, `source.json`, records the ref asked
for, the commit it resolved to, the registry's version and the SHA-256 of each file, which
`tests/unit/test_error_registry_vendored.py` checks the vendored bytes against. The copies are
never edited by hand: a code to change is changed in `mthds` and vendored again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SOURCE_REPOSITORY = "mthds-ai/mthds"
SOURCE_DIRECTORY = "docs/spec/openapi"
SNAPSHOT_NAME = "mthds-error-registry.json"
SCHEMA_NAME = "mthds-error-registry.schema.json"
SIDECAR_NAME = "source.json"
REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIRECTORY = REPO_ROOT / "vendor" / "mthds-error-registry"


class VendoringError(Exception):
    """The registry cannot be vendored from the checkout and ref given."""


def _git(checkout: Path, *arguments: str) -> bytes:
    completed = subprocess.run(["git", "-C", str(checkout), *arguments], capture_output=True, check=False)  # ruff: ignore[start-process-with-partial-path]
    if completed.returncode != 0:
        msg = f"git {' '.join(arguments)} failed in '{checkout}': {completed.stderr.decode(errors='replace').strip()}"
        raise VendoringError(msg)
    return completed.stdout


def vendor(checkout: Path, *, ref: str) -> tuple[str, str]:
    """Copy the registry's snapshot and schema committed at `ref` and write the sidecar.

    Returns:
        The commit `ref` resolved to, and the version of the registry vendored.
    """
    if not (checkout / ".git").exists():
        msg = f"'{checkout}' is not a git checkout; give the path of an mthds checkout."
        raise VendoringError(msg)
    commit = _git(checkout, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    snapshot = _git(checkout, "show", f"{commit}:{SOURCE_DIRECTORY}/{SNAPSHOT_NAME}")
    schema = _git(checkout, "show", f"{commit}:{SOURCE_DIRECTORY}/{SCHEMA_NAME}")
    header = json.loads(snapshot)
    version = header.get("version")
    if not isinstance(version, str) or not isinstance(header.get("codes"), list):
        msg = f"{SOURCE_DIRECTORY}/{SNAPSHOT_NAME} at {ref} is not a registry snapshot: it has no version or no codes."
        raise VendoringError(msg)
    VENDOR_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (VENDOR_DIRECTORY / SNAPSHOT_NAME).write_bytes(snapshot)
    (VENDOR_DIRECTORY / SCHEMA_NAME).write_bytes(schema)
    sidecar = {
        "source_repository": SOURCE_REPOSITORY,
        "source_directory": SOURCE_DIRECTORY,
        "source_ref": ref,
        "source_commit": commit,
        "registry_version": version,
        "files": {
            SNAPSHOT_NAME: hashlib.sha256(snapshot).hexdigest(),
            SCHEMA_NAME: hashlib.sha256(schema).hexdigest(),
        },
    }
    (VENDOR_DIRECTORY / SIDECAR_NAME).write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return commit, version


def differs_from(checkout: Path, *, ref: str) -> list[str]:
    """The vendored files that differ from those committed at `ref`, empty when they are the same bytes."""
    commit = _git(checkout, "rev-parse", "--verify", f"{ref}^{{commit}}").decode().strip()
    differing: list[str] = []
    for name in (SNAPSHOT_NAME, SCHEMA_NAME):
        published = _git(checkout, "show", f"{commit}:{SOURCE_DIRECTORY}/{name}")
        vendored_path = VENDOR_DIRECTORY / name
        if not vendored_path.is_file() or vendored_path.read_bytes() != published:
            differing.append(name)
    return differing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mthds", type=Path, help="the path of an mthds checkout")
    parser.add_argument("--ref", required=True, help="the ref or tag to vendor from, such as v7.1.0")
    parser.add_argument("--check", action="store_true", help="write nothing and fail when the vendored files differ from the ref's")
    arguments = parser.parse_args()
    try:
        if arguments.check:
            differing = differs_from(arguments.mthds.resolve(), ref=arguments.ref)
            for name in differing:
                sys.stderr.write(f"error: vendor/mthds-error-registry/{name} differs from {SOURCE_DIRECTORY}/{name} at {arguments.ref}.\n")
            if differing:
                return 1
            sys.stdout.write(f"The vendored core error registry is the one mthds {arguments.ref} publishes.\n")
            return 0
        commit, version = vendor(arguments.mthds.resolve(), ref=arguments.ref)
    except VendoringError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    sys.stdout.write(f"Vendored the core error registry {version} from mthds {arguments.ref} ({commit}) into vendor/mthds-error-registry/.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
