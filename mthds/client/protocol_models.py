"""Wire models for the MTHDS Protocol discovery + validation surfaces.

Mirrors `mthds-protocol.openapi.yaml` (the standard's normative artifact):
    POST /validate -> ValidationReport
    GET  /models   -> ModelDeck
    GET  /version  -> VersionInfo

All response models declare the protocol's BASE fields only and are
extension-open (`extra="allow"`): an implementation may return more, and those
server-specific fields are preserved as accessible attributes — the response
side of the same passthrough principle as the request-side `extra`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from mthds._compat import StrEnum
from mthds._utils.pydantic_utils import empty_list_factory_of


class ModelCategory(StrEnum):
    """Model categories accepted by the protocol's `GET /models?type=` filter."""

    LLM = "llm"
    EXTRACT = "extract"
    IMG_GEN = "img_gen"
    SEARCH = "search"


class ModelInfo(BaseModel):
    """One entry of the model deck (`ModelDeck.models[]`) — base fields + extensions."""

    model_config = ConfigDict(extra="allow")

    name: str
    type: ModelCategory | None = None


class ModelDeck(BaseModel):
    """The model deck a runner can route to — `GET /models`.

    The protocol's base is the `models` list; implementations may add their own
    routing metadata (aliases, fallback chains, anything else) as extensions.
    """

    model_config = ConfigDict(extra="allow")

    models: list[ModelInfo] = Field(default_factory=empty_list_factory_of(ModelInfo))


class ValidationReport(BaseModel):
    """Verdict of `POST /validate` for a VALID bundle — the 200 status IS the verdict.

    Failures never reach this model — they are RFC 7807 problems (HTTP 422).
    The protocol declares no body fields; implementations may include their own
    artifacts (parsed structures, graphs, anything else), preserved here as
    extension attributes.
    """

    model_config = ConfigDict(extra="allow")


class VersionInfo(BaseModel):
    """Protocol + runner versions — `GET /version` (always public).

    The handshake clients use for feature detection. The protocol defines two
    fields; implementations may add their own identification (a name, an
    underlying runtime version, anything else) as extensions.
    """

    model_config = ConfigDict(extra="allow")

    protocol_version: str
    runner_version: str | None = None
