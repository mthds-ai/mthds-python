from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel, Field, model_validator
from pydantic.functional_validators import SkipValidation
from typing_extensions import Annotated

from mthds._compat import StrEnum
from mthds._serialization import clean_json_content
from mthds.client.exceptions import PipelineRequestError
from mthds.models.pipe_output import DictPipeOutputAbstract, PipeOutputAbstract, VariableMultiplicity
from mthds.models.pipeline_inputs import PipelineInputs
from mthds.models.working_memory import DictStuffAbstract, DictWorkingMemoryAbstract, WorkingMemoryAbstract

if TYPE_CHECKING:
    from typing_extensions import Self

    from mthds.models.stuff import StuffType

MAIN_STUFF_NAME = "main_stuff"

PipeOutputT = TypeVar("PipeOutputT")


class RunRequest(BaseModel):
    """Body of the protocol's `POST /execute` — mirrors `RunRequest` in
    `mthds-protocol.openapi.yaml`.

    Attributes:
        pipe_code (str | None): Code of the pipe to execute
        mthds_contents (list[str] | None): List of MTHDS bundle contents to load
        inputs (PipelineInputs | WorkingMemory | None): Inputs in PipelineInputs format - Pydantic validation is skipped
            to preserve the flexible format (dicts, strings, StuffContent objects, etc.)
        output_name (str | None): Name of the output slot to write to
        output_multiplicity (VariableMultiplicity | None): Output multiplicity setting
        dynamic_output_concept_ref (str | None): Override for the dynamic output concept ref

    """

    pipe_code: str | None = None
    mthds_contents: list[str] | None = None
    inputs: Annotated[PipelineInputs | WorkingMemoryAbstract[Any] | None, SkipValidation] = None
    output_name: str | None = None
    output_multiplicity: VariableMultiplicity | None = None
    dynamic_output_concept_ref: str | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_request(cls, values: dict[str, Any]):
        if values.get("pipe_code") is None and not values.get("mthds_contents") and not values.get("method_id"):
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
    """Body of the protocol's `POST /start` — `RunRequest` plus the async extras.

    Mirrors `StartRequest` in `mthds-protocol.openapi.yaml`, with the hosted
    `method_id` extension:

    - `pipeline_run_id` — client-supplied run identifier; bare runners accept
      it, the hosted API rejects it with 422 (the server-generated id in
      `StartAck` is always authoritative).
    - `callback_urls` — completion webhooks, HMAC-signed by the runner via
      `X-Completion-Signature`. http/https only; private/loopback/metadata
      hosts are rejected server-side.
    - `method_id` — HOSTED EXTENSION: a stored method in the active org's
      catalog, mutually exclusive with `mthds_contents`. The platform is the
      source of truth for which combinations it accepts; the SDK does not
      over-validate.
    """

    pipeline_run_id: str | None = Field(default=None, max_length=128)
    callback_urls: list[str] | None = None
    method_id: str | None = Field(default=None, min_length=1)


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


class DictStartAck(StartAck[DictPipeOutputAbstract]):
    """Concrete start ack with Dict-serialized output."""


class DictRunResult(RunResult[DictPipeOutputAbstract]):
    """Concrete execution result with Dict-serialized output."""

    _dict_stuff_class: ClassVar[type[DictStuffAbstract]] = DictStuffAbstract
    _dict_working_memory_class: ClassVar[type[DictWorkingMemoryAbstract]] = DictWorkingMemoryAbstract
    _dict_pipe_output_class: ClassVar[type[DictPipeOutputAbstract]] = DictPipeOutputAbstract

    @classmethod
    def _serialize_working_memory(cls, working_memory: WorkingMemoryAbstract[StuffType]) -> DictWorkingMemoryAbstract:
        """Convert WorkingMemory to dict with DictStuff objects (content as dict).

        Keeps the WorkingMemory structure but converts each Stuff.content to dict.

        Args:
            working_memory: The WorkingMemory to serialize

        Returns:
            Dict with root containing DictStuff objects (serialized) and aliases
        """
        dict_stuffs_root: dict[str, DictStuffAbstract] = {}

        # Convert each Stuff -> DictStuff by dumping only the content
        for stuff_name, stuff in working_memory.root.items():
            dict_stuff = cls._dict_stuff_class(
                concept=stuff.concept.concept_ref,
                content=stuff.content.model_dump(serialize_as_any=True),
            )
            dict_stuffs_root[stuff_name] = dict_stuff

        return cls._dict_working_memory_class(root=dict_stuffs_root, aliases=working_memory.aliases)

    @classmethod
    def from_pipe_output(
        cls,
        pipe_output: PipeOutputAbstract[WorkingMemoryAbstract[StuffType]],
        pipeline_run_id: str = "",
        created_at: str = "",
        state: RunState = RunState.COMPLETED,
        finished_at: str | None = None,
    ) -> DictRunResult:
        """Create a DictRunResult from a PipeOutput object.

        Args:
            pipe_output: The PipeOutput to convert
            pipeline_run_id: Unique identifier for the run
            created_at: Timestamp when the run was created
            state: Current state of the run
            finished_at: Timestamp when the run finished
        Returns:
            DictRunResult with the pipe output serialized to reduced format

        """
        return cls(
            pipeline_run_id=pipeline_run_id,
            created_at=created_at,
            state=state,
            finished_at=finished_at,
            pipe_output=cls._dict_pipe_output_class(
                working_memory=cls._serialize_working_memory(pipe_output.working_memory),
                pipeline_run_id=pipe_output.pipeline_run_id,
            ),
            main_stuff_name=pipe_output.working_memory.aliases.get(MAIN_STUFF_NAME, MAIN_STUFF_NAME),
        )
