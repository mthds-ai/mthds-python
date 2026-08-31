"""Shared test data constants for unit tests."""

from typing import Any, ClassVar

from mthds.protocol.input_form import InputFormField, ListField, TextField, TextItem
from mthds.protocol.pipe_io_contracts import PresenceMarker


class ExecuteWireResponses:
    """Captured `/v1/execute` 200 bodies in the wire forms a compliant runner may return."""

    # The hosted pipelex-api runner's shape (captured live against api-dev on 2026-07-03):
    # the full PipeOutput dump — per-stuff `stuff_code` / `stuff_name` and `concept` as the
    # full object, pipe-output extras (`graph_spec`, `tokens_usages`, `working_memory_raw`,
    # assembly errors), and run-lifecycle extras at the top level.
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
                        "concept": {
                            "code": "Text",
                            "domain_code": "native",
                            "description": "A text",
                            "structure_class_name": "TextContent",
                            "refines": None,
                        },
                        "content": {"text": "Marie Curie joined the University of Paris in 1906."},
                    },
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
            "working_memory_raw": {"root": {}, "aliases": {}},
            "graph_spec": {"nodes": [], "edges": []},
            "graph_assembly_error": None,
            "tokens_usages": [],
            "usage_assembly_error": None,
        },
    }

    # The reduced form this SDK's own serialization (`from_pipe_output`) emits:
    # `concept` as the namespaced ref string, base fields only.
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
    _OUTPUT: ClassVar[dict[str, Any]] = {"concept_ref": "legal.Summary", "multiplicity": "single", "item_count": None, "optional": False}

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
    OUTPUT_UNKNOWN_MEMBER: ClassVar[dict[str, Any]] = {**_OUTPUT, "json_schema": _TEXT_SCHEMA}
    OUTPUT_FIXED_WITHOUT_COUNT: ClassVar[dict[str, Any]] = {**_OUTPUT, "multiplicity": "fixed"}
    OUTPUT_FIXED_OPTIONAL: ClassVar[dict[str, Any]] = {"concept_ref": "legal.Clause", "multiplicity": "fixed", "item_count": 3, "optional": True}
    ENTRY_WITHOUT_INPUTS: ClassVar[dict[str, Any]] = {"output": _OUTPUT}
    ENTRY_UNKNOWN_MEMBER: ClassVar[dict[str, Any]] = {"inputs": {}, "output": _OUTPUT, "description": "Summarize a contract"}

    # Accepted.
    ENTRY_WITHOUT_DECLARED_INPUTS: ClassVar[dict[str, Any]] = {"inputs": {}, "output": _OUTPUT}
    OUTPUT_SINGLE_OPTIONAL: ClassVar[dict[str, Any]] = {"concept_ref": "legal.Clause", "multiplicity": "single", "item_count": None, "optional": True}


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
