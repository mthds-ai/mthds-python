"""Wire models for the input-form descriptor — mirrors `docs/spec/input-form-descriptor.md` (the standard's normative page, `mthds` v0.9.0).

    input_form : InputForm = dict[pipe_ref, PipeInputFormDescriptor]
        PipeInputFormDescriptor.fields : list[InputFormField], in authored input order
            InputFormField = TextField | ProseField | DateField | NumberField | BooleanField
                           | EnumField | DocumentField | ImageField | ObjectField | ListField
                           | UnknownField                          (discriminated on `kind`)
                ObjectField.fields : list[InputFormField]          (recursion through a structure)
                ListField.item     : InputFormItem                 (recursion through an element)
            InputFormItem  = TextItem | ProseItem | … | UnknownItem
                             (the same closed union, one layer down: every slot but `name`)

The descriptor is the presentation view of a method's inputs: for each pipe, an ordered list
of field descriptors a renderer turns into a fill-in form with no schema heuristics, no
hardcoded native-concept table and no description matching — every fact a form needs is
stated. It is a **recommended extension field** of the `POST /validate` valid report, where
it rides the field name `input_form` (`ValidationReport.model_extra`); how a caller asks a
particular implementation for it is that implementation's decision. It is equally derivable
offline from a resolved library, and it is keyed by the same `pipe_ref` set as
`mthds.protocol.pipe_io_contracts`. These models type it wherever it is obtained, and they
are deliberately free of anything runtime-specific so that an engine imports them for what
it emits rather than restating them. The `hints` slot's shape follows
`docs/spec/intent-hints.md`.

Why a discriminated union rather than one model with optional per-kind slots. The page
discriminates on `kind`, gives each kind its own additional slots (`datetime` on `date`,
`integer` and the bounds on `number`, `choices` on `enum`, `fields` on `object`, `item` and
`item_count` on `list`, the constraint slots on the text kinds) and declares every field
descriptor a closed shape. One model carrying every slot as optional could only reject
members the standard never defined at all: it would let a `text` node smuggle `choices` and
a `boolean` node carry `item_count`, and an after-validator would have to restate the page's
whole table by hand to catch that. A union of per-kind models, each `extra="forbid"`, makes
the table the shape itself — a slot that does not belong to a kind is an unknown member of
that kind's model, and a kind's required slots are simply required fields. It is also what
the TypeScript mirror in `mthds-js` declares, so the two clients agree by construction.
A consumer narrows a parsed node with `match node: case ListField(): ...` (or `isinstance`).
A node is never parsed in isolation: the payload arrives as a typed field (see `InputForm`).

Named field, nameless item — two layers, not one optional slot. The page gives `name` as
applicable "on every node except a `list`'s `item`", and says why: an item "has no authored
name and carries no `name` member at all — the index labels items, and a sentinel would be a
value two producers could pick differently". Both halves of that rule are structural here,
so neither needs a validator and neither can be stated only in prose. `InputFormItem` is the
nameless union — the shape of a `list`'s `item`, whose per-kind models (`TextItem`,
`ObjectItem`, …) declare no `name` at all, so a wire item carrying one is an unknown member
of a closed shape. `InputFormField` is that same union one layer up, each per-kind model
(`TextField`, `ObjectField`, …) being its item counterpart plus a required `name: str`, so a
named position that omits it fails the parse and a consumer reading `field.name` gets a
`str` rather than something to narrow. It is the pydantic spelling of the TypeScript mirror's
`InputFormField = InputFormItem & { name: string }`. Which layer applies is decided by
position, never by content: `PipeInputFormDescriptor.fields` and `ObjectField.fields` hold
`InputFormField`, `ListField.item` holds `InputFormItem`.

Absent, never `null`. A slot that does not apply to a node is absent from the wire, and
applicable falsy values (`required: false`, `integer: false`) are stated. The models own
that rule: optional slots are `X | None = None`, and the common serializer drops the `None`s,
so a plain `model_dump()` reproduces the wire without the caller reaching for
`exclude_none` — which would also strip the contract's `item_count: null`, which must stay.
The contrast is deliberate on both sides: the descriptor's `ListField.item_count` is present
exactly on a fixed `[N]` slot and absent otherwise, where the contract carries `null`.
The rule binds the intake too: a wire node spelling absence as an explicit `null` (`title: null`,
`item_count: null` on a variable list) is non-canonical and fails the parse, with `default_value`
the one carve-out — its `null` IS "no default" per the page. Programmatic construction is exempt:
`TextField(..., title=maybe_title)` with `None` stays the natural idiom for an engine, and the
check binds raw wire mappings alone (see `PipeInputFormDescriptor.reject_explicit_wire_nulls`).

Closed shapes. Every object the page defines — a per-pipe descriptor, a field descriptor —
is a closed shape (`extra="forbid"`): a member this version of the standard does not define
is version drift, rejected here, at the parse, where catching it is cheap. That is the
deliberate opposite of the validate report's own extension policy: the report is the
envelope and grows; the artifact is the view and does not. The `hints` map is the sole
exception, and in content only: its shape is fixed and strictly validated (a flat map of
string to string), while unknown keys and unknown intent words inside it are carried
through, exactly as the language's content-leniency rule requires. Growth happens through
the standard, as a minor version.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal, Self, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer, model_validator

from mthds.protocol.pipe_io_contracts import PresenceMarker


class FieldKind(StrEnum):
    """The closed `kind` union of a field descriptor: what the value *is*, never which control renders it.

    Kind is decided from stated facts — a concept's identity, its refinement chain, its resolved
    structure — and never by sniffing a schema's shape or matching a description. `unknown` is the
    mandatory escape hatch: a producer that cannot map a node honestly reports it rather than
    guessing, and a renderer then falls back to raw entry against the contract's `json_schema`.
    """

    TEXT = "text"
    PROSE = "prose"
    DATE = "date"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    DOCUMENT = "document"
    IMAGE = "image"
    OBJECT = "object"
    LIST = "list"
    UNKNOWN = "unknown"


class InputFormItemBase(BaseModel):
    """The common slots every field descriptor carries whatever its kind, and whatever its position — `name` excluded.

    Not a wire shape on its own: a node on the wire is always one of the per-kind models, and
    `InputFormItem` is their discriminated union. Each per-kind item model declares its `kind`
    literal first and its additional slots after these; each per-kind *field* model is that item
    model plus `name` (see `InputFormNamedNode`). Closed shape (`extra="forbid"`): an unknown
    member is version drift, rejected at the parse. A slot that does not apply to a node is
    absent, never `null`; the serializer below owns that rule, so a plain `model_dump()`
    reproduces the wire.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    """Human label; a renderer falls back to `name`. A generated or internal type name is not a
    title and is never reported as one."""

    concept_ref: str | None = None
    """The fully-qualified concept reference the node carries (`native.Document`, `legal.Invoice`):
    present on every top-level field and on every nested node that is concept-typed. On a `list`
    node it names the ELEMENT concept, and the `item` carries the same reference."""

    refines: list[str] | None = None
    """The concept's refinement chain, immediate parent first, walked to its end. Absent when the
    concept refines nothing. "Does this refine `native.X`?" is a membership test on this list."""

    description: str | None = None
    """Helper text, from the authored concept or field description."""

    required: bool
    """On a top-level field, the caller must supply the slot — derived as `presence != "optional"`,
    and a top-level field stating the pair incoherently is rejected at the parse; on a nested
    field, the field must be present within its concept's payload. The two levels never interact.
    Drives layout — whether the *user* must put content in before the run may start is `gating`."""

    presence: PresenceMarker | None = None
    """Top-level fields only: the authored presence marker of the pipe's input slot, three-valued so
    that `!` is not flattened away. Nested fields carry no `presence` — it is a pipe-slot fact, and a
    nested node carrying one is rejected at the parse, as is a top-level field missing one."""

    gating: bool | None = None
    """Top-level fields only: the run cannot start until the caller provides content for this slot.
    Stated rather than re-derived from `required` — a variable-length list is required yet never
    gates, since the empty list is a legitimate value; a fixed-count list does. Nested fields carry no
    `gating`, and a nested node carrying one is rejected at the parse, as is a top-level field
    missing one."""

    default_value: Any = None
    """The value applied when the caller omits the field. Absent unless a default was authored — the
    `null` a schema projection attaches to every optional field is an emission artifact and is never
    reported here. Always beside `required: false`: the pair with `required: true` is rejected."""

    examples: list[Any] | None = None
    """Example values for the field — shaped now, filled by the language later; advisory."""

    hints: dict[str, str] | None = None
    """The node's effective intent hints: the final key-by-key merge the language defines, so a
    consumer reads one map and walks nothing. Flat string-to-string by contract, strictly; unknown
    keys and unknown intent words ride through, content-lenient. A node with no effective hints has
    no `hints` member. Non-normative: a renderer that ignores hints stays correct."""

    @property
    def node_label(self) -> str:
        """How the node names itself when an error message has to point at it.

        A `list`'s `item` has no authored name to give, so it says what it is instead; the named
        layer overrides this with the name. Pydantic reports the location too — this is the half a
        reader recognizes without counting indices.
        """
        return "a list item"

    @model_validator(mode="after")
    def validate_default_needs_optional(self) -> Self:
        """A descriptor never carries both `required: true` and a `default_value`."""
        if self.required and self.default_value is not None:
            msg = f"{self.node_label} carries both 'required: true' and a 'default_value': two contradictory instructions on one node"
            raise ValueError(msg)
        return self

    @model_serializer(mode="wrap")
    def serialize_without_inapplicable_slots(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Drop the slots that do not apply (`None`), keep applicable falsy values, and lead with the identity slots.

        `kind` and `name` come first on the wire the page shows, but a named model declares `name`
        last — it is the layer added on top of the per-kind item model — so the order is restored
        here rather than left to the declaration order two classes apart.
        """
        dumped: dict[str, Any] = handler(self)
        wire = {slot: value for slot, value in dumped.items() if value is not None}
        leading = {slot: wire.pop(slot) for slot in ("kind", "name") if slot in wire}
        return {**leading, **wire}


class TextValuedItemBase(InputFormItemBase):
    """The constraint slots the text kinds (`text`, `prose`) share, stated where a producer holds them."""

    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    format: str | None = None
    """An open string set carrying the schema formats the `date` kind does not absorb (`time`, `uri`, …).
    A `native.Time` slot and a `type = "time"` field are `text` with `format: "time"`."""


class TextItem(TextValuedItemBase):
    """`text` — a short single-line string."""

    kind: Literal[FieldKind.TEXT] = FieldKind.TEXT


class ProseItem(TextValuedItemBase):
    """`prose` — flowing free text."""

    kind: Literal[FieldKind.PROSE] = FieldKind.PROSE


class DateItem(InputFormItemBase):
    """`date` — a calendar date, or a point in time."""

    kind: Literal[FieldKind.DATE] = FieldKind.DATE
    datetime: bool
    """`True` when the value carries a time of day, `False` for a bare calendar date. Required."""


class NumberItem(InputFormItemBase):
    """`number` — an integer or a floating-point number, with its optional bounds."""

    kind: Literal[FieldKind.NUMBER] = FieldKind.NUMBER
    integer: bool
    """`True` when the value is an integer. Required, and stated even when `False`."""

    minimum: int | float | None = None
    maximum: int | float | None = None
    exclusive_minimum: int | float | None = None
    exclusive_maximum: int | float | None = None


class BooleanItem(InputFormItemBase):
    """`boolean` — true or false."""

    kind: Literal[FieldKind.BOOLEAN] = FieldKind.BOOLEAN


class EnumItem(InputFormItemBase):
    """`enum` — one of a fixed set of values."""

    kind: Literal[FieldKind.ENUM] = FieldKind.ENUM
    choices: list[str]
    """The allowed values, verbatim. Required, and always a list even for a single choice, so that
    no consumer has to read a single-value form."""


class DocumentItem(InputFormItemBase):
    """`document` — a document supplied as a file or a URL.

    No accept-list and no upload affordance: what the value is rides `concept_ref` and `refines`,
    and how a renderer offers a file is the renderer's decision.
    """

    kind: Literal[FieldKind.DOCUMENT] = FieldKind.DOCUMENT


class ImageItem(InputFormItemBase):
    """`image` — an image, which a renderer may preview."""

    kind: Literal[FieldKind.IMAGE] = FieldKind.IMAGE


def _check_pipe_slot_facts_absent(*, node: InputFormItemBase, position: str) -> None:
    """Enforce the placement rule: `presence` and `gating` are pipe-slot facts, stated on top-level fields only.

    Raised from the parent, so the error names the offending child itself — pydantic reports the
    location of the node that recursed, not of the member that broke the rule.
    """
    for slot, value in (("presence", node.presence), ("gating", node.gating)):
        if value is not None:
            msg = f"{position} carries '{slot}': '{slot}' is a pipe-slot fact, stated on top-level fields only"
            raise ValueError(msg)


def _raw_node_label(*, node: dict[str, Any], fallback: str) -> str:
    """How a raw wire mapping names itself before the parse gives it a model: by its stated name, else by position."""
    name = node.get("name")
    if isinstance(name, str):
        return f"field '{name}'"
    return fallback


def _check_no_explicit_nulls(*, node: dict[str, Any], position: str) -> None:
    """Reject an explicit `null` in a raw wire node: a slot that does not apply is absent, never `null`.

    `default_value` is the one carve-out — its `null` IS "no default" per the page, opaque authored
    content rather than a non-canonical spelling of absence. Recurses through the two structural
    slots (`fields`, `item`); everything else a node carries is scalar or opaque content. Non-dict
    members are left to the parse itself.
    """
    for slot, value in node.items():
        if value is None and slot != "default_value":
            msg = f"{position} carries '{slot}: null': a slot that does not apply to a node is absent from the wire, never null"
            raise ValueError(msg)
    raw_members = node.get("fields")
    if isinstance(raw_members, list):
        for raw_member in cast("list[Any]", raw_members):
            if isinstance(raw_member, dict):
                nested = cast("dict[str, Any]", raw_member)
                nested_position = (
                    f"Nested {_raw_node_label(node=nested, fallback='field')} of {_raw_node_label(node=node, fallback='an object node')}"
                )
                _check_no_explicit_nulls(node=nested, position=nested_position)
    raw_item = node.get("item")
    if isinstance(raw_item, dict):
        item = cast("dict[str, Any]", raw_item)
        _check_no_explicit_nulls(node=item, position=f"The item of {_raw_node_label(node=node, fallback='a list node')}")


def _check_pipe_slot_facts_stated(*, node: InputFormItemBase, position: str) -> None:
    """Enforce the placement rule's positive half: a top-level field states both pipe-slot facts.

    Raised from the descriptor, so the error names the offending field itself — pydantic reports
    the location of the container that recursed, not of the member that broke the rule.
    """
    for slot, value in (("presence", node.presence), ("gating", node.gating)):
        if value is None:
            msg = f"{position} states no '{slot}': '{slot}' is a pipe-slot fact every top-level field carries"
            raise ValueError(msg)


class ObjectItem(InputFormItemBase):
    """`object` — a structured concept, recursing through its resolved payload fields."""

    kind: Literal[FieldKind.OBJECT] = FieldKind.OBJECT
    fields: list[InputFormField]
    """The concept's effective payload fields, in declared order. Required — empty for a concept
    whose structure declares no field. A structure field is authored under a name, so these are
    `InputFormField`s however the enclosing node was reached."""

    @model_validator(mode="after")
    def validate_nested_placement(self) -> Self:
        """A nested field carries neither `presence` nor `gating`: both are facts of the pipe's input slot."""
        for nested in self.fields:
            _check_pipe_slot_facts_absent(node=nested, position=f"Nested field '{nested.name}' of {self.node_label}")
        return self


class ListItem(InputFormItemBase):
    """`list` — an array of one element type, recursing through its `item`.

    An input slot authored `Concept[]` is a `list` with no `item_count`; one authored `Concept[N]`
    carries `item_count: N`. `Concept[1]` is single — no list framing — so a stated count is always
    at least 2. `concept_ref` and `refines` name the element concept, and the `item` carries the
    same `concept_ref`; on a plural node the merged `hints` ride both the list and its item.
    """

    kind: Literal[FieldKind.LIST] = FieldKind.LIST
    item: InputFormItem
    """The element descriptor, rendered once per entry. Required, and nameless by shape: the
    element is reached by index, so `InputFormItem` is the union with no `name` member to carry."""

    item_count: int | None = None
    """The fixed count as a structured fact — present exactly on a fixed `[N]` slot, absent
    otherwise (the contract carries `null` there instead; the two artifacts differ deliberately)."""

    @model_validator(mode="after")
    def validate_item_count(self) -> Self:
        """A stated `item_count` is always greater than one: a count of one is single, not a list."""
        if self.item_count is not None and self.item_count < 2:
            msg = f"The list at {self.node_label} states 'item_count' {self.item_count}; a fixed count is at least 2, and a count of one is single"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_item_placement(self) -> Self:
        """A list's `item` carries neither `presence` nor `gating`: both are facts of the pipe's input slot."""
        _check_pipe_slot_facts_absent(node=self.item, position=f"The item of {self.node_label}")
        return self


class UnknownItem(InputFormItemBase):
    """`unknown` — not honestly describable as any other kind.

    The mandatory escape hatch that makes a total derivation truthful: a renderer falls back to raw
    entry against the slot's `json_schema` in the pipe I/O contract.
    """

    kind: Literal[FieldKind.UNKNOWN] = FieldKind.UNKNOWN


InputFormItem: TypeAlias = Annotated[
    TextItem | ProseItem | DateItem | NumberItem | BooleanItem | EnumItem | DocumentItem | ImageItem | ObjectItem | ListItem | UnknownItem,
    Field(discriminator="kind"),
]
"""One field descriptor without an authored identifier — the shape a `list`'s `item` carries.

The page's rule, made structural: an item "has no authored name and carries no `name` member at
all", because the index labels items and a sentinel would be a value two producers could pick
differently. None of these models declares `name`, and all are closed shapes, so an item carrying
one is an unknown member and fails the parse. Every other position holds an `InputFormField` —
this same union plus the name.
"""


class InputFormNamedNode(BaseModel):
    """The authored identifier — the one slot that separates a named position from a `list`'s `item`.

    Mixed into each per-kind item model to form its `InputFormField` counterpart, which is the
    pydantic spelling of the TypeScript mirror's `InputFormField = InputFormItem & { name: string }`.
    Not a wire shape on its own, and never mixed into `ListItem.item`: that is the whole point of
    keeping it a separate layer rather than an optional slot on the common base.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    """The identifier as authored: the input slot name on a top-level field, the structure field
    name on a nested one. Required wherever it applies — the page states it for every node it
    admits, so `str | None` would be a shape saying otherwise."""

    @property
    def node_label(self) -> str:
        """How the node names itself when an error message has to point at it: by its name."""
        return f"field '{self.name}'"


class TextField(InputFormNamedNode, TextItem):
    """`text` at a named position — a top-level field or a structure field."""


class ProseField(InputFormNamedNode, ProseItem):
    """`prose` at a named position."""


class DateField(InputFormNamedNode, DateItem):
    """`date` at a named position."""


class NumberField(InputFormNamedNode, NumberItem):
    """`number` at a named position."""


class BooleanField(InputFormNamedNode, BooleanItem):
    """`boolean` at a named position."""


class EnumField(InputFormNamedNode, EnumItem):
    """`enum` at a named position."""


class DocumentField(InputFormNamedNode, DocumentItem):
    """`document` at a named position."""


class ImageField(InputFormNamedNode, ImageItem):
    """`image` at a named position."""


class ObjectField(InputFormNamedNode, ObjectItem):
    """`object` at a named position, recursing through `fields` — themselves named."""


class ListField(InputFormNamedNode, ListItem):
    """`list` at a named position, recursing through a nameless `item`."""


class UnknownField(InputFormNamedNode, UnknownItem):
    """`unknown` at a named position."""


InputFormField: TypeAlias = Annotated[
    TextField | ProseField | DateField | NumberField | BooleanField | EnumField | DocumentField | ImageField | ObjectField | ListField | UnknownField,
    Field(discriminator="kind"),
]
"""One named field descriptor: a recursive node, discriminated on `kind` — one per-kind model per kind of the closed union.

This is `InputFormItem` plus a required `name`, and it is what every position but a `list`'s
`item` holds: `PipeInputFormDescriptor.fields` (the top-level fields, in authored input order) and
`ObjectField.fields` (a structure's payload fields). An `object` node recurses through `fields`
into more of these, a `list` node through `item` into an `InputFormItem`. A node is reached by
parsing the payload it arrives in (see `InputForm`), never parsed in isolation; a consumer narrows
a parsed node with `match` or `isinstance`.
"""

# The two recursive kinds name the union aliases before those exist; resolve them now that they do.
ObjectItem.model_rebuild()
ListItem.model_rebuild()
ObjectField.model_rebuild()
ListField.model_rebuild()


class PipeInputFormDescriptor(BaseModel):
    """The input form of one pipe — one `input_form` entry.

    `fields` holds one descriptor per declared input slot, in authored input order: the order is why
    the descriptor is a sibling artifact of the contract rather than a decoration inside it. A pipe
    with no inputs maps to `{"fields": []}` — an empty form is a valid form, not an omitted entry.
    Closed shape (`extra="forbid"`).
    """

    model_config = ConfigDict(extra="forbid")

    fields: list[InputFormField]

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_wire_nulls(cls, data: Any) -> Any:
        """A wire payload never spells absence as `null`: an explicit `null` on any slot but `default_value` fails the parse.

        Stated here, on the container every wire node arrives through, rather than on the node
        base: a node-level `mode="before"` validator cannot tell a raw wire mapping from the
        keyword arguments of a programmatic construction, and an engine building nodes with
        `title=None` and friends is the supported idiom. At this level the two are
        distinguishable — wire nodes arrive as raw mappings, programmatic ones as already-built
        models — so only the mappings are walked.
        """
        if not isinstance(data, dict):
            return data
        raw_form = cast("dict[str, Any]", data)
        raw_fields = raw_form.get("fields")
        if isinstance(raw_fields, list):
            for raw_field in cast("list[Any]", raw_fields):
                if isinstance(raw_field, dict):
                    raw_node = cast("dict[str, Any]", raw_field)
                    _check_no_explicit_nulls(node=raw_node, position=f"Top-level {_raw_node_label(node=raw_node, fallback='field')}")
        return raw_form

    @model_validator(mode="after")
    def validate_top_level_placement(self) -> Self:
        """A top-level field states both `presence` and `gating`: pipe-slot facts are stated, never re-derived."""
        for field in self.fields:
            _check_pipe_slot_facts_stated(node=field, position=f"Top-level {field.node_label}")
        return self

    @model_validator(mode="after")
    def validate_required_restates_presence(self) -> Self:
        """A top-level field's `required` agrees with its marker: `required == (presence != "optional")`, exactly as the page derives it."""
        for field in self.fields:
            if field.presence is not None and field.required is field.presence.is_optional:
                msg = (
                    f"Top-level {field.node_label} states 'required: {str(field.required).lower()}' beside 'presence: {field.presence}': "
                    "on a top-level field, 'required' is derived as presence != 'optional'"
                )
                raise ValueError(msg)
        return self


InputForm: TypeAlias = dict[str, PipeInputFormDescriptor]
"""The `input_form` artifact: namespaced `pipe_ref` (`domain_path.pipe_code`) → the pipe's input form.

The same key set as `pipe_io_contracts` — the descriptor is per pipe input, and that map's key
space is its natural address. The artifact arrives as an extension field of the validate report,
so a consumer parses it by declaring a typed field — `input_form: InputForm | None = None` on a
model extending the report — and pydantic parses the map and the discriminated union from that
plain annotation; no adapter machinery is involved.
"""
