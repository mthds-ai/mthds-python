"""Dict-serialized wire models — the SDK's concrete JSON materialization of the protocol's domain shapes.

These are the JSON forms the runners deal in: each `Stuff` reduced to
`{concept: <ref>, content}`, working memory as a flat root + aliases, the
pipe-output as that working memory + a run id, and `DictRunResultExecute` as the
protocol's `RunResult` carrying a `DictPipeOutput`. The abstract (non-dict)
domain shapes these mirror live in `mthds.protocol.*`.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from mthds._compat import StrEnum
from mthds._utils.pydantic_utils import empty_list_factory_of
from mthds.protocol.models import InvalidValidationReport, RunResultExecute, ValidationDiagnostic, ValidationReport

if TYPE_CHECKING:
    from mthds.protocol.pipe_output import PipeOutputAbstract
    from mthds.protocol.stuff import StuffType
    from mthds.protocol.working_memory import WorkingMemoryAbstract


MAIN_STUFF_NAME = "main_stuff"


class DictStuffAbstract(BaseModel, ABC):
    model_config = ConfigDict(extra="forbid", strict=True)
    concept: str
    content: Any


class DictWorkingMemoryAbstract(BaseModel, ABC):
    model_config = ConfigDict(extra="forbid", strict=True)
    root: dict[str, DictStuffAbstract]
    aliases: dict[str, str]


class DictPipeOutputAbstract(BaseModel, ABC):
    model_config = ConfigDict(extra="forbid", strict=True)
    working_memory: DictWorkingMemoryAbstract
    pipeline_run_id: str


class DictRunResultExecute(RunResultExecute[DictPipeOutputAbstract]):
    """Concrete execute result with Dict-serialized output.

    `main_stuff_name` (when set by a runner) is an implementation extension
    field riding the protocol's extension-open response — not a protocol field.
    """

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
    ) -> DictRunResultExecute:
        """Create a DictRunResultExecute from a PipeOutput object.

        Args:
            pipe_output: The PipeOutput to convert
            pipeline_run_id: Unique identifier for the run
        Returns:
            DictRunResultExecute with the pipe output serialized to reduced format

        """
        # `main_stuff_name` is an extension field — validated construction keeps
        # it in `model_extra` without naming it a typed parameter.
        resolved_run_id = pipeline_run_id or pipe_output.pipeline_run_id
        return cls.model_validate(
            {
                "pipeline_run_id": resolved_run_id,
                "pipe_output": cls._dict_pipe_output_class(
                    working_memory=cls._serialize_working_memory(pipe_output.working_memory),
                    pipeline_run_id=pipe_output.pipeline_run_id,
                ),
                "main_stuff_name": pipe_output.working_memory.aliases.get(MAIN_STUFF_NAME, MAIN_STUFF_NAME),
            }
        )


# ── Pipelex narrowing of the `POST /validate` 200-diagnostic union ───
#
# The protocol layer (`mthds.protocol.models`) declares the brand-neutral verdict
# shapes; the pipelex runner narrows them with its structural artifacts and its
# closed `ValidationErrorCategory` vocabulary. Names here carry Pipelex branding
# because they are runtime-specific; the protocol field names stay neutral.


class DryRunStatus(StrEnum):
    """Per-pipe dry-run sweep outcome on `ValidatedPipeEntry.status`."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"


class ValidationErrorCategory(StrEnum):
    """The closed `validation_errors[].category` vocabulary (locked).

    Mirrors the single source of truth in the conformance suite
    (`conformance/conformance/validation_contract.py`); keep in sync with it.
    """

    BLUEPRINT_VALIDATION = "blueprint_validation"
    PIPE_FACTORY = "pipe_factory"
    PIPE_VALIDATION = "pipe_validation"
    DRY_RUN = "dry_run"


class ValidatedPipeEntry(BaseModel):
    """One entry of `PipelexValidationReport.validated_pipes[]`."""

    model_config = ConfigDict(extra="allow")

    pipe_ref: str
    status: DryRunStatus


class ValidationErrorItem(ValidationDiagnostic):
    """Pipelex's structured `validation_errors[]` item — narrows the protocol base.

    `category` narrows to the closed `ValidationErrorCategory` set; the locators are
    populated per category and dropped from the wire when unset. Built by pipelex's
    one shared builder, so the hosted `InvalidReport` and the agent-CLI envelope
    cannot drift.
    """

    category: ValidationErrorCategory  # pyright: ignore[reportIncompatibleVariableOverride]
    error_type: str | None = None
    pipe_code: str | None = None
    concept_code: str | None = None
    domain_code: str | None = None
    source: str | None = None
    field_path: str | None = None
    field_name: str | None = None
    missing_concept_code: str | None = None
    variable_names: list[str] | None = None
    declared_concepts: list[str] | None = None


class PipelexValidationReport(ValidationReport):
    """The valid arm narrowed with pipelex's structural artifacts (`is_valid: true`)."""

    bundle_blueprint: dict[str, Any] = Field(default_factory=dict)
    pipe_io_contracts: dict[str, Any] = Field(default_factory=dict)
    graph_spec: Any = None
    validated_pipes: list[ValidatedPipeEntry] = Field(default_factory=empty_list_factory_of(ValidatedPipeEntry))
    pending_signatures: list[str] = Field(default_factory=list)
    is_runnable: bool = True
    message: str = ""
    mthds_contents: list[str] | None = None
    rendered_markdown: str | None = None
    """Opt-in Pipelex-API presentation extra: the server-rendered Markdown view of the verdict,
    present only when the request asked for it (`render: ["markdown"]`); absent (None) otherwise."""


class PipelexInvalidReport(InvalidValidationReport[ValidationErrorItem]):
    """The invalid arm carrying pipelex's structured `validation_errors[]` (`is_valid: false`)."""

    rendered_markdown: str | None = None
    """Opt-in Pipelex-API presentation extra: the server-rendered Markdown view of the invalid
    verdict, present only when the request asked for it (`render: ["markdown"]`); absent otherwise."""


PipelexValidationResult: TypeAlias = Annotated[
    PipelexValidationReport | PipelexInvalidReport,
    Field(discriminator="is_valid"),
]
"""Pipelex's `POST /v1/validate` 200 response — discriminated on `is_valid`."""


PipelexValidationResultAdapter: TypeAdapter[PipelexValidationResult] = TypeAdapter(PipelexValidationResult)
"""The single parse path for a 200 `/validate` body — built once at import (TypeAdapter construction is expensive).

Routes on the `is_valid` discriminant: a present `True` → `PipelexValidationReport`, a present
`False` → `PipelexInvalidReport`. A body missing/with-a-bad `is_valid` cannot be tagged and raises
`pydantic.ValidationError`, so a malformed 200 can never be mistaken for a valid verdict.
"""
