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
