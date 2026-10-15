"""Git's ignore patterns, read and matched exactly as git reads and matches them.

The membership rule reads the tree's `.gitignore` files and the manifest's `[package] exclude`
patterns "with git's own semantics" and matches them "byte for byte, letter case included, as git
matches with `core.ignoreCase` off" (`mthds/docs/spec/method-tree.md`, "The Membership Rule").
This module is a port of the two pieces of git that define those semantics, so that no library's
reading of `.gitignore` can differ from git's:

- `dir.c`: how a pattern file is split into patterns (`add_patterns_from_buffer`,
  `trim_trailing_spaces`, `parse_path_pattern`), and how a pattern is matched against a path
  (`match_basename`, `match_pathname`, `last_matching_pattern_from_list`).
- `wildmatch.c`: the glob matcher, run on the UTF-8 bytes of a path as git runs it, so `?` matches
  one byte, not one character, and a bracket expression is a set of bytes.

A gitignore library working on characters (such as `pathspec`) differs from git on exactly those
points, and on the precedence of nested files, which this module leaves to the lister: the lister
asks the deepest file first and stops at the first that matches, as git's exclude stack does.

Patterns are normalized to NFC before they are parsed, and paths are matched as their NFC tree
paths, as the standard asks.
"""

from __future__ import annotations

from typing import NamedTuple

from mthds.method_tree.tree_path import nfc

# The return values of git's `dowild`.
_WM_MATCH = 0
_WM_NOMATCH = 1
_WM_ABORT_ALL = -1
_WM_ABORT_TO_STARSTAR = -2

_NUL = 0
_SLASH = ord("/")
_BACKSLASH = ord("\\")
_STAR = ord("*")
_QUESTION = ord("?")
_LEFT_BRACKET = ord("[")
_RIGHT_BRACKET = ord("]")
_BANG = ord("!")
_CARET = ord("^")
_DASH = ord("-")
_COLON = ord(":")
_SPACE = ord(" ")
_HASH = ord("#")
_CARRIAGE_RETURN = ord("\r")

UTF8_BOM = b"\xef\xbb\xbf"

# The characters git's `is_glob_special` names.
_GLOB_SPECIAL = frozenset({_STAR, _QUESTION, _LEFT_BRACKET, _BACKSLASH})


def _byte_at(data: bytes, index: int) -> int:
    """The byte at `index`, or NUL past the end, as a C string reads."""
    if index < len(data):
        return data[index]
    return _NUL


# ── git's ctype, ASCII only (git-compat-util.h and ctype.c) ─────────────────────


def _is_alpha(byte: int) -> bool:
    return ord("a") <= byte <= ord("z") or ord("A") <= byte <= ord("Z")


def _is_digit(byte: int) -> bool:
    return ord("0") <= byte <= ord("9")


def _is_space(byte: int) -> bool:
    # git's `isspace` is tab, line feed, carriage return and space, not the vertical tab or form feed.
    return byte in {0x09, 0x0A, 0x0D, 0x20}


def _is_print(byte: int) -> bool:
    return 0x20 <= byte <= 0x7E


def _is_cntrl(byte: int) -> bool:
    return byte < 0x20 or byte == 0x7F


def _is_punct(byte: int) -> bool:
    return _is_print(byte) and not _is_alpha(byte) and not _is_digit(byte) and byte != _SPACE


def _is_xdigit(byte: int) -> bool:
    return _is_digit(byte) or ord("a") <= byte <= ord("f") or ord("A") <= byte <= ord("F")


def _character_class_matches(name: bytes, byte: int) -> bool | None:
    """Whether `byte` is in the POSIX class `name`, or None for a class git does not know."""
    match name:
        case b"alnum":
            return _is_alpha(byte) or _is_digit(byte)
        case b"alpha":
            return _is_alpha(byte)
        case b"blank":
            return byte in {_SPACE, 0x09}
        case b"cntrl":
            return _is_cntrl(byte)
        case b"digit":
            return _is_digit(byte)
        case b"graph":
            return _is_print(byte) and not _is_space(byte)
        case b"lower":
            return ord("a") <= byte <= ord("z")
        case b"print":
            return _is_print(byte)
        case b"punct":
            return _is_punct(byte)
        case b"space":
            return _is_space(byte)
        case b"upper":
            return ord("A") <= byte <= ord("Z")
        case b"xdigit":
            return _is_xdigit(byte)
        case _:
            return None


# ── wildmatch.c ───────────────────────────────────────────────────────────────


