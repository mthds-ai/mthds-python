"""The JSON number types every model of the problem document validates against, in strict reading.

Pydantic's lax mode reads `"422"` and `true` as the integer `422` and `1`, which no reader of the
protocol does: JSON gives a number as a number. `JsonInteger` and `JsonNumber` accept only a JSON
number, and read an integral one as an `int`, as a JavaScript reader sees it, so that `2.0` reads as
`2`. Both the problem models (`mthds.protocol.problem.models`) and the generated parameters models of
the core registry (`mthds.protocol.problem.registry`) use them. The problem models import the
registry, so the types live in a module of their own, which the generated registry imports without
a cycle.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, TypeAlias

from pydantic import BeforeValidator
from pydantic_core import PydanticCustomError


def integral_as_int(value: float) -> int | float:
    """A JSON number as a JavaScript reader sees it: a float with no fractional part reads as an `int`, so that `2.0` reads as `2`."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _json_integer(value: Any) -> Any:
    """Accept a JSON integer only: a number with no fractional part, never a string or a boolean."""
    if isinstance(value, bool) or not isinstance(value, int | float) or (isinstance(value, float) and not value.is_integer()):
        error_type = "json_integer"
        msg = "A JSON integer is required."
        raise PydanticCustomError(error_type, msg)
    return int(value)


def _json_number(value: Any) -> Any:
    """Accept a JSON number only, never a string, a boolean, an infinity or `NaN`; an integral value reads as an integer."""
    if isinstance(value, bool) or not isinstance(value, int | float) or (isinstance(value, float) and not math.isfinite(value)):
        error_type = "json_number"
        msg = "A JSON number is required."
        raise PydanticCustomError(error_type, msg)
    return integral_as_int(value)


JsonInteger: TypeAlias = Annotated[int, BeforeValidator(_json_integer)]
"""A JSON integer: `422` and `422.0` read as `422`, while `"422"` and `true` are refused."""

JsonNumber: TypeAlias = Annotated[int | float, BeforeValidator(_json_number)]
"""A JSON number: an integral value reads as an `int`, as a JavaScript reader sees it, and a string, a boolean, an infinity or `NaN` is refused."""
