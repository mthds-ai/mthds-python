"""The shared method-tree conformance corpus, vendored from `conformance`, and the cases it holds."""

import json
from pathlib import Path
from typing import Any, ClassVar

FIXTURES_DIRECTORY = Path(__file__).resolve().parents[2] / "fixtures"


def _load_corpus() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES_DIRECTORY / "method_tree_corpus.json").read_bytes())
    return loaded


class MethodTreeCorpus:
    """The vendored corpus file, its sidecar, and its kinds of case keyed by what names each."""

    CORPUS_PATH: ClassVar[Path] = FIXTURES_DIRECTORY / "method_tree_corpus.json"
    SIDECAR_PATH: ClassVar[Path] = FIXTURES_DIRECTORY / "method_tree_corpus.source.json"
    CORPUS_NAME: ClassVar[str] = "mthds-method-tree"
    SUPPORTED_FORMAT: ClassVar[int] = 1
    DOCUMENT: ClassVar[dict[str, Any]] = _load_corpus()
    TREE_CASES: ClassVar[list[dict[str, Any]]] = DOCUMENT["trees"]
    MAP_CASES: ClassVar[list[dict[str, Any]]] = DOCUMENT["maps"]
    PATH_CASES: ClassVar[list[dict[str, Any]]] = DOCUMENT["paths"]


class HostCapability:
    """The capabilities a tree case's `requires` names, which the host's file system may lack."""

    CASE_SENSITIVE_NAMES: ClassVar[str] = "case_sensitive_names"
    NORMALIZATION_SENSITIVE_NAMES: ClassVar[str] = "normalization_sensitive_names"
    SYMBOLIC_LINKS: ClassVar[str] = "symbolic_links"
    NAMED_PIPES: ClassVar[str] = "named_pipes"


class ReferenceTree:
    """A tree known only by its set of tree paths, and the files in it that hold references."""

    TREE_PATHS: ClassVar[frozenset[str]] = frozenset(
        {
            "main.mthds",
            "templates/letter.html",
            "templates/logo.png",
            "templates/partials/header.html",
            "shared/logo.png",
            "assets/100%.txt",
            "assets/caf\u00e9.txt",
            "assets/my logo.png",
        }
    )
    BUNDLE: ClassVar[str] = "main.mthds"
    TEMPLATE: ClassVar[str] = "templates/letter.html"
    PARTIAL: ClassVar[str] = "templates/partials/header.html"
    LONE_BUNDLE: ClassVar[str] = "greet.mthds"
