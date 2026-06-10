"""Wire models for the MTHDS Protocol discovery + validation surfaces.

Mirrors `mthds-protocol.openapi.yaml` (the standard's normative artifact):
    POST /validate -> ValidationReport
    GET  /models   -> ModelDeck
    GET  /version  -> VersionInfo
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mthds._compat import StrEnum
from mthds._utils.pydantic_utils import empty_list_factory_of


class ModelCategory(StrEnum):
    """Model categories accepted by the protocol's `GET /models?type=` filter."""

    LLM = "llm"
    EXTRACT = "extract"
    IMG_GEN = "img_gen"
    SEARCH = "search"


class ModelInfo(BaseModel):
    """One entry of the model deck (`ModelDeck.models[]`)."""

    name: str
    type: ModelCategory | None = None


class ModelDeck(BaseModel):
    """The model deck a runner can route to — `GET /models`.

    Mirrors the protocol's `ModelDeck`: presets (`models`), `aliases`, and
    routing `waterfalls`. Tolerant of unknown fields so implementations can
    enrich the deck (default `extra="ignore"`).
    """

    models: list[ModelInfo] = Field(default_factory=empty_list_factory_of(ModelInfo))
    aliases: dict[str, str] = Field(default_factory=dict)
    waterfalls: dict[str, list[str]] = Field(default_factory=dict)


class ValidationReport(BaseModel):
    """Structural artifacts returned by `POST /validate` when the bundle is valid.

    Failures never reach this model — they are RFC 7807 problems (HTTP 422).
    All artifacts are optional: the protocol marks none of them required, and
    implementations fill what they can produce.
    """

    blueprint: Any = None
    graph_spec: Any = None
    pipe_structures: Any = None


class VersionInfo(BaseModel):
    """Protocol + implementation versions — `GET /version` (always public).

    The handshake clients use for feature detection: `implementation`
    identifies the runner, and hosted extensions (durable runs, `method_id`)
    light up based on what the server advertises.
    """

    protocol_version: str
    implementation: str
    implementation_version: str
    runtime_version: str | None = None
