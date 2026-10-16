"""The problem document of the MTHDS Protocol, as a reader reads it: RFC 9457 members plus the core's.

`Problem` is the body of every error answer a runner sends, and the shape every error this package
raises carries on its `problem` attribute, whether the runner sent it or the client built it for a
failure that never reached the runner. `ProblemItem` is one fault of a problem with several, and
the item of a `/validate` verdict's `errors` and `warnings`.

The models follow the protocol's reader rules (the "Errors" section of the standard's protocol page):

- **Closed for emitters, open for readers.** Every model accepts members it does not declare and
  keeps them, so `problem.model_extra` holds a runner's `request_id` or any member a later protocol
  adds. A domain, a retry verdict, a step kind or a fix's safety the protocol does not list is kept
  as the plain string received, since this package widens each of these enums to any string; a
  value it lists reads as the enum member. A fix operation of a kind the protocol does not list
  reads as `UnknownFixOp`.
- **The declared members are typed.** A body whose declared member has the wrong type, such as a
  `status` written as a string, a `null` where the protocol leaves a member out, or a code outside
  the code pattern, is no problem document, and the client reads it as an unreadable answer.
- **A reader falls back on the family.** `effective_domain` and `effective_step_kind` read a value
  the reader does not know by the code's family, as the generated registry declares it, then as
  `runtime` and `report`. A retry verdict is never read by the family: `effective_retry` reads an
  unknown one as `no`, so that nothing is repeated on a guess. `effective_safety` reads an unknown
  safety as `unsafe`.

`as_wire()` gives a problem back as the members it was read from, in JSON types.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self, TypeAlias, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, model_validator

from mthds.protocol.problem.json_types import JsonInteger, JsonNumber
from mthds.protocol.problem.registry import (
    CORE_CODE_SPECS,
    FAMILY_DOMAINS,
    FAMILY_STEP_KINDS,
    CodeSpec,
    ProblemDomain,
    RetryVerdict,
    StepKind,
)

if TYPE_CHECKING:
    import builtins

PROBLEM_CODE_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,2}$"
"""The shape of a registry code: lowercase and dotted, a family and a name, after its owner's prefix for an extension code."""

FIX_CODE_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
"""The shape of a suggested fix's `fix_code`: kebab case."""

ParamsModelT = TypeVar("ParamsModelT", bound=BaseModel)


class FixSafety(StrEnum):
    """Whether a suggested fix may be applied without asking anyone."""

    SAFE = "safe"
    UNSAFE = "unsafe"


class _ProblemPart(BaseModel):
    """The base of every model of the problem document: open to undeclared members, closed to `null` declared ones.

    The protocol leaves a member with no value out and never writes it as `null`, so a declared
    member given as `null` is a mistyped member, and the document holding it does not validate.
    """

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _refuse_null_members(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        members = cast("dict[str, Any]", data)
        for name in cls.model_fields:
            if name in members and members[name] is None:
                msg = f"The member '{name}' is null; a member with no value is left out."
                raise ValueError(msg)
        return members

    def as_wire(self) -> dict[str, Any]:
        """The members this was read or built from, in JSON types, undeclared members included."""
        return self.model_dump(mode="json", exclude_unset=True)


def _family_of(code: str) -> str:
    """A code's family: the code without its last segment."""
    return code.rsplit(".", 1)[0]


def _family_domain(code: str) -> ProblemDomain:
    return FAMILY_DOMAINS.get(_family_of(code), ProblemDomain.RUNTIME)


class ProblemParams(_ProblemPart):
    """The typed facts a problem's sentences were written from.

    Each code declares its own parameters, and the generated registry gives each core code a model of
    them (`CORE_CODE_SPECS[code].params_model`), which `Problem.params_as` validates into. This model
    types only the parameter the protocol types for every reader, `missing_blobs`; every other
    parameter rides `model_extra` as received.
    """

    missing_blobs: list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]] | None = None


class ProblemLocation(_ProblemPart):
    """Where the error happened, in the method, the request or the run; every member is optional."""

    pipe: str | None = None
    path: list[str] | None = None
    input: str | None = None
    field: str | None = None
    item: Annotated[JsonInteger, Field(ge=0)] | None = None
    attempt: Annotated[JsonInteger, Field(ge=1)] | None = None
    file: str | None = None
    line: Annotated[JsonInteger, Field(ge=1)] | None = None
    column: Annotated[JsonInteger, Field(ge=1)] | None = None


class NextStep(_ProblemPart):
    """What the reader should do next: a kind from the protocol's closed list, and the step in one sentence."""

    kind: Annotated[StepKind | str, Field(union_mode="left_to_right")]
    detail: str


# ── Suggested fixes ────────────────────────────────────────────────────


