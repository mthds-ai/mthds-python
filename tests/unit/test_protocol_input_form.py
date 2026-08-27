"""Parity and strictness tests for `mthds.protocol.input_form` against the engine-produced fixture.

The fixture `tests/fixtures/protocol/input_form.json` is the reference engine's own emission,
committed byte-for-byte here and in `mthds-js` (its README carries the provenance, and records
that this capture has no known divergence from the pages the models mirror). It is parsed the way
the artifact actually arrives: as a typed field declared on a model narrowing the validate report —
pydantic parses the map and the discriminated union from the plain annotation, no adapter machinery
involved. Every entry must parse under the closed shapes —
`extra="forbid"` on every model is what makes the parse a real check — and dump back to exactly
the input: absent slots stay absent, never `null`, and applicable falsy values are kept.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from mthds.protocol.input_form import (
    BooleanField,
    DateField,
    DocumentField,
    EnumField,
    FieldKind,
    ImageField,
    InputForm,
    ListField,
    NumberField,
    ObjectField,
    ObjectItem,
    PipeInputFormDescriptor,
    ProseField,
    TextField,
    TextItem,
    UnknownField,
    UnknownItem,
)
from mthds.protocol.pipe_io_contracts import PresenceMarker
from tests.unit.test_data import InputFormWireNodes


class NarrowedValidateReport(BaseModel):
    """How the artifact arrives: a typed field on a model narrowing the validate report.

    `pipelex-sdk-python` declares exactly this field (as `InputForm | None`) on its own report
    narrowing at Stage 3.4; a plain field annotation is the whole parse path.
    """

    model_config = ConfigDict(extra="forbid")

    input_form: InputForm


_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "protocol" / "input_form.json"
_RAW: dict[str, Any] = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
_REPORT = NarrowedValidateReport.model_validate({"input_form": _RAW})
_FORM = _REPORT.input_form


class TestInputFormProtocolModels:
    @pytest.mark.parametrize("pipe_ref", [pytest.param(pipe_ref, id=pipe_ref) for pipe_ref in _RAW])
    def test_fixture_entry_parses_strictly_and_round_trips(self, pipe_ref: str) -> None:
        """Each per-pipe descriptor parses under the closed shapes and dumps back to the exact input."""
        descriptor = PipeInputFormDescriptor.model_validate(_RAW[pipe_ref])
        assert descriptor.model_dump(mode="json") == _RAW[pipe_ref]
        assert json.loads(descriptor.model_dump_json()) == _RAW[pipe_ref]

    def test_whole_artifact_round_trips(self) -> None:
        """Parsed as the typed field it rides in on, the whole payload dumps back unchanged."""
        assert list(_FORM) == list(_RAW)
        assert _REPORT.model_dump(mode="json") == {"input_form": _RAW}
        assert json.loads(_REPORT.model_dump_json()) == {"input_form": _RAW}

    def test_slot_facts_are_stated_on_top_level_fields(self) -> None:
        """Presence, required, gating and the structured multiplicity are read as stated facts."""
        markers = _FORM["input_semantics_probe.probe_markers"].fields
        assert [field.name for field in markers] == ["opt", "many", "two", "forced"]
        opt, many, two, forced = markers

        assert isinstance(opt, ObjectField)
        assert opt.presence is PresenceMarker.OPTIONAL
        assert opt.required is False
        assert opt.gating is False

        assert isinstance(many, ListField)
        assert many.presence is PresenceMarker.PLAIN
        assert many.required is True
        assert many.gating is False
        assert many.item_count is None
        assert "item_count" not in many.model_dump()
        assert isinstance(many.item, ObjectItem)
        assert not hasattr(many.item, "name")
        assert many.item.concept_ref == "input_semantics_probe.Widget"
        assert many.item.concept_ref == many.concept_ref

        assert isinstance(two, ListField)
        assert two.item_count == 2
        assert two.gating is True
        assert two.concept_ref == "input_semantics_probe.Gadget"

        assert isinstance(forced, ProseField)
        assert forced.presence is PresenceMarker.FORCE
        assert forced.presence.is_optional is False
        assert forced.concept_ref == "native.Text"
        assert forced.kind is FieldKind.PROSE

    def test_nested_fields_carry_their_kind_slots(self) -> None:
        """Every kind of the closed union appears in the Widget structure, with its own required and optional slots."""
        widget = _FORM["input_semantics_probe.probe_single"].fields[0]
        assert isinstance(widget, ObjectField)
        assert widget.presence is PresenceMarker.PLAIN
        by_name = {field.name: field for field in widget.fields}
        assert list(by_name)[:4] == ["shorthand_note", "title", "subtitle", "summary"]

        shorthand = by_name["shorthand_note"]
        assert isinstance(shorthand, TextField)
        assert shorthand.required is True
        assert shorthand.presence is None
        assert shorthand.gating is None
        assert "presence" not in shorthand.model_dump()

        count = by_name["count"]
        assert isinstance(count, NumberField)
        assert count.integer is True
        assert count.default_value == 42
        assert count.required is False

        price = by_name["price"]
        assert isinstance(price, NumberField)
        assert price.integer is False
        assert price.default_value == 9.99
        assert price.model_dump()["integer"] is False

        enabled = by_name["enabled"]
        assert isinstance(enabled, BooleanField)
        assert enabled.default_value is True

        released_on = by_name["released_on"]
        assert isinstance(released_on, DateField)
        assert released_on.datetime is False
        assert released_on.default_value == "2026-01-15"
        launched_at = by_name["launched_at"]
        assert isinstance(launched_at, DateField)
        assert launched_at.datetime is True

        daily_at = by_name["daily_at"]
        assert isinstance(daily_at, TextField)
        assert daily_at.format == "time"
        assert daily_at.default_value == "12:30:00"

        tags = by_name["tags"]
        assert isinstance(tags, ListField)
        assert isinstance(tags.item, TextItem)
        assert tags.default_value == ["PROBE_tag_a", "PROBE_tag_b"]
        assert tags.item_count is None
        matrix = by_name["matrix"]
        assert isinstance(matrix, ListField)
        assert isinstance(matrix.item, UnknownItem)

        gadgets = by_name["gadgets"]
        assert isinstance(gadgets, ListField)
        assert gadgets.concept_ref == "input_semantics_probe.Gadget"
        assert isinstance(gadgets.item, ObjectItem)
        assert [field.name for field in gadgets.item.fields] == ["name", "trinket"]
        trinket = gadgets.item.fields[1]
        assert isinstance(trinket, ObjectField)
        assert trinket.required is False
        assert [field.name for field in trinket.fields] == ["label"]

        assert isinstance(by_name["attributes"], UnknownField)
        scores = by_name["scores"]
        assert isinstance(scores, UnknownField)
        assert scores.default_value == {"speed": 5}

        icon = by_name["icon"]
        assert isinstance(icon, ImageField)
        assert icon.concept_ref == "native.Image"

        tone = by_name["tone"]
        assert isinstance(tone, EnumField)
        assert tone.choices == ["PROBE_choice_formal", "PROBE_choice_casual", "PROBE_choice_playful"]
        assert tone.default_value == "PROBE_choice_casual"
        only_choice = by_name["only_choice"]
        assert isinstance(only_choice, EnumField)
        assert only_choice.choices == ["PROBE_choice_single"]

    def test_native_and_refined_concepts_state_identity(self) -> None:
        """Kind comes from stated identity: `concept_ref` and the `refines` chain, never a sniffed shape."""
        natives = {field.name: field for field in _FORM["input_semantics_probe.probe_native_inputs"].fields}
        assert isinstance(natives["document_in"], DocumentField)
        assert natives["document_in"].concept_ref == "native.Document"
        assert isinstance(natives["image_in"], ImageField)
        assert isinstance(natives["yesno_in"], BooleanField)
        number_in = natives["number_in"]
        assert isinstance(number_in, NumberField)
        assert number_in.integer is False
        time_in = natives["time_in"]
        assert isinstance(time_in, TextField)
        assert time_in.format == "time"
        page_in = natives["page_in"]
        assert isinstance(page_in, ObjectField)
        assert page_in.concept_ref == "native.Page"
        assert [field.name for field in page_in.fields] == ["text_and_images", "page_view"]

        refined = {field.name: field for field in _FORM["input_semantics_probe.probe_refined"].fields}
        refdoc = refined["refdoc"]
        assert isinstance(refdoc, DocumentField)
        assert refdoc.refines == ["native.Document"]
        extra = refined["extra"]
        assert isinstance(extra, ObjectField)
        assert extra.refines == ["input_semantics_probe.SpecialEntity", "input_semantics_probe.BaseEntity"]
        assert [field.name for field in extra.fields] == ["ident"]
        special = refined["special"]
        assert isinstance(special, ObjectField)
        assert special.refines == ["input_semantics_probe.BaseEntity"]

    def test_a_pinned_native_structure_lands_on_the_object_arm(self) -> None:
        """A native carrying a pinned structure is an `object` recursing through it, never a scalar standing in for it."""
        natives = {field.name: field for field in _FORM["input_semantics_probe.probe_native_inputs"].fields}

        date_in = natives["date_in"]
        assert isinstance(date_in, ObjectField)
        assert date_in.concept_ref == "native.Date"
        date_fields = {field.name: field for field in date_in.fields}
        assert list(date_fields) == ["date", "time"]
        assert isinstance(date_fields["date"], DateField)
        assert date_fields["date"].datetime is False
        assert date_fields["date"].required is True
        assert isinstance(date_fields["time"], TextField)
        assert date_fields["time"].format == "time"
        assert date_fields["time"].required is False

        html_in = natives["html_in"]
        assert isinstance(html_in, ObjectField)
        assert html_in.concept_ref == "native.Html"
        html_fields = {field.name: field for field in html_in.fields}
        assert list(html_fields) == ["inner_html", "css_class"]
        assert isinstance(html_fields["inner_html"], TextField)
        assert html_fields["inner_html"].required is True
        assert isinstance(html_fields["css_class"], TextField)
        assert html_fields["css_class"].required is False

    def test_every_node_but_a_list_item_is_named(self) -> None:
        """The whole capture agrees with the shape: a name everywhere the page admits one, and none on a list's item.

        The models make both halves structural, so a conforming payload cannot say otherwise — this
        walks the engine's own emission to state that the engine agrees, which is the parity the
        fixture exists for. Both arms are asserted non-empty so a payload without lists, or without
        fields, could not satisfy this vacuously.
        """
        named: list[Any] = []
        items: list[dict[str, Any]] = []

        def walk(node: dict[str, Any], *, is_item: bool) -> None:
            if is_item:
                items.append(node)
            else:
                named.append(node.get("name"))
            for nested in node.get("fields", []):
                walk(nested, is_item=False)
            item = node.get("item")
            if item is not None:
                walk(item, is_item=True)

        for descriptor in _RAW.values():
            for field in descriptor["fields"]:
                walk(field, is_item=False)

        assert named, "the capture states no named node at all"
        assert items, "the capture states no list item at all, so the nameless half proves nothing"
        assert all(isinstance(name, str) and name for name in named)
        assert all("name" not in item for item in items)

    def test_hints_ride_every_site_and_stay_content_lenient(self) -> None:
        """The effective hints ride the node (and both halves of a plural node); unknown keys are preserved."""
        hinted = {field.name: field for field in _FORM["input_semantics_hinted.hinted_slots"].fields}
        review = hinted["hinted"]
        assert isinstance(review, ObjectField)
        assert review.hints == {"intent": "prose"}
        review_fields = {field.name: field for field in review.fields}
        assert isinstance(review_fields["headline"], TextField)
        assert review_fields["headline"].hints == {"intent": "label"}
        assert isinstance(review_fields["body"], ProseField)
        stars = review_fields["stars"]
        assert isinstance(stars, NumberField)
        assert stars.hints == {"intent": "rating"}
        assert stars.integer is True
        assert review_fields["plain"].hints is None
        assert "hints" not in review_fields["plain"].model_dump()
        assert review_fields["quirk"].hints == {"emphasis": "HINTED_unknown_value"}

        badges = hinted["hinted_marked"]
        assert isinstance(badges, ListField)
        assert badges.hints == {"intent": "label"}
        assert isinstance(badges.item, TextItem)
        assert badges.item.hints == {"intent": "label"}
        assert badges.gating is False

    @pytest.mark.parametrize(
        "node",
        [
            pytest.param(InputFormWireNodes.UNKNOWN_MEMBER, id="unknown member on a node"),
            pytest.param(InputFormWireNodes.SLOT_OF_ANOTHER_KIND, id="slot of another kind"),
            pytest.param(InputFormWireNodes.UNKNOWN_KIND, id="kind outside the closed union"),
            pytest.param(InputFormWireNodes.NUMBER_WITHOUT_INTEGER, id="number without integer"),
            pytest.param(InputFormWireNodes.DATE_WITHOUT_DATETIME, id="date without datetime"),
            pytest.param(InputFormWireNodes.ENUM_WITHOUT_CHOICES, id="enum without choices"),
            pytest.param(InputFormWireNodes.OBJECT_WITHOUT_FIELDS, id="object without fields"),
            pytest.param(InputFormWireNodes.LIST_WITHOUT_ITEM, id="list without item"),
            pytest.param(InputFormWireNodes.LIST_COUNT_OF_ONE, id="list with item_count 1"),
            pytest.param(InputFormWireNodes.REQUIRED_WITH_DEFAULT, id="required with a default_value"),
            pytest.param(InputFormWireNodes.HINT_VALUE_NOT_A_STRING, id="hint value that is not a string"),
            pytest.param(InputFormWireNodes.NESTED_UNKNOWN_MEMBER, id="unknown member on a nested node"),
            pytest.param(InputFormWireNodes.NESTED_PRESENCE, id="presence on a nested field"),
            pytest.param(InputFormWireNodes.NESTED_GATING, id="gating on a nested field"),
            pytest.param(InputFormWireNodes.ITEM_WITH_PRESENCE, id="presence on a list's item"),
            pytest.param(InputFormWireNodes.TOP_LEVEL_WITHOUT_PRESENCE, id="top-level field without presence"),
            pytest.param(InputFormWireNodes.TOP_LEVEL_WITHOUT_GATING, id="top-level field without gating"),
            pytest.param(InputFormWireNodes.TOP_LEVEL_OPTIONAL_YET_REQUIRED, id="top-level optional yet required"),
            pytest.param(InputFormWireNodes.TOP_LEVEL_PLAIN_YET_NOT_REQUIRED, id="top-level plain yet not required"),
            pytest.param(InputFormWireNodes.TOP_LEVEL_OPTIONAL_YET_GATING, id="top-level optional yet gating"),
            pytest.param(InputFormWireNodes.TITLE_EXPLICIT_NULL, id="explicit null title"),
            pytest.param(InputFormWireNodes.REFINES_EXPLICIT_NULL, id="explicit null refines"),
            pytest.param(InputFormWireNodes.ITEM_COUNT_NULL_ON_VARIABLE_LIST, id="explicit null item_count on a variable list"),
            pytest.param(InputFormWireNodes.NESTED_TITLE_EXPLICIT_NULL, id="explicit null title on a nested field"),
            pytest.param(InputFormWireNodes.ITEM_TITLE_EXPLICIT_NULL, id="explicit null title on a list's item"),
            pytest.param(InputFormWireNodes.ITEM_WITH_NAME, id="name on a list's item"),
            pytest.param(InputFormWireNodes.TOP_LEVEL_WITHOUT_NAME, id="top-level field without a name"),
            pytest.param(InputFormWireNodes.NESTED_WITHOUT_NAME, id="nested field without a name"),
        ],
    )
    def test_closed_shapes_reject(self, node: dict[str, Any]) -> None:
        """A member the standard does not define, a slot of another kind, or a broken invariant fails the parse."""
        with pytest.raises(ValidationError):
            PipeInputFormDescriptor.model_validate({"fields": [node]})

    def test_descriptor_is_a_closed_shape(self) -> None:
        """The per-pipe descriptor rejects unknown members and accepts the empty form."""
        with pytest.raises(ValidationError):
            PipeInputFormDescriptor.model_validate(InputFormWireNodes.DESCRIPTOR_UNKNOWN_MEMBER)
        empty = PipeInputFormDescriptor.model_validate(InputFormWireNodes.EMPTY_FORM)
        assert empty.fields == []
        assert empty.model_dump() == {"fields": []}

    def test_hints_content_leniency_is_the_sole_exception(self) -> None:
        """Unknown hint keys and unknown intent words are carried through untouched."""
        descriptor = PipeInputFormDescriptor.model_validate({"fields": [InputFormWireNodes.HINTS_CONTENT_LENIENT]})
        node = descriptor.fields[0]
        assert isinstance(node, TextField)
        assert node.hints == {"emphasis": "strong", "intent": "a-word-from-a-later-version"}
        assert node.model_dump()["hints"] == InputFormWireNodes.HINTS_CONTENT_LENIENT["hints"]

    def test_default_value_null_is_no_default(self) -> None:
        """`default_value: null` is "no default" per the page, never a rejected null — the one carve-out from the explicit-null rule."""
        descriptor = PipeInputFormDescriptor.model_validate({"fields": [InputFormWireNodes.DEFAULT_VALUE_EXPLICIT_NULL]})
        motto = descriptor.fields[0]
        assert isinstance(motto, TextField)
        assert motto.default_value is None
        assert "default_value" not in motto.model_dump()

    def test_programmatic_construction_accepts_none_kwargs(self) -> None:
        """`TextField(..., title=maybe_title)` with `None` stays the supported idiom: the explicit-null rule binds the wire, not the constructor."""
        field = TextField(name="title", title=None, refines=None, required=True, presence=PresenceMarker.PLAIN, gating=True)
        descriptor = PipeInputFormDescriptor(fields=[field])
        assert descriptor.fields[0].title is None
        assert descriptor.model_dump() == {"fields": [{"kind": "text", "name": "title", "required": True, "presence": "plain", "gating": True}]}

    def test_absent_slots_stay_absent_and_falsy_slots_are_stated(self) -> None:
        """A plain dump owns the wire rule: no `null` for an inapplicable slot, and `false` is kept."""
        price_descriptor = PipeInputFormDescriptor.model_validate({"fields": [InputFormWireNodes.FALSY_SLOTS_STATED]})
        price = price_descriptor.fields[0]
        assert isinstance(price, NumberField)
        assert price.model_dump() == {"kind": "number", "name": "price", "required": False, "presence": "optional", "gating": False, "integer": False}
        assert list(price.model_dump()) == ["kind", "name", "required", "presence", "gating", "integer"]

        tags_descriptor = PipeInputFormDescriptor.model_validate({"fields": [InputFormWireNodes.ITEM_WITHOUT_NAME]})
        tags = tags_descriptor.fields[0]
        assert isinstance(tags, ListField)
        assert not hasattr(tags.item, "name")
        dumped = tags.model_dump()
        assert "name" not in dumped["item"]
        assert dumped == InputFormWireNodes.ITEM_WITHOUT_NAME

        stars_descriptor = PipeInputFormDescriptor.model_validate({"fields": [InputFormWireNodes.NUMBER_WITH_INTEGRAL_BOUNDS]})
        stars = stars_descriptor.fields[0]
        assert isinstance(stars, NumberField)
        assert stars.minimum == 1
        assert stars.maximum == 5
        assert stars.model_dump(mode="json") == InputFormWireNodes.NUMBER_WITH_INTEGRAL_BOUNDS
