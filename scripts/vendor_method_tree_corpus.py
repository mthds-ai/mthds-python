"""Vendor the shared method-tree conformance corpus from a `conformance` checkout, byte for byte.

Usage: `make vendor-tree-corpus CONFORMANCE=<path to a conformance checkout>`.

The corpus is copied unchanged to `tests/fixtures/method_tree_corpus.json`, and its sidecar,
`tests/fixtures/method_tree_corpus.source.json`, records the conformance commit it came from and
the SHA-256 of each vendored file, which `tests/unit/method_tree/test_method_tree_corpus_parity.py`
checks the vendored bytes against. The copy is never edited by hand: a case to change is changed
in `conformance` and vendored again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SOURCE_REPOSITORY = "Pipelex/conformance"
SOURCE_PATH = "tests/method_tree/fixtures/method-tree-corpus.json"
CORPUS_NAME = "mthds-method-tree"
SUPPORTED_FORMAT = 1
REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIRECTORY = REPO_ROOT / "tests" / "fixtures"
VENDORED_NAME = "method_tree_corpus.json"
SIDECAR_NAME = "method_tree_corpus.source.json"


class VendoringError(Exception):
    """The corpus cannot be vendored from the checkout given."""


def _git(checkout: Path, *arguments: str) -> bytes:
    completed = subprocess.run(["git", "-C", str(checkout), *arguments], capture_output=True, check=False)  # ruff: ignore[start-process-with-partial-path]
    if completed.returncode != 0:
        msg = f"git {' '.join(arguments)} failed in '{checkout}': {completed.stderr.decode(errors='replace').strip()}"
        raise VendoringError(msg)
    return completed.stdout


def vendor(checkout: Path) -> tuple[str, bool]:
    """Copy the corpus committed at the checkout's HEAD and write its sidecar.

    The committed corpus is copied, never the working copy, so that the commit the sidecar names
    holds exactly the bytes vendored.

    Returns:
        The conformance commit vendored, and whether the checkout's working copy of the corpus differs from it.
    """
    source = checkout / SOURCE_PATH
    if not source.is_file():
        msg = f"'{checkout}' holds no {SOURCE_PATH}; give the path of a conformance checkout."
        raise VendoringError(msg)
    commit = _git(checkout, "rev-parse", "HEAD").decode().strip()
    data = _git(checkout, "show", f"HEAD:{SOURCE_PATH}")
    working_copy_differs = source.read_bytes() != data
    header = json.loads(data)
    if header.get("corpus") != CORPUS_NAME or header.get("format") != SUPPORTED_FORMAT:
        found = f"corpus {header.get('corpus')!r} format {header.get('format')!r}"
        msg = f"{SOURCE_PATH} is {found}; this repository reads {CORPUS_NAME!r} format {SUPPORTED_FORMAT}."
        raise VendoringError(msg)
    (FIXTURES_DIRECTORY / VENDORED_NAME).write_bytes(data)
    sidecar = {
        "source_repository": SOURCE_REPOSITORY,
        "source_path": SOURCE_PATH,
        "source_commit": commit,
        "files": {VENDORED_NAME: hashlib.sha256(data).hexdigest()},
    }
    (FIXTURES_DIRECTORY / SIDECAR_NAME).write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return commit, working_copy_differs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("conformance", type=Path, help="the path of a conformance checkout")
    arguments = parser.parse_args()
    try:
        commit, working_copy_differs = vendor(arguments.conformance.resolve())
    except VendoringError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    if working_copy_differs:
        sys.stderr.write(f"warning: the checkout's working copy of {SOURCE_PATH} has uncommitted changes, which were not vendored.\n")
    sys.stdout.write(f"Vendored {SOURCE_PATH} from conformance {commit} into tests/fixtures/{VENDORED_NAME}.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
