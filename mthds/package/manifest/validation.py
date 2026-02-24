from typing import Any

from mthds._utils.string_utils import is_snake_case
from mthds.package.qualified_ref import QualifiedRef


def is_domain_code_valid(code: Any) -> bool:
    """Check if a domain code is valid.

    Accepts single-segment (e.g. "legal") and hierarchical dotted paths
    (e.g. "legal.contracts", "legal.contracts.shareholder").
    Each segment must be snake_case.
    Supports cross-package domain codes (e.g. "alias->scoring").
    """
    if not isinstance(code, str):
        return False
    if QualifiedRef.has_cross_package_prefix(code):
        _, remainder = QualifiedRef.split_cross_package_ref(code)
        return is_domain_code_valid(code=remainder)
    if not code or code.startswith(".") or code.endswith(".") or ".." in code:
        return False
    return all(is_snake_case(segment) for segment in code.split("."))


def is_pipe_code_valid(pipe_code: str) -> bool:
    return is_snake_case(pipe_code)
