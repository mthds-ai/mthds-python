import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mthds.method_tree.digest import sha256_hex
from mthds.method_tree.file_entry import Base64FileEntry, HashFileEntry, InMemoryBlobStore, encode_file_entry, encode_file_map, read_file_map
from mthds.method_tree.lister import list_method_tree
from mthds.method_tree.written_tree import read_written_tree, write_tree


class TestMethodTreeFileEntry:
    @pytest.mark.parametrize(
        ("data", "by_hash", "expected"),
        [
            pytest.param(b"# Greetings\n", False, "# Greetings\n", id="text travels as a string"),
            pytest.param(b"\xff\x00", False, {"base64": "/wA="}, id="bytes that are not UTF-8 travel as Base64"),
            pytest.param(b"hi", True, {"sha256": sha256_hex(b"hi"), "size": 2}, id="bytes the receiver holds travel by hash"),
        ],
    )
    def test_encode_file_entry(self, data: bytes, by_hash: bool, expected: str | dict[str, str | int]):
        assert encode_file_entry(data, by_hash=by_hash) == expected

    @pytest.mark.parametrize(
        "fields",
        [
            pytest.param({"base64": "aGl="}, id="padding bits that are not zero"),
            pytest.param({"base64": "aGk"}, id="missing padding"),
            pytest.param({"base64": "aG k="}, id="a character outside the alphabet"),
        ],
    )
    def test_base64_entry_must_be_canonical(self, fields: dict[str, str]):
        with pytest.raises(ValidationError):
            Base64FileEntry.model_validate(fields)

    @pytest.mark.parametrize(
        "fields",
        [
            pytest.param({"sha256": "a" * 64, "size": 13.0}, id="a size written with a fraction"),
            pytest.param({"sha256": "a" * 64, "size": True}, id="a boolean size"),
            pytest.param({"sha256": "A" * 64, "size": 13}, id="an uppercase hash"),
            pytest.param({"sha256": "a" * 64, "size": 13, "url": "https://example.com"}, id="a key of no form"),
        ],
    )
    def test_hash_entry_is_strict(self, fields: dict[str, object]):
        with pytest.raises(ValidationError):
            HashFileEntry.model_validate(fields)

    def test_map_a_sender_writes_reads_back_as_the_listed_tree(self, tmp_path: Path):
        """A listed tree, sent as a map partly by hash, reads back on the receiver as the same files and the same digest."""
        (tmp_path / "main.mthds").write_text('domain = "greetings"\n', encoding="utf-8")
        (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (tmp_path / "card.html").write_text("<p>Hello</p>\n", encoding="utf-8")
        tree = list_method_tree(tmp_path)
        contents = {tree_path: tree.file_location(tree_path).read_bytes() for tree_path in tree.tree_paths}
        held = contents["card.html"]
        document = json.dumps(encode_file_map(contents, held_by_receiver=frozenset({sha256_hex(held)})))
        reading = read_file_map(document, blob_store=InMemoryBlobStore([held]))
        assert reading.tree.digest == tree.digest
        assert reading.contents == contents

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
