"""The closed vocabularies of the method tree: refusal codes, exclusion rules, reference contexts and limits.

The refusal codes and the exclusion rules are the strings the shared conformance corpus
(`conformance/specs/mthds-method-tree.md`, "Refusals") holds every implementation to, so a
consumer branches on them and renaming one is a change to that contract. The wording of an
error message is this package's own; the code is what is stable.
"""

from __future__ import annotations

from enum import StrEnum


class TreeRefusalCode(StrEnum):
    """Why a tree, a map of file entries, a tree path, a file reference or a function name is refused."""

    # Listing a tree from a directory or from a lone `.mthds` file.
    SYMBOLIC_LINK = "symbolic_link"
    SPECIAL_FILE = "special_file"
    INVALID_TREE_PATH = "invalid_tree_path"
    NORMALIZATION_COLLISION = "normalization_collision"
    PATH_COLLISION = "path_collision"
    EMPTY_TREE = "empty_tree"
    LONE_FILE_EXCLUDED = "lone_file_excluded"
    # A `.gitignore` file in the tree whose bytes are not UTF-8, named by its tree path.
    GITIGNORE_NOT_UTF8 = "gitignore_not_utf8"
    # Reading a map of file entries.
    DUPLICATE_KEY = "duplicate_key"
    EXCLUDED_NAME = "excluded_name"
    MALFORMED_ENTRY = "malformed_entry"
    MISSING_BLOB = "missing_blob"
    # Resolving a file reference.
    REFERENCE_INVALID = "reference_invalid"
    REFERENCE_LEAVES_TREE = "reference_leaves_tree"
    REFERENCE_NOT_A_TREE_PATH = "reference_not_a_tree_path"
    REFERENCE_NOT_IN_TREE = "reference_not_in_tree"
    REFERENCE_IN_ONE_FILE_TREE = "reference_in_one_file_tree"
    # Locating a `PipeFunc`'s function.
    FUNCTION_NAME_WITHOUT_MODULE = "function_name_without_module"
    FUNCTION_NAME_INVALID_SEGMENT = "function_name_invalid_segment"
    MODULE_NOT_IN_TREE = "module_not_in_tree"
    MODULE_AMBIGUOUS = "module_ambiguous"


class ExclusionRule(StrEnum):
    """Which part of the membership rule keeps a file out of a tree listed from a directory."""

    DOT_SEGMENT = "dot_segment"
    PYCACHE_OR_NODE_MODULES = "pycache_or_node_modules"
    VIRTUAL_ENVIRONMENT = "virtual_environment"
    NESTED_REPOSITORY = "nested_repository"
    NESTED_PACKAGE = "nested_package"
    GITIGNORE = "gitignore"
    PACKAGE_EXCLUDE = "package_exclude"

    @property
    def names_directory(self) -> bool:
        """Whether a refusal citing this rule also names the excluded directory, as the standard asks for these rules."""
        match self:
            case ExclusionRule.NESTED_REPOSITORY | ExclusionRule.NESTED_PACKAGE:
                return True
            case (
                ExclusionRule.DOT_SEGMENT
                | ExclusionRule.PYCACHE_OR_NODE_MODULES
                | ExclusionRule.VIRTUAL_ENVIRONMENT
                | ExclusionRule.GITIGNORE
                | ExclusionRule.PACKAGE_EXCLUDE
            ):
                return False

    @property
    def description(self) -> str:
        """The rule in words, for an error message."""
        match self:
            case ExclusionRule.DOT_SEGMENT:
                return "a path segment starting with a dot"
            case ExclusionRule.PYCACHE_OR_NODE_MODULES:
                return "a __pycache__ or node_modules directory"
            case ExclusionRule.VIRTUAL_ENVIRONMENT:
                return "a Python virtual environment, a directory holding pyvenv.cfg"
            case ExclusionRule.NESTED_REPOSITORY:
                return "a nested repository, a directory below the root holding a .git entry"
            case ExclusionRule.NESTED_PACKAGE:
                return "a nested package, a directory below the root holding its own METHODS.toml"
            case ExclusionRule.GITIGNORE:
                return "a .gitignore pattern"
            case ExclusionRule.PACKAGE_EXCLUDE:
                return "a [package] exclude pattern of METHODS.toml"


class ReferenceContext(StrEnum):
    """Where a file reference is written: a bundle field naming a path, or a relative URL in a template."""

    PATH = "path"
    URL = "url"


class TreeLimitKind(StrEnum):
    """Which limit a listing stopped at."""

    FILE_COUNT = "file_count"
    TOTAL_BYTES = "total_bytes"
    FILE_BYTES = "file_bytes"

    @property
    def description(self) -> str:
        """The limit in words, for an error message."""
        match self:
            case TreeLimitKind.FILE_COUNT:
                return "files"
            case TreeLimitKind.TOTAL_BYTES:
                return "bytes in all"
            case TreeLimitKind.FILE_BYTES:
                return "bytes in one file"
