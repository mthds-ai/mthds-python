"""Wire models for the MTHDS Protocol — mirrors `mthds-protocol.openapi.yaml` (the standard's normative artifact).

    POST /execute  : RunRequest   -> RunResult (200, pipe_output present)
    POST /start    : RunRequest   -> RunResult (202, pipe_output absent)
    POST /validate :              -> ValidationReport
    GET  /models   :              -> ModelDeck
    GET  /version  :              -> VersionInfo

Request models declare the protocol's BASIC arguments only and are
extension-open (`extra="allow"`): an implementation may accept extra request
properties, and any extension arg given to a constructor is kept and
serialized to the wire instead of being silently dropped.

Response models declare the protocol's BASE fields only and are extension-open
too: an implementation may return more, and those server-specific fields are
preserved as accessible attributes — the response side of the same passthrough
principle as the request-side `extra`.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.functional_validators import SkipValidation
from typing_extensions import Annotated

from mthds._compat import StrEnum
from mthds._utils.pydantic_utils import empty_list_factory_of
from mthds.models.pipe_output import VariableMultiplicity
from mthds.models.pipeline_inputs import PipelineInputs
from mthds.models.working_memory import WorkingMemoryAbstract

PipeOutputT = TypeVar("PipeOutputT")


# ── Requests (`POST /execute`, `POST /start`) ────────────────────────


class RunRequest(BaseModel):
    """Body of the protocol's `POST /execute` — mirrors `RunRequest` in
    `mthds-protocol.openapi.yaml`.

    The declared fields are the protocol's **basic** arguments. The model is
    deliberately open (`extra="allow"`): an implementation may accept extra
    request properties, and any extension arg given to the constructor is kept
    and serialized to the wire instead of being silently dropped.

    Attributes:
        pipe_code (str | None): Code of the pipe to execute
        mthds_contents (list[str] | None): List of MTHDS bundle contents to load
        inputs (PipelineInputs | WorkingMemory | None): Inputs in PipelineInputs format - Pydantic validation is skipped
            to preserve the flexible format (dicts, strings, StuffContent objects, etc.)
        output_name (str | None): Name of the output slot to write to
        output_multiplicity (VariableMultiplicity | None): Output multiplicity setting
        dynamic_output_concept_ref (str | None): Override for the dynamic output concept ref

    """

    model_config = ConfigDict(extra="allow")

    pipe_code: str | None = None
    mthds_contents: list[str] | None = None
    inputs: Annotated[PipelineInputs | WorkingMemoryAbstract[Any] | None, SkipValidation] = None
    output_name: str | None = None
    output_multiplicity: VariableMultiplicity | None = None
    dynamic_output_concept_ref: str | None = None


# ── Run response (`POST /execute` 200, `POST /start` 202) ────────────


class RunResult(BaseModel, Generic[PipeOutputT]):
    """The protocol's single run response — `POST /execute` 200 (`pipe_output`
    present), `POST /start` 202 and the optional `/execute` 202 degrade
    (`pipe_output` absent).

    Exactly two base fields: the authoritative server-generated
    `pipeline_run_id` and the method's `pipe_output`. Anything more an
    implementation returns (a run state, timestamps, output naming, anything
    else) is an extension field — preserved as accessible attributes
    (`extra="allow"`), never named by this SDK.
    """

    model_config = ConfigDict(extra="allow")

    pipeline_run_id: str
    pipe_output: PipeOutputT | None = None


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
