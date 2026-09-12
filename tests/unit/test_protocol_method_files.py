"""The catalog serialization, held to the TypeScript twin edge for edge.

`mthds/protocol/method_files.py` mirrors `mthds-js`'s `protocol/method_files.ts`, and a port of a
format like this one fails quietly: it round-trips its own output and still drops a file the twin
keeps, keeps one the twin drops, or writes bytes the twin would not. So the cases here are not what
the port was expected to do but what the twin was observed to do — `MethodFileCases` records the
bytes and the verdicts a run of the twin printed — and the happy round-trip is the least of them.
"""

import json

import pytest
from pydantic import ValidationError

from mthds.protocol.exceptions import PipelineRequestError
from mthds.protocol.method_files import MethodFile, parse_method_files, serialize_method_files
from tests.unit.test_data import MethodFileCases

_TWIN_FILES = [MethodFile.model_validate(entry) for entry in MethodFileCases.TWIN_FILES]


class TestMethodFiles:
    def test_serialization_writes_the_twins_bytes(self):
        # Same value is not the bar; same string is. `json.dumps` defaults — spaced separators,
        # `\uXXXX` for anything outside ASCII — decode to the same files and store differently.
        assert serialize_method_files(_TWIN_FILES) == MethodFileCases.TWIN_SERIALIZED

    def test_the_serialized_form_is_the_named_array_in_stored_order(self):
        assert json.loads(serialize_method_files(_TWIN_FILES)) == MethodFileCases.TWIN_FILES
        reversed_files = list(reversed(_TWIN_FILES))
        assert json.loads(serialize_method_files(reversed_files)) == list(reversed(MethodFileCases.TWIN_FILES))

    def test_no_files_serializes_to_the_empty_string_and_never_to_the_literal_array(self):
        # `""` is the platform's "no source" / "clear the field" sentinel; `"[]"` would be stored
        # as a source and shipped to the TOML parser.
        assert serialize_method_files([]) == ""
        assert serialize_method_files([MethodFile(name="empty.py", content="   ")]) == ""

    def test_serialization_drops_blank_entries_and_keeps_the_rest(self):
        files = [MethodFile(name="a.py", content="x"), MethodFile(name="b.py", content=""), MethodFile(name="c.py", content="y")]
        assert json.loads(serialize_method_files(files)) == [{"name": "a.py", "content": "x"}, {"name": "c.py", "content": "y"}]

    @pytest.mark.parametrize(("topic", "content", "is_blank"), MethodFileCases.BLANK_PREDICATE)
    def test_blank_is_what_the_twin_calls_blank(self, topic: str, content: str, is_blank: bool):
        # The predicate is ECMAScript `trim`'s set, spelled out. `str.strip()` would pass the
        # happy cases and fail exactly these: the BOM it keeps, the C0 separators it drops.
        serialized = serialize_method_files([MethodFile(name="f", content=content)])
        if is_blank:
            assert serialized == "", topic
            assert parse_method_files(content) == [], topic
        else:
            assert json.loads(serialized) == [{"name": "f", "content": content}], topic
            with pytest.raises(PipelineRequestError):
                parse_method_files(content)

    def test_parsing_reads_the_twins_bytes_back_into_files(self):
        assert parse_method_files(MethodFileCases.TWIN_SERIALIZED) == _TWIN_FILES

    @pytest.mark.parametrize(("topic", "source"), MethodFileCases.NO_FILES_SOURCES)
    def test_a_blank_source_and_an_empty_array_are_both_no_files(self, topic: str, source: str | None):
        assert parse_method_files(source) == [], topic

    def test_parsing_drops_blank_entries_so_the_round_trip_is_stable(self):
        source = json.dumps([{"name": "a.py", "content": "x"}, {"name": "b.py", "content": " "}])
        assert parse_method_files(source) == [MethodFile(name="a.py", content="x")]

    def test_parsing_tolerates_and_strips_an_extra_member(self):
        # The wire may carry more than the two members; the typed surface carries exactly two.
        # Validating an entry through the closed model would refuse what the twin accepts.
        assert parse_method_files('[{"name":"a.py","content":"x","extra":1}]') == [MethodFile(name="a.py", content="x")]

    def test_parsing_keeps_order_duplicates_and_blank_names(self):
        # A blank name is not a reason to drop an entry — the platform's decoder disagrees, and the
        # port follows the twin so the three implementations do not split two against one.
        source = '[{"name":"z","content":"1"},{"name":"a","content":"2"},{"name":"a","content":"3"},{"name":"","content":"4"}]'
        assert parse_method_files(source) == [
            MethodFile(name="z", content="1"),
            MethodFile(name="a", content="2"),
            MethodFile(name="a", content="3"),
            MethodFile(name="", content="4"),
        ]

    def test_round_trip_serialize_then_parse(self):
        assert parse_method_files(serialize_method_files(_TWIN_FILES)) == _TWIN_FILES
        assert parse_method_files(serialize_method_files([])) == []

    @pytest.mark.parametrize(("topic", "source"), MethodFileCases.CONTRACT_VIOLATIONS)
    def test_anything_but_the_named_array_is_a_contract_violation(self, topic: str, source: str):
        with pytest.raises(PipelineRequestError) as exc_info:
            parse_method_files(source)
        assert "method file" in str(exc_info.value).lower(), topic

    def test_the_typed_shape_is_closed_and_strict(self):
        # Leniency lives in the parser, not the type: a consumer constructing a file gets exactly
        # `name` and `content`, both strings.
        with pytest.raises(ValidationError):
            MethodFile.model_validate({"name": "a.py", "content": "x", "extra": 1})
        with pytest.raises(ValidationError):
            MethodFile.model_validate({"name": 1, "content": "x"})
