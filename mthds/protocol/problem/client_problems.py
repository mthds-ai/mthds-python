"""The problems a client builds itself, for a failure the runtime's answer does not describe.

A client reads every failure as a problem under a registered code: the runtime's own problem when it
sent one, and otherwise a problem the client states from the registry, such as `client.unreachable`
when no connection opened or `client.response_unreadable` when the answer is no problem document.
`make_client_problem` builds one from the generated registry alone, so that every client of the
standard states the same failure in the same words:

- `type` is the code's page under the core base URL, and `title`, `domain` and `retry` are the code's.
- `detail` and the step's `detail` are the code's templates with its parameters filled in: `{name}`
  takes the parameter's value, a list joined with ", ", and `{{` and `}}` are literal braces.
- The step is the one aimed at the domain's actor when the client's caller is that actor, as for the
  domains `input` (the caller) and `runtime` (nobody beforehand, so whoever reads it), and the one
  aimed at any other reader for the domains `method`, `account` and `operator`.
- `params` is present whenever the code declares parameters, an operator-only one left out, so it
  may be empty; an integral number reads as an integer, as a JavaScript client writes it.
- `status` is given only for a code the client reads from an answer's status, never for a code of
  its own, which describes no answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from mthds.protocol.problem.models import Problem
from mthds.protocol.problem.registry import CORE_BASE_URL, CORE_CODE_SPECS, CoreCode, ProblemDomain, StepSpec

if TYPE_CHECKING:
    from collections.abc import Mapping


def render_template(template: str, *, params: Mapping[str, Any]) -> str:
    """Fill a registry template with a code's parameters.

    Args:
        template: A code's `detail` or a step's `detail`, naming parameters as `{name}`.
        params: The parameters, by name.

    Returns:
        The sentence, `{name}` replaced by the parameter's value, a list's items joined with ", ",
        and `{{` and `}}` read as literal braces.

    Raises:
        ValueError: If the template names a parameter `params` does not hold, or a brace is unmatched.
    """
    pieces: list[str] = []
    index_char = 0
    while index_char < len(template):
        char = template[index_char]
        if template.startswith("{{", index_char):
            pieces.append("{")
            index_char += 2
            continue
        if template.startswith("}}", index_char):
            pieces.append("}")
            index_char += 2
            continue
        if char == "{":
            end = template.find("}", index_char)
            if end < 0:
                msg = f"The template '{template}' opens a brace it never closes."
                raise ValueError(msg)
            name = template[index_char + 1 : end]
            if name not in params:
                msg = f"The template '{template}' names the parameter '{name}', which is not given."
                raise ValueError(msg)
            pieces.append(_rendered_value(params[name]))
            index_char = end + 1
            continue
        pieces.append(char)
        index_char += 1
    return "".join(pieces)


def _rendered_value(value: Any) -> str:
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return ", ".join(_rendered_value(item) for item in items)
    return str(_json_value(value))


def _json_value(value: Any) -> Any:
    """A parameter's value as a JSON writer writes it: an integral float as an integer, a list item by item."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        items = cast("list[Any]", value)
        return [_json_value(item) for item in items]
    return value


def _caller_step(code: CoreCode) -> StepSpec:
    """The step a client's caller reads for a code the client states itself."""
    spec = CORE_CODE_SPECS[code]
    match spec.domain:
        case ProblemDomain.INPUT | ProblemDomain.RUNTIME:
            return spec.actor_step
        case ProblemDomain.METHOD | ProblemDomain.ACCOUNT | ProblemDomain.OPERATOR:
            return spec.other_step


def make_client_problem(
    code: CoreCode,
    *,
    params: Mapping[str, Any] | None = None,
    status: int | None = None,
    retry_after: float | None = None,
) -> Problem:
    """Build the problem a client states for `code`, from the registry alone.

    Args:
        code: A core code.
        params: The code's parameters, by name; an optional or operator-only one may be left out.
        status: The status of the answer the problem reads, for a code read from an answer's status.
        retry_after: The delay before a retry, for a code whose retry verdict is `yes`.

    Returns:
        The problem, as `Problem` reads it.

    Raises:
        ValueError: If `params` names a parameter the code does not declare.
        pydantic.ValidationError: If a parameter has the wrong type.
    """
    spec = CORE_CODE_SPECS[code]
    given = {name: _json_value(value) for name, value in (params or {}).items()}
    declared = {param.name for param in spec.params}
    undeclared = sorted(set(given) - declared)
    if undeclared:
        msg = f"The code '{code}' declares no parameter {', '.join(undeclared)}."
        raise ValueError(msg)
    validated = spec.params_model.model_validate(given).model_dump(mode="json", exclude_none=True)
    operator_only = {param.name for param in spec.params if param.operator_only}
    wire_params = {name: value for name, value in validated.items() if name in declared and name not in operator_only}
    step = _caller_step(code)
    members: dict[str, Any] = {
        "type": f"{CORE_BASE_URL}/{code}",
        "title": spec.title,
        "detail": render_template(spec.detail, params=wire_params),
        "code": spec.code,
        "domain": spec.domain,
        "retry": spec.retry,
        "next_step": {"kind": step.kind, "detail": render_template(step.detail, params=wire_params)},
    }
    if spec.params:
        members["params"] = wire_params
    if status is not None:
        members["status"] = status
    if retry_after is not None:
        members["retry_after"] = _json_value(retry_after)
    return Problem.model_validate(members)
