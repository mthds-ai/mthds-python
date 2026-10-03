"""Shared test data constants for unit tests."""

from typing import Any, ClassVar

from mthds.protocol.input_form import (
    BooleanField,
    DateField,
    ImageItem,
    InputFormField,
    ListField,
    NumberField,
    ObjectField,
    ObjectItem,
    TextField,
    TextItem,
    UnknownField,
)
from mthds.protocol.pipe_io_contracts import PresenceMarker


class ExecuteWireResponses:
    """`/v1/execute` 200 bodies: the shapes a compliant runner returns, and one it must not."""

    # The hosted pipelex-api runner's shape: the full PipeOutput dump, every stuff naming its
    # concept by its ref string, with per-stuff `stuff_code` / `stuff_name`, the working
    # memory's `absences`, pipe-output extras (`graph_spec`, `tokens_usages`,
    # `working_memory_raw`, assembly errors) and run-lifecycle extras at the top level. The key
    # set follows the blocking response conformance captured from the hosted plane; the values
    # are hand-built, the real capture being `tests/fixtures/hosted_run/`.
    HOSTED_FULL_DUMP: ClassVar[dict[str, Any]] = {
        "pipeline_run_id": "run_7f3a",
        "created_at": "2026-07-03T09:15:01.000000+00:00",
        "finished_at": "2026-07-03T09:15:07.000000+00:00",
        "state": "COMPLETED",
        "main_stuff_name": "extracted_entities",
        "pipe_output": {
            "pipeline_run_id": "run_7f3a",
            "working_memory": {
                "root": {
                    "text": {
                        "stuff_code": "a1b2c3d4",
                        "stuff_name": "text",
                        "concept": "native.Text",
                        "content": {"text": "Marie Curie joined the University of Paris in 1906."},
                    },
                    "extracted_entities": {
                        "stuff_code": "e5f6a7b8",
                        "stuff_name": "extracted_entities",
                        "concept": "extract_entities.ExtractedEntities",
                        "content": {"entities": [{"name": "Marie Curie", "kind": "person"}]},
                    },
                },
                "aliases": {"main_stuff": "extracted_entities"},
                "absences": {},
            },
            "working_memory_raw": {"root": {}, "aliases": {}},
            "graph_spec": {"nodes": [], "edges": []},
            "graph_assembly_error": None,
            "pipe_io_artifacts": None,
            "pipe_io_artifacts_error": None,
            "tokens_usages": [],
            "usage_assembly_error": None,
        },
    }

    # The reduced form this SDK's own serialization (`from_pipe_output`) emits: base fields only.
    REDUCED: ClassVar[dict[str, Any]] = {
        "pipeline_run_id": "run_7f3a",
        "pipe_output": {
            "pipeline_run_id": "run_7f3a",
            "working_memory": {
                "root": {
                    "extracted_entities": {
                        "concept": "extract_entities.ExtractedEntities",
                        "content": {"entities": [{"name": "Marie Curie", "kind": "person"}]},
                    },
                },
                "aliases": {"main_stuff": "extracted_entities"},
            },
        },
        "main_stuff_name": "extracted_entities",
    }

    # What the hosted runner sent before the runtime stopped dumping the concept object onto the
    # wire, abridged from a body captured against api-dev on 2026-07-03: the concept's whole
    # definition riding the stuff in place of its ref. The standard names a stuff's concept by its
    # ref string, so this body is refused, at the `concept` of the stuff that carries the object.
    CONCEPT_OBJECT: ClassVar[dict[str, Any]] = {
        "pipeline_run_id": "run_7f3a",
        "pipe_output": {
            "pipeline_run_id": "run_7f3a",
            "working_memory": {
                "root": {
                    "extracted_entities": {
                        "stuff_code": "e5f6a7b8",
                        "stuff_name": "extracted_entities",
                        "concept": {
                            "code": "ExtractedEntities",
                            "domain_code": "extract_entities",
                            "description": "Entities extracted from a text",
                            "structure_class_name": "extract_entities__ExtractedEntities",
                            "refines": None,
                        },
                        "content": {"entities": [{"name": "Marie Curie", "kind": "person"}]},
                    },
                },
                "aliases": {"main_stuff": "extracted_entities"},
            },
        },
    }


class HostedRunCapture:
    """What the real hosted working memory in `tests/fixtures/hosted_run/` holds."""

    FILE_NAME: ClassVar[str] = "hosted-working-memory.json"

    # Every slot of the captured working memory, mapped to the concept ref it names. Between them
    # they cover a native concept, two domain concepts refining `Text` and a structured one, so a
    # narrower re-capture fails here rather than quietly testing less.
    EXPECTED_CONCEPT_REFS: ClassVar[dict[str, str]] = {
        "topic": "native.Text",
        "joke": "joke_judge.Joke",
        "verdict": "joke_judge.FunninessVerdict",
        "analysis": "joke_judge.JokeAnalysis",
    }
    MAIN_STUFF_SLOT: ClassVar[str] = "analysis"
    EXTENSION_FIELDS: ClassVar[frozenset[str]] = frozenset({"stuff_code", "stuff_name"})


class CliWorkingMemoryDumps:
    """Working memories as `pipelex run --working-memory-path` writes them, and two it must not."""

    # The runtime's `smart_dump()`: each stuff names its concept by its ref string beside its
    # `stuff_code` and `stuff_name`.
    REF_STRING: ClassVar[dict[str, Any]] = {
        "root": {
            "answer": {
                "stuff_code": "k3Rt9",
                "stuff_name": "answer",
                "concept": "answer.Answer",
                "content": {"text": "Because."},
            },
        },
        "aliases": {"main_stuff": "answer"},
    }

    # Each case is a malformed `answer` stuff, which the local runner refuses at its `concept`
    # rather than inventing a ref for it.
    MALFORMED_CONCEPT_CASES: ClassVar[list[tuple[str, dict[str, Any]]]] = [
        (
            "concept-object",
            {
                "stuff_code": "k3Rt9",
                "stuff_name": "answer",
                "concept": {"code": "Answer", "domain_code": "answer", "description": "An answer"},
                "content": {"text": "Because."},
            },
        ),
        (
            "concept-missing",
            {"stuff_code": "k3Rt9", "stuff_name": "answer", "content": {"text": "Because."}},
        ),
    ]


