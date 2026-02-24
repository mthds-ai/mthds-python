class MthdsPackageError(Exception):
    """Base exception for all mthds package management errors."""

    def __init__(self, message: str = "") -> None:
        self.message = message
        super().__init__(message)


class ManifestError(MthdsPackageError):
    pass


class ManifestParseError(ManifestError):
    pass


class ManifestValidationError(ManifestError):
    pass


class VCSFetchError(MthdsPackageError):
    """Raised when a git clone or tag listing operation fails."""


class VersionResolutionError(MthdsPackageError):
    """Raised when no version satisfying the constraint can be found in remote tags."""


class PackageCacheError(MthdsPackageError):
    """Raised when cache operations (lookup, store) fail."""


class LockFileError(MthdsPackageError):
    """Raised when lock file parsing, generation, or I/O fails."""


class IntegrityError(MthdsPackageError):
    """Raised when a cached package does not match its lock file hash."""


class DependencyResolveError(MthdsPackageError):
    """Raised when a dependency cannot be resolved."""


class TransitiveDependencyError(MthdsPackageError):
    """Raised for cycles or unsatisfiable diamond constraints in transitive resolution."""
