"""The file entry, the form a tree travels in, and a receiver's reading of a map of file entries.

A tree travels as a JSON object mapping each tree path to an entry in one of these forms
(`mthds/docs/spec/method-tree.md`, "The File Entry"):

- a string, the file's text, whose bytes are its UTF-8 encoding exactly;
- `{"base64": "…"}`, any bytes, in canonical padded standard Base64;
- `{"sha256": "…", "size": …}`, bytes the receiver already holds in its blob store.

A receiver reads the map from the JSON text it parses, never from an already-decoded dictionary,
because some refusals are only visible in the text: a key given twice, and a `size` written with a
fraction or an exponent.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from typing import Any, NamedTuple, Protocol, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from typing_extensions import override

from mthds.method_tree.digest import is_sha256_hex, sha256_hex, tree_digest, tree_files_from_contents
from mthds.method_tree.discovery import DEFAULT_DIRECTORY_NAMES, MANIFEST_NAME, VENV_MARKER_NAME
from mthds.method_tree.exceptions import MethodTreeRefusedError, TreeRefusal, TreeSourceError
from mthds.method_tree.models import MethodTree
from mthds.method_tree.tree_path import path_collisions, sorted_tree_paths, tree_path_violation
from mthds.method_tree.vocabulary import TreeRefusalCode

# How deeply a map of file entries may nest, a bound of this receiver's own: a map nests two
# levels deep, and Python's own decoder gives up at a depth that varies from one version to the
# next (none at all from 3.14 on), so the receiver bounds it below every decoder's limit and
# answers the same on every supported Python.
MAX_JSON_DEPTH = 64

BASE64_KEY = "base64"
SHA256_KEY = "sha256"
SIZE_KEY = "size"


def decode_canonical_base64(encoded: str) -> bytes:
    """Decode padded standard Base64 (RFC 4648 section 4) with no line break, whose padding bits are zero.

    Canonical means each byte string has one encoding: `aGk=` is `hi`, while `aGl=`, which a
    lenient decoder also reads as `hi`, is refused.

    Raises:
        ValueError: When `encoded` is not canonical padded standard Base64.
    """
    try:
        decoded = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        msg = "not padded standard Base64"
        raise ValueError(msg) from exc
    if base64.b64encode(decoded).decode("ascii") != encoded:
        msg = "not canonical Base64: its padding bits are not zero"
        raise ValueError(msg)
    return decoded


class Base64FileEntry(BaseModel):
    """A file entry carrying any bytes in canonical padded standard Base64."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    base64: str

    @field_validator("base64")
    @classmethod
    def validate_canonical(cls, value: str) -> str:
        decode_canonical_base64(value)
        return value

    @classmethod
    def make_from_bytes(cls, data: bytes) -> Base64FileEntry:
        return cls(base64=base64.b64encode(data).decode("ascii"))

    @property
    def data(self) -> bytes:
        return decode_canonical_base64(self.base64)


class HashFileEntry(BaseModel):
    """A file entry naming bytes the receiver already holds, by their SHA-256 and their size."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    sha256: str
    # Strict, so a size `json` read as a float, being written with a fraction or an exponent, or a
    # boolean is refused: that is the one check of this form only the raw text decides.
    size: int = Field(ge=0)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not is_sha256_hex(value):
            msg = "not 64 lowercase hexadecimal digits"
            raise ValueError(msg)
        return value

    @classmethod
    def make_from_bytes(cls, data: bytes) -> HashFileEntry:
        return cls(sha256=sha256_hex(data), size=len(data))


FileEntry: TypeAlias = str | Base64FileEntry | HashFileEntry
"""One file of a tree as it travels: its text, its bytes in Base64, or the hash of bytes the receiver holds.

`pydantic_core.to_json` writes each form as the wire has it: the string itself, `{"base64": …}`, and
`{"sha256": …, "size": …}`.
"""

MethodFiles: TypeAlias = Mapping[str, FileEntry]
"""A method tree as it travels, the MTHDS Protocol's `files`: a map from tree path to file entry, holding at least one file."""


def encode_file_entry(data: bytes, *, by_hash: bool = False) -> FileEntry:
    """The entry a sender writes for a file's bytes.

    Args:
        data: The file's bytes.
        by_hash: Whether to name the bytes by hash, for a receiver known to hold them already.

    Returns:
        A hash entry when `by_hash`, else the text when the bytes are UTF-8, else a Base64 entry.
    """
    if by_hash:
        return HashFileEntry.make_from_bytes(data)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return Base64FileEntry.make_from_bytes(data)