class ModelDeckWireBodies:
    """`GET /models` 200 bodies, among them one a runner of a later protocol minor may send."""

    # One entry per way a deck entry's `type` can read: a category this package knew before
    # `judgment`, `judgment` itself, a category no protocol version this package knows defines,
    # and no category at all. The unknown value stands for a later minor's category, so it is
    # deliberately not a word any MTHDS settings family uses today.
    MIXED_CATEGORIES: ClassVar[dict[str, Any]] = {
        "models": [
            {"name": "gpt-test", "type": "llm"},
            {"name": "judge-test", "type": "judgment"},
            {"name": "speech-test", "type": "speech_to_text"},
            {"name": "untyped-test"},
        ],
        "aliases": {"best": "gpt-test"},
    }


class InputFormWireNodes:
    """Hand-written field descriptors probing the closed shapes of `mthds.protocol.input_form`.

    They complement the engine-produced parity fixture in `tests/fixtures/protocol/`, which only
    shows conforming nodes: these state what a member the standard never defined, a slot of
    another kind, or a broken invariant looks like on the wire.
    """

    # Rejected at the parse.
    UNKNOWN_MEMBER: ClassVar[dict[str, Any]] = {"kind": "text", "name": "title", "required": True, "widget": "textarea"}
    SLOT_OF_ANOTHER_KIND: ClassVar[dict[str, Any]] = {"kind": "text", "name": "tone", "required": False, "choices": ["formal", "casual"]}
    UNKNOWN_KIND: ClassVar[dict[str, Any]] = {"kind": "slider", "name": "volume", "required": True}
    NUMBER_WITHOUT_INTEGER: ClassVar[dict[str, Any]] = {"kind": "number", "name": "count", "required": True}
    DATE_WITHOUT_DATETIME: ClassVar[dict[str, Any]] = {"kind": "date", "name": "released_on", "required": True}
    ENUM_WITHOUT_CHOICES: ClassVar[dict[str, Any]] = {"kind": "enum", "name": "tone", "required": True}
    OBJECT_WITHOUT_FIELDS: ClassVar[dict[str, Any]] = {"kind": "object", "name": "widget", "required": True}
    LIST_WITHOUT_ITEM: ClassVar[dict[str, Any]] = {"kind": "list", "name": "tags", "required": True}
    LIST_COUNT_OF_ONE: ClassVar[dict[str, Any]] = {
        "kind": "list",
        "name": "two",
        "required": True,
        "item": {"kind": "text", "required": True},
        "item_count": 1,
    }
    REQUIRED_WITH_DEFAULT: ClassVar[dict[str, Any]] = {"kind": "text", "name": "motto", "required": True, "default_value": "carpe diem"}
    HINT_VALUE_NOT_A_STRING: ClassVar[dict[str, Any]] = {"kind": "text", "name": "headline", "required": True, "hints": {"intent": 3}}
    NESTED_UNKNOWN_MEMBER: ClassVar[dict[str, Any]] = {
        "kind": "object",
        "name": "widget",
        "required": True,
        "fields": [{"kind": "text", "name": "title", "required": True, "placeholder": "Title"}],
    }
    NESTED_PRESENCE: ClassVar[dict[str, Any]] = {
        "kind": "object",
        "name": "widget",
        "required": True,
        "fields": [{"kind": "text", "name": "title", "required": True, "presence": "plain"}],
    }
    NESTED_GATING: ClassVar[dict[str, Any]] = {
        "kind": "object",
        "name": "widget",
        "required": True,
        "fields": [{"kind": "text", "name": "title", "required": True, "gating": False}],
    }
    ITEM_WITH_PRESENCE: ClassVar[dict[str, Any]] = {
        "kind": "list",
        "name": "tags",
        "required": True,
        "item": {"kind": "text", "required": True, "presence": "plain"},
    }
    TOP_LEVEL_WITHOUT_PRESENCE: ClassVar[dict[str, Any]] = {"kind": "text", "name": "title", "required": True, "gating": True}
    TOP_LEVEL_WITHOUT_GATING: ClassVar[dict[str, Any]] = {"kind": "text", "name": "title", "required": True, "presence": "plain"}
    TOP_LEVEL_OPTIONAL_YET_REQUIRED: ClassVar[dict[str, Any]] = {
        "kind": "text",
        "name": "title",
        "required": True,
        "presence": "optional",
        "gating": False,
    }
    TOP_LEVEL_PLAIN_YET_NOT_REQUIRED: ClassVar[dict[str, Any]] = {
        "kind": "text",
        "name": "title",
        "required": False,
        "presence": "plain",
        "gating": False,
    }
    TOP_LEVEL_OPTIONAL_YET_GATING: ClassVar[dict[str, Any]] = {
        "kind": "text",
        "name": "title",
        "required": False,
        "presence": "optional",
        "gating": True,
    }
    TITLE_EXPLICIT_NULL: ClassVar[dict[str, Any]] = {
        "kind": "text",
        "name": "title",
        "title": None,
        "required": True,
        "presence": "plain",
        "gating": True,
    }
    REFINES_EXPLICIT_NULL: ClassVar[dict[str, Any]] = {
        "kind": "text",
        "name": "title",
        "refines": None,
        "required": True,
        "presence": "plain",
        "gating": True,
    }
    ITEM_COUNT_NULL_ON_VARIABLE_LIST: ClassVar[dict[str, Any]] = {
        "kind": "list",
        "name": "tags",
        "required": True,
        "presence": "plain",
        "gating": False,
        "item": {"kind": "text", "required": True},
        "item_count": None,
    }
    NESTED_TITLE_EXPLICIT_NULL: ClassVar[dict[str, Any]] = {
        "kind": "object",
        "name": "widget",
        "required": True,
        "presence": "plain",
        "gating": True,
        "fields": [{"kind": "text", "name": "note", "title": None, "required": True}],
    }
    ITEM_TITLE_EXPLICIT_NULL: ClassVar[dict[str, Any]] = {
        "kind": "list",
        "name": "tags",
        "required": True,
        "presence": "plain",
        "gating": False,
        "item": {"kind": "text", "title": None, "required": True},
    }
    ITEM_WITH_NAME: ClassVar[dict[str, Any]] = {
        "kind": "list",
        "name": "tags",
        "required": True,
        "presence": "plain",
        "gating": False,
        "item": {"kind": "text", "name": "tags", "required": True},
    }
    TOP_LEVEL_WITHOUT_NAME: ClassVar[dict[str, Any]] = {"kind": "text", "required": True, "presence": "plain", "gating": True}
    NESTED_WITHOUT_NAME: ClassVar[dict[str, Any]] = {
        "kind": "object",
        "name": "widget",
        "required": True,
        "presence": "plain",
        "gating": True,
        "fields": [{"kind": "text", "required": True}],
    }
    DESCRIPTOR_UNKNOWN_MEMBER: ClassVar[dict[str, Any]] = {"fields": [], "layout": "two-column"}

    # Accepted, and what the accepted dump must look like.
    HINTS_CONTENT_LENIENT: ClassVar[dict[str, Any]] = {
        "kind": "text",
        "name": "quirk",
        "required": False,
        "presence": "optional",
        "gating": False,
        "hints": {"emphasis": "strong", "intent": "a-word-from-a-later-version"},
    }
    FALSY_SLOTS_STATED: ClassVar[dict[str, Any]] = {
        "kind": "number",
        "name": "price",
        "required": False,
        "presence": "optional",
        "gating": False,
        "integer": False,
    }
    ITEM_WITHOUT_NAME: ClassVar[dict[str, Any]] = {
        "kind": "list",
        "name": "tags",
        "concept_ref": "native.Text",
        "required": True,
        "presence": "plain",
        "gating": False,
        "item": {"kind": "prose", "concept_ref": "native.Text", "required": True},
    }
    NUMBER_WITH_INTEGRAL_BOUNDS: ClassVar[dict[str, Any]] = {
        "kind": "number",
        "name": "stars",
        "required": False,
        "presence": "optional",
        "gating": False,
        "integer": True,
        "minimum": 1,
        "maximum": 5,
    }
    DEFAULT_VALUE_EXPLICIT_NULL: ClassVar[dict[str, Any]] = {
        "kind": "text",
        "name": "motto",
        "required": False,
        "presence": "optional",
        "gating": False,
        "default_value": None,
    }
    EMPTY_FORM: ClassVar[dict[str, Any]] = {"fields": []}


