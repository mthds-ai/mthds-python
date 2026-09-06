import pytest

from mthds.package.manifest.schema import MTHDS_STANDARD_VERSION, is_mthds_version_satisfied, is_valid_semver, is_valid_version_constraint
from mthds.package.semver import SemVerError
from mthds.protocol.protocol import PROTOCOL_VERSION


class TestVersions:
    """The two numbers this library copies from the standard's cut, and how a manifest constraint is evaluated against one of them."""

    def test_constants_match_the_standards_cut(self):
        # Pinned deliberately: these are copies of a cut made in the standard
        # (https://mthds.ai/spec/versioning/), so a value moving here without a
        # cut moving there is exactly what this asserts against.
        assert MTHDS_STANDARD_VERSION == "2.0.0"
        assert PROTOCOL_VERSION == "0.6.0"
        assert is_valid_semver(MTHDS_STANDARD_VERSION)
        assert is_valid_semver(PROTOCOL_VERSION)

    @pytest.mark.parametrize(
        ("topic", "constraint", "is_satisfied"),
        [
            ("the constraint every manifest written before the cut carries", ">=1.0.0", True),
            ("an exact pin on the current standard", "2.0.0", True),
            ("a caret range over the current major", "^2.0.0", True),
            ("a tilde range over the current minor", "~2.0.0", True),
            ("a wildcard over the current major", "2.*", True),
            ("any standard version at all", "*", True),
            ("a compound range spelled with a space, as the manifest format documents it", ">=2.0.0, <3.0.0", True),
            ("the same compound range spelled without one", ">=2.0.0,<3.0.0", True),
            ("a caret range over the superseded major", "^1.0.0", False),
            ("a package that predates the cut and says so", "<2.0.0", False),
            ("a package needing a standard that does not exist yet", ">=3.0.0", False),
            ("a compound range closing below the current standard", ">=1.0.0, <2.0.0", False),
        ],
    )
    def test_manifest_constraint_evaluated_against_the_standard_version(self, topic: str, constraint: str, is_satisfied: bool):
        assert is_valid_version_constraint(constraint), f"{topic}: the manifest format must accept this spelling"
        assert is_mthds_version_satisfied(constraint) is is_satisfied, topic

    def test_unparsable_constraint_raises(self):
        with pytest.raises(SemVerError, match="Invalid semver constraint"):
            is_mthds_version_satisfied("not valid!!")
