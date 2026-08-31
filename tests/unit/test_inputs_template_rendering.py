"""The projection's public entry point, on the ground the fixture corpus cannot cover.

The corpus pins the bytes for every captured pipe, which is the deliverable; what it cannot pin is
the behaviour on a form the capture holds no example of — a pipe that declares no inputs at all —
or the entry point's own contract on the format it is asked for. Those are stated here.
"""

from typing import Any

import pytest

from mthds.protocol.input_form import InputFormField, PipeInputFormDescriptor
from mthds.protocol.inputs_template import (
    ENVELOPE_CONTENT_KEY,
    InputsTemplateFormat,
    format_slot_signature,
    keeps_envelope,
    project_inputs_template,
    render_inputs_template,
)
from tests.unit.test_data import CompactSlotCases, SlotSignatureCases

EMPTY_DESCRIPTOR = PipeInputFormDescriptor(fields=[])


class TestInputsTemplateRendering:
    @pytest.mark.parametrize("explicit", [False, True])
    def test_a_pipe_declaring_no_inputs_projects_to_an_empty_template(self, explicit: bool):
        # An empty input form is a valid form, and the projection says so rather than refusing: the
        # reference engine's own renderer is the one that raises on a pipe with no inputs.
        assert project_inputs_template(descriptor=EMPTY_DESCRIPTOR, explicit=explicit) == {}
        assert render_inputs_template(descriptor=EMPTY_DESCRIPTOR, explicit=explicit, output_format=InputsTemplateFormat.JSON) == "{}"
        assert render_inputs_template(descriptor=EMPTY_DESCRIPTOR, explicit=explicit, output_format=InputsTemplateFormat.TOML) == ""

    def test_the_format_is_accepted_in_its_wire_spelling(self):
        # It arrives as a plain string from a CLI flag or a request field — the parity suite passes
        # one — and a `str` naming a format must render the document its member renders.
        rendered_from_wire = render_inputs_template(descriptor=EMPTY_DESCRIPTOR, explicit=False, output_format="json")  # type: ignore[arg-type]
        assert rendered_from_wire == render_inputs_template(descriptor=EMPTY_DESCRIPTOR, explicit=False, output_format=InputsTemplateFormat.JSON)

    def test_an_unknown_format_is_refused_rather_than_rendered_empty(self):
        # The alternative is a match that falls through every arm and hands back `None`, which reads
        # downstream as a template with no content rather than as a caller error.
        with pytest.raises(ValueError, match="yaml"):
            render_inputs_template(descriptor=EMPTY_DESCRIPTOR, explicit=False, output_format="yaml")  # type: ignore[arg-type]

    @pytest.mark.parametrize(("topic", "field", "expected"), SlotSignatureCases.SIGNATURES)
    def test_a_slot_signature_is_rebuilt_from_the_descriptor_alone(self, topic: str, field: InputFormField, expected: str):
        # The `# concept: …` comment a compact TOML template carries is io-ref notation, and a client
        # projection has only the descriptor to rebuild it from: the concept reference, the `list`
        # node's own count, and the authored presence marker.
        assert format_slot_signature(field=field) == expected, topic
        # And the case is a slot a real payload could carry: without this, the notation is pinned
        # against field combinations the standard's own parse rejects.
        assert PipeInputFormDescriptor(fields=[field]).fields == [field], topic

    @pytest.mark.parametrize(("topic", "field", "expected"), CompactSlotCases.ENVELOPE_RETENTION)
    def test_a_plural_slot_keeps_its_envelope_on_the_same_terms_as_the_single_one(self, topic: str, field: InputFormField, expected: bool):
        # What a shaper is handed at a plural slot is one element at a time, so the envelope question
        # is the element's. The corpus captures no plural native slot at all, which is why the rule is
        # stated here: without it `native.Date[]` unwraps to a bare array of the very objects a single
        # `native.Date` keeps its envelope to avoid, and the template no longer runs.
        assert keeps_envelope(node=field) is expected, topic
        compact = project_inputs_template(descriptor=PipeInputFormDescriptor(fields=[field]), explicit=False)
        assert (ENVELOPE_CONTENT_KEY in compact[field.name]) is expected, topic

    @pytest.mark.parametrize("explicit", [False, True])
    def test_each_element_of_a_fixed_count_slot_is_its_own_value(self, explicit: bool):
        # A `Concept[N]` slot renders N elements that are identical in content, and a template is a
        # thing somebody fills IN: were they one repeated object, typing into the first entry of the
        # returned mapping would type into every other one.
        template = project_inputs_template(descriptor=PipeInputFormDescriptor(fields=[CompactSlotCases.FIXED_COUNT_SLOT]), explicit=explicit)
        slot: Any = template[CompactSlotCases.FIXED_COUNT_SLOT.name]
        elements: list[dict[str, Any]] = slot[ENVELOPE_CONTENT_KEY] if explicit else slot
        assert elements[0] == elements[1]
        assert elements[0] is not elements[1]
        elements[0]["label"] = "filled in by the caller"
        assert elements[1]["label"] != elements[0]["label"]
