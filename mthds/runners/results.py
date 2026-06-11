"""Concrete run response with Dict-serialized output — the SDK's default
materialization of the protocol's `RunResult`, shared by every runner
implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from mthds.models.pipe_output import DictPipeOutputAbstract
from mthds.models.working_memory import DictStuffAbstract, DictWorkingMemoryAbstract
from mthds.protocol.models import RunResult

if TYPE_CHECKING:
    from mthds.models.pipe_output import PipeOutputAbstract
    from mthds.models.stuff import StuffType
    from mthds.models.working_memory import WorkingMemoryAbstract


MAIN_STUFF_NAME = "main_stuff"


class DictRunResult(RunResult[DictPipeOutputAbstract]):
    """Concrete run result with Dict-serialized output.

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
    ) -> DictRunResult:
        """Create a DictRunResult from a PipeOutput object.

        Args:
            pipe_output: The PipeOutput to convert
            pipeline_run_id: Unique identifier for the run
        Returns:
            DictRunResult with the pipe output serialized to reduced format

        """
        # `main_stuff_name` is an extension field — validated construction keeps
        # it in `model_extra` without naming it a typed parameter.
        return cls.model_validate(
            {
                "pipeline_run_id": pipeline_run_id,
                "pipe_output": cls._dict_pipe_output_class(
                    working_memory=cls._serialize_working_memory(pipe_output.working_memory),
                    pipeline_run_id=pipe_output.pipeline_run_id,
                ),
                "main_stuff_name": pipe_output.working_memory.aliases.get(MAIN_STUFF_NAME, MAIN_STUFF_NAME),
            }
        )
