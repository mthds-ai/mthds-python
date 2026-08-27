# Protocol parity fixtures

`input_form.json` and `pipe_io_contracts.json` are one real payload pair produced by the reference engine's own derivation, committed here **byte-for-byte** and committed identically in `mthds-js`. That identity is the Stage 2.3 parity of the input-form program (`wip/input-form/plan.md` at the workspace root): the same bytes parse strictly against `mthds.protocol` in Python and type-check against `mthds/protocol` in TypeScript, so the two clients mirror each other by measurement rather than by intent. Do not edit these files — a change is a new capture, landed in both repos.

## Provenance

- Bundles: `pipelex/tests/data/input_semantics/hinted_bundle.mthds` and `pipelex/tests/data/input_semantics/probe_bundle.mthds`.
- Command, run from the `pipelex` checkout: `pipelex-dev trace-input-semantics tests/data/input_semantics/hinted_bundle.mthds tests/data/input_semantics/probe_bundle.mthds`. The trace's hop-5 outputs, `hop5_input_form.json` and `hop5_pipe_io_contracts.json`, are these two files. The argument order is part of the capture: it decides the key order of the emitted maps.
- Engine: `pipelex` at checkout `bdd853c41`, carrying #1154 (the engine adopting these very models) and #1155 (the catch-up to MTHDS v0.9.0). Its `pyproject.toml` still reads 0.53.0 — that release is not cut yet, so the SHA is the identifier, as `bc97dad0b` was for the previous capture.
- Pages the models mirror: `mthds` v0.9.0, `docs/spec/pipe-io-contracts.md` and `docs/spec/input-form-descriptor.md` (the `hints` slot's shape from `docs/spec/intent-hints.md`), with the pinned native definitions from `docs/spec/native-concepts.md`.

## Known engine drift

Where the fixture and a page disagree, the page wins: the models mirror the pages, and the fixture is kept as captured. **This capture has no known divergence.** The three the previous one carried were all fixed in the engine before it was taken, and each is asserted positively by the suite now rather than merely absent:

- A `list`'s `item` carries no `name` member (`L-260826-0ed8dd`) — `test_every_node_but_a_list_item_is_named` walks every node of the capture and holds both halves.
- Description-only concepts (`Essay`, `Badge`, `PlainNote`, `StringNote`) no longer carry a fabricated `refines: ["native.Text"]` (`L-260826-0ed8dd`).
- `native.Date` and `native.Html` land on the page's `object` arm with fields derived from the pinned definitions, rather than as `date` / `prose` scalars (`L-260826-236839`), and `native.Html`'s `css_class` is optional as MTHDS v0.9.0 states it (`L-260826-3cea94`) — `test_a_pinned_native_structure_lands_on_the_object_arm` holds both.

## The `json_schema` projection is the producer's, not the page's

`pipe_io_contracts.json` carries pydantic's auto-generated titles — `"title": "Inner Html"`, `"title": "ImageContent"` — because the engine projects each slot's schema from its runtime pydantic content class. That is **not** a divergence, and it should not be re-filed as one:

- `docs/spec/pipe-io-contracts.md:124` says outright that a producer MAY carry the concept's identity or description inside the schema document as `title`, and that consumers MUST NOT depend on it — `concept_ref` is the authoritative statement.
- `:44` leaves the `json_schema` slot's content unfixed beyond the two rules in "The input schema"; the projection follows the concept model and the producer's chosen dialect.

What matters is that the projection agrees with the standard's pinned definitions, and as of `pipelex` #1155 that is machine-checked in a chain rather than assumed: `tests/unit/pipelex/codegen/test_native_expansion.py` holds each runtime content class to its pinned blueprint, and `tests/unit/pipelex/core/concepts/test_pinned_natives_vs_standard.py` holds the pinned blueprints to `mthds/docs/spec/native-concepts.md`, read unpinned at the standard's default branch by a CI job of its own.
