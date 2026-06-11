"""Wire models for the MTHDS Protocol — mirrors `mthds-protocol.openapi.yaml` (the standard's normative artifact).

    POST /execute  : RunRequest   -> RunResult (200)
    POST /start    : StartRequest -> StartAck (202)
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

from abc import ABC
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.functional_validators import SkipValidation
from typing_extensions import Annotated

from mthds._compat import StrEnum
from mthds._serialization import clean_json_content
from mthds._utils.pydantic_utils import empty_list_factory_of
from mthds.models.pipe_output import VariableMultiplicity
from mthds.models.pipeline_inputs import PipelineInputs
from mthds.models.working_memory import WorkingMemoryAbstract
from mthds.protocol.exceptions import PipelineRequestError

if TYPE_CHECKING:
    from typing_extensions import Self

    from mthds.models.stuff import StuffType

MAIN_STUFF_NAME = "main_stuff"

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

    @model_validator(mode="before")
    @classmethod
    def validate_request(cls, values: dict[str, Any]):
        # The protocol requires at least one of pipe_code / mthds_contents. When the
        # body carries extension args (keys outside the declared fields), an extension
        # may be the method selector — the server is the source of truth, so the SDK
        # does not over-validate.
        has_extensions = any(key not in cls.model_fields for key in values)
        if values.get("pipe_code") is None and not values.get("mthds_contents") and not has_extensions:
            msg = (
                "pipe_code and mthds_contents cannot both be empty. Either: both are provided, or if there are no mthds_contents, "
                "then pipe_code must be provided and must reference a pipe already registered in the library. "
                "If mthds_contents is provided but no pipe_code, the first content must have a main_pipe property."
            )
            raise PipelineRequestError(msg)
        return values

    @classmethod
    def from_working_memory(
        cls,
        pipe_code: str | None,
        mthds_contents: list[str] | None = None,
        working_memory: WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_ref: str | None = None,
    ) -> RunRequest:
        """Create a RunRequest from a WorkingMemory object.

        Args:
            pipe_code: The code identifying the pipe to execute
            mthds_contents: List of MTHDS bundle contents to load
            working_memory: The WorkingMemory to convert
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_ref: Override for the dynamic output concept ref
        Returns:
            RunRequest with the working memory serialized to reduced format

        """
        pipeline_inputs: dict[str, dict[str, Any]] = {}
        if working_memory is not None:
            for stuff_name, stuff in working_memory.root.items():
                content_dict = stuff.content.model_dump(serialize_as_any=True)
                clean_content = clean_json_content(content_dict)

                # Create plain dict instead of DictStuff instance for JSON serialization
                pipeline_inputs[stuff_name] = {
                    "concept": stuff.concept.code,
                    "content": clean_content,
                }

        return cls(
            pipe_code=pipe_code,
            mthds_contents=mthds_contents,
            inputs=cast("PipelineInputs", pipeline_inputs),
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_ref=dynamic_output_concept_ref,
        )

    @classmethod
    def from_body(cls, request_body: dict[str, Any]) -> RunRequest:
        """Create a RunRequest from raw request body dictionary.

        Args:
            request_body: Raw dictionary from API request body

        Returns:
            RunRequest object with dictionary working_memory

        """
        # Support both singular "mthds_content" (legacy) and plural "mthds_contents"
        mthds_contents = request_body.get("mthds_contents")
        if mthds_contents is None:
            mthds_content = request_body.get("mthds_content")
            if mthds_content is not None:
                mthds_contents = [mthds_content]
        return cls(
            pipe_code=request_body.get("pipe_code"),
            mthds_contents=mthds_contents,
            inputs=request_body.get("inputs", {}),
            output_name=request_body.get("output_name"),
            output_multiplicity=request_body.get("output_multiplicity"),
            dynamic_output_concept_ref=request_body.get("dynamic_output_concept_ref"),
        )


class StartRequest(RunRequest):
    """Body of the protocol's `POST /start` — `RunRequest` plus `pipeline_run_id`.

    Mirrors `StartRequest` in `mthds-protocol.openapi.yaml`:

    - `pipeline_run_id` — client-supplied run identifier; bare runners accept
      it, the hosted API rejects it with 422 (the server-generated id in
      `StartAck` is always authoritative).

    Extension args are NOT protocol fields — like on `RunRequest`, they pass
    through `extra="allow"` and serialize to the wire as top-level properties.
    """

    pipeline_run_id: str | None = Field(default=None, max_length=128)


# ── Run responses (`POST /execute` 200, `POST /start` 202) ───────────


class RunState(StrEnum):
    """Run lifecycle state — mirrors the protocol's `RunState` enum."""

    STARTED = "STARTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"


class RunResponse(BaseModel):
    """Common shape of the protocol's run responses (`StartAck` ⊂ `RunResult`)."""

    pipeline_run_id: str
    created_at: str
    state: RunState
    finished_at: str | None = None
    main_stuff_name: str | None = None

    @classmethod
    def from_api_response(cls, response: dict[str, Any]) -> Self:
        """Create a run response from an API response dictionary.

        Args:
            response: Dictionary containing the API response data

        Returns:
            Run response instance created from the response data

        """
        return cls.model_validate(response)


class RunResult(RunResponse, ABC, Generic[PipeOutputT]):
    """Abstract result of a completed execution (`POST /execute` 200, callback
    payloads) — includes `pipe_output`.
    """

    pipe_output: PipeOutputT


class StartAck(RunResponse, ABC, Generic[PipeOutputT]):
    """Abstract ack of a started execution (`POST /start` 202); `pipe_output`
    is absent on the wire and optional here for implementation extensions.
    """

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
