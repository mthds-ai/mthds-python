from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel, model_validator
from pydantic.functional_validators import SkipValidation
from typing_extensions import Annotated

from mthds._compat import StrEnum
from mthds._serialization import clean_json_content
from mthds.exceptions import PipelineRequestError
from mthds.models.pipe_output import DictPipeOutputAbstract, PipeOutputAbstract, VariableMultiplicity
from mthds.models.pipeline_inputs import PipelineInputs
from mthds.models.working_memory import DictStuffAbstract, DictWorkingMemoryAbstract, WorkingMemoryAbstract

if TYPE_CHECKING:
    from typing_extensions import Self

    from mthds.models.stuff import StuffType

MAIN_STUFF_NAME = "main_stuff"

PipeOutputT = TypeVar("PipeOutputT")


class PipelineRequest(BaseModel):
    """Request for executing a pipeline.

    Attributes:
        pipe_code (str | None): Code of the pipe to execute
        mthds_content (str | None): Content of the pipeline bundle to execute
        inputs (PipelineInputs | WorkingMemory | None): Inputs in PipelineInputs format - Pydantic validation is skipped
            to preserve the flexible format (dicts, strings, StuffContent objects, etc.)
        output_name (str | None): Name of the output slot to write to
        output_multiplicity (VariableMultiplicity | None): Output multiplicity setting
        dynamic_output_concept_code (str | None): Override for the dynamic output concept code

    """

    pipe_code: str | None = None
    mthds_content: str | None = None
    inputs: Annotated[PipelineInputs | WorkingMemoryAbstract[Any] | None, SkipValidation] = None
    output_name: str | None = None
    output_multiplicity: VariableMultiplicity | None = None
    dynamic_output_concept_code: str | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_request(cls, values: dict[str, Any]):
        if values.get("pipe_code") is None and values.get("mthds_content") is None:
            msg = (
                "pipe_code and mthds_content cannot be None together. Its either: Both of them, or if there is no mthds_content, "
                "then pipe_code must be provided and must reference a pipe already registered in the library."
                "If mthds_content is provided but no pipe_code, mthds_content must have a main_pipe property."
            )
            raise PipelineRequestError(msg)
        return values

    @classmethod
    def from_working_memory(
        cls,
        pipe_code: str | None,
        mthds_content: str | None,
        working_memory: WorkingMemoryAbstract[StuffType] | None = None,
        output_name: str | None = None,
        output_multiplicity: VariableMultiplicity | None = None,
        dynamic_output_concept_code: str | None = None,
    ) -> PipelineRequest:
        """Create a PipelineRequest from a WorkingMemory object.

        Args:
            pipe_code: The code identifying the pipeline to execute
            mthds_content: Content of the pipeline bundle to execute
            working_memory: The WorkingMemory to convert
            output_name: Name of the output slot to write to
            output_multiplicity: Output multiplicity setting
            dynamic_output_concept_code: Override for the dynamic output concept code
        Returns:
            PipelineRequest with the working memory serialized to reduced format

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
            mthds_content=mthds_content,
            inputs=cast("PipelineInputs", pipeline_inputs),
            output_name=output_name,
            output_multiplicity=output_multiplicity,
            dynamic_output_concept_code=dynamic_output_concept_code,
        )

    @classmethod
    def from_body(cls, request_body: dict[str, Any]) -> PipelineRequest:
        """Create a PipelineRequest from raw request body dictionary.

        Args:
            request_body: Raw dictionary from API request body

        Returns:
            PipelineRequest object with dictionary working_memory

        """
        return cls(
            pipe_code=request_body.get("pipe_code"),
            mthds_content=request_body.get("mthds_content"),
            inputs=request_body.get("inputs", {}),
            output_name=request_body.get("output_name"),
            output_multiplicity=request_body.get("output_multiplicity"),
            dynamic_output_concept_code=request_body.get("dynamic_output_concept_code"),
        )


class PipelineState(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"
    STARTED = "STARTED"


class PipelineResponse(BaseModel):
    """Response for pipeline start requests (no output yet)."""

    pipeline_run_id: str
    created_at: str
    pipeline_state: PipelineState
    finished_at: str | None = None
    main_stuff_name: str | None = None

    @classmethod
    def from_api_response(cls, response: dict[str, Any]) -> Self:
        """Create a PipelineResponse from an API response dictionary.

        Args:
            response: Dictionary containing the API response data

        Returns:
            PipelineResponse instance created from the response data

        """
        return cls.model_validate(response)


class PipelineExecuteResponse(PipelineResponse, ABC, Generic[PipeOutputT]):
    """Abstract response for completed pipeline execution, includes pipe_output."""

    pipe_output: PipeOutputT


class PipelineStartResponse(PipelineResponse, ABC, Generic[PipeOutputT]):
    """Abstract response for started pipeline execution, pipe_output is optional."""

    pipe_output: PipeOutputT | None = None


class DictPipelineStartResponse(PipelineStartResponse[DictPipeOutputAbstract]):
    """Concrete pipeline start response with Dict-serialized output."""


class DictPipelineExecuteResponse(PipelineExecuteResponse[DictPipeOutputAbstract]):
    """Concrete pipeline execution response with Dict-serialized output."""

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
        pipeline_state: PipelineState = PipelineState.COMPLETED,
        finished_at: str | None = None,
    ) -> DictPipelineExecuteResponse:
        """Create a DictPipelineExecuteResponse from a PipeOutput object.

        Args:
            pipe_output: The PipeOutput to convert
            pipeline_run_id: Unique identifier for the pipeline run
            created_at: Timestamp when the pipeline was created
            pipeline_state: Current state of the pipeline
            finished_at: Timestamp when the pipeline finished
        Returns:
            DictPipelineExecuteResponse with the pipe output serialized to reduced format

        """
        return cls(
            pipeline_run_id=pipeline_run_id,
            created_at=created_at,
            pipeline_state=pipeline_state,
            finished_at=finished_at,
            pipe_output=cls._dict_pipe_output_class(
                working_memory=cls._serialize_working_memory(pipe_output.working_memory),
                pipeline_run_id=pipe_output.pipeline_run_id,
            ),
            main_stuff_name=pipe_output.working_memory.aliases.get(MAIN_STUFF_NAME, MAIN_STUFF_NAME),
        )