class PipeIOContractWireNodes:
    """Hand-written contract entries probing the closed shapes of `mthds.protocol.pipe_io_contracts`."""

    _TEXT_SCHEMA: ClassVar[dict[str, Any]] = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    _OUTPUT: ClassVar[dict[str, Any]] = {
        "concept_ref": "legal.Summary",
        "multiplicity": "single",
        "item_count": None,
        "optional": False,
        "json_schema": _TEXT_SCHEMA,
    }

    # Rejected at the parse.
    INPUT_UNKNOWN_MEMBER: ClassVar[dict[str, Any]] = {
        "concept_ref": "native.Text",
        "presence": "plain",
        "multiplicity": "single",
        "item_count": None,
        "json_schema": _TEXT_SCHEMA,
        "label": "Instructions",
    }
    INPUT_ITEM_COUNT_MISSING: ClassVar[dict[str, Any]] = {
        "concept_ref": "native.Text",
        "presence": "plain",
        "multiplicity": "single",
        "json_schema": _TEXT_SCHEMA,
    }
    INPUT_FIXED_WITHOUT_COUNT: ClassVar[dict[str, Any]] = {
        "concept_ref": "legal.Clause",
        "presence": "plain",
        "multiplicity": "fixed",
        "item_count": None,
        "json_schema": {"type": "array", "items": _TEXT_SCHEMA},
    }
    INPUT_SINGLE_WITH_COUNT: ClassVar[dict[str, Any]] = {
        "concept_ref": "legal.Clause",
        "presence": "plain",
        "multiplicity": "single",
        "item_count": 2,
        "json_schema": _TEXT_SCHEMA,
    }
    INPUT_FIXED_COUNT_OF_ONE: ClassVar[dict[str, Any]] = {
        "concept_ref": "legal.Clause",
        "presence": "plain",
        "multiplicity": "fixed",
        "item_count": 1,
        "json_schema": {"type": "array", "items": _TEXT_SCHEMA, "minItems": 1, "maxItems": 1},
    }
    INPUT_UNKNOWN_PRESENCE: ClassVar[dict[str, Any]] = {
        "concept_ref": "native.Text",
        "presence": "required",
        "multiplicity": "single",
        "item_count": None,
        "json_schema": _TEXT_SCHEMA,
    }
    INPUT_VARIABLE_OPTIONAL: ClassVar[dict[str, Any]] = {
        "concept_ref": "legal.Clause",
        "presence": "optional",
        "multiplicity": "variable",
        "item_count": None,
        "json_schema": {"type": "array", "items": _TEXT_SCHEMA},
    }
    INPUT_FIXED_FORCED: ClassVar[dict[str, Any]] = {
        "concept_ref": "legal.Clause",
        "presence": "force",
        "multiplicity": "fixed",
        "item_count": 3,
        "json_schema": {"type": "array", "items": _TEXT_SCHEMA, "minItems": 3, "maxItems": 3},
    }
    OUTPUT_UNKNOWN_MEMBER: ClassVar[dict[str, Any]] = {**_OUTPUT, "presence": "plain"}
    """`presence` on an output. The marker is an INPUT-slot fact — `!` may not appear on an output
    and `?` is what `optional` states — so this is the member the output shape most plausibly grows
    by mistake, which is why it is the one the closed-shape case uses."""

    OUTPUT_WITHOUT_SCHEMA: ClassVar[dict[str, Any]] = {k: v for k, v in _OUTPUT.items() if k != "json_schema"}
    """An output stating no payload schema. Omitted members fail the parse like unknown ones do:
    the schema is required precisely so a consumer never has to infer a payload's shape from the
    payload."""
    OUTPUT_FIXED_WITHOUT_COUNT: ClassVar[dict[str, Any]] = {**_OUTPUT, "multiplicity": "fixed"}
    OUTPUT_FIXED_OPTIONAL: ClassVar[dict[str, Any]] = {
        "concept_ref": "legal.Clause",
        "multiplicity": "fixed",
        "item_count": 3,
        "optional": True,
        "json_schema": _TEXT_SCHEMA,
    }
    ENTRY_WITHOUT_INPUTS: ClassVar[dict[str, Any]] = {"output": _OUTPUT}
    ENTRY_UNKNOWN_MEMBER: ClassVar[dict[str, Any]] = {"inputs": {}, "output": _OUTPUT, "description": "Summarize a contract"}

    # Accepted.
    ENTRY_WITHOUT_DECLARED_INPUTS: ClassVar[dict[str, Any]] = {"inputs": {}, "output": _OUTPUT}
    OUTPUT_SINGLE_OPTIONAL: ClassVar[dict[str, Any]] = {
        "concept_ref": "legal.Clause",
        "multiplicity": "single",
        "item_count": None,
        "optional": True,
        "json_schema": _TEXT_SCHEMA,
    }


