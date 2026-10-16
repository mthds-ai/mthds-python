from pathlib import Path

import pytest
from pydantic import ValidationError
from pydantic_core import to_json

from mthds.method_tree.digest import sha256_hex
from mthds.method_tree.exceptions import MethodTreeRefusedError, TreeSourceError
from mthds.method_tree.file_entry import (
    MAX_JSON_DEPTH,
    Base64FileEntry,
    FileEntry,
    HashFileEntry,
    InMemoryBlobStore,
    encode_file_entry,
    encode_file_map,
    read_file_map,
)
from mthds.method_tree.lister import list_method_tree
from mthds.method_tree.vocabulary import TreeRefusalCode


class TestMethodTreeFileEntry:
    @pytest.mark.parametrize(
        ("data", "by_hash", "expected", "expected_json"),
        [
            pytest.param(b"# Greetings\n", False, "# Greetings\n", '"# Greetings\\n"', id="text travels as a string"),
            pytest.param(b"\xff\x00", False, Base64FileEntry(base64="/wA="), '{"base64":"/wA="}', id="bytes that are not UTF-8 travel as Base64"),
            pytest.param(
                b"hi",
                True,
                HashFileEntry(sha256=sha256_hex(b"hi"), size=2),
                '{"sha256":"' + sha256_hex(b"hi") + '","size":2}',
                id="bytes the receiver holds travel by hash",
            ),
        ],
    )
    def test_encode_file_entry(self, data: bytes, by_hash: bool, expected: FileEntry, expected_json: str):
        """Each entry is the typed form, and `to_json` writes it exactly as the wire has it."""
        entry = encode_file_entry(data, by_hash=by_hash)
        assert entry == expected
        assert to_json(entry).decode("utf-8") == expected_json

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
            pytest.param({"sha256": "a" * 64 + "\n", "size": 13}, id="a hash followed by a line feed"),
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
        document = to_json(encode_file_map(contents, held_by_receiver=frozenset({sha256_hex(held)}))).decode("utf-8")
        reading = read_file_map(document, blob_store=InMemoryBlobStore([held]))
        assert reading.tree.digest == tree.digest
        assert reading.contents == contents

    @pytest.mark.parametrize(
        "document",
        [
            pytest.param('{"a.txt": {"sha256": "' + "a" * 64 + '", "size": ' + "9" * 5000 + "}}", id="an integer longer than Python converts"),
            pytest.param("[" * 100_000 + "]" * 100_000, id="nesting deeper than some decoders follow"),
            pytest.param('{"a.txt": ' + "[" * MAX_JSON_DEPTH + "]" * MAX_JSON_DEPTH + "}", id="nesting just past the receiver's bound"),
            pytest.param('{"a.txt": {"sha256": "' + "a" * 64 + '", "size": NaN}}', id="NaN"),
            pytest.param('{"a.txt": {"sha256": "' + "a" * 64 + '", "size": -Infinity}}', id="-Infinity"),
        ],
    )
    def test_document_this_receiver_cannot_read_is_a_source_error(self, document: str):
        """Hostile JSON text ends in the documented source error, never in a bare ValueError or RecursionError."""
        with pytest.raises(TreeSourceError, match="not JSON text this receiver can read"):
            read_file_map(document)

    @pytest.mark.parametrize(
        "entry",
        [
            pytest.param('{"sha256": "' + "a" * 64 + '\\n", "size": 2}', id="a hash followed by a line feed"),
            pytest.param('{"sha256": "' + "a" * 64 + '", "size": 2.0}', id="a size written with a fraction"),
            pytest.param('{"sha256": "' + "a" * 64 + '", "size": 2e0}', id="a size written with an exponent"),
            pytest.param('{"base64": "aGl="}', id="Base64 whose padding bits are not zero"),
            pytest.param('{"base64": "aGk=", "size": 2}', id="a key of no form"),
        ],
    )
    def test_malformed_entry_is_refused(self, entry: str):
        with pytest.raises(MethodTreeRefusedError) as refused:
            read_file_map('{"a.txt": ' + entry + "}", blob_store=InMemoryBlobStore([b"hi"]))
        assert refused.value.refusal.code == TreeRefusalCode.MALFORMED_ENTRY
        assert refused.value.refusal.names == ["a.txt"]

    def test_nesting_within_the_bound_is_read_as_an_entry(self):
        """Nesting the decoder follows on every supported Python ends in the standard's refusal, not a source error."""
        nested = "[" * (MAX_JSON_DEPTH - 1) + "]" * (MAX_JSON_DEPTH - 1)
        with pytest.raises(MethodTreeRefusedError) as refused:
            read_file_map('{"a.txt": ' + nested + "}")
        assert refused.value.refusal.code == TreeRefusalCode.MALFORMED_ENTRY
