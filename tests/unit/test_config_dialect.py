"""Tests for the ~/.mthds/config dotenv dialect against the shared conformance fixture.

The vendored ``tests/fixtures/config_dialect_cases.json`` is a byte-identical copy of the
canonical case file in ``conformance/tests/mthds/fixtures/`` (the dialect is pinned by
``docs/specs/mthds-config-file.md`` in the workspace repo, and the conformance repo's
``check-fixture-drift`` guard keeps the copies in sync). Running the cases here keeps this
repo's own fast suite catching parser regressions without the conformance repo checked out.
"""

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

# The dialect engine is deliberately private (an implementation detail of the config surface);
# this suite pins the dialect itself, so it reaches the private names on purpose.
from mthds.config import _parse_dotenv, _serialize_dotenv  # noqa: PLC2701  # pyright: ignore[reportPrivateUsage]

_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "config_dialect_cases.json"


class ParseCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    input: str
    expected: dict[str, str]


class SerializeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    entries: dict[str, str]
    expected: str


class RewriteCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    description: str
    input: str
    expected: str


class DialectCases(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    parse_cases: list[ParseCase]
    serialize_cases: list[SerializeCase]
    rewrite_cases: list[RewriteCase]


_CASES = DialectCases.model_validate_json(_FIXTURE_PATH.read_text(encoding="utf-8"))


class TestConfigDialect:
    """The dotenv parser/serializer conforms to every case in the shared dialect fixture."""

    @pytest.mark.parametrize("case", [pytest.param(case, id=case.name) for case in _CASES.parse_cases])
    def test_parse(self, case: ParseCase) -> None:
        """Raw file text parses to exactly the expected mapping."""
        assert _parse_dotenv(case.input) == case.expected, f"{case.name}: {case.description}"

    @pytest.mark.parametrize("case", [pytest.param(case, id=case.name) for case in _CASES.serialize_cases])
    def test_serialize(self, case: SerializeCase) -> None:
        """An entries mapping serializes to exactly the expected text."""
        assert _serialize_dotenv(case.entries) == case.expected, f"{case.name}: {case.description}"

    @pytest.mark.parametrize("case", [pytest.param(case, id=case.name) for case in _CASES.serialize_cases])
    def test_round_trip(self, case: SerializeCase) -> None:
        """parse(serialize(entries)) yields the same entries back — serialization is lossless for representable entries."""
        assert _parse_dotenv(_serialize_dotenv(case.entries)) == case.entries, f"{case.name}: round-trip must be lossless"

    @pytest.mark.parametrize("case", [pytest.param(case, id=case.name) for case in _CASES.rewrite_cases])
    def test_rewrite(self, case: RewriteCase) -> None:
        """A parse-then-serialize rewrite (what a programmatic set does) produces exactly the expected text."""
        assert _serialize_dotenv(_parse_dotenv(case.input)) == case.expected, f"{case.name}: {case.description}"
