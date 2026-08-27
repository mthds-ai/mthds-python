"""Shared test data constants for unit tests."""

from typing import Any, ClassVar


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
