"""Wire models for pipe I/O contracts — mirrors `docs/spec/pipe-io-contracts.md` (the standard's normative page, `mthds` v0.9.0).

    pipe_io_contracts : PipeIOContracts = dict[pipe_ref, PipeIOContract]
        PipeIOContract.inputs : dict[input name, PipeInputContract]
        PipeIOContract.output : PipeOutputContract

A pipe I/O contract states, for one pipe, exactly what a caller must supply and what the
pipe resolves to: for each declared input, the concept it expects, its authored presence
marker, how many items it takes and the JSON Schema its content must satisfy; for the
output, the concept it produces and how many items that is. It is a projection of the
resolved library, not a second declaration of it.

The artifact is a **recommended extension field** of the `POST /validate` valid report,
where it rides the field name `pipe_io_contracts` (`ValidationReport.model_extra`). It is
equally derivable offline from a resolved library, with no server involved; these models
type it wherever it is obtained, and they are deliberately free of anything runtime-
specific so that an engine imports them for what it emits rather than restating them.

Closed shapes. Every object the page defines — a contract entry, an input contract, an
output contract — is a closed shape (`extra="forbid"`): a member this version of the
standard does not define is version drift, and it is rejected here, at the parse, where
catching it is cheap. That is the deliberate opposite of the validate report's own
extension policy: the report is the envelope and grows; the artifact is the contract and
does not. Growth happens through the standard, as a minor version.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, model_validator


class PresenceMarker(StrEnum):
    """The authored presence marker of a declared input slot, verbatim and three-valued.

    `plain` (no marker) and `force` (`!`) are the same requirement on the caller — the slot
    must be supplied — and differ only in what the author asserted; `optional` (`?`) means the
    caller may omit the slot and the pipe handles the absence itself. The distinction is kept on
    the wire because lint and graph surfaces read it, and a producer flattening it to a boolean
    would destroy it for every consumer at once. A consumer that only needs "may this be absent?"
    answers it as `is_optional`, in exactly one place.
    """

    PLAIN = "plain"
    OPTIONAL = "optional"
    FORCE = "force"

    @property
    def is_optional(self) -> bool:
        """Whether the caller may omit the slot — the one question most consumers ask of a marker."""
        match self:
            case PresenceMarker.OPTIONAL:
                return True
            case PresenceMarker.PLAIN | PresenceMarker.FORCE:
                return False

    @property
    def is_plain(self) -> bool:
        """Whether the slot was authored with no marker at all — what a plural slot always reports."""
        match self:
            case PresenceMarker.PLAIN:
                return True
            case PresenceMarker.OPTIONAL | PresenceMarker.FORCE:
                return False


class IOMultiplicity(StrEnum):
    """How many items a slot takes or a pipe resolves to: one item, a variable-length list, or a fixed count.

    Read together with `item_count`, which is non-null exactly on the `fixed` arm. `Concept[1]`
    is `single` — one item, no list framing — because the language says so, so a `fixed` count on
    this wire is always greater than one.
    """

    SINGLE = "single"
    VARIABLE = "variable"
    FIXED = "fixed"

    @property
    def is_plural(self) -> bool:
        """Whether the slot carries a list (`variable` or `fixed`) rather than one item."""
        match self:
            case IOMultiplicity.VARIABLE | IOMultiplicity.FIXED:
                return True
            case IOMultiplicity.SINGLE:
                return False


def _check_item_count_pairing(*, multiplicity: IOMultiplicity, item_count: int | None) -> None:
    """Enforce the pair rule: `item_count` is non-null exactly when `multiplicity` is `fixed`, and then at least 2."""
    match multiplicity:
        case IOMultiplicity.FIXED:
            if item_count is None:
                msg = "A 'fixed' multiplicity must carry its exact 'item_count'"
                raise ValueError(msg)
            if item_count < 2:
                msg = f"A 'fixed' multiplicity carries a count of at least 2, got {item_count}: a count of one is 'single'"
                raise ValueError(msg)
        case IOMultiplicity.SINGLE | IOMultiplicity.VARIABLE:
            if item_count is not None:
                msg = f"'item_count' is null off the 'fixed' arm, got {item_count} with multiplicity '{multiplicity}'"
                raise ValueError(msg)


class PipeInputContract(BaseModel):
    """One declared input slot: the concept it expects, its presence, its plurality and the JSON Schema of its content.

    Keyed in `PipeIOContract.inputs` by the authored input name, dotted names included.
    Every member is required: `item_count` is always on the wire, `null` off the fixed arm.
    Closed shape (`extra="forbid"`): an unknown member is version drift, rejected at the parse.
    """

    model_config = ConfigDict(extra="forbid")

    concept_ref: str
    """The fully-qualified concept the slot expects, with any multiplicity suffix stripped — a
    `Concept[]` slot names `Concept`. Plurality is stated by `multiplicity`, never here, and
    concept identity is read from this member, never sniffed out of `json_schema`."""

    presence: PresenceMarker
    """The authored presence marker, verbatim. A slot whose `multiplicity` is `variable` or `fixed`
    always reports `plain`: markers may not be combined with multiplicity."""

    multiplicity: IOMultiplicity
    item_count: int | None
    """The exact item count, non-null exactly when `multiplicity` is `fixed`. Always on the wire —
    the input-form descriptor makes the opposite choice and omits the slot when it does not apply;
    the two artifacts differ deliberately, and each states its own rule."""

    json_schema: dict[str, Any]
    """The JSON Schema of the slot's content — what the caller puts in the slot, not its envelope.
    A plural slot's schema is `{"type": "array", "items": <element schema>}`, carrying `minItems`
    and `maxItems` equal to `item_count` on the fixed arm only. The page fixes those two rules
    and nothing else about the projection."""

    @model_validator(mode="after")
    def validate_item_count_pairing(self) -> Self:
        _check_item_count_pairing(multiplicity=self.multiplicity, item_count=self.item_count)
        return self

    @model_validator(mode="after")
    def validate_presence_pairing(self) -> Self:
        """Markers may not be combined with multiplicity, so a plural slot always reports `plain`."""
        if self.multiplicity.is_plural and not self.presence.is_plain:
            msg = f"A '{self.multiplicity}' slot reports presence 'plain', got '{self.presence}': markers may not be combined with multiplicity"
            raise ValueError(msg)
        return self


class PipeOutputContract(BaseModel):
    """What the pipe resolves to: the concept it produces, how many items that is, and whether it may be absent.

    Deliberately asymmetric with the input side: an output carries a two-valued `optional` where
    an input carries a three-valued `presence`, because `!` MUST NOT appear on an output — a force
    marker is a use-site assertion about an input, so a three-valued output slot would have an arm
    nothing can ever produce. No output member carries a schema: the payload a run produces is the
    run's own result. Closed shape (`extra="forbid"`).
    """

    model_config = ConfigDict(extra="forbid")

    concept_ref: str
    """The fully-qualified concept the pipe produces, multiplicity suffix stripped."""

    multiplicity: IOMultiplicity
    item_count: int | None
    """The exact item count, non-null exactly when `multiplicity` is `fixed` — always on the wire,
    the same rule as `PipeInputContract.item_count`."""

    optional: bool
    """`True` when the output is declared optional (`?`): a **successful** run may leave it absent —
    a recorded absence instead of a value — not that the run may fail. Never `True` on a plural output:
    `?` may not be combined with multiplicity, and an absent plural is the empty list."""

    @model_validator(mode="after")
    def validate_item_count_pairing(self) -> Self:
        _check_item_count_pairing(multiplicity=self.multiplicity, item_count=self.item_count)
        return self

    @model_validator(mode="after")
    def validate_optional_pairing(self) -> Self:
        """`?` may not be combined with multiplicity: a plural output is never optional, it is the empty list."""
        if self.multiplicity.is_plural and self.optional:
            msg = f"A '{self.multiplicity}' output is never 'optional': an absent plural is the empty list, not a recorded absence"
            raise ValueError(msg)
        return self


class PipeIOContract(BaseModel):
    """The contract of one pipe — one `pipe_io_contracts` entry, with both members required.

    `inputs` is a map from authored input name to input contract, and it deliberately contracts no
    order: an ordered view of a pipe's inputs is the input-form descriptor's job, which keeps this
    artifact byte-stable whatever a renderer needs. A pipe with no declared inputs carries
    `inputs: {}` — a stated fact, never an omitted member. Closed shape (`extra="forbid"`).
    """

    model_config = ConfigDict(extra="forbid")

    inputs: dict[str, PipeInputContract]
    output: PipeOutputContract


PipeIOContracts: TypeAlias = dict[str, PipeIOContract]
"""The `pipe_io_contracts` artifact: namespaced `pipe_ref` (`domain_path.pipe_code`) → the pipe's contract.

Every pipe in the resolved library has an entry, contract-only pipe signatures included; a bare or
same-domain-implicit key never appears. The input-form descriptor is keyed by the same `pipe_ref`
set. The artifact arrives as an extension field of the validate report, so a consumer parses it
by declaring a typed field — `pipe_io_contracts: PipeIOContracts | None = None` on a model
extending the report — and pydantic parses the whole map from that plain annotation; no adapter
machinery is involved.
"""
