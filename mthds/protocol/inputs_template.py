"""The inputs-template projection: one pipe's input-form descriptor rendered as a fill-in template.

A template is what somebody — a person at a form, an agent preparing a run — fills in and hands back
as the pipe's inputs. It used to be built server-side and fetched over HTTP; it is projected here
instead, from the `input_form` descriptor the standard already defines, so a client holding the
descriptor needs nothing further to offer a template for a method it does not have on disk.

**The projection walks the descriptor, never a runtime content class**, and that is the whole
difference from the reference engine's own renderer: the engine reflects the pydantic class each
input resolves to, so its template states what the *runtime* holds, where this states what the
*method declares*. Every difference the two exhibit is recorded, with worked sites, in
`tests/fixtures/protocol/inputs_template/manifest.json`.

The bar this is held to is **byte identity with the TypeScript twin** in the `mthds` npm package,
across every kind of the closed vocabulary, both shapes and both formats. That is what stops the
JS/Python asymmetry the build-route retirement removed from being rebuilt one layer up, and it is a
measured contract rather than an intention: `tests/fixtures/protocol/inputs_template/` holds the
expected bytes, both repos commit it identically, and each runs the twin of the same parity suite.
The TOML half of it is spelled out by `mthds.protocol.toml_emitter` rather than by either language's
TOML library, for the reasons that module states.

Two shapes, and the difference is what the runtime's own input shaper can take back:

- **compact** — the light form a smart-inputs run accepts directly: a bare string for a text slot, a
  bare URL for a file-ish one, the content mapping for a structured one. A slot whose bare value the
  shaper could *not* rebuild keeps its `{concept, content}` envelope, because a template that does
  not run is not a template.
- **explicit** — every slot keeps the ceremonial `{concept, content}` envelope, whatever it holds.

Three rules are this projection's own, because the descriptor states facts the engine reads
elsewhere: an `enum` takes its first choice (the engine picks at random, which no committed template
could carry), an `unknown` node renders as an empty mapping — the escape hatch's only honest value —
and a fixed `Concept[N]` slot renders `N` elements rather than one.

Every match over `FieldKind` here is exhaustive and carries no default arm, deliberately: a kind
added to the standard breaks this module where the rule for it has to be written, rather than
falling through to a guess.
"""

import json
from enum import StrEnum
from typing import Any

from mthds.protocol.input_form import (
    FieldKind,
    InputFormField,
    InputFormItem,
    PipeInputFormDescriptor,
)
from mthds.protocol.pipe_io_contracts import PresenceMarker
from mthds.protocol.toml_emitter import render_inline_layout, render_table_layout

MOCK_URL_PREFIX = "https://mock.invalid/"
FILE_CONTENT_KEY = "url"
TIME_FORMAT = "time"

# The two keys of the ceremonial envelope — the explicit shape's whole framing, and what a compact
# slot keeps when its value is not re-shapable from a bare one.
ENVELOPE_CONCEPT_KEY = "concept"
ENVELOPE_CONTENT_KEY = "content"

# The single wire key a native scalar's value sits inside. It is a fact about the *payload*, which
# the descriptor deliberately does not carry — so the projection needs this table to build the
# explicit `{concept, content}` envelope. It is the standard's to state, not any runtime's: the
# native content shapes are pinned by `docs/spec/native-concepts.md`.
TEXT_CONTENT_KEY = "text"
NUMBER_CONTENT_KEY = "number"
BOOLEAN_CONTENT_KEY = "yes_no"
DATE_CONTENT_KEY = "date"
TIME_CONTENT_KEY = "time"

NATIVE_PREFIX = "native."

# The natives an input shaper cannot build top-down: their compact form keeps the whole
# `{concept, content}` envelope, because a bare value at one of these positions is not re-shapable.
# The vocabulary is the standard's closed native set (`docs/spec/native-concepts.md`), which is why
# a projection may consult it: it reads an identity the descriptor states, never sniffs a shape.
OUT_OF_MATRIX_NATIVES = frozenset(
    {
        "Anything",
        "Composite",
        "Dynamic",
        "Html",
        "JSON",
        "Page",
        "SearchResult",
        "TextAndImages",
    }
)