def _match_bracket(pattern: bytes, p_index: int, t_ch: int, *, pathname: bool) -> tuple[int, int]:
    """Match one text byte against the bracket expression opening at `pattern[p_index]`.

    Returns the index of the expression's closing `]` and `_WM_MATCH`, or an index and the result
    that ends the whole match.
    """
    p_index += 1
    p_ch = _byte_at(pattern, p_index)
    if p_ch == _CARET:
        p_ch = _BANG
    negated = p_ch == _BANG
    if negated:
        p_index += 1
        p_ch = _byte_at(pattern, p_index)
    prev_ch = _NUL
    matched = False
    while True:
        if p_ch == _NUL:
            return p_index, _WM_ABORT_ALL
        if p_ch == _BACKSLASH:
            p_index += 1
            p_ch = _byte_at(pattern, p_index)
            if p_ch == _NUL:
                return p_index, _WM_ABORT_ALL
            if t_ch == p_ch:
                matched = True
        elif p_ch == _DASH and prev_ch != _NUL and _byte_at(pattern, p_index + 1) not in {_NUL, _RIGHT_BRACKET}:
            p_index += 1
            p_ch = _byte_at(pattern, p_index)
            if p_ch == _BACKSLASH:
                p_index += 1
                p_ch = _byte_at(pattern, p_index)
                if p_ch == _NUL:
                    return p_index, _WM_ABORT_ALL
            if prev_ch <= t_ch <= p_ch:
                matched = True
            p_ch = _NUL
        elif p_ch == _LEFT_BRACKET and _byte_at(pattern, p_index + 1) == _COLON:
            class_start = p_index + 2
            p_index = class_start
            while _byte_at(pattern, p_index) not in {_NUL, _RIGHT_BRACKET}:
                p_index += 1
            if _byte_at(pattern, p_index) == _NUL:
                return p_index, _WM_ABORT_ALL
            class_length = p_index - class_start - 1
            if class_length < 0 or pattern[p_index - 1] != _COLON:
                # No ":]": the "[" is an ordinary member of the set, and the scan resumes after it.
                p_index = class_start - 2
                p_ch = _LEFT_BRACKET
                if t_ch == p_ch:
                    matched = True
            else:
                in_class = _character_class_matches(pattern[class_start : class_start + class_length], t_ch)
                if in_class is None:
                    return p_index, _WM_ABORT_ALL
                if in_class:
                    matched = True
                p_ch = _NUL
        elif t_ch == p_ch:
            matched = True
        prev_ch = p_ch
        p_index += 1
        p_ch = _byte_at(pattern, p_index)
        if p_ch == _RIGHT_BRACKET:
            break
    if matched == negated or (pathname and t_ch == _SLASH):
        return p_index, _WM_NOMATCH
    return p_index, _WM_MATCH


def _dowild(pattern: bytes, p_index: int, text: bytes, t_index: int, *, pathname: bool) -> int:
    """Git's `dowild`: match `pattern[p_index:]` against `text[t_index:]`, with `WM_PATHNAME` when `pathname`."""
    while _byte_at(pattern, p_index) != _NUL:
        p_ch = _byte_at(pattern, p_index)
        t_ch = _byte_at(text, t_index)
        if t_ch == _NUL and p_ch != _STAR:
            return _WM_ABORT_ALL
        if p_ch == _BACKSLASH:
            # A literal match with the next character; a trailing backslash matches nothing.
            p_index += 1
            if t_ch != _byte_at(pattern, p_index):
                return _WM_NOMATCH
        elif p_ch == _QUESTION:
            if pathname and t_ch == _SLASH:
                return _WM_NOMATCH
        elif p_ch == _STAR:
            outcome = _match_star(pattern, p_index, text, t_index, pathname=pathname)
            if isinstance(outcome, int):
                return outcome
            p_index, t_index = outcome
        elif p_ch == _LEFT_BRACKET:
            p_index, result = _match_bracket(pattern, p_index, t_ch, pathname=pathname)
            if result != _WM_MATCH:
                return result
        elif t_ch != p_ch:
            return _WM_NOMATCH
        p_index += 1
        t_index += 1
    if t_index < len(text):
        return _WM_NOMATCH
    return _WM_MATCH


