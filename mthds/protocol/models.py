"""Wire models for the MTHDS Protocol — mirrors `mthds-protocol.openapi.yaml` (the standard's normative artifact).

    POST /execute  : -> RunResultExecute (200: pipeline_run_id + pipe_output)
    POST /start    : -> RunResultStart   (202: pipeline_run_id only)
    POST /validate :              -> ValidationReport
    GET  /models   :              -> ModelDeck
    GET  /version  :              -> VersionInfo

The protocol has no request *model*: the SDK runners take the request's basic
arguments as named parameters and serialize the wire body directly, merging
any server-specific extension args as top-level properties.

Response models declare the protocol's BASE fields only and are extension-open
too: an implementation may return more, and those server-specific fields are
preserved as accessible attributes — the response side of the same passthrough
principle as the request-side `extra`.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from mthds._compat import StrEnum
from mthds._utils.pydantic_utils import empty_list_factory_of

PipeOutputT = TypeVar("PipeOutputT")


# ── Run responses (`POST /execute` 200, `POST /start` 202) ───────────


class RunResultExecute(BaseModel, Generic[PipeOutputT]):
    """`POST /execute` 200 — the completed run.

    Two base fields: the authoritative server-generated `pipeline_run_id` and
    the method's `pipe_output` (always present — a completed run has output).
    Extension-open (`extra="allow"`): anything more an implementation returns
    (a run state, timestamps, output naming) rides `model_extra`, never named
    by this SDK.
    """

    model_config = ConfigDict(extra="allow")

    pipeline_run_id: str
    pipe_output: PipeOutputT


class RunResultStart(BaseModel):
    """`POST /start` 202 (and the optional `/execute` 202 degrade) — the started
    run's authoritative `pipeline_run_id`, nothing else.

    A started run has no output yet; how it is delivered later (polling,
    callbacks, anything else) is implementation-defined and outside the
    protocol. Extension-open (`extra="allow"`): an implementation may add its
    own fields (a workflow id, a created-at timestamp), preserved via
    `model_extra`.
    """

    model_config = ConfigDict(extra="allow")

    pipeline_run_id: str


# ── Discovery + validation (`POST /validate`, `GET /models`, `GET /version`) ──


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
