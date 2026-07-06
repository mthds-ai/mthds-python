"""Runner types for the MTHDS CLI."""

from enum import StrEnum


class RunnerType(StrEnum):
    """Supported runner types."""

    API = "api"
    PIPELEX = "pipelex"
