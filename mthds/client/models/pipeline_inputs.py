from typing import Any, Sequence

from typing_extensions import TypeAlias

from mthds.client.models.stuff import DictStuffAbstract, StuffContentAbstract

# StuffContentOrData represents all possible formats for pipeline inputs input:
# Case 1: Direct content (no 'concept' key)
#   - 1.1: str (simple string)
#   - 1.2: Sequence[str] (list of strings)
#   - 1.3: StuffContent (a StuffContent object)
#   - 1.4: Sequence[StuffContent] (list of StuffContent objects, covariant)
#   - 1.5: ListContent[StuffContent] (a ListContent object containing StuffContent items)
# Case 2: Dict with 'concept' AND 'content' keys
#   - 2.1: {"concept": str, "content": str}
#   - 2.2: {"concept": str, "content": Sequence[str]}
#   - 2.3: {"concept": str, "content": StuffContent}
#   - 2.4: {"concept": str, "content": Sequence[StuffContent]}
#   - 2.5: {"concept": str, "content": dict[str, Any]}
#   - 2.6: {"concept": str, "content": Sequence[dict[str, Any]}
#   Note: Case 2 formats can be provided as plain dict or DictStuffAbstract instance
StuffContentOrData: TypeAlias = (
    str  # Case 1.1
    | Sequence[str]  # Case 1.2
    | StuffContentAbstract  # Case 1.3 (also covers Case 1.5 as ListContent is a StuffContent)
    | Sequence[StuffContentAbstract]  # Case 1.4 (covariant - accepts list[TextContent], etc.)
    | dict[str, Any]  # Case 2.1-2.7 - plain dicts with {"concept": str, "content": Any} structure
    | DictStuffAbstract  # Case 2.7 - DictStuffAbstract instances (same structure as dict but as Pydantic model)
)
PipelineInputs: TypeAlias = dict[str, StuffContentOrData]  # Can include both dict and StuffContent