TomlScalar: TypeAlias = bool | int | float | str
TomlValue: TypeAlias = TomlScalar | dict[str, TomlScalar]


class SetKeyOp(_ProblemPart):
    """Write `key = value` in the table at `table_path`."""

    kind: Literal["set_key"]
    table_path: list[str]
    key: str
    value: TomlValue


class EnsureTableOp(_ProblemPart):
    """Create the table at `table_path` when it is absent."""

    kind: Literal["ensure_table"]
    table_path: Annotated[list[str], Field(min_length=1)]


class DeleteKeyOp(_ProblemPart):
    """Remove `key` from the table at `table_path`."""

    kind: Literal["delete_key"]
    table_path: list[str]
    key: str


class DeleteTableOp(_ProblemPart):
    """Remove the table at `table_path`, every part of it included."""

    kind: Literal["delete_table"]
    table_path: Annotated[list[str], Field(min_length=1)]


class RenameTableKeyOp(_ProblemPart):
    """Rename `key` to `new_key` within the table at `table_path`."""

    kind: Literal["rename_table_key"]
    table_path: list[str]
    key: str
    new_key: str


class MoveKeyOp(_ProblemPart):
    """Move `key` from the table at `table_path` into the table at `new_table_path` under `new_key`."""

    kind: Literal["move_key"]
    table_path: list[str]
    key: str
    new_table_path: list[str]
    new_key: str


class RemapValueOp(_ProblemPart):
    """Rewrite the string value of `key` in the table at `table_path` through `mapping`."""

    kind: Literal["remap_value"]
    table_path: list[str]
    key: str
    mapping: Annotated[dict[str, str], Field(min_length=1)]


class UnknownFixOp(_ProblemPart):
    """The reader-side catch-all: an operation whose `kind` is none the protocol lists, which an applier never applies."""

    kind: str


_KNOWN_FIX_OP_KINDS: frozenset[str] = frozenset(
    {"set_key", "ensure_table", "delete_key", "delete_table", "rename_table_key", "move_key", "remap_value"}
)
_UNKNOWN_FIX_OP_TAG = "unknown"


def _fix_op_tag(value: Any) -> str:
    """The variant an operation matches: its own kind when the protocol lists it, the catch-all otherwise."""
    kind: Any
    if isinstance(value, dict):
        kind = cast("dict[str, Any]", value).get("kind")
    else:
        kind = getattr(value, "kind", None)
    if isinstance(kind, str) and kind in _KNOWN_FIX_OP_KINDS:
        return kind
    return _UNKNOWN_FIX_OP_TAG


FixOp: TypeAlias = Annotated[
    Annotated[SetKeyOp, Tag("set_key")]
    | Annotated[EnsureTableOp, Tag("ensure_table")]
    | Annotated[DeleteKeyOp, Tag("delete_key")]
    | Annotated[DeleteTableOp, Tag("delete_table")]
    | Annotated[RenameTableKeyOp, Tag("rename_table_key")]
    | Annotated[MoveKeyOp, Tag("move_key")]
    | Annotated[RemapValueOp, Tag("remap_value")]
    | Annotated[UnknownFixOp, Tag(_UNKNOWN_FIX_OP_TAG)],
    Discriminator(_fix_op_tag),
]
"""One operation of a suggested fix, matched on its `kind`, with `UnknownFixOp` taking every kind the protocol does not list."""


class SuggestedFix(_ProblemPart):
    """A deterministic fix for one fault: operations over a bundle of the method, addressed by TOML key path."""

    fix_code: Annotated[str, Field(pattern=FIX_CODE_PATTERN)]
    description: str
    safety: Annotated[FixSafety | str, Field(union_mode="left_to_right")]
    file: str | None = None
    ops: Annotated[list[FixOp], Field(min_length=1)]

    @property
    def effective_safety(self) -> FixSafety:
        """The fix's safety, a value the reader does not know reading as `unsafe`."""
        if isinstance(self.safety, FixSafety):
            return self.safety
        return FixSafety.UNSAFE

    @property
    def is_applicable(self) -> bool:
        """Whether an applier may apply the fix: never when one of its operations is of a kind it does not know."""
        return not any(isinstance(operation, UnknownFixOp) for operation in self.ops)


# ── Items and problems ─────────────────────────────────────────────────


