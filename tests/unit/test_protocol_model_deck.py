import pytest
from pydantic import ValidationError

from mthds.protocol.models import ModelCategory, ModelDeck
from tests.unit.test_data import ModelDeckWireBodies


class TestProtocolModelDeck:
    def test_categories_are_the_protocols(self) -> None:
        """The enum carries the protocol's categories, in the order the specification lists them."""
        assert list(ModelCategory) == ["llm", "extract", "img_gen", "search", "judgment"]

    @pytest.mark.parametrize(
        ("topic", "index_entry", "expected_name", "expected_type"),
        [
            ("a category every protocol version defines", 0, "gpt-test", ModelCategory.LLM),
            ("the judgment category", 1, "judge-test", ModelCategory.JUDGMENT),
            ("a category this package does not recognize", 2, "speech-test", "speech_to_text"),
            ("an entry with no category", 3, "untyped-test", None),
        ],
    )
    def test_deck_keeps_every_entry_whatever_its_category(
        self,
        topic: str,
        index_entry: int,
        expected_name: str,
        expected_type: ModelCategory | str | None,
    ) -> None:
        """A deck carrying a category this package does not know validates whole: a known category
        reads as its enum member, and an unknown one keeps its raw string (the protocol's reader rule).
        """
        deck = ModelDeck.model_validate(ModelDeckWireBodies.MIXED_CATEGORIES)

        assert [model.name for model in deck.models] == ["gpt-test", "judge-test", "speech-test", "untyped-test"], topic
        entry = deck.models[index_entry]
        assert entry.name == expected_name, topic
        assert entry.type == expected_type, topic
        # A StrEnum member equals its raw string, so equality alone cannot tell the member from a plain str.
        assert type(entry.type) is type(expected_type), topic

    def test_deck_dumps_back_to_the_wire_body(self) -> None:
        """An unknown category survives the round trip as the runner sent it, beside the deck's extensions."""
        deck = ModelDeck.model_validate(ModelDeckWireBodies.MIXED_CATEGORIES)

        assert deck.model_dump(mode="json", exclude_none=True) == ModelDeckWireBodies.MIXED_CATEGORIES

    def test_entry_type_that_is_not_a_string_is_refused(self) -> None:
        """The reader rule tolerates a category it does not recognize, not a `type` that is no category at all."""
        with pytest.raises(ValidationError, match=r"models\.0\.type"):
            ModelDeck.model_validate({"models": [{"name": "gpt-test", "type": 3}]})
