from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.method_tree import lister
from mthds.method_tree.exceptions import MethodTreeRefusedError, TreeLimitError, TreeSourceError
from mthds.method_tree.lister import list_method_tree, list_method_tree_at_root
from mthds.method_tree.models import TreeLimits
from mthds.method_tree.vocabulary import TreeLimitKind, TreeRefusalCode
from mthds.package.discovery import find_package_manifest

MANIFEST_TEXT = '[package]\naddress = "github.com/acme/letters"\nversion = "1.0.0"\ndescription = "Letters"\n'


def _write(root: Path, files: dict[str, str]) -> None:
    for relative_path, text in files.items():
        location = root.joinpath(*relative_path.split("/"))
        location.parent.mkdir(parents=True, exist_ok=True)
        location.write_text(text, encoding="utf-8")


class TestMethodTreeLister:
    @pytest.mark.parametrize(
        ("limits", "kind", "limit", "reached"),
        [
            pytest.param(TreeLimits(max_files=2), TreeLimitKind.FILE_COUNT, 2, 3, id="file count"),
            pytest.param(TreeLimits(max_total_bytes=10), TreeLimitKind.TOTAL_BYTES, 10, 12, id="total bytes"),
            pytest.param(TreeLimits(max_file_bytes=3), TreeLimitKind.FILE_BYTES, 3, 4, id="one file's bytes"),
        ],
    )
    def test_limit_stops_the_walk_before_hashing(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        limits: TreeLimits,
        kind: TreeLimitKind,
        limit: int,
        reached: int,
    ):
        """The walk counts files and sums their sizes as it goes, and stops at the first limit passed without hashing a file."""
        _write(tmp_path, {"a.txt": "aaaa", "b.txt": "bbbb", "c.txt": "cccc", "d.txt": "dddd"})
        hash_spy = mocker.spy(lister, "hash_file")
        with pytest.raises(TreeLimitError) as stopped:
            list_method_tree(tmp_path, limits=limits)
        assert stopped.value.kind == kind
        assert stopped.value.limit == limit
        assert stopped.value.reached == reached
        assert stopped.value.root == tmp_path.resolve()
        assert str(tmp_path.resolve()) in stopped.value.message
        assert f"{reached} " in stopped.value.message
        assert f"limit of {limit} " in stopped.value.message
        hash_spy.assert_not_called()

    def test_tree_within_its_limits_is_listed(self, tmp_path: Path):
        _write(tmp_path, {"a.txt": "aaaa", "b.txt": "bbbb"})
        tree = list_method_tree(tmp_path, limits=TreeLimits(max_files=2, max_total_bytes=8, max_file_bytes=4))
        assert tree.tree_paths == ["a.txt", "b.txt"]

    @pytest.mark.parametrize(
        ("handed_over", "message"),
        [
            pytest.param("missing", "Cannot list a method tree", id="a path that does not exist"),
            pytest.param("notes.txt", "must be a .mthds bundle", id="a file that is not a bundle"),
        ],
    )
    def test_source_that_cannot_be_listed(self, tmp_path: Path, handed_over: str, message: str):
        _write(tmp_path, {"notes.txt": "notes"})
        with pytest.raises(TreeSourceError, match=message):
            list_method_tree(tmp_path / handed_over)

    def test_symbolic_link_to_a_directory_handed_over_is_followed(self, tmp_path: Path):
        """A caller naming a directory through a link lists the directory; links inside the tree are still refused."""
        method = tmp_path / "method"
        _write(method, {"METHODS.toml": MANIFEST_TEXT, "main.mthds": 'domain = "letters"\n'})
        Path(tmp_path / "shortcut").symlink_to(method)
        tree = list_method_tree(tmp_path / "shortcut")
        assert tree.directory == method.resolve()
        assert tree.tree_paths == ["METHODS.toml", "main.mthds"]

    def test_listing_at_a_fixed_root_ignores_a_manifest_above(self, tmp_path: Path):
        """A fetched package's tree is rooted at its own directory, whatever a manifest above it says."""
        _write(tmp_path, {"METHODS.toml": MANIFEST_TEXT, "package/flow.mthds": 'domain = "flow"\n'})
        assert list_method_tree(tmp_path / "package").directory == tmp_path.resolve()
        tree = list_method_tree_at_root(tmp_path / "package")
        assert tree.directory == (tmp_path / "package").resolve()
        assert tree.tree_paths == ["flow.mthds"]

    def test_manifest_exclude_with_a_line_break_cannot_be_read(self, tmp_path: Path):
        _write(tmp_path, {"METHODS.toml": MANIFEST_TEXT + 'exclude = ["a\\nb"]\n', "main.mthds": 'domain = "letters"\n'})
        with pytest.raises(TreeSourceError, match="line break"):
            list_method_tree(tmp_path)

    def test_gitignore_that_is_not_utf8_names_its_path(self, tmp_path: Path):
        _write(tmp_path, {"METHODS.toml": MANIFEST_TEXT, "main.mthds": 'domain = "letters"\n'})
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "guide.md").write_text("guide", encoding="utf-8")
        (tmp_path / "docs" / ".gitignore").write_bytes(b"caf\xe9.txt\n")
        with pytest.raises(MethodTreeRefusedError) as refused:
            list_method_tree(tmp_path)
        assert refused.value.refusal.code == TreeRefusalCode.GITIGNORE_NOT_UTF8
        assert refused.value.refusal.names == ["docs/.gitignore"]

    def test_file_location_follows_the_spelling_on_disk(self, tmp_path: Path):
        """A name the file system holds decomposed is listed in NFC and still read from where it lies."""
        decomposed = "café.txt"
        _write(tmp_path, {decomposed: "coffee"})
        tree = list_method_tree(tmp_path)
        assert tree.tree_paths == ["café.txt"]
        assert tree.file_location("café.txt").read_text(encoding="utf-8") == "coffee"

    def test_package_manifest_discovery_stops_at_a_git_file(self, tmp_path: Path):
        """Manifest Discovery stops at a `.git` entry of any kind, such as the file a submodule or a worktree holds."""
        _write(tmp_path, {"METHODS.toml": MANIFEST_TEXT, "vendor/.git": "gitdir: ../.git/modules/vendor\n", "vendor/tool.mthds": 'domain = "tool"\n'})
        assert find_package_manifest(tmp_path / "vendor" / "tool.mthds") is None
        manifest = find_package_manifest(tmp_path / "main.mthds")
        assert manifest is not None
        assert manifest.address == "github.com/acme/letters"