# `native.Number`'s content is a number union, placeholdered as `1` rather than as the `0` / `0.0` a
# plain `type = "number"` structure field takes. The descriptor states `kind = "number"` for both,
# so the native identity is what separates them.
NATIVE_NUMBER = "Number"
NATIVE_NUMBER_PLACEHOLDER = 1

CONCEPT_COMMENT_PREFIX = "concept: "


class InputsTemplateFormat(StrEnum):
    """The serialization a rendered inputs template is asked for."""

    JSON = "json"
    TOML = "toml"


def render_inputs_template(*, descriptor: PipeInputFormDescriptor, explicit: bool, output_format: InputsTemplateFormat) -> str:
    """Project one pipe's descriptor into a fill-in inputs template and serialize it.

    Args:
        descriptor: The pipe's input-form descriptor.
        explicit: When True, keep the ceremonial `{concept, content}` envelope on every slot; when
            False, emit the compact shape a smart-inputs run accepts directly.
        output_format: The serialization to render. Accepts the wire spelling too — the format
            arrives as a plain string from a CLI flag or a request field, and an unknown one is a
            `ValueError` here rather than a silently empty document.

    Returns:
        The serialized template: JSON with no trailing newline, TOML with exactly one.
    """
    template = project_inputs_template(descriptor=descriptor, explicit=explicit)
    match InputsTemplateFormat(output_format):
        case InputsTemplateFormat.JSON:
            return json.dumps(template, indent=2, ensure_ascii=False)
        case InputsTemplateFormat.TOML:
            if explicit:
                return render_table_layout(template=template)
            return render_inline_layout(template=template, comments=project_concept_comments(descriptor=descriptor))


def project_inputs_template(*, descriptor: PipeInputFormDescriptor, explicit: bool) -> dict[str, Any]:
    """Project one pipe's descriptor into the fill-in inputs template.

    Args:
        descriptor: The pipe's input-form descriptor.
        explicit: When True, keep the ceremonial `{concept, content}` envelope on every slot; when
            False, emit the compact shape a smart-inputs run accepts directly.

    Returns:
        The template, one entry per declared input slot, in authored order.
    """
    template: dict[str, Any] = {}
    for field in descriptor.fields:
        if explicit:
            template[field.name] = {
                ENVELOPE_CONCEPT_KEY: field.concept_ref,
                ENVELOPE_CONTENT_KEY: _slot_content(node=field, name=field.name),
            }
        else:
            template[field.name] = _compact_slot(field=field)
    return template


def project_concept_comments(*, descriptor: PipeInputFormDescriptor) -> dict[str, str]:
    """The per-slot `concept: …` comment map a compact TOML rendering carries above each key."""
    return {field.name: f"{CONCEPT_COMMENT_PREFIX}{format_slot_signature(field=field)}" for field in descriptor.fields}


def format_slot_signature(*, field: InputFormField) -> str:
    """The io-ref notation for one declared slot — `Concept`, `Concept[]`, `Concept[2]`, `Concept?`, `Concept!`.

    Rebuilt from the descriptor, because that is all a client projection has: the concept reference,
    the multiplicity the `list` node states, and the authored presence marker.
    """
    presence = field.presence or PresenceMarker.PLAIN
    concept_ref = field.concept_ref or ""
    return f"{concept_ref}{_multiplicity_suffix(field=field)}{_presence_symbol(presence=presence)}"


def _multiplicity_suffix(*, field: InputFormField) -> str:
    """The io-ref plurality suffix: none for a single slot, `[]` for a variable list, `[N]` for a fixed one."""
    match field.kind:
        case FieldKind.LIST:
            if field.item_count is None:
                return "[]"
            return f"[{field.item_count}]"
        case (
            FieldKind.TEXT
            | FieldKind.PROSE
            | FieldKind.DATE
            | FieldKind.NUMBER
            | FieldKind.BOOLEAN
            | FieldKind.ENUM
            | FieldKind.DOCUMENT
            | FieldKind.IMAGE
            | FieldKind.OBJECT
            | FieldKind.UNKNOWN
        ):
            return ""