class TomlEmitterCases:
    """One case per rule the deterministic TOML emitter states, as `(topic, input…, expected bytes)`."""

    TABLE_LAYOUT: ClassVar[list[tuple[str, dict[str, Any], str]]] = [
        (
            "scalars come before tables, each half in authored order, one blank line before every header",
            {"alpha": "a", "obj": {"beta": 1, "nested": {"gamma": True}}, "zeta": 2},
            'alpha = "a"\nzeta = 2\n\n[obj]\nbeta = 1\n\n[obj.nested]\ngamma = true\n',
        ),
        (
            "a table whose members are all tables states no header: its children carry the dotted path",
            {"outer": {"inner": {"leaf": 1}}},
            "[outer.inner]\nleaf = 1\n",
        ),
        (
            "an empty table is not a super table — it has no child to carry its path, so it states its header",
            {"first": {"alpha": 1}, "empty": {}},
            "[first]\nalpha = 1\n\n[empty]\n",
        ),
        (
            "a non-empty list of mappings is an array of tables: one header per element",
            {"items": [{"alpha": 1}, {"alpha": 2}]},
            "[[items]]\nalpha = 1\n\n[[items]]\nalpha = 2\n",
        ),
        (
            (
                "an array-of-tables element always states its header, even with nothing but tables inside — "
                "and takes its blank line, where tomlkit, which rendered the corpus, omits it (L-260831-4031a7)"
            ),
            {"outer": [{"inner": {"leaf": 1}}]},
            "[[outer]]\n\n[outer.inner]\nleaf = 1\n",
        ),
        (
            "a list of scalars, an empty list and a mixed list are inline arrays, not arrays of tables",
            {"tags": ["one", "two"], "none": [], "mixed": [{"alpha": 1}, 2]},
            'tags = ["one", "two"]\nnone = []\nmixed = [{alpha = 1}, 2]\n',
        ),
        (
            "TOML has no null: a None keeps its key and takes an empty string, at every depth",
            {"missing": None, "obj": {"also": None}},
            'missing = ""\n\n[obj]\nalso = ""\n',
        ),
        (
            "a key TOML cannot spell bare is quoted, in a header path as much as on a line",
            {"a.b": 1, "with space": {"": 2}, "ok-1": 3},
            '"a.b" = 1\nok-1 = 3\n\n["with space"]\n"" = 2\n',
        ),
        (
            "a basic string takes the compact escapes, and any other control character its code point",
            {"text": 'quote " slash \\ break \n tab \t control \x01 accent é'},
            'text = "quote \\" slash \\\\ break \\n tab \\t control \\u0001 accent é"\n',
        ),
        (
            "numbers and booleans keep their own spelling: an integer bare, a float with its point",
            {"count": 0, "price": 0.0, "ratio": 1.5, "negative": -7, "enabled": False, "disabled": True},
            "count = 0\nprice = 0.0\nratio = 1.5\nnegative = -7\nenabled = false\ndisabled = true\n",
        ),
    ]

    INLINE_LAYOUT: ClassVar[list[tuple[str, dict[str, Any], dict[str, str], str]]] = [
        (
            "every value stays at the top level, and a key with a comment takes it on the line above",
            {"note": "text_value", "widget": {"label": "x"}},
            {"note": "concept: native.Text"},
            '# concept: native.Text\nnote = "text_value"\nwidget = {label = "x"}\n',
        ),
        (
            "structure nests as inline tables and inline arrays, however deep, and empty ones stay visible",
            {"deep": {"inner": {"items": [{}, {"alpha": 1}]}}, "empty": {}},
            {},
            "deep = {inner = {items = [{}, {alpha = 1}]}}\nempty = {}\n",
        ),
        (
            "a comment for a key the template does not hold is ignored, and an empty one takes no line",
            {"alpha": 1},
            {"alpha": "", "beta": "concept: never.Rendered"},
            "alpha = 1\n",
        ),
        (
            "authored order is what survives — the reason a compact template is laid out inline at all",
            {"structured": {"alpha": 1}, "scalar": "z"},
            {},
            'structured = {alpha = 1}\nscalar = "z"\n',
        ),
    ]

    UNSPELLABLE_VALUES: ClassVar[list[Any]] = [object(), {1, 2}, b"bytes"]

    # A comment is the one text that reaches the document unquoted, so a line terminator inside it
    # ends the comment instead of corrupting it, and turns what follows into live TOML.
    UNSPELLABLE_COMMENTS: ClassVar[list[str]] = [
        "concept: native.Text\nrogue = 1",
        "concept: native.Text\rrogue = 1",
        "concept: native.Text\x00",
    ]