def _match_star(pattern: bytes, p_index: int, text: bytes, t_index: int, *, pathname: bool) -> int | tuple[int, int]:
    """The `*` case of `dowild`: a final result, or the indices to resume at when a single `*` consumed up to a `/`."""
    match_slash: bool
    p_index += 1
    if _byte_at(pattern, p_index) == _STAR:
        prev_p = p_index - 2
        while _byte_at(pattern, p_index) == _STAR:
            p_index += 1
        following = _byte_at(pattern, p_index)
        if not pathname:
            match_slash = True
        elif (prev_p < 0 or pattern[prev_p] == _SLASH) and (
            following in {_NUL, _SLASH} or (following == _BACKSLASH and _byte_at(pattern, p_index + 1) == _SLASH)
        ):
            # A "**/" may match no directory at all: try the rest of the pattern right here first.
            if following == _SLASH and _dowild(pattern, p_index + 1, text, t_index, pathname=pathname) == _WM_MATCH:
                return _WM_MATCH
            match_slash = True
        else:
            match_slash = False
    else:
        match_slash = not pathname
    following = _byte_at(pattern, p_index)
    if following == _NUL:
        # A trailing "**" matches everything; a trailing "*" only what holds no more slash.
        if not match_slash and _SLASH in text[t_index:]:
            return _WM_ABORT_TO_STARSTAR
        return _WM_MATCH
    if not match_slash and following == _SLASH:
        # A single "*" followed by a slash matches up to the next slash of the text.
        slash_index = text.find(b"/", t_index)
        if slash_index == -1:
            return _WM_NOMATCH
        return p_index, slash_index
    t_ch = _byte_at(text, t_index)
    while t_ch != _NUL:
        if following not in _GLOB_SPECIAL:
            # The text before the next literal must belong to the star: skip to it.
            while True:
                t_ch = _byte_at(text, t_index)
                if t_ch in {_NUL, following} or (not match_slash and t_ch == _SLASH):
                    break
                t_index += 1
            if t_ch != following:
                return _WM_ABORT_ALL if match_slash else _WM_ABORT_TO_STARSTAR
        matched = _dowild(pattern, p_index, text, t_index, pathname=pathname)
        if matched != _WM_NOMATCH:
            if not match_slash or matched != _WM_ABORT_TO_STARSTAR:
                return matched
        elif not match_slash and t_ch == _SLASH:
            return _WM_ABORT_TO_STARSTAR
        t_index += 1
        t_ch = _byte_at(text, t_index)
    return _WM_ABORT_ALL


def wildmatch(pattern: bytes, text: bytes, *, pathname: bool) -> bool:
    """Git's `wildmatch` without case folding: whether the glob `pattern` matches `text`, both as bytes.

    With `pathname`, `*`, `?` and a bracket expression never match a `/`, and `**` matches across
    directories where a slash or an end of pattern bounds it.
    """
    return _dowild(pattern, 0, text, 0, pathname=pathname) == _WM_MATCH


# ── dir.c ─────────────────────────────────────────────────────────────────────


class GitPattern(NamedTuple):
    """One parsed pattern line, as git's `parse_path_pattern` leaves it."""

    pattern: bytes
    negative: bool
    must_be_dir: bool
    no_dir: bool
    ends_with: bool
    no_wildcard_length: int


def _simple_length(pattern: bytes) -> int:
    """The length of the pattern's leading run holding no glob special character."""
    for index_byte, byte in enumerate(pattern):
        if byte in _GLOB_SPECIAL:
            return index_byte
    return len(pattern)


def _trim_trailing_spaces(line: bytes) -> bytes:
    """Git's `trim_trailing_spaces`: drop trailing spaces, but not a space a backslash escapes, nor a tab."""
    last_space: int | None = None
    index_byte = 0
    while index_byte < len(line):
        byte = line[index_byte]
        if byte == _SPACE:
            if last_space is None:
                last_space = index_byte
        elif byte == _BACKSLASH:
            index_byte += 1
            if index_byte >= len(line):
                return line
            last_space = None
        else:
            last_space = None
        index_byte += 1
    if last_space is not None:
        return line[:last_space]
    return line


def parse_pattern(line: bytes) -> GitPattern | None:
    """Git's `parse_path_pattern` on one line already stripped of its line ending; None for an empty pattern, which matches nothing."""
    negative = line.startswith(b"!")
    body = line[1:] if negative else line
    must_be_dir = body.endswith(b"/")
    if must_be_dir:
        body = body[:-1]
    if not body:
        return None
    no_dir = b"/" not in body
    no_wildcard_length = _simple_length(body)
    ends_with = body.startswith(b"*") and _simple_length(body[1:]) == len(body) - 1
    return GitPattern(
        pattern=body,
        negative=negative,
        must_be_dir=must_be_dir,
        no_dir=no_dir,
        ends_with=ends_with,
        no_wildcard_length=no_wildcard_length,
    )


