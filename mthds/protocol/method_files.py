"""The canonical **catalog serialization** of a method's source files — mirrors `mthds-js`'s `protocol/method_files.ts`.

    catalog string  ──parse_method_files──▶  list[MethodFile]  (ordered, named)
    list[MethodFile] ──serialize_method_files──▶  catalog string

The catalog string is the JSON `[{ name, content }]` array form (the webapp-editor format)
that the hosted platform persists for a stored method's `.mthds` source and its custom
PipeFunc `python`. One canonical type plus one (de)serializer, so every Python consumer —
`pipelex-sdk`, an MCP server, a client that fetches a stored method and wants its bundle
back — agrees on the shape instead of each re-porting the platform's decoder and drifting.
The TypeScript twin exists for the same reason on its side; the two are held to the same
behaviour, edge for edge, and the test suite pins the Python side against bytes produced by
running the twin.

This is the AT-REST catalog representation and is distinct from the run-surface `files`
map (an unordered path-to-text mapping on a run request): the catalog stores an ordered,
named ARRAY. The empty list is serialized as the empty string `""` — the platform's "no
source" / "clear the field" sentinel — never as the literal `"[]"`.

Four rules a port gets wrong while still round-tripping the happy case, all stated here:

- **Blank means ECMAScript-blank.** A file carries no source when its content is empty or
  whitespace-only, and "whitespace" is what `String.prototype.trim` strips — the closed set
  in `_ECMASCRIPT_TRIM_CHARS` below — not what Python's `str.isspace` says. The two sets
  disagree at both ends: Python strips U+001C to U+001F and U+0085, which the twin keeps as
  content; the twin strips the byte-order mark U+FEFF, which Python keeps. A file the twin
  drops must be a file this side drops, so the predicate is spelled out rather than borrowed
  from `str.strip()`, and a test derives it from the Unicode categories rather than sampling it.
- **The bytes are `JSON.stringify`'s.** Compact separators, non-ASCII text left as UTF-8, and
  only the characters JSON requires escaped. Python's `json.dumps` defaults to spaced
  separators and backslash-u escapes for anything outside ASCII: same value, different bytes,
  and an at-rest representation that hashes or compares differently on the two sides.
- **An unpaired surrogate is the one code point `ensure_ascii=False` still gets wrong.** It
  writes the raw code point, and the resulting string cannot be encoded as UTF-8 at all, so it
  fails at the storage boundary rather than at this typed surface; the twin's well-formed
  `JSON.stringify` escapes it. `_escape_lone_surrogates` reapplies that escape after the dump.
- **`json.loads` accepts three constants `JSON.parse` refuses.** `NaN`, `Infinity` and
  `-Infinity` are a Python extension to JSON. A catalog string carrying one anywhere parses here
  and throws in the twin — and an ignored extra member is the case that bites, because no later
  shape check ever looks there. `parse_constant` refuses all three, so the two sides cannot
  return opposite verdicts on identical bytes.

Where this deliberately departs from the platform's own decoder (`method_source_to_contents`
and `parse_stored_files` in `pipelex-server`'s platform member), it follows the twin, so that
the three implementations do not split two against one:

- The platform has no blank-source guard on the contents path at all — `method_source_to_contents`
  goes straight to `json.loads` and hands back the raw string when that fails — so a
  whitespace-only raw source becomes a whitespace bundle there and fails downstream at the TOML
  parse; here, as in the twin, it is "no source".
- The platform's own blankness is Python's `str.strip()`, so it disagrees with the twin in both
  directions on an entry's content: a BOM-only file is content to the platform and blank here,
  while a file of U+001C to U+001F or U+0085 is blank to the platform and content here. Here, as
  in the twin, blankness is ECMAScript's.
- The platform drops an entry whose `name` is blank; here, as in the twin, the name is not
  inspected — only a blank `content` drops an entry.
- The platform treats a source that is not the file-array form as one legacy bare bundle, reads
  a whole array as one such bundle as soon as a single entry is malformed, and drops an entry
  whose `content` is not a string while keeping the rest. Here, as in the twin, every one of
  those is a contract violation of this typed surface, and **this package does not decode the
  legacy bare-bundle shape at all**: a consumer holding one of the platform's very old
  plain-string rows must handle the `PipelineRequestError` itself, because the catalog
  file-array is always the named-array form.

Two obligations this surface does not discharge, which its consumers therefore own:

- **A `name` is untrusted text, not a checked path.** Neither this module nor the twin validates
  it, so `../../../etc/passwd`, an absolute path, a Windows path and the empty string all
  round-trip untouched. Anything that materializes a catalog to disk must check containment
  itself; this module only preserves what the catalog held.
- **Duplicate names are kept here and refused downstream.** The catalog form permits them, and
  the platform rejects a method whose `.mthds` and `.py` file names collide, so uniqueness is
  the producer's obligation rather than something a parse will tell it about.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, NoReturn, cast

from pydantic import BaseModel, ConfigDict

from mthds.protocol.exceptions import PipelineRequestError

if TYPE_CHECKING:
    from collections.abc import Sequence


class MethodFile(BaseModel):
    """One named source file of a method bundle: a bundle-relative path and its text.

    A closed, strict shape — a consumer building one gets exactly `name` and `content`, both
    strings. Leniency toward what the wire carries (extra members, which are tolerated and
    stripped) belongs to `parse_method_files`, not to the type.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    name: str
    """Bundle-relative path, e.g. `"funcs/price.py"` or `"bundle.mthds"`.

    Untrusted text, preserved exactly as the catalog held it: neither this type nor the twin
    checks that it is in fact relative, so a consumer writing it to disk validates containment.
    """

    content: str
    """The file's UTF-8 text content."""


