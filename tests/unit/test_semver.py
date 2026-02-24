import pytest
from semantic_version import Version  # type: ignore[import-untyped]

from mthds.package.semver import (
    SemVerError,
    parse_constraint,
    parse_version,
    parse_version_tag,
    select_minimum_version,
    select_minimum_version_for_multiple_constraints,
    version_satisfies,
)


class TestSemver:
    """Tests for the mthds.package.semver module."""

    # --- parse_version ---

    @pytest.mark.parametrize(
        ("version_str", "expected_str"),
        [
            ("1.2.3", "1.2.3"),
            ("v1.2.3", "1.2.3"),
            ("0.0.1", "0.0.1"),
            ("10.20.30", "10.20.30"),
        ],
    )
    def test_parse_version(self, version_str: str, expected_str: str):
        result = parse_version(version_str)
        assert str(result) == expected_str

    @pytest.mark.parametrize("invalid", ["not-a-version", "", "1.0", "abc"])
    def test_parse_version_invalid(self, invalid: str):
        with pytest.raises(SemVerError, match="Invalid semver"):
            parse_version(invalid)

    # --- parse_constraint ---

    @pytest.mark.parametrize("constraint_str", ["^1.0.0", ">=1.0.0,<2.0.0", "*"])
    def test_parse_constraint(self, constraint_str: str):
        result = parse_constraint(constraint_str)
        assert result is not None

    @pytest.mark.parametrize("invalid", [">>>1.0.0", "not_valid"])
    def test_parse_constraint_invalid(self, invalid: str):
        with pytest.raises(SemVerError, match="Invalid semver constraint"):
            parse_constraint(invalid)

    # --- version_satisfies ---

    @pytest.mark.parametrize(
        ("version_str", "constraint_str", "expected"),
        [
            ("1.5.0", "^1.0.0", True),
            ("2.0.0", "^1.0.0", False),
            ("1.0.0", ">=1.0.0,<2.0.0", True),
            ("2.0.0", ">=1.0.0,<2.0.0", False),
        ],
    )
    def test_version_satisfies(self, version_str: str, constraint_str: str, expected: bool):
        version = parse_version(version_str)
        constraint = parse_constraint(constraint_str)
        assert version_satisfies(version, constraint) == expected

    # --- select_minimum_version ---

    def test_select_minimum_version_empty_list(self):
        constraint = parse_constraint("^1.0.0")
        result = select_minimum_version([], constraint)
        assert result is None

    def test_select_minimum_version_single_match(self):
        versions = [Version("1.5.0")]
        constraint = parse_constraint("^1.0.0")
        result = select_minimum_version(versions, constraint)
        assert result == Version("1.5.0")

    def test_select_minimum_version_multiple_returns_minimum(self):
        versions = [Version("1.5.0"), Version("1.2.0"), Version("1.9.0")]
        constraint = parse_constraint("^1.0.0")
        result = select_minimum_version(versions, constraint)
        assert result == Version("1.2.0")

    def test_select_minimum_version_no_match(self):
        versions = [Version("2.0.0"), Version("3.0.0")]
        constraint = parse_constraint("^1.0.0")
        result = select_minimum_version(versions, constraint)
        assert result is None

    # --- select_minimum_version_for_multiple_constraints ---

    def test_select_minimum_multiple_constraints_compatible(self):
        versions = [Version("1.0.0"), Version("1.3.0"), Version("1.5.0"), Version("2.0.0")]
        constraints = [parse_constraint("^1.0.0"), parse_constraint(">=1.2.0")]
        result = select_minimum_version_for_multiple_constraints(versions, constraints)
        assert result == Version("1.3.0")

    def test_select_minimum_multiple_constraints_conflicting(self):
        versions = [Version("1.0.0"), Version("2.0.0")]
        constraints = [parse_constraint("^1.0.0"), parse_constraint("^2.0.0")]
        result = select_minimum_version_for_multiple_constraints(versions, constraints)
        assert result is None

    def test_select_minimum_multiple_constraints_empty_list(self):
        constraints = [parse_constraint("^1.0.0")]
        result = select_minimum_version_for_multiple_constraints([], constraints)
        assert result is None

    # --- parse_version_tag ---

    @pytest.mark.parametrize(
        ("tag", "expected_str"),
        [
            ("1.2.3", "1.2.3"),
            ("v1.2.3", "1.2.3"),
        ],
    )
    def test_parse_version_tag_valid(self, tag: str, expected_str: str):
        result = parse_version_tag(tag)
        assert result is not None
        assert str(result) == expected_str

    @pytest.mark.parametrize("tag", ["release-20240101", "latest", ""])
    def test_parse_version_tag_non_semver(self, tag: str):
        result = parse_version_tag(tag)
        assert result is None