class ProblemItem(_ProblemPart):
    """One fault of a problem with several, and one finding of a `/validate` verdict.

    An item carries its own code but no verdict; `effective_domain` reads its domain from its code.
    """

    code: Annotated[str, Field(pattern=PROBLEM_CODE_PATTERN)]
    detail: str
    params: ProblemParams | None = None
    location: ProblemLocation | None = None
    suggestions: list[str] | None = None
    suggested_fix: SuggestedFix | None = None

    @property
    def code_spec(self) -> CodeSpec | None:
        """The registry's entry for the item's code, `None` for a code the core registry does not hold."""
        return CORE_CODE_SPECS.get(self.code)

    @property
    def effective_domain(self) -> ProblemDomain:
        """Who must act on this fault: its code's domain, else its family's, else `runtime`."""
        spec = self.code_spec
        if spec is not None:
            return spec.domain
        return _family_domain(self.code)

    def params_as(self, params_model: type[ParamsModelT]) -> ParamsModelT:
        """The item's parameters validated into `params_model`, such as a code's generated parameters model.

        Raises:
            pydantic.ValidationError: If the parameters do not validate into the model.
        """
        return params_model.model_validate(self.params.as_wire() if self.params is not None else {})


class Problem(_ProblemPart):
    """An RFC 9457 problem document carrying the MTHDS core members.

    `type`, `title`, `status` and `detail` are the RFC's; `code`, `domain`, `retry`, `retry_after`,
    `next_step`, `params`, `location`, `errors` and `pipeline_run_id` are the core's. A program
    branches on `code`, and on `effective_domain`, `effective_retry` and `effective_step_kind`,
    which read every value the protocol lists; for one it does not, the domain and the step kind fall
    back on the code's family and the retry verdict reads as `no`. The sentences (`detail`,
    `next_step.detail`) are for a person and are never parsed.

    `status` is the HTTP status of the answer the problem is the body of: a runner always writes it,
    the client fills it from the answer when a body leaves it out, and a problem the client builds for
    a failure of its own has none. `retry_after` is the delay before a retry, when known.
    """

    type: str
    title: str
    status: Annotated[JsonInteger, Field(ge=100, le=599)] | None = None
    detail: str
    code: Annotated[str, Field(pattern=PROBLEM_CODE_PATTERN)]
    domain: Annotated[ProblemDomain | str, Field(union_mode="left_to_right")]
    retry: Annotated[RetryVerdict | str, Field(union_mode="left_to_right")]
    retry_after: Annotated[JsonNumber, Field(ge=0)] | None = None
    next_step: NextStep
    params: ProblemParams | None = None
    location: ProblemLocation | None = None
    errors: Annotated[list[ProblemItem], Field(min_length=1)] | None = None
    pipeline_run_id: str | None = None

    @property
    def family(self) -> str:
        """The code's family: the code without its last segment."""
        return _family_of(self.code)

    @property
    def code_spec(self) -> CodeSpec | None:
        """The registry's entry for the problem's code, `None` for a code the core registry does not hold."""
        return CORE_CODE_SPECS.get(self.code)

    @property
    def effective_domain(self) -> ProblemDomain:
        """Who must act: the problem's domain, else its family's, else `runtime`."""
        if isinstance(self.domain, ProblemDomain):
            return self.domain
        return _family_domain(self.code)

    @property
    def effective_retry(self) -> RetryVerdict:
        """Whether repeating the operation can succeed, a verdict the reader does not know reading as `no`, never by the family."""
        if isinstance(self.retry, RetryVerdict):
            return self.retry
        return RetryVerdict.NO

    @property
    def effective_step_kind(self) -> StepKind:
        """What to do next: the step's kind, else its family's, else `report`."""
        if isinstance(self.next_step.kind, StepKind):
            return self.next_step.kind
        return FAMILY_STEP_KINDS.get(self.family, StepKind.REPORT)

    @property
    def is_retryable(self) -> bool:
        """Whether the operation may be repeated: only for a retry verdict of `yes`.

        This package never repeats a request by itself. A caller that does repeats only when this is
        true, after `retry_after` seconds when it is given, and never on `outcome_unknown`, where
        the run may already exist: it reads the run instead.
        """
        match self.effective_retry:
            case RetryVerdict.YES:
                return True
            case RetryVerdict.NO | RetryVerdict.OUTCOME_UNKNOWN:
                return False

    @property
    def outcome_is_unknown(self) -> bool:
        """Whether the operation may already have taken effect, so that it must never be repeated automatically."""
        match self.effective_retry:
            case RetryVerdict.OUTCOME_UNKNOWN:
                return True
            case RetryVerdict.NO | RetryVerdict.YES:
                return False

    def params_as(self, params_model: builtins.type[ParamsModelT]) -> ParamsModelT:
        """The problem's parameters validated into `params_model`, such as a code's generated parameters model.

        Raises:
            pydantic.ValidationError: If the parameters do not validate into the model.
        """
        return params_model.model_validate(self.params.as_wire() if self.params is not None else {})

    def with_members(self, **members: Any) -> Self:
        """A copy with `members` added or replaced, validated again so that they count as read."""
        return self.__class__.model_validate({**self.as_wire(), **members})