class SlotSignatureCases:
    """One top-level slot per io-ref notation the compact TOML `# concept: …` comment has to rebuild."""

    SIGNATURES: ClassVar[list[tuple[str, InputFormField, str]]] = [
        (
            "an unmarked single slot is its bare concept reference",
            TextField(name="note", concept_ref="native.Text", required=True, presence=PresenceMarker.PLAIN, gating=True),
            "native.Text",
        ),
        (
            "the force assertion is kept, not flattened into the plain marker it requires the same of",
            TextField(name="forced", concept_ref="native.Text", required=True, presence=PresenceMarker.FORCE, gating=True),
            "native.Text!",
        ),
        (
            "an optional slot carries its marker, and never gates",
            TextField(name="maybe", concept_ref="native.Text", required=False, presence=PresenceMarker.OPTIONAL, gating=False),
            "native.Text?",
        ),
        (
            "a variable-length list takes empty brackets — the element concept is what is named",
            ListField(
                name="many",
                concept_ref="input_semantics.Thing",
                required=True,
                presence=PresenceMarker.PLAIN,
                gating=False,
                item=TextItem(concept_ref="input_semantics.Thing", required=True),
            ),
            "input_semantics.Thing[]",
        ),
        (
            "a fixed-count list states its count, which is the count the projection renders",
            ListField(
                name="two",
                concept_ref="input_semantics.Thing",
                required=True,
                presence=PresenceMarker.PLAIN,
                gating=True,
                item=TextItem(concept_ref="input_semantics.Thing", required=True),
                item_count=2,
            ),
            "input_semantics.Thing[2]",
        ),
    ]


class CompactSlotCases:
    """Top-level slots the shared fixture corpus holds no example of, each a slot a method may author.

    The corpus captures no plural native slot at all, and the envelope rule is decided per element:
    what an input shaper is handed at a plural slot is one element at a time. `native.Date` is the
    case that makes it visible — the optional `time` beside its required `date` makes its payload an
    object, which is why a single one keeps its `{concept, content}` envelope.
    """

    DATE_PAYLOAD: ClassVar[list[InputFormField]] = [
        DateField(name="date", required=True, datetime=False),
        TextField(name="time", required=False, format="time"),
    ]

    ENVELOPE_RETENTION: ClassVar[list[tuple[str, InputFormField, bool]]] = [
        (
            "a single object-shaped native keeps its envelope: a bare date object is not re-shapable",
            ObjectField(name="date_in", concept_ref="native.Date", required=True, presence=PresenceMarker.PLAIN, gating=True, fields=DATE_PAYLOAD),
            True,
        ),
        (
            "a list of that same native keeps it too — the question is the element's, never the list's",
            ListField(
                name="dates_in",
                concept_ref="native.Date",
                required=True,
                presence=PresenceMarker.PLAIN,
                gating=False,
                item=ObjectItem(concept_ref="native.Date", required=True, fields=DATE_PAYLOAD),
            ),
            True,
        ),
        (
            "a list of an out-of-matrix native keeps it, exactly as the single does",
            ListField(
                name="htmls_in",
                concept_ref="native.Html",
                required=True,
                presence=PresenceMarker.PLAIN,
                gating=False,
                item=ObjectItem(concept_ref="native.Html", required=True, fields=[TextField(name="inner_html", required=True)]),
            ),
            True,
        ),
        (
            "a list of a scalar native does not: a bare URL per element is what a shaper takes back",
            ListField(
                name="images_in",
                concept_ref="native.Image",
                required=True,
                presence=PresenceMarker.PLAIN,
                gating=False,
                item=ImageItem(concept_ref="native.Image", required=True),
            ),
            False,
        ),
        (
            "a list over an authored concept does not: it names no native to be unbuildable as",
            ListField(
                name="gadgets_in",
                concept_ref="probe.Gadget",
                required=True,
                presence=PresenceMarker.PLAIN,
                gating=False,
                item=ObjectItem(concept_ref="probe.Gadget", required=True, fields=[TextField(name="label", required=True)]),
            ),
            False,
        ),
    ]

    # The verdict natives the standard pinned at 3.0.0, with their fields as the input-form descriptor
    # states them: a `dict` member is `unknown`, and `integer` is a `number` with `integer: true`.
    CHOICE_PAYLOAD: ClassVar[list[InputFormField]] = [
        TextField(name="choice", required=True),
        NumberField(name="confidence", required=False, integer=False),
        UnknownField(name="probabilities", required=False),
    ]
    RATING_PAYLOAD: ClassVar[list[InputFormField]] = [
        NumberField(name="level", required=True, integer=True),
        NumberField(name="confidence", required=False, integer=False),
        UnknownField(name="probabilities", required=False),
        NumberField(name="position", required=False, integer=False),
    ]

    VERDICT_NATIVES: ClassVar[list[tuple[str, InputFormField, bool]]] = [
        (
            "a Choice keeps its envelope: a bare option key would read exactly as a Text does",
            ObjectField(
                name="choice_in", concept_ref="native.Choice", required=True, presence=PresenceMarker.PLAIN, gating=True, fields=CHOICE_PAYLOAD
            ),
            True,
        ),
        (
            "a Rating keeps it too: a bare level would read exactly as a Number does",
            ObjectField(
                name="rating_in", concept_ref="native.Rating", required=True, presence=PresenceMarker.PLAIN, gating=True, fields=RATING_PAYLOAD
            ),
            True,
        ),
        (
            "a YesNo does not: its input is a boolean, its probability being what a judging model reports",
            BooleanField(name="yes_no_in", concept_ref="native.YesNo", required=True, presence=PresenceMarker.PLAIN, gating=True),
            False,
        ),
    ]

    FIXED_COUNT_SLOT: ClassVar[ListField] = ListField(
        name="two",
        concept_ref="probe.Gadget",
        required=True,
        presence=PresenceMarker.PLAIN,
        gating=True,
        item_count=2,
        item=ObjectItem(concept_ref="probe.Gadget", required=True, fields=[TextField(name="label", required=True)]),
    )


