import stat
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.method_tree import written_tree
from mthds.method_tree.discovery import DirectoryEntry, EntryKind
from mthds.method_tree.exceptions import MethodTreeRefusedError
from mthds.method_tree.lister import list_method_tree
from mthds.method_tree.vocabulary import TreeRefusalCode
from mthds.method_tree.written_tree import read_written_tree, write_tree


class TestMethodTreeWrittenTree:
    def test_written_tree_reads_back_with_the_listed_digest(self, tmp_path: Path):
        """A tree written out holds its files at their tree paths and nothing else, and reads back with the same digest."""
        source = tmp_path / "source"
        (source / "templates").mkdir(parents=True)
        (source / "templates" / "letter.html").write_text("<p>Dear</p>\n", encoding="utf-8")
        (source / "main.mthds").write_text('domain = "letters"\n', encoding="utf-8")
        (source / ".env").write_text("SECRET=1\n", encoding="utf-8")
        tree = list_method_tree(source)
        destination = tmp_path / "copy"
        destination.mkdir()
        write_tree(tree, destination=destination)
        assert not (destination / ".env").exists()
        written = read_written_tree(destination)
        assert written.tree_paths == ["main.mthds", "templates/letter.html"]
        assert written.digest == tree.digest

    def test_written_file_keeps_its_permission_bits(self, tmp_path: Path):
        """A script the package marks executable stays executable in its written copy."""
        source = tmp_path / "source"
        source.mkdir()
        script = source / "setup.sh"
        script.write_text("#!/bin/sh\n", encoding="utf-8")
        script.chmod(0o755)
        (source / "notes.txt").write_text("notes", encoding="utf-8")
        (source / "notes.txt").chmod(0o640)
        destination = tmp_path / "copy"
        destination.mkdir()
        write_tree(list_method_tree(source), destination=destination)
        assert stat.S_IMODE((destination / "setup.sh").stat().st_mode) == 0o755
        assert stat.S_IMODE((destination / "notes.txt").stat().st_mode) == 0o640

    @pytest.mark.parametrize(
        ("root_entries", "inner_entries", "expected_names"),
        [
            pytest.param(
                [DirectoryEntry(raw_name="caf\u00e9.txt", kind=EntryKind.FILE), DirectoryEntry(raw_name="cafe\u0301.txt", kind=EntryKind.FILE)],
                {},
                ["cafe\u0301.txt", "caf\u00e9.txt"],
                id="two spellings of one file",
            ),
            pytest.param(
                [DirectoryEntry(raw_name="caf\u00e9", kind=EntryKind.DIRECTORY), DirectoryEntry(raw_name="cafe\u0301", kind=EntryKind.DIRECTORY)],
                {
                    "caf\u00e9": [DirectoryEntry(raw_name="menu.txt", kind=EntryKind.FILE)],
                    "cafe\u0301": [DirectoryEntry(raw_name="prices.txt", kind=EntryKind.FILE)],
                },
                ["cafe\u0301", "caf\u00e9"],
                id="two spellings of one directory",
            ),
        ],
    )
    def test_normalization_collision_in_a_written_tree_is_refused(
        self,
        tmp_path: Path,
        mocker: MockerFixture,
        root_entries: list[DirectoryEntry],
        inner_entries: dict[str, list[DirectoryEntry]],
        expected_names: list[str],
    ):
        """Two names a normalization-sensitive file system holds apart would be read at one tree path, so one file would be lost."""

        def listed(location: Path) -> list[DirectoryEntry]:
            return root_entries if location == tmp_path else inner_entries[location.name]

        mocker.patch.object(written_tree, "read_directory", side_effect=listed)
        hash_spy = mocker.spy(written_tree, "hash_file")
        with pytest.raises(MethodTreeRefusedError) as refused:
            read_written_tree(tmp_path)
        assert refused.value.refusal.code == TreeRefusalCode.NORMALIZATION_COLLISION
        assert refused.value.refusal.names == expected_names
        hash_spy.assert_not_called()