def encode_file_map(contents: Mapping[str, bytes], *, held_by_receiver: frozenset[str] | None = None) -> dict[str, FileEntry]:
    """The map of file entries a sender writes for a tree whose bytes it holds, keyed by tree path in tree path order.

    Args:
        contents: Each file's bytes, by tree path.
        held_by_receiver: The SHA-256 hashes, in lowercase hexadecimal, of the bytes the receiver
            already holds; those files are sent by hash. None for a receiver holding none.
    """
    held = held_by_receiver or frozenset()
    return {
        tree_path: encode_file_entry(contents[tree_path], by_hash=sha256_hex(contents[tree_path]) in held)
        for tree_path in sorted_tree_paths(contents)
    }


class BlobStore(Protocol):
    """The bytes a receiver already holds, by their SHA-256."""

    def read_blob(self, sha256: str) -> bytes | None:
        """The bytes whose SHA-256 is `sha256`, in lowercase hexadecimal, or None when the store does not hold them."""
        ...


class InMemoryBlobStore(BlobStore):
    """A blob store holding its bytes in memory, keyed by their SHA-256."""

    def __init__(self, blobs: list[bytes] | None = None) -> None:
        self._blobs: dict[str, bytes] = {}
        for blob in blobs or []:
            self.add(blob)

    def add(self, data: bytes) -> str:
        """Store `data` and return its SHA-256."""
        digest = sha256_hex(data)
        self._blobs[digest] = data
        return digest

    @override
    def read_blob(self, sha256: str) -> bytes | None:
        return self._blobs.get(sha256)


class _JsonObject(NamedTuple):
    """A JSON object as the key and value pairs it was written with, in document order, a key given twice included."""

    pairs: list[tuple[str, Any]]


_ENTRY_FORMS: dict[frozenset[str], type[Base64FileEntry | HashFileEntry]] = {
    frozenset({BASE64_KEY}): Base64FileEntry,
    frozenset({SHA256_KEY, SIZE_KEY}): HashFileEntry,
}


def _refuse_json_constant(constant: str) -> Any:
    """Refuse `NaN`, `Infinity` and `-Infinity`, which `json.loads` accepts as an extension and JSON does not hold."""
    msg = f"{constant} is not a JSON value"
    raise ValueError(msg)


def _parse_keeping_pairs(document: str) -> Any:
    return json.loads(document, object_pairs_hook=_JsonObject, parse_constant=_refuse_json_constant)


def _json_depth(parsed: Any) -> int:
    """How deeply a decoded document nests arrays and objects, a scalar at the top being depth zero; walked without recursion."""
    deepest = 0
    pending: list[tuple[Any, int]] = [(parsed, 0)]
    while pending:
        node, depth = pending.pop()
        children: list[Any]
        if isinstance(node, _JsonObject):
            children = [value for _key, value in node.pairs]
        elif isinstance(node, list):
            children = cast("list[Any]", node)
        else:
            continue
        deepest = max(deepest, depth + 1)
        pending.extend((child, depth + 1) for child in children)
    return deepest


def excluded_name_violation(key: str) -> bool:
    """Whether a tree path names a file the membership rule could never admit.

    That is one holding a segment starting with a dot, one inside a `__pycache__` or `node_modules`
    directory, a file named `pyvenv.cfg`, or a `METHODS.toml` file anywhere but at the root.
    """
    segments = key.split("/")
    if any(segment.startswith(".") for segment in segments):
        return True
    if any(segment in DEFAULT_DIRECTORY_NAMES for segment in segments[:-1]):
        return True
    if segments[-1] == VENV_MARKER_NAME:
        return True
    return segments[-1] == MANIFEST_NAME and len(segments) > 1


class FileMapReading(NamedTuple):
    """A map of file entries a receiver accepted: the tree it carries, and each file's bytes by tree path."""

    tree: MethodTree
    contents: dict[str, bytes]


def _refusal(code: TreeRefusalCode, *, names: list[str], explanation: str) -> MethodTreeRefusedError:
    msg = f"The map of file entries is refused: {explanation}"
    return MethodTreeRefusedError(msg, refusal=TreeRefusal(code=code, names=names))