class MethodFileCases:
    """Vectors for the catalog serialization, pinned against the TypeScript twin.

    `TWIN_SERIALIZED` is the exact string `serializeMethodFiles(TWIN_FILES)` printed when run from
    `mthds-js/src/protocol/method_files.ts` (2026-09-12, node 24): compact separators, UTF-8 left as
    is, the double quote, the backslash and the LF and TAB it happens to contain escaped and nothing
    else. `BLANK_PREDICATE` is what the same run said of each code point — which single-character
    contents `serializeMethodFiles` dropped and which `parseMethodFiles` read as "no source" — so
    every disagreement between ECMAScript's `trim` and Python's `str.isspace` is stated as a case
    rather than assumed away. It samples the set; `test_the_trim_set_is_ecmascripts_whole_trim_set`
    is what actually holds the set complete, by deriving it.
    """

    TWIN_FILES: ClassVar[list[dict[str, str]]] = [
        {
            "name": "bundle.mthds",
            "content": 'domain = "x"\n[concept.\u00c9t\u00e9]\n'
            'description = "caf\u00e9 \u2014 \u00fcn\u00efc\u00f6d\u00e9 \u65e5\u672c \U0001f642"\n',
        },
        {"name": "funcs/price.py", "content": 'def price():\n\treturn "a\\\\b" + \'\\u00e9\' + "/" + "<tag>" + "&"\n'},
    ]
    TWIN_SERIALIZED: ClassVar[str] = (
        '[{"name":"bundle.mthds","content":"domain = \\"x\\"\\n[concept.\u00c9t\u00e9]\\n'
        'description = \\"caf\u00e9 \u2014 \u00fcn\u00efc\u00f6d\u00e9 \u65e5\u672c \U0001f642\\"\\n"},'
        '{"name":"funcs/price.py","content":"def price():\\n\\treturn \\"a\\\\\\\\b\\" + \'\\\\u00e9\' + \\"/\\" + \\"<tag>\\" + \\"&\\"\\n"}]'
    )

    # (topic, single-character content, whether the twin treats it as blank)
    BLANK_PREDICATE: ClassVar[list[tuple[str, str, bool]]] = [
        ("U+0009 TAB", "\t", True),
        ("U+000A LF", "\n", True),
        ("U+000B VT", "\v", True),
        ("U+000C FF", "\f", True),
        ("U+000D CR", "\r", True),
        ("U+0020 SPACE", " ", True),
        ("U+00A0 NBSP", "\u00a0", True),
        ("U+1680 OGHAM SPACE MARK", "\u1680", True),
        ("U+2000 EN QUAD", "\u2000", True),
        ("U+200A HAIR SPACE", "\u200a", True),
        ("U+2028 LINE SEPARATOR", "\u2028", True),
        ("U+2029 PARAGRAPH SEPARATOR", "\u2029", True),
        ("U+202F NARROW NBSP", "\u202f", True),
        ("U+205F MEDIUM MATHEMATICAL SPACE", "\u205f", True),
        ("U+3000 IDEOGRAPHIC SPACE", "\u3000", True),
        ("U+FEFF BOM — blank to the twin, not to str.isspace", "\ufeff", True),
        ("U+001C FILE SEPARATOR — content to the twin, whitespace to str.isspace", "\x1c", False),
        ("U+001D GROUP SEPARATOR — content to the twin, whitespace to str.isspace", "\x1d", False),
        ("U+001E RECORD SEPARATOR — content to the twin, whitespace to str.isspace", "\x1e", False),
        ("U+001F UNIT SEPARATOR — content to the twin, whitespace to str.isspace", "\x1f", False),
        ("U+0085 NEXT LINE — content to the twin, whitespace to str.isspace", "\x85", False),
        ("U+200B ZERO WIDTH SPACE — content on both sides", "\u200b", False),
        ("U+180E MONGOLIAN VOWEL SEPARATOR — content on both sides", "\u180e", False),
    ]

    # (topic, source) — every one read by the twin as "no files"
    NO_FILES_SOURCES: ClassVar[list[tuple[str, str | None]]] = [
        ("the empty string", ""),
        ("whitespace only", "   "),
        ("a mix of every whitespace kind, the BOM included", " \n\t\r \ufeff "),
        ("None, a field never set", None),
        ("the empty JSON array", "[]"),
        ("the empty JSON array with trailing whitespace", "[]  "),
        ("the empty JSON array with leading whitespace", "  []"),
    ]

    # (topic, source) — every one refused by the twin with PipelineRequestError
    CONTRACT_VIOLATIONS: ClassVar[list[tuple[str, str]]] = [
        ("raw bundle text is the legacy shape, not the catalog array", "domain = 'x'"),
        ("a BOM before the array is not JSON on either side", "\ufeff[]"),
        ("a JSON object, even one shaped like an entry", '{"name":"a.py","content":"x"}'),
        ("JSON null", "null"),
        ("a JSON string", '"abc"'),
        ("a JSON number", "1"),
        ("a bare NaN, refused by the decoder now and by the array check regardless", "NaN"),
        ("an entry missing content", '[{"name":"a.py"}]'),
        ("an entry that is a bare string", '["a.py"]'),
        ("an entry that is null", "[null]"),
        ("an entry that is an array", "[[]]"),
        ("an entry whose name is not a string", '[{"name":1,"content":"x"}]'),
        ("an entry whose content is not a string", '[{"name":"a","content":1}]'),
        ("an entry whose content is null", '[{"name":"a","content":null}]'),
        ("one good entry does not excuse a bad one", '[{"name":"a","content":"x"},{"name":"b"}]'),
        # `json.loads` accepts these three as a Python extension and the twin's `JSON.parse`
        # throws on every one. A bare `NaN` above is caught by the array check whatever the
        # decoder does; inside an ignored member nothing downstream would ever look, so these
        # are the cases that actually pin `parse_constant`.
        ("NaN inside an ignored extra member", '[{"name":"a","content":"x","extra":NaN}]'),
        ("Infinity inside an ignored extra member", '[{"name":"a","content":"x","extra":Infinity}]'),
        ("-Infinity nested in an ignored member's array", '[{"name":"a","content":"x","extra":[1,-Infinity]}]'),
        ("Infinity as a whole entry", "[Infinity]"),
    ]

    # (topic, content, the exact string the twin's `JSON.stringify` printed for that one file)
    # `json.dumps(ensure_ascii=False)` writes an unpaired surrogate raw, which is not UTF-8
    # encodable at all, so these fail at the storage boundary rather than at the typed surface.
    LONE_SURROGATES: ClassVar[list[tuple[str, str, str]]] = [
        ("a lone high surrogate", "\ud800", '[{"name":"f","content":"\\ud800"}]'),
        ("a lone low surrogate", "\udfff", '[{"name":"f","content":"\\udfff"}]'),
        ("a lone surrogate between text", "a\ud800b", '[{"name":"f","content":"a\\ud800b"}]'),
        ("an astral character stays raw, being one code point", "\U0001f642", '[{"name":"f","content":"\U0001f642"}]'),
    ]

    # (topic, content, the exact string the twin's `JSON.stringify` printed for that one file)
    # A Python `str` addresses code points and can hold the two halves of a pair as two of them,
    # where the twin — addressing UTF-16 code units — holds one astral character and writes it
    # raw. The pair is combined before the dump, so these are the twin's bytes and not two
    # escapes. Built with `chr` so no source encoding can quietly collapse a pair into one code
    # point, which is exactly the mistake that hides this case.
    SURROGATE_PAIRS: ClassVar[list[tuple[str, str, str]]] = [
        ("a pair is the astral character it encodes", chr(0xD83D) + chr(0xDE42), '[{"name":"f","content":"\U0001f642"}]'),
        ("the lowest pair", chr(0xD800) + chr(0xDC00), '[{"name":"f","content":"\U00010000"}]'),
        ("the highest pair", chr(0xDBFF) + chr(0xDFFF), '[{"name":"f","content":"\U0010ffff"}]'),
        (
            "a lone high before a pair stays lone, the pair still combines",
            chr(0xD800) + chr(0xD800) + chr(0xDC00),
            '[{"name":"f","content":"\\ud800\U00010000"}]',
        ),
        ("a low before a high is two lone surrogates", chr(0xDC00) + chr(0xD800), '[{"name":"f","content":"\\udc00\\ud800"}]'),
        (
            "a pair followed by a lone low",
            chr(0xD83D) + chr(0xDE42) + chr(0xDFFF),
            '[{"name":"f","content":"\U0001f642\\udfff"}]',
        ),
    ]

    # A JSON integer long enough to exceed `sys.get_int_max_str_digits()` makes Python's decoder
    # raise a bare `ValueError` from `int()` — not a `JSONDecodeError` — where the twin, having one
    # number type and no such limit, parses the same bytes. The limit is 4300 digits by default.
    OVERSIZED_INTEGER_DIGITS: ClassVar[int] = 4301


