"""Runner types for the MTHDS CLI."""

from mthds._compat import StrEnum


class RunnerType(StrEnum):
    """Supported runner types."""

    API = "api"
    PIPELEX = "pipelex"
