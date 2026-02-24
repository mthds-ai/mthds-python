import pytest

from mthds.package.exceptions import (
    DependencyResolveError,
    IntegrityError,
    LockFileError,
    ManifestError,
    ManifestParseError,
    ManifestValidationError,
    MthdsPackageError,
    PackageCacheError,
    TransitiveDependencyError,
    VCSFetchError,
    VersionResolutionError,
)


class TestExceptions:
    """Tests for the mthds.package.exceptions hierarchy."""

    def test_base_exception_message(self):
        exc = MthdsPackageError("something went wrong")
        assert exc.message == "something went wrong"
        assert str(exc) == "something went wrong"

    def test_base_exception_default_message(self):
        exc = MthdsPackageError()
        assert exc.message == ""

    @pytest.mark.parametrize(
        ("child_cls", "parent_cls"),
        [
            (ManifestError, MthdsPackageError),
            (ManifestParseError, ManifestError),
            (ManifestValidationError, ManifestError),
            (VCSFetchError, MthdsPackageError),
            (VersionResolutionError, MthdsPackageError),
            (PackageCacheError, MthdsPackageError),
            (LockFileError, MthdsPackageError),
            (IntegrityError, MthdsPackageError),
            (DependencyResolveError, MthdsPackageError),
            (TransitiveDependencyError, MthdsPackageError),
        ],
    )
    def test_subclass_hierarchy(self, child_cls: type, parent_cls: type):
        """Each concrete exception is a subclass of its expected parent."""
        exc = child_cls("test")
        assert isinstance(exc, parent_cls)

    def test_catching_parent_catches_child(self):
        """Catching a parent class should also catch subclass exceptions."""
        msg_parse = "parse failed"
        with pytest.raises(ManifestError):
            raise ManifestParseError(msg_parse)

        msg_validation = "validation failed"
        with pytest.raises(MthdsPackageError):
            raise ManifestValidationError(msg_validation)
