"""The deterministic TOML emitter's layout rules, stated as bytes.

The shared fixture corpus in `tests/fixtures/protocol/inputs_template/` is what pins the emitter
against its TypeScript twin, but it can only exercise the shapes the captured bundles happen to
produce. These cases state each rule on its own, so the rule that failed is named by the test that
broke — and so the twin has an executable statement of the contract rather than a paragraph of prose.
"""

import tomllib
from typing import Any, cast

import pytest

from mthds.protocol.toml_emitter import TomlEmissionError, render_inline_layout, render_table_layout
from tests.unit.test_data import TomlEmitterCases


def _substitute_nulls(value: Any) -> Any:
    """The emitter's own null rule, restated here so a round-trip compares like with like."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return {key: _substitute_nulls(member) for key, member in cast("dict[str, Any]", value).items()}
    if isinstance(value, list):
        return [_substitute_nulls(element) for element in cast("list[Any]", value)]
    return value


class TestTomlEmitter:
    @pytest.mark.parametrize(("topic", "template", "expected"), TomlEmitterCases.TABLE_LAYOUT)
    def test_the_table_layout_follows_its_stated_rules(self, topic: str, template: dict[str, object], expected: str):
        assert render_table_layout(template=template) == expected, topic

    @pytest.mark.parametrize(("topic", "template", "comments", "expected"), TomlEmitterCases.INLINE_LAYOUT)
    def test_the_inline_layout_follows_its_stated_rules(self, topic: str, template: dict[str, object], comments: dict[str, str], expected: str):
        assert render_inline_layout(template=template, comments=comments) == expected, topic

    def test_an_empty_template_renders_as_an_empty_document_in_both_layouts(self):
        # Not a blank line and not a lone newline: a pipe declaring no inputs has nothing to fill in.
        assert render_table_layout(template={}) == ""
        assert render_inline_layout(template={}, comments={}) == ""

    @pytest.mark.parametrize("value", TomlEmitterCases.UNSPELLABLE_VALUES)
    def test_a_value_with_no_toml_spelling_is_refused_rather_than_guessed(self, value: object):
        with pytest.raises(TomlEmissionError):
            render_table_layout(template={"slot": value})
        with pytest.raises(TomlEmissionError):
            render_inline_layout(template={"slot": value}, comments={})

    @pytest.mark.parametrize(("topic", "template", "expected"), TomlEmitterCases.TABLE_LAYOUT)
    def test_the_table_layout_emits_toml_that_parses_back_to_what_went_in(self, topic: str, template: dict[str, Any], expected: str):
        # The expected bytes are what the twin is held to; that they are also *valid TOML carrying
        # the template* is the separate property, and the one a corpus of committed bytes cannot
        # state on its own. A layout rule that produced a well-formed-looking document saying
        # something else would pass every byte comparison there is.
        assert tomllib.loads(expected) == _substitute_nulls(template), topic

    @pytest.mark.parametrize(("topic", "template", "comments", "expected"), TomlEmitterCases.INLINE_LAYOUT)
    def test_the_inline_layout_emits_toml_that_parses_back_to_what_went_in(
        self, topic: str, template: dict[str, Any], comments: dict[str, str], expected: str
    ):
        assert tomllib.loads(expected) == _substitute_nulls(template), topic
        # The comments are the half a parse throws away, so they are checked as text: a comment on
        # a key the template holds is a line of its own — the whole reason this layout exists — and
        # one naming a key it does not hold is nowhere in the document.
        for key, comment_text in comments.items():
            if not comment_text:
                continue
            assert (f"# {comment_text}\n" in expected) is (key in template), topic