def _presence_symbol(*, presence: PresenceMarker) -> str:
    """The io-ref suffix symbol a presence marker renders as."""
    match presence:
        case PresenceMarker.PLAIN:
            return ""
        case PresenceMarker.OPTIONAL:
            return "?"
        case PresenceMarker.FORCE:
            return "!"


def native_code(*, node: InputFormItem) -> str | None:
    """The native concept this node's chain names, if any.

    Reads `concept_ref` first, then the `refines` membership list, so a concept refining a native
    resolves the same way the native itself does.
    """
    candidates: list[str] = []
    if node.concept_ref is not None:
        candidates.append(node.concept_ref)
    if node.refines is not None:
        candidates.extend(node.refines)
    for candidate in candidates:
        if candidate.startswith(NATIVE_PREFIX):
            return candidate[len(NATIVE_PREFIX) :]
    return None


def keeps_envelope(*, node: InputFormItem) -> bool:
    """Whether this slot's compact form keeps the ceremonial envelope instead of unwrapping.

    Two ways to earn it, and both mean the same thing — a bare value at this position is not
    re-shapable, so unwrapping would pin a template that does not run. Either the native is one a
    shaper cannot build top-down at all, or the descriptor states it as an object: a shaper's
    bare-value arm dispatches a native on its scalar kind, so it rejects the object outright.
    `native.Date` is the second case — it is a scalar a shaper knows, until the optional `time`
    beside its required `date` makes the rendered form an object.
    """
    code = native_code(node=node)
    if code is None:
        return False
    if code in OUT_OF_MATRIX_NATIVES:
        return True
    match node.kind:
        case FieldKind.OBJECT:
            return True
        case (
            FieldKind.TEXT
            | FieldKind.PROSE
            | FieldKind.DATE
            | FieldKind.NUMBER
            | FieldKind.BOOLEAN
            | FieldKind.ENUM
            | FieldKind.DOCUMENT
            | FieldKind.IMAGE
            | FieldKind.LIST
            | FieldKind.UNKNOWN
        ):
            return False


def slot_content_key(*, node: InputFormItem) -> str | None:
    """The single wire key a slot-position scalar's value sits inside, or None when it is not one."""
    match node.kind:
        case FieldKind.TEXT | FieldKind.PROSE:
            if node.format == TIME_FORMAT:
                return TIME_CONTENT_KEY
            return TEXT_CONTENT_KEY
        case FieldKind.NUMBER:
            return NUMBER_CONTENT_KEY
        case FieldKind.BOOLEAN:
            return BOOLEAN_CONTENT_KEY
        case FieldKind.DATE:
            return DATE_CONTENT_KEY
        case FieldKind.ENUM:
            return TEXT_CONTENT_KEY
        case FieldKind.IMAGE | FieldKind.DOCUMENT:
            return FILE_CONTENT_KEY
        case FieldKind.OBJECT | FieldKind.LIST | FieldKind.UNKNOWN:
            return None


def _leaf_placeholder(*, node: InputFormItem, name: str) -> Any:
    """The fill-in value for a node the descriptor states as a leaf.

    `name` is the name of the field the value occupies, which is what the placeholder is built from:
    a structure field's own name when the leaf sits inside a content mapping, and the content key
    when it sits at a slot, where the value occupies its native content shape's single field.
    """
    match node.kind:
        case FieldKind.TEXT | FieldKind.PROSE:
            if node.format == TIME_FORMAT:
                return "12:00:00"
            return f"{name}_value"
        case FieldKind.DATE:
            if node.datetime:
                return "2026-01-01T12:00:00"
            return "2026-01-01"
        case FieldKind.NUMBER:
            if native_code(node=node) == NATIVE_NUMBER:
                return NATIVE_NUMBER_PLACEHOLDER
            if node.integer:
                return 0
            return 0.0
        case FieldKind.BOOLEAN:
            return False
        case FieldKind.ENUM:
            # The first choice, never a random one: these bytes are committed.
            if node.choices:
                return node.choices[0]
            return f"{name}_value"
        case FieldKind.IMAGE | FieldKind.DOCUMENT:
            return f"{MOCK_URL_PREFIX}{FILE_CONTENT_KEY}"
        case FieldKind.OBJECT | FieldKind.LIST | FieldKind.UNKNOWN:
            msg = f"Not a leaf kind: {node.kind}"
            raise ValueError(msg)


