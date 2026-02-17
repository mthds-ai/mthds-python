try:
    from enum import StrEnum  # Python 3.11+
except ImportError:  # Python 3.10
    from backports.strenum import StrEnum  # type: ignore[assignment, import-not-found, no-redef]

__all__ = ["StrEnum"]
