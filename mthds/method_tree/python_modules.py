"""Locating a `PipeFunc`'s function in its tree from its `function_name`.

A `function_name` is a Python import path from the root of the tree holding the bundle, the tree's
root being the import root: `funcs.text_utils.shout` names the function `shout` of the module
`funcs/text_utils.py`, or of `funcs/text_utils/__init__.py` (`mthds/docs/spec/method-tree.md`,
"Python Modules"). The name is normalized to NFC first, and each segment must then be a Python
identifier that is not a keyword and that NFKC leaves unchanged: Python reads identifiers in NFKC,
so a segment such as `ﬁle` (a ligature) or a fullwidth letter would import another name than the
one written, and it is refused rather than mapped.
"""

from __future__ import annotations

import keyword
import unicodedata
from typing import TYPE_CHECKING, NamedTuple

from mthds.method_tree.exceptions import MethodTreeRefusedError, TreeRefusal
from mthds.method_tree.tree_path import nfc, sorted_tree_paths
from mthds.method_tree.vocabulary import TreeRefusalCode

if TYPE_CHECKING:
    from mthds.method_tree.models import MethodTree


class FunctionLocation(NamedTuple):
    """Where a `function_name` points: the tree path of its module and the function's name in it."""

    module: str
    function: str


def is_valid_function_segment(segment: str) -> bool:
    """Whether a segment of a `function_name`, already in NFC, is an identifier, not a keyword, and unchanged by NFKC."""
    return segment.isidentifier() and not keyword.iskeyword(segment) and unicodedata.normalize("NFKC", segment) == segment


def locate_function(function_name: str, *, tree: MethodTree) -> FunctionLocation:
    """Split a `function_name` at its last dot and find its module among the tree's files.

    Raises:
        MethodTreeRefusedError: When the name holds no dot, a segment is not a valid identifier,
            or the tree holds neither `<path>.py` nor `<path>/__init__.py`, or holds both.
    """
    normalized = nfc(function_name)
    if "." not in normalized:
        msg = f"The function_name {function_name!r} holds no dot, so it names no module: write it as 'module.function', such as 'funcs.text.shout'."
        raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.FUNCTION_NAME_WITHOUT_MODULE, names=[function_name]))
    segments = normalized.split(".")
    for segment in segments:
        if not is_valid_function_segment(segment):
            msg = (
                f"The function_name {function_name!r} holds the segment {segment!r}, which is not a Python identifier, is a keyword, "
                "or changes under NFKC normalization."
            )
            raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.FUNCTION_NAME_INVALID_SEGMENT, names=[function_name]))
    module_path = "/".join(segments[:-1])
    candidates = [f"{module_path}.py", f"{module_path}/__init__.py"]
    held = [candidate for candidate in candidates if candidate in tree.members]
    if not held:
        msg = f"The function_name {function_name!r} names a module the method tree does not hold: neither {candidates[0]!r} nor {candidates[1]!r}."
        raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.MODULE_NOT_IN_TREE, names=[function_name]))
    if len(held) > 1:
        msg = f"The function_name {function_name!r} names a module the method tree holds twice, as {held[0]!r} and {held[1]!r}; remove one."
        raise MethodTreeRefusedError(msg, refusal=TreeRefusal(code=TreeRefusalCode.MODULE_AMBIGUOUS, names=sorted_tree_paths(held)))
    return FunctionLocation(module=held[0], function=segments[-1])
