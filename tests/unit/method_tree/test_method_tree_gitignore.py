import pytest

from mthds.method_tree.gitignore import PatternList


class TestMethodTreeGitignore:
    @pytest.mark.parametrize(
        ("gitignore", "tree_path", "is_dir", "is_excluded"),
        [
            pytest.param(b"*.log\n", "logs/run.log", False, True, id="a pattern without a slash matches a name at any depth"),
            pytest.param(b"/build\n", "src/build", True, False, id="a leading slash anchors the pattern to its file's directory"),
            pytest.param(b"build/\n", "build", False, False, id="a trailing slash matches a directory only"),
            pytest.param(b"build/\n", "build", True, True, id="a trailing slash matches the directory"),
            pytest.param(b"a/**/c\n", "a/x/y/c", False, True, id="a double star crosses directories"),
            pytest.param(b"a/*/c\n", "a/x/y/c", False, False, id="a single star does not cross a slash"),
            pytest.param(b"a/foo**/x\n", "a/fooz/y/x", False, True, id="git's literal-prefix shortcut lets a double star after it cross a slash"),
            pytest.param(b"caf?.txt\n", "caf\u00e9.txt", False, False, id="a question mark matches one byte, not one character"),
            pytest.param(b"caf??.txt\n", "caf\u00e9.txt", False, True, id="two question marks match the two bytes of a composed letter"),
            pytest.param(b"*.PY\n", "a.py", False, False, id="letter case is matched exactly"),
            pytest.param(b"secret.txt \n", "secret.txt", False, True, id="a trailing space is trimmed"),
            pytest.param(b"secret.txt\\ \n", "secret.txt ", False, True, id="an escaped trailing space is kept"),
            pytest.param(b"notes.txt\r\n", "notes.txt", False, True, id="a carriage return before the line feed is dropped"),
            pytest.param(b"\xef\xbb\xbfnotes.txt\n", "notes.txt", False, True, id="a leading byte order mark is skipped"),
            pytest.param(b"#notes.txt\n", "#notes.txt", False, False, id="a line starting with a hash is a comment"),
            pytest.param(b"\\#notes.txt\n", "#notes.txt", False, True, id="an escaped hash starts a pattern"),
            pytest.param("cafe\u0301.txt\n".encode(), "caf\u00e9.txt", False, True, id="a decomposed pattern is normalized to NFC"),
        ],
    )
    def test_pattern_matches_as_git_does(self, gitignore: bytes, tree_path: str, is_dir: bool, is_excluded: bool):
        """The port of git's dir.c and wildmatch.c answers as `git check-ignore` does with core.ignoreCase off."""
        pattern_list = PatternList.make_from_bytes(gitignore, base="")
        matched = pattern_list.last_match(tree_path, is_dir=is_dir)
        assert (matched is not None and not matched.negative) is is_excluded

    def test_negation_later_in_a_file_wins(self):
        pattern_list = PatternList.make_from_bytes(b"*.txt\n!keep.txt\n", base="")
        kept = pattern_list.last_match("keep.txt", is_dir=False)
        assert kept is not None
        assert kept.negative
        dropped = pattern_list.last_match("drop.txt", is_dir=False)
        assert dropped is not None
        assert not dropped.negative

    def test_patterns_apply_relative_to_their_file(self):
        pattern_list = PatternList.make_from_bytes(b"/draft.txt\n", base="docs")
        assert pattern_list.last_match("docs/draft.txt", is_dir=False) is not None
        assert pattern_list.last_match("docs/sub/draft.txt", is_dir=False) is None

    def test_bytes_that_are_not_utf8_are_refused(self):
        with pytest.raises(UnicodeDecodeError):
            PatternList.make_from_bytes(b"caf\xe9.txt\n", base="")
