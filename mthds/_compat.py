import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
    from typing import Self
else:
    from backports.strenum import StrEnum  # type: ignore[import-not-found, no-redef]
    from typing_extensions import Self  # type: ignore[assignment]

__all__ = ["Self", "StrEnum"]