def parse_pattern_lines(data: bytes) -> list[GitPattern]:
    """Git's `add_patterns_from_buffer`: the patterns of a pattern file's bytes, in file order.

    Lines split at line feeds; a line that is empty or starts with `#` is skipped; a carriage
    return before the line feed is dropped, then trailing spaces; a NUL ends a pattern, as it
    ends a C string.
    """
    patterns: list[GitPattern] = []
    for raw_line in data.split(b"\n"):
        if not raw_line or raw_line.startswith(b"#"):
            continue
        line = raw_line[:-1] if raw_line.endswith(b"\r") else raw_line
        nul_index = line.find(b"\0")
        if nul_index != -1:
            line = line[:nul_index]
        parsed = parse_pattern(_trim_trailing_spaces(line))
        if parsed is not None:
            patterns.append(parsed)
    return patterns


def _match_basename(pattern: GitPattern, basename: bytes) -> bool:
    """Git's `match_basename`, its literal and `*literal` shortcuts included."""
    if pattern.no_wildcard_length == len(pattern.pattern):
        return basename == pattern.pattern
    if pattern.ends_with:
        return basename.endswith(pattern.pattern[1:])
    return wildmatch(pattern.pattern, basename, pathname=False)


def _match_pathname(pattern: GitPattern, relative_path: bytes) -> bool:
    """Git's `match_pathname` on a path already relative to the directory of the file holding the pattern.

    Git compares the pattern's literal prefix first and hands only the rest to `wildmatch`, which
    is not always the same as matching the whole pattern: a `**` the prefix ends right before is
    then at the start of what `wildmatch` sees, so `a/foo**/x` matches `a/fooz/y/x` in git. The
    prefix is compared the same way here.
    """
    body = pattern.pattern
    prefix = pattern.no_wildcard_length
    if body.startswith(b"/"):
        body = body[1:]
        prefix -= 1
    name = relative_path
    if prefix:
        if prefix > len(name) or body[:prefix] != name[:prefix]:
            return False
        body = body[prefix:]
        name = name[prefix:]
        if not body and not name:
            return True
    return wildmatch(body, name, pathname=True)


class PatternList:
    """The patterns of one source, a `.gitignore` file or the manifest's exclude list, with the directory they apply from.

    Args:
        patterns: The patterns in source order.
        base: The tree path of the directory holding the source, `""` for the root.
    """

    def __init__(self, patterns: list[GitPattern], *, base: str) -> None:
        self.patterns = patterns
        self.base = base
        self._prefix = f"{base}/".encode("utf-8", errors="surrogateescape") if base else b""

    @classmethod
    def make_from_bytes(cls, data: bytes, *, base: str) -> PatternList:
        """Read a `.gitignore` file's bytes: skip a leading byte order mark, decode as UTF-8, normalize to NFC.

        Raises:
            UnicodeDecodeError: When the bytes, past a leading byte order mark, are not UTF-8.
        """
        body = data.removeprefix(UTF8_BOM)
        text = body.decode("utf-8")
        return cls(parse_pattern_lines(nfc(text).encode("utf-8")), base=base)

    @classmethod
    def make_from_entries(cls, entries: list[str], *, base: str) -> PatternList:
        """Read the entries of `[package] exclude`, each one line of a `core.excludesFile`, normalized to NFC."""
        data = b"".join(f"{nfc(entry)}\n".encode("utf-8", errors="surrogateescape") for entry in entries)
        return cls(parse_pattern_lines(data), base=base)

    def last_match(self, tree_path: str, *, is_dir: bool) -> GitPattern | None:
        """Git's `last_matching_pattern_from_list`: the last pattern of the list matching the path, or None.

        Args:
            tree_path: The path from the tree's root, which must lie under this list's base.
            is_dir: Whether the path names a directory; a symbolic link is not one.
        """
        encoded = tree_path.encode("utf-8", errors="surrogateescape")
        relative = encoded[len(self._prefix) :] if self._prefix and encoded.startswith(self._prefix) else encoded
        basename = encoded.rsplit(b"/", 1)[-1]
        for pattern in reversed(self.patterns):
            if pattern.must_be_dir and not is_dir:
                continue
            if pattern.no_dir:
                if _match_basename(pattern, basename):
                    return pattern
                continue
            if _match_pathname(pattern, relative):
                return pattern
        return None
