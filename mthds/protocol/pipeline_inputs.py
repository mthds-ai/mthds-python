from typing import Any, Sequence

from typing_extensions import TypeAlias

from mthds.protocol.stuff import StuffContentAbstract

# StuffContentOrData represents all possible formats for a pipeline input value:
# Case 1: Direct content (no 'concept' key)
#   - 1.1: str (simple string)
#   - 1.2: Sequence[str] (list of strings)
#   - 1.3: StuffContent (a StuffContent object)
#   - 1.4: Sequence[StuffContent] (list of StuffContent objects, covariant)
#   - 1.5: ListContent[StuffContent] (a ListContent object containing StuffContent items)
# Case 2: Dict with 'concept' AND 'content' keys
#   - 2.1-2.6: {"concept": str, "content": str | Sequence[str] | StuffContent | Sequence[StuffContent] | dict | Sequence[dict]}
#   Provided as a plain dict (the dict-serialized `DictStuff` form lives runner-side, in mthds.runners.api.models).
StuffContentOrData: TypeAlias = (
    str  # Case 1.1
    | Sequence[str]  # Case 1.2
    | StuffContentAbstract  # Case 1.3 (also covers Case 1.5 as ListContent is a StuffContent)
    | Sequence[StuffContentAbstract]  # Case 1.4 (covariant - accepts list[TextContent], etc.)
    | dict[str, Any]  # Case 2.x - plain dicts with {"concept": str, "content": Any} structure
)
PipelineInputs: TypeAlias = dict[str, StuffContentOrData]  # Can include both dicts and StuffContent