def read_file_map(document: str, *, blob_store: BlobStore | None = None) -> FileMapReading:
    """Read a map of file entries from its JSON text, as a receiver of a request's `files` field reads it.

    The checks run in this order, the first failing one deciding the refusal: a key given twice,
    a key that is not a tree path, a key the membership rule could never admit, keys that collide,
    an empty map, then each entry in document order (malformed, or an entry object giving a key
    twice), and last every hash entry whose bytes the blob store does not hold at the stated size,
    all of them named at once.

    Args:
        document: The JSON text of the map.
        blob_store: The bytes the receiver holds; None for a receiver holding none.

    Raises:
        MethodTreeRefusedError: When the standard refuses the map; its `refusal.code` says why.
        TreeSourceError: When `document` is not JSON text holding an object.
    """
    too_deep = f"The map of file entries is not JSON text this receiver can read: it nests deeper than {MAX_JSON_DEPTH} levels."
    try:
        parsed = _parse_keeping_pairs(document)
    except RecursionError as exc:
        # Python 3.13 and earlier give up on deep nesting at a depth of their own, above the bound.
        raise TreeSourceError(too_deep) from exc
    except ValueError as exc:
        # A syntax error, a constant JSON does not hold, or an integer longer than Python converts.
        msg = f"The map of file entries is not JSON text this receiver can read: {exc}"
        raise TreeSourceError(msg) from exc
    if _json_depth(parsed) > MAX_JSON_DEPTH:
        raise TreeSourceError(too_deep)
    if not isinstance(parsed, _JsonObject):
        msg = "The map of file entries must be a JSON object."
        raise TreeSourceError(msg)
    seen: set[str] = set()
    for key, _value in parsed.pairs:
        if key in seen:
            raise _refusal(TreeRefusalCode.DUPLICATE_KEY, names=[key], explanation=f"the key {key!r} is given twice.")
        seen.add(key)
    for key, _value in parsed.pairs:
        violation = tree_path_violation(key)
        if violation is not None:
            raise _refusal(TreeRefusalCode.INVALID_TREE_PATH, names=[key], explanation=f"the key {key!r} is not a tree path: {violation}.")
    for key, _value in parsed.pairs:
        if excluded_name_violation(key):
            explanation = f"the key {key!r} names a file the membership rule keeps out of every tree."
            raise _refusal(TreeRefusalCode.EXCLUDED_NAME, names=[key], explanation=explanation)
    keys = [key for key, _value in parsed.pairs]
    colliding = path_collisions(keys)
    if colliding:
        explanation = f"keys collide once case-folded, or one names a directory of another: {', '.join(repr(key) for key in colliding)}."
        raise _refusal(TreeRefusalCode.PATH_COLLISION, names=colliding, explanation=explanation)
    if not parsed.pairs:
        raise _refusal(TreeRefusalCode.EMPTY_TREE, names=[], explanation="it holds no file, and a method tree holds at least one.")
    contents: dict[str, bytes] = {}
    missing: set[str] = set()
    for key, entry in parsed.pairs:
        data = _entry_bytes(key=key, entry=entry, blob_store=blob_store, missing=missing)
        if data is not None:
            contents[key] = data
    if missing:
        names = sorted(missing)
        explanation = f"the receiver does not hold the bytes these hash entries name, at their stated size: {', '.join(names)}."
        raise _refusal(TreeRefusalCode.MISSING_BLOB, names=names, explanation=explanation)
    files = tree_files_from_contents(contents)
    return FileMapReading(tree=MethodTree(files=files, digest=tree_digest(files)), contents=contents)


def _entry_bytes(*, key: str, entry: Any, blob_store: BlobStore | None, missing: set[str]) -> bytes | None:
    """An entry's bytes; None for a hash entry the store lacks, whose hash is added to `missing`."""
    if isinstance(entry, str):
        try:
            return entry.encode("utf-8")
        except UnicodeEncodeError as exc:
            refused = _refusal(
                TreeRefusalCode.MALFORMED_ENTRY, names=[key], explanation=f"the text of {key!r} holds a code point UTF-8 cannot encode."
            )
            raise refused from exc
    if not isinstance(entry, _JsonObject):
        raise _refusal(TreeRefusalCode.MALFORMED_ENTRY, names=[key], explanation=f"the entry of {key!r} is neither a string nor an object.")
    entry_keys = [entry_key for entry_key, _value in entry.pairs]
    if len(set(entry_keys)) != len(entry_keys):
        raise _refusal(TreeRefusalCode.DUPLICATE_KEY, names=[key], explanation=f"the entry of {key!r} gives one of its keys twice.")
    form = _ENTRY_FORMS.get(frozenset(entry_keys))
    if form is None:
        explanation = f"the entry of {key!r} is neither a base64 object nor a sha256 and size object."
        raise _refusal(TreeRefusalCode.MALFORMED_ENTRY, names=[key], explanation=explanation)
    try:
        validated = form.model_validate(dict(entry.pairs))
    except ValidationError as exc:
        reasons = "; ".join(f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors())
        refused = _refusal(TreeRefusalCode.MALFORMED_ENTRY, names=[key], explanation=f"the entry of {key!r} is malformed ({reasons}).")
        raise refused from exc
    if isinstance(validated, Base64FileEntry):
        return validated.data
    held = blob_store.read_blob(validated.sha256) if blob_store is not None else None
    if held is None or len(held) != validated.size:
        missing.add(validated.sha256)
        return None
    return held