def _item_repetitions(*, item_count: int | None) -> int:
    """How many elements a list renders: its declared count, or one example for a variable list."""
    if item_count is None:
        return 1
    return item_count


def project_value(*, node: InputFormItem, name: str) -> Any:
    """The value one descriptor node takes inside a content mapping.

    A scalar-typed node is its bare placeholder; a concept-typed one (`image`, `document`, `object`)
    is the content mapping its concept carries, because that is what sits at the field in the
    payload.

    One case reads as a scalar and is not: a nested node that names a native concept holds that
    native's own content object, not a bare value — `native.Text` inside a page's text-and-images is
    a text content, so the payload carries `{"text": …}` there. The descriptor states the difference
    itself, in whether the node carries a `concept_ref`: an authored `type = "text"` structure field
    carries none and stays bare.
    """
    match node.kind:
        case FieldKind.TEXT | FieldKind.PROSE | FieldKind.DATE | FieldKind.NUMBER | FieldKind.BOOLEAN | FieldKind.ENUM:
            content_key = slot_content_key(node=node) if native_code(node=node) is not None else None
            if content_key is not None:
                return {content_key: _leaf_placeholder(node=node, name=content_key)}
            return _leaf_placeholder(node=node, name=name)
        case FieldKind.IMAGE | FieldKind.DOCUMENT:
            return {FILE_CONTENT_KEY: _leaf_placeholder(node=node, name=FILE_CONTENT_KEY)}
        case FieldKind.OBJECT:
            return {member.name: project_value(node=member, name=member.name) for member in node.fields}
        case FieldKind.LIST:
            item_value = project_value(node=node.item, name=f"{name}_item")
            return [item_value for _ in range(_item_repetitions(item_count=node.item_count))]
        case FieldKind.UNKNOWN:
            return {}


def _slot_content(*, node: InputFormItem, name: str) -> Any:
    """The `content` half of one slot's envelope — what the concept carries at that position."""
    content_key = slot_content_key(node=node)
    if content_key is not None:
        return {content_key: _leaf_placeholder(node=node, name=content_key)}
    match node.kind:
        case FieldKind.LIST:
            item_content = _slot_content(node=node.item, name=f"{name}_item")
            return [item_content for _ in range(_item_repetitions(item_count=node.item_count))]
        case (
            FieldKind.OBJECT
            | FieldKind.UNKNOWN
            | FieldKind.TEXT
            | FieldKind.PROSE
            | FieldKind.DATE
            | FieldKind.NUMBER
            | FieldKind.BOOLEAN
            | FieldKind.ENUM
            | FieldKind.IMAGE
            | FieldKind.DOCUMENT
        ):
            return project_value(node=node, name=name)


def _compact_value(*, node: InputFormItem, name: str) -> Any:
    """One slot's (or one slot element's) compact value: a scalar unwraps, everything else keeps its mapping."""
    content_key = slot_content_key(node=node)
    if content_key is not None:
        return _leaf_placeholder(node=node, name=content_key)
    return project_value(node=node, name=name)


def _compact_slot(*, field: InputFormField) -> Any:
    """One slot in the compact shape.

    A slot whose bare value is not re-shapable keeps the whole envelope, exactly as the engine's own
    compact rendering does: unwrapping it would emit a template that no longer runs.
    """
    if keeps_envelope(node=field):
        return {ENVELOPE_CONCEPT_KEY: field.concept_ref, ENVELOPE_CONTENT_KEY: _slot_content(node=field, name=field.name)}
    match field.kind:
        case FieldKind.LIST:
            item_value = _compact_value(node=field.item, name=f"{field.name}_item")
            return [item_value for _ in range(_item_repetitions(item_count=field.item_count))]
        case (
            FieldKind.OBJECT
            | FieldKind.UNKNOWN
            | FieldKind.TEXT
            | FieldKind.PROSE
            | FieldKind.DATE
            | FieldKind.NUMBER
            | FieldKind.BOOLEAN
            | FieldKind.ENUM
            | FieldKind.IMAGE
            | FieldKind.DOCUMENT
        ):
            return _compact_value(node=field, name=field.name)
