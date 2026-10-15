"""Resolving a file reference against the tree that holds it, by the standard's seven steps.

A file reference is written in a file of the tree, its holder, either in a bundle field naming a
file (path context) or as a relative URL in a template (URL context). It is resolved against the
directory of its holder (`mthds/docs/spec/method-tree.md`, "File References"):

1. Take its path: in URL context, drop the fragment, then the query.
2. Check its form: a backslash or a leading `/` is malformed, and so is a scheme in path context.
3. Decode it: in URL context, split it at each `/` and percent-decode each segment.
4. Normalize it to NFC.
5. Resolve it lexically against the holder's directory; a `..` climbing above the root leaves the tree.
6. Check the result: the root itself, with or without a trailing `/`, goes on to step 7; any other
   result that is not a tree path is refused as such.
7. Look it up: the result must name a file of the tree.

The first step that fails decides the refusal. A URL naming a scheme, holding an authority or
having no path is no file reference: it is left exactly as written, never resolved and never refused.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING
from urllib.parse import unquote

from mthds.method_tree.discovery import kind_at_tree_path
from mthds.method_tree.exceptions import MethodTreeRefusedError, TreeRefusal
from mthds.method_tree.tree_path import CONTROL_CATEGORY, directories_of, nfc, tree_path_violation
from mthds.method_tree.vocabulary import ReferenceContext, TreeRefusalCode

if TYPE_CHECKING:
    from mthds.method_tree.models import MethodTree, TreeExclusion

SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
MALFORMED_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
ROOT_RESOLVED = "."


def _count_control_characters(text: str) -> int:
    return sum(1 for character in text if unicodedata.category(character) == CONTROL_CATEGORY)


def _url_path_part(reference: str) -> str:
    """A URL's path as written: what is left once the fragment, then the query, are dropped.

    `urllib.parse.urlsplit` is not used: it silently drops tabs and line breaks, which the standard
    keeps so that the result check can refuse them.
    """
    return reference.split("#", 1)[0].split("?", 1)[0]


def is_file_reference(reference: str, *, context: ReferenceContext) -> bool:
    """Whether a reference is a file reference at all.

    Every reference in a bundle field is one. In a URL, one naming a scheme (`https:`, `data:`,
    `mailto:`), one holding an authority (`//host/x`) and one with no path once its query and
    fragment are dropped (`?v=2`, `#top`, the empty URL) are not.
    """
    match context:
        case ReferenceContext.PATH:
            return True
        case ReferenceContext.URL:
            if SCHEME_PATTERN.match(reference):
                return False
            path_part = _url_path_part(reference)
            return bool(path_part) and not path_part.startswith("//")


def _refuse(reference: str, *, holder: str, code: TreeRefusalCode, explanation: str, resolved: str | None = None) -> MethodTreeRefusedError:
    msg = f"The file reference {reference!r} in {holder!r} {explanation}"
    return MethodTreeRefusedError(msg, refusal=TreeRefusal(code=code, names=[reference], resolved=resolved))


def _decode_url_path(reference: str, *, holder: str) -> str:
    """Steps 1 to 3 in URL context: the path, its form checked and each segment percent-decoded."""
    path_part = _url_path_part(reference)
    if path_part.startswith("/") or "\\" in path_part:
        raise _refuse(reference, holder=holder, code=TreeRefusalCode.REFERENCE_INVALID, explanation="starts with '/' or holds a backslash.")
    decoded_segments: list[str] = []
    for segment in path_part.split("/"):
        if MALFORMED_PERCENT_ESCAPE.search(segment):
            explanation = "holds a '%' not followed by two hexadecimal digits; write a literal '%' as '%25'."
            raise _refuse(reference, holder=holder, code=TreeRefusalCode.REFERENCE_INVALID, explanation=explanation)
        try:
            decoded = unquote(segment, encoding="utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            refused = _refuse(
                reference, holder=holder, code=TreeRefusalCode.REFERENCE_INVALID, explanation="percent-decodes to bytes that are not UTF-8."
            )
            raise refused from exc
        if "/" in decoded or "\\" in decoded or _count_control_characters(decoded) > _count_control_characters(segment):
            explanation = "percent-decodes to a '/', a backslash or a control character, which no segment may hold."
            raise _refuse(reference, holder=holder, code=TreeRefusalCode.REFERENCE_INVALID, explanation=explanation)
        decoded_segments.append(decoded)
    return "/".join(decoded_segments)


def _reference_path(reference: str, *, holder: str, context: ReferenceContext) -> str:
    """Steps 1 to 4: the path a file reference names, decoded in URL context, in NFC."""
    path: str
    match context:
        case ReferenceContext.PATH:
            if not reference:
                raise _refuse(reference, holder=holder, code=TreeRefusalCode.REFERENCE_NOT_A_TREE_PATH, explanation="is empty, so it names no file.")
            if SCHEME_PATTERN.match(reference) or reference.startswith("/") or "\\" in reference:
                explanation = "names a scheme, starts with '/' or holds a backslash; write a path relative to the file that holds it."
                raise _refuse(reference, holder=holder, code=TreeRefusalCode.REFERENCE_INVALID, explanation=explanation)
            path = reference
        case ReferenceContext.URL:
            path = _decode_url_path(reference, holder=holder)
    return nfc(path)


def lexical_join(*, holder: str, path: str) -> list[str] | None:
    """Step 5: join `path` to the directory of `holder`, drop each `.`, and let each `..` remove the segment before it.

    Returns the segments of the result, or None when a `..` would climb above the root.
    """
    resolved: list[str] = []
    for segment in [*holder.split("/")[:-1], *path.split("/")]:
        if segment == ".":
            continue
        if segment == "..":
            if not resolved:
                return None
            resolved.pop()
            continue
        resolved.append(segment)
    return resolved


def resolve_reference(reference: str, *, holder: str, context: ReferenceContext, tree: MethodTree) -> str | None:
    """Resolve a file reference written in `holder`, a file of `tree`.

    Args:
        reference: The reference exactly as written.
        holder: The tree path of the file holding the reference.
        context: `path` for a bundle field naming a file, `url` for a relative URL in a template.
        tree: The tree the holder belongs to.

    Returns:
        The tree path of the file the reference names, or None for a URL that is no file reference,
        which the caller leaves exactly as written.

    Raises:
        MethodTreeRefusedError: When the reference is refused; `refusal.code` says at which step,
            and `refusal.resolved` holds what it resolved to from step 5 on.
        ValueError: When `holder` is not a file of `tree`.
    """
    if holder not in tree.members:
        msg = f"the holder {holder!r} is not a file of the tree"
        raise ValueError(msg)
    if not is_file_reference(reference, context=context):
        return None
    path = _reference_path(reference, holder=holder, context=context)
    segments = lexical_join(holder=holder, path=path)
    if segments is None:
        raise _refuse(reference, holder=holder, code=TreeRefusalCode.REFERENCE_LEAVES_TREE, explanation="climbs above the root of its method tree.")
    # The root itself, with no segment or with only a trailing '/', as `../` from `templates/x.html`
    # resolves to, passes the result check and is refused at the lookup as not in the tree.
    is_root = segments in ([], [""])
    resolved = ROOT_RESOLVED if is_root else "/".join(segments)
    if not is_root:
        violation = tree_path_violation(resolved)
        if violation is not None:
            explanation = f"resolves to {resolved!r}, which is not a tree path: {violation}."
            raise _refuse(reference, holder=holder, code=TreeRefusalCode.REFERENCE_NOT_A_TREE_PATH, explanation=explanation, resolved=resolved)
    if resolved in tree.members:
        return resolved
    if tree.is_one_file:
        explanation = (
            "names a file beside the bundle, but the bundle was named alone with no METHODS.toml at or above it, "
            "so its tree holds that one file. Hand over the method's directory instead."
        )
        raise _refuse(reference, holder=holder, code=TreeRefusalCode.REFERENCE_IN_ONE_FILE_TREE, explanation=explanation)
    exclusion = None if is_root else _exclusion_at(tree, tree_path=resolved)
    what = "the root of the tree, not a file" if is_root else f"{resolved!r}, which is not a file of the tree"
    reason = f": it is kept out by {exclusion.rule.description}" if exclusion is not None else ""
    msg = f"The file reference {reference!r} in {holder!r} resolves to {what}{reason}."
    refusal = TreeRefusal(
        code=TreeRefusalCode.REFERENCE_NOT_IN_TREE,
        names=[reference],
        resolved=resolved,
        excluded_by=exclusion.rule if exclusion is not None else None,
        excluded_directory=exclusion.directory if exclusion is not None and exclusion.rule.names_directory else None,
    )
    raise MethodTreeRefusedError(msg, refusal=refusal)


def _exclusion_at(tree: MethodTree, *, tree_path: str) -> TreeExclusion | None:
    """The rule keeping out a file, a link or another non-directory entry at `tree_path`, or None when none is there.

    An entry the listing visited and kept out carries its rule. One inside a pruned directory was
    never visited, so the directory's rule is given only after checking on disk that such an
    entry is there.
    """
    visited = tree.excluded_files.get(tree_path)
    if visited is not None:
        return visited
    if tree.directory is None:
        return None
    for directory in directories_of(tree_path):
        pruned = tree.excluded_directories.get(directory)
        if pruned is None:
            continue
        below = tree_path[len(directory) + 1 :].split("/")
        kind = kind_at_tree_path(directory=tree.directory, raw_directory=tree.raw_paths.get(directory, directory), segments=below)
        if kind is None or kind.is_directory:
            return None
        return pruned
    return None
