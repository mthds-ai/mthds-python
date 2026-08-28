---
status: landed
item: L-260828-b40047
---

# Restore the input-form models' serialization JSON Schema

**Item:** L-260828-b40047 (bug, P2, owner `mthds-python`), discovered from `pipelex-api` while preparing the `pipelex` bump that carries `pipelex` PR #1154. Written 2026-08-28.

## The bug

Every per-kind input-form model in `mthds/protocol/input_form.py` — the `*Item` models and their `*Field` counterparts — publishes an empty JSON Schema in serialization mode: `{"type": "object", "additionalProperties": true}`, with no `properties`, no `required` and no `kind` literal. The validation-mode schema is complete. The cause is the shared wrap serializer on `InputFormItemBase`, `serialize_without_inapplicable_slots`, whose return annotation is `-> dict[str, Any]`: pydantic turns a serializer's return annotation into the serialization JSON Schema, and the JSON-schema generator prefers that over the model's own generated schema whenever one exists.

It matters because FastAPI generates response-model schemas in serialization mode. `pipelex-api` publishes `PipeInputFormDescriptor` on `POST /v1/validate`, so once its `pipelex` pin imports these models from this package its OpenAPI artifact describes `fields` as a `oneOf` over opaque arms with a `discriminator` on a `kind` that no arm declares. The models themselves did not loosen (`extra="forbid"` still holds); only the published description of them is gone.

Reproduced here against `mthds` 0.11.0 with pydantic 2.12.5:

```
$ .venv/bin/python -c "import json; from mthds.protocol.input_form import TextField
print(json.dumps(TextField.model_json_schema(mode='serialization')))"
{"additionalProperties": true, "type": "object"}
```

## The decision: drop the return annotation, do not add a schema hook

Two fixes were on the table, and the first one is taken.

- **Remove the `-> dict[str, Any]` annotation from the serializer.** With no annotation pydantic builds no `return_schema` for the serializer, so the generator falls through to the model's generated schema. Verified on a scratch copy of the real module on 2026-08-28: every arm under `PipeInputFormDescriptor`'s `fields.items.oneOf` regains `properties`, `required` and `additionalProperties: false`, each arm's `kind` const matches its key in the discriminator mapping, `ListField.item` keeps its nested `oneOf` plus discriminator, and the serialization schema becomes identical to the validation schema for every per-kind model. Dump behaviour is unchanged: `None` slots are dropped and `kind` / `name` still lead.
- **A `__get_pydantic_json_schema__` override on the base class** was the fallback in case the linters insisted on an annotation. They do not: the ruff configuration already ignores the `missing-return-type-*` rules, pyright strict infers the return type from the body, and mypy runs without `disallow_incomplete_defs`. A probe module with an unannotated wrap serializer passes all three. The hook would have to strip the `serialization` key from the core schema before delegating — more code, more coupling to pydantic internals, for the same result.

`return_type=Any` on the decorator is not an option: it publishes `{}`, an even emptier schema.

The cost is one deliberate exception to this repo's "every function return must be typed" rule. The serializer's docstring states the reason so that nobody re-adds the annotation as a cleanup.

## Steps

1. **Housekeeping.** `ledger claim L-260828-b40047`. Branch `fix/Input-form-serialization-schema` off `dev`.
2. **Test first — `tests/unit/test_protocol_input_form.py`**, inside the existing `TestInputFormProtocolModels` class (one test class per module):
   - A parametrized test over every member of both unions, obtained with `typing.get_args` on `InputFormField` and `InputFormItem`, asserting that `model_json_schema(mode="serialization")` equals `model_json_schema(mode="validation")`, carries `properties`, has `additionalProperties` set to `False`, and states the model's kind as `properties.kind.const`. This fails on the current code.
   - A descriptor-level test on `PipeInputFormDescriptor.model_json_schema(mode="serialization")`: every `$ref` arm under `fields.items.oneOf` resolves to a `$defs` entry whose `kind` const matches its key in `discriminator.mapping`. This is the exact shape a FastAPI response model publishes, so it pins the consumer-visible fix rather than only the per-model one.
3. **Fix — `mthds/protocol/input_form.py`**, `InputFormItemBase.serialize_without_inapplicable_slots`. Remove the `-> dict[str, Any]` return annotation and add a paragraph to the docstring: the return is deliberately unannotated because pydantic would publish the annotation as the serialization JSON Schema and erase the per-kind shapes that FastAPI consumers embed in their OpenAPI artifacts, and `return_type=Any` is worse. `Any` stays imported — it still types `dumped` and several fields.
4. **Docs.** In `docs/runners.md`, "The validate artifacts" section, beside the bullet on the serializer's absent-never-`null` rule: one sentence that the models' serialization JSON Schema is complete, so a server that embeds them in a response model (FastAPI, OpenAPI) publishes the per-kind field shapes. In `CHANGELOG.md`, a new `## [Unreleased]` heading with a `### Fixed` entry; no version bump — that is the release's job.
5. **Verify.** `make fui && make cc`, then `make agent-test`.
6. **PR against `dev`**, body `Closes L-260828-b40047`. After the merge, `/ledger-land` from this repo.

## What this unblocks

Nothing hard. `pipelex-api` item L-260828-f7bff1 takes the `pipelex` bump that carries #1154 with the degenerate union and records it in its changelog; its artifact regains the field-level detail on the first bump whose resolved `mthds` carries this fix. That edge already exists on the ledger. The related item L-260824-52d6fe (owner `pipelex`) covers the other models named there — `ConceptBlueprint`, `ConceptStructureBlueprint`, `InputSlotBlueprint` — which are still `pipelex` source and are not touched here.

## Landing record

**The fix landed** in commit `979d90c`, merged to `dev` as `8feec62` by [PR #52](https://github.com/mthds-ai/mthds-python/pull/52) on 2026-08-28, which closed L-260828-b40047. Every check was green — lint and tests on Python 3.11 through 3.14, `uv-lock-check`, and the Greptile and cubic reviews.

The plan was followed as written, with two things worth recording because neither can be re-derived:

- **No `noqa` was needed on the unannotated serializer.** The plan predicted this from reading the configuration; it is now confirmed by a clean `make cc` — ruff's ignore list already carries the `missing-return-type-*` rules, pyright infers the return from the body, and mypy runs without `disallow_incomplete_defs`. An added `# noqa: ANN201` would itself have been flagged as unused, so the fallback `__get_pydantic_json_schema__` hook was never needed.
- **The serialization schema of a recursive model roots at a `$ref`.** `ObjectField`, `ListField`, `ObjectItem` and `ListItem` return `{"$defs": {…}, "$ref": "#/$defs/<Model>"}` rather than an inline object, so the per-model test dereferences the root before asserting on it. A test written against the inline shape alone would have passed vacuously on those four.

**The `mthds` version that first published it** is not yet decided: the changelog entry sits under `## [Unreleased]` and `pyproject.toml` was deliberately left alone, since cutting the version is the release play's job. There is no open `release` item for `mthds-python` — the fix reaches PyPI, and therefore any consumer, only once one is filed and run.

**The `pipelex-api` bump that picked it up** is likewise pending, and is tracked as its own item rather than here: L-260828-f7bff1 (owner `pipelex-api`, blocked by L-260828-f4e88c) regenerates that repo's OpenAPI artifact at the `pipelex` bump carrying #1154. Its artifact regains the field-level detail on the first bump whose resolved `mthds` carries this fix — that is, on a published version, not on this merge.