class RefusedRunBodies:
    """Problem documents a runner answers when it refuses a request, as they came off the wire.

    The first three are the dev plane's `POST /v1/execute` refusals of the execution-errors
    acceptance methods, captured on 2026-09-27 through `MthdsAPIClient` against
    `https://api-dev.pipelex.com` (pipelex-api v0.29.0 on pipelex 0.67.0) and kept verbatim: a bundle
    the runner refused at load with an itemized diagnostic, a run that failed at a pipe's combine
    step, and a run that failed on a model the deck does not serve. The rest are the other shapes a
    runner or a gateway in front of it may answer.
    """

    UNKNOWN_MODEL_AT_LOAD: ClassVar[str] = (
        '{"type":"https://docs.pipelex.com/latest/errors/validate-bundle-error/","title":"Validate bundle","status":422,'
        "\"detail\":\"Pipe 'draft_pitch' (PipeLLM), field 'model': Model handle 'gpt-5.1' was not found in the model deck\\n\\n"
        'Did you mean: gpt-5.5, gpt-5.4, gpt-5.6-sol, gpt-5.4-pro, gpt-5.6-luna","instance":"/v1/execute",'
        '"request_id":"req_a3dd6900-7909-48d3-b551-0140e73ac7fc","error_category":"configuration","error_domain":"input",'
        '"retryable":false,"error_type":"ValidateBundleError","validation_errors":[{"category":"pipe_validation",'
        "\"message\":\"Pipe 'draft_pitch' (PipeLLM), field 'model': Model handle 'gpt-5.1' was not found in the model deck\\n\\n"
        'Did you mean: gpt-5.5, gpt-5.4, gpt-5.6-sol, gpt-5.4-pro, gpt-5.6-luna","error_type":"unknown_model",'
        '"pipe_code":"draft_pitch","domain_code":"sales_copy","field_path":"pipe.draft_pitch.model","field_name":"model",'
        '"model_reference":"gpt-5.1","model_type":"llm","suggestions":["gpt-5.5","gpt-5.4","gpt-5.6-sol","gpt-5.4-pro","gpt-5.6-luna"]}],'
        '"user_action":{"kind":"change_input","detail":"Edit the bundle as each validation error says: apply its suggested fix '
        'where it has one, after confirming an unsafe one"}}'
    )
    UNKNOWN_MODEL_DETAIL: ClassVar[str] = (
        "Pipe 'draft_pitch' (PipeLLM), field 'model': Model handle 'gpt-5.1' was not found in the model deck\n\n"
        "Did you mean: gpt-5.5, gpt-5.4, gpt-5.6-sol, gpt-5.4-pro, gpt-5.6-luna"
    )
    UNKNOWN_MODEL_NEXT_STEP: ClassVar[str] = (
        "Edit the bundle as each validation error says: apply its suggested fix where it has one, after confirming an unsafe one"
    )

    COMBINE_FAILURE_AT_RUN: ClassVar[str] = (
        '{"type":"https://docs.pipelex.com/latest/errors/stuff-factory-error/","title":"Stuff factory","status":422,'
        "\"detail\":\"Pipe 'analyze_topics' failed (review_topics → analyze_topics): PipeParallel 'analyze_topics' cannot "
        "combine its branch results into its output 'TopicReview'. Branch 'draft_ideas' gives result 'ideas' as a list, "
        "'Idea[]', but field 'ideas' of 'TopicReview' holds a single item. Declare the field as a list in the structure of "
        "'TopicReview', with type 'list', item_type 'concept' and item_concept_ref 'Idea', or make branch 'draft_ideas' output "
        'a single \'Idea\'.","instance":"/v1/execute","request_id":"req_d4212542-63a6-4ddb-87c9-4b968785c8c5",'
        '"error_domain":"input","error_type":"StuffFactoryError","user_action":{"kind":"change_input","detail":"Branch '
        "'draft_ideas' gives result 'ideas' as a list, 'Idea[]', but field 'ideas' of 'TopicReview' holds a single item. "
        "Declare the field as a list in the structure of 'TopicReview', with type 'list', item_type 'concept' and "
        "item_concept_ref 'Idea', or make branch 'draft_ideas' output a single 'Idea'.\"}}"
    )
    COMBINE_FAILURE_NEXT_STEP: ClassVar[str] = (
        "Branch 'draft_ideas' gives result 'ideas' as a list, 'Idea[]', but field 'ideas' of 'TopicReview' holds a single item. "
        "Declare the field as a list in the structure of 'TopicReview', with type 'list', item_type 'concept' and "
        "item_concept_ref 'Idea', or make branch 'draft_ideas' output a single 'Idea'."
    )

    UNSERVED_MODEL_AT_RUN: ClassVar[str] = (
        '{"type":"https://docs.pipelex.com/latest/errors/model-not-found-error/","title":"Model not found","status":422,'
        "\"detail\":\"Pipe 'condense_article' failed (digest_article → condense_article): Model handle 'gpt-5.1' was not "
        'found in the model deck.","instance":"/v1/execute","request_id":"req_b7d2c66f-b2d5-4dc7-bd4f-6cf98abfbdc0",'
        '"error_category":"configuration","error_domain":"input","retryable":false,"error_type":"ModelNotFoundError",'
        '"user_action":{"kind":"change_model","detail":"Change the model \'gpt-5.1\' to an LLM the model deck serves."}}'
    )
    UNSERVED_MODEL_DETAIL: ClassVar[str] = (
        "Pipe 'condense_article' failed (digest_article → condense_article): Model handle 'gpt-5.1' was not found in the model deck."
    )
    UNSERVED_MODEL_NEXT_STEP: ClassVar[str] = "Change the model 'gpt-5.1' to an LLM the model deck serves."

    # An older runner answer: `HTTPException` with a dict detail, no RFC 9457 members.
    LEGACY_DETAIL_OBJECT: ClassVar[str] = '{"detail":{"error_type":"PipeRunError","message":"Pipe \'summarize\' failed: the input is empty"}}'
    # A framework's unmatched-route answer.
    PLAIN_DETAIL_STRING: ClassVar[str] = '{"detail":"Not Found"}'
    # A problem that names its class but not the occurrence.
    TITLE_ONLY: ClassVar[str] = '{"type":"about:blank","title":"Malformed request","status":422}'
    # A gateway's page in front of the runner: no JSON at all.
    GATEWAY_HTML: ClassVar[str] = "<html><head><title>502 Bad Gateway</title></head><body><h1>502 Bad Gateway</h1></body></html>"
    # Every member present with the wrong type, or empty, so each reads as absent.
    MALFORMED_MEMBERS: ClassVar[str] = (
        '{"type":42,"title":"","instance":["/v1/execute"],"detail":"The input is empty","request_id":"","error_domain":7,'
        '"retryable":"false","user_action":{"kind":"change_input","detail":""},'
        '"validation_errors":[{"category":"pipe_validation","message":"ok"},{"message":"no category"}]}'
    )
