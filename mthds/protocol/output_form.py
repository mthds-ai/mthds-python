"""Wire models for the output-form descriptor — mirrors `docs/spec/output-form-descriptor.md`.

    output_form : OutputForm = dict[pipe_ref, PipeOutputFormDescriptor]
        PipeOutputFormDescriptor.field : InputFormField

The presentation view of what a pipe RESOLVES TO, and the exact twin of `input_form` for
the other half of the contract. Where the input-form descriptor states, in authored order,
what each declared input slot is, this states what the single output is: its kind, its
nesting, its constraints — everything a consumer needs to render a result, register a tool
signature with a return type, or project a typed structure for it.

## An output is a concept ref exactly like an input is

That is the whole design, and it is why this module declares almost nothing of its own.
The same concepts, the same structures, the same field kinds, the same nesting, so the same
node vocabulary: `field` is an `InputFormField`, reused verbatim from
`mthds.protocol.input_form`. There is no parallel node union, no second `kind` enum, and no
second place for kinds to drift.

What differs is only the SLOT facts, and there are three:

- **`name`.** An input's name is authored by the method; an output has none to author. The
  node still carries one, because `InputFormField` is the named half of the union and a
  nameless node is the shape a `list`'s `item` holds. A producer states `"output"`. Nothing
  reads it: a result is labelled by its concept, and a list entry by its index — the same
  rule this page's input twin already fixes for list items. It is an address, not a label.
- **`presence`.** Three-valued on an input; an output has no marker to state — `!` MUST NOT
  appear on one, and `?` is stated by the contract's `optional`.
- **`gating`.** Whether Run waits for the slot. Meaningless for a result.

All three of the latter two are already optional on the node, precisely so a node can exist
without them, and this module enforces their ABSENCE the way the input descriptor enforces
their presence. A producer that stamps a slot fact onto an output node fails the parse.

## One `field`, not a `fields` list

The one shape difference from `PipeInputFormDescriptor`, and it follows from the language
rather than from taste: a pipe has exactly one output where it may have many inputs. A list
of one would invite a consumer to loop, and a producer to wonder what a second entry means.

## Plurality is on the DESCRIPTOR, never on the concept

`concept_ref` is the element with any multiplicity suffix stripped, on both sides of the
contract — a `Concept[]` output names `Concept`. So a plural output is a `list` node whose
`item` is the element node, exactly as a plural input's descriptor is, and a producer must
perform that wrap from the contract's `multiplicity`: the concept alone cannot state it.

This is the one place producing this artifact is real work rather than reuse, and it fails
silently when skipped — a `Concept[]` output described as its element renders one item where
a run produced many. A consumer never sees the wrap: it reads `kind: "list"` and never
touches the contract for plurality.

## Read with the contract, never instead of it

The descriptor states what the field IS; `PipeOutputContract.json_schema` states the shape
of the payload it arrives in, and names the property that payload sits under. Neither is
sufficient alone, which is why the two landed in the same version of the standard.

Closed shapes, on the same policy as every artifact model here: a member this version does
not define is version drift, rejected at the parse.
"""

from __future__ import annotations

from typing import Any, Self, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, model_validator

from mthds.protocol.input_form import (
    InputFormField,
    _check_no_explicit_nulls,  # pyright: ignore[reportPrivateUsage]
    _check_pipe_slot_facts_absent,  # pyright: ignore[reportPrivateUsage]
    _raw_node_label,  # pyright: ignore[reportPrivateUsage]
)

__all__ = ["OutputForm", "PipeOutputFormDescriptor"]


class PipeOutputFormDescriptor(BaseModel):
    """The output form of one pipe — one `output_form` entry, carrying the single output node.

    Closed shape (`extra="forbid"`). The node itself is an `InputFormField`, so it is parsed by
    the same discriminated union every input node is, and a consumer narrows it the same way.
    """

    model_config = ConfigDict(extra="forbid")

    field: InputFormField
    """What the pipe resolves to, described. A `list` node on a plural output, whose `item` is the
    element; the element concept is named by `concept_ref` on both, suffix stripped."""

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_wire_nulls(cls, data: Any) -> Any:
        """A wire payload never spells absence as `null` — the same rule `PipeInputFormDescriptor` states, for the same reason.

        Enforced on the container rather than on the node base because only here can a raw wire
        mapping be told apart from the keyword arguments of a programmatic construction, where
        building a node with `title=None` is the supported idiom.
        """
        if not isinstance(data, dict):
            return data
        raw_form = cast("dict[str, Any]", data)
        raw_field = raw_form.get("field")
        if isinstance(raw_field, dict):
            raw_node = cast("dict[str, Any]", raw_field)
            _check_no_explicit_nulls(node=raw_node, position=f"The output {_raw_node_label(node=raw_node, fallback='field')}")
        return raw_form

    @model_validator(mode="after")
    def validate_no_pipe_slot_facts(self) -> Self:
        """An output node states neither `presence` nor `gating`: both are facts of an INPUT slot, and an output has none.

        The mirror image of `PipeInputFormDescriptor.validate_top_level_placement`, which demands
        both on a top-level input field. Enforcing the absence rather than ignoring a stray value
        is what keeps the reused node type honest: `presence` and `gating` are optional on it so
        that a slotless node can exist, not so that a producer may fill them in with something
        plausible.
        """
        _check_pipe_slot_facts_absent(node=self.field, position=f"The output {self.field.node_label}")
        return self


OutputForm: TypeAlias = dict[str, PipeOutputFormDescriptor]
"""The `output_form` artifact: namespaced `pipe_ref` (`domain_path.pipe_code`) → the pipe's output form.

The same key set as `pipe_io_contracts` and `input_form` — every pipe in the resolved library has
an entry, contract-only pipe signatures included. The artifact arrives as an extension field of the
validate report, so a consumer parses it by declaring a typed field — `output_form: OutputForm |
None = None` on a model extending the report — and pydantic parses the map and the discriminated
union from that plain annotation; no adapter machinery is involved.
"""