# The code points ECMAScript's `String.prototype.trim` strips — WhiteSpace (TAB, VT, FF, SP,
# NBSP, ZWNBSP and every Zs-category character) plus the four LineTerminators — spelled out
# so the blank predicate is the twin's, not `str.isspace`'s. Python's set is wider on the
# control side (it strips U+001C to U+001F and U+0085, which JavaScript keeps) and narrower at
# U+FEFF (which JavaScript strips); the tests pin every one of those disagreements, and one of
# them derives this set from the Unicode categories so a dropped code point cannot pass.
_ECMASCRIPT_TRIM_CHARS = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def _is_blank(text: str) -> bool:
    """A file carries no source when its content is empty or ECMAScript-whitespace-only."""
    return text.strip(_ECMASCRIPT_TRIM_CHARS) == ""


# Every surrogate code point in a Python `str` is inherently unpaired — an astral character is
# one code point, never a pair — and `json.dumps(ensure_ascii=False)` writes such a code point
# raw, producing a `str` that cannot be encoded as UTF-8 at all. The twin's `JSON.stringify` has
# escaped it since ES2019 (well-formed stringify), so the escape is reapplied after the dump.
_LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")


def _escape_lone_surrogates(dumped: str) -> str:
    """Escape unpaired surrogates the way `JSON.stringify` does, leaving every other character raw."""
    return _LONE_SURROGATE.sub(lambda match: f"\\u{ord(match.group()):04x}", dumped)


def _refuse_json_constant(constant: str) -> NoReturn:
    """Refuse the three constants `json.loads` accepts as an extension and `JSON.parse` rejects."""
    msg = f"Method file source is not valid JSON; expected a [{{ name, content }}] array (got `{constant}`)."
    raise PipelineRequestError(msg)


def serialize_method_files(files: Sequence[MethodFile]) -> str:
    """Serialize method files to the canonical catalog string.

    Blank-content entries are dropped (a zero-source file is not persisted), so the canonical
    form never carries an empty file — which also means a list of nothing but blank files and an
    empty list are the same call, both signalling "clear the stored source". An empty result
    serializes to `""` — the platform's "no source" / "clear the field" signal — not `"[]"`. The
    bytes are those of the twin's `JSON.stringify`: compact, UTF-8 left as is, only the
    JSON-mandated escapes, and an unpaired surrogate escaped rather than written raw.

    Args:
        files: The files, in the order they are to be stored.

    Returns:
        The catalog string, or `""` when no file carries source.
    """
    kept: list[dict[str, str]] = [
        {"name": method_file.name, "content": method_file.content} for method_file in files if not _is_blank(method_file.content)
    ]
    if not kept:
        return ""
    return _escape_lone_surrogates(json.dumps(kept, ensure_ascii=False, separators=(",", ":")))


def parse_method_files(source: str | None) -> list[MethodFile]:
    """Parse the canonical catalog string back into method files.

    A blank source (`""` / whitespace / `None`) and an empty JSON array both yield `[]`. A JSON
    `[{ name, content }]` array yields those files in order, with blank-content entries dropped
    (mirroring serialization, so the round-trip is stable) and any extra member of an entry
    ignored. Duplicate names are kept, and a blank name is not a reason to drop an entry.

    Anything else — a non-array JSON value, an array entry that is not an object with string
    `name` and string `content`, unparseable text (a legacy raw bundle string included), one of
    the three constants `json.loads` accepts as an extension and `JSON.parse` refuses (`NaN`,
    `Infinity`, `-Infinity`), or nesting deep enough to exhaust the decoder — is a contract
    violation for this typed surface and raises `PipelineRequestError`.

    Args:
        source: The stored catalog string, or `None` for a field that was never set.

    Returns:
        The files the catalog holds, in stored order.
    """
    if source is None or _is_blank(source):
        return []

    parsed: Any
    try:
        parsed = json.loads(source, parse_constant=_refuse_json_constant)
    except (json.JSONDecodeError, RecursionError) as exc:
        msg = "Method file source is not valid JSON; expected a [{ name, content }] array."
        raise PipelineRequestError(msg) from exc

    if not isinstance(parsed, list):
        msg = "Method file source must be a JSON array of { name, content } entries."
        raise PipelineRequestError(msg)

    files: list[MethodFile] = []
    for entry in cast("list[Any]", parsed):
        method_file = _method_file_from_entry(entry)
        if method_file is None:
            msg = "Each method file entry must be an object with string `name` and string `content`."
            raise PipelineRequestError(msg)
        if not _is_blank(method_file.content):
            files.append(method_file)
    return files


def _method_file_from_entry(entry: Any) -> MethodFile | None:
    """Read one array entry as a file, or `None` when it is not the `{ name, content }` shape.

    Only the two members are read and both must be strings; anything else the entry carries
    is ignored, as the twin ignores it.
    """
    if not isinstance(entry, dict):
        return None
    members = cast("dict[str, Any]", entry)
    name = members.get("name")
    content = members.get("content")
    if not isinstance(name, str) or not isinstance(content, str):
        return None
    return MethodFile(name=name, content=content)
