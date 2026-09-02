# Protocol parity fixtures

`input_form.json` and `pipe_io_contracts.json` are one real payload pair produced by the reference engine's own derivation, committed here **byte-for-byte** and committed identically in `mthds-js` — as is everything else in this directory, `README.md` aside, which `conformance/scripts/check-protocol-fixture-parity.py` compares between the two mirrors file by file. That identity is the Stage 2.3 parity of the input-form program (`wip/input-form/plan.md` at the workspace root): the same bytes parse strictly against `mthds.protocol` in Python and type-check against `mthds/protocol` in TypeScript, so the two clients mirror each other by measurement rather than by intent. Do not edit these files — a change is a new capture, landed in both repos.

## Provenance

- Bundles, in this order: `pipelex/tests/data/input_semantics/hinted_bundle.mthds`, `probe_bundle.mthds`, `scaffold_bundle.mthds`. The argument order is part of the capture: it decides the key order of the emitted maps, so a swapped order produces the same content with different bytes and breaks the byte parity with `mthds-js`. A bundle added at the end keeps the existing bytes stable.
- Command, run at the `pipelex` checkout root:

  ```bash
  pipelex-dev generate-projection-corpus \
    tests/data/input_semantics/hinted_bundle.mthds \
    tests/data/input_semantics/probe_bundle.mthds \
    tests/data/input_semantics/scaffold_bundle.mthds \
    -o <dir>
  ```

  Copy `input_form.json`, `pipe_io_contracts.json` and the whole `inputs_template/` tree from `<dir>` into this directory and into `mthds-js`'s twin of it, then run `npm run fixtures:protocol` there to regenerate its TypeScript twins. The `engine/` directory the command also writes is **not** committed: it holds the reference engine's own renderings, which is what the divergence record below is measured against.
- Engine: `pipelex`, at the change that introduced `pipelex-dev generate-projection-corpus` (its own page is `pipelex/docs/contribute/generate-projection-corpus.md`). That command replaced `trace-input-semantics` as the producer of these files; generating from the two original bundles alone reproduces the previous capture byte for byte, so the move was a no-op diff.
- Pages the models mirror: `mthds` v0.9.0, `docs/spec/pipe-io-contracts.md` and `docs/spec/input-form-descriptor.md` (the `hints` slot's shape from `docs/spec/intent-hints.md`), with the pinned native definitions from `docs/spec/native-concepts.md`.

## The inputs templates

`inputs_template/` is the second half of the corpus, and the reason it grew: a pipe's fill-in inputs template is now projected **client-side** from the descriptor beside it, once here and once in the `mthds` TypeScript package, and the two projections must produce the same bytes — TOML `# concept:` comment lines included — or the JS/Python asymmetry that retiring the server-side build routes removed is simply rebuilt one layer up.

One file per pipe, shape and format: `<pipe_ref>.<compact|explicit>.<json|toml>`, holding the projection's exact return value (the JSON carries no trailing newline; the TOML carries exactly one). `inputs_template/manifest.json` states what the corpus covers, where it departs from the reference engine's own inputs-template renderer, and which of its own templates the runtime's input shaper refuses today.

The corpus is **contract-first**: it landed before either projection, so each is written against a stated expectation instead of the expectation being back-filled from whatever the first implementation happened to emit. `tests/unit/test_inputs_template_projection.py` runs its jobs — byte parity (skip-gated on `mthds.protocol.inputs_template`; that projection has landed under `L-260830-e7c5b5`, so the job runs), kind coverage against the whole closed `FieldKind` vocabulary, file-set completeness, the agreement of the two payload files on which pipes the capture holds, the divergence lapse check, the agreement of the bullet list below with the manifest's own declarations, and the integrity of the unshapeable record.

### Why it departs from the engine, deliberately

The expectation is not the engine's output. It is authored by a reference projection that walks the **descriptor** — the authored facts a method states — where the engine's renderer reflects the **runtime content classes**; the shipped projections have only the descriptor, so the contract has to be authored from it too. Each class of difference is declared in the manifest with worked sites, so the record can be checked here with no engine present, and the generator refuses to write a capture holding an undeclared difference — or one whose declared class has stopped occurring, so an engine fix retires its entry deliberately:

- `optional-field-included` — an optional structure field is rendered at every depth; the engine hides one at depth 1 and shows one nested deeper.
- `file-leaf-not-expanded` — a `document`/`image` node is a leaf carrying only its URL; the engine expands the runtime content class and asks for a width, a mime type and a caption.
- `fixed-count-honoured` — a `Concept[N]` slot renders N elements; the engine emits one, which the runtime's own input shaper then rejects, so its template does not run.
- `text-named-url` — a text field merely **named** `url` takes a text placeholder; the engine picks a placeholder by field name.
- `object-native-keeps-envelope` — a native that renders as an object once its optional field is included keeps its `{concept, content}` envelope, because the shaper dispatches a native's bare value on its scalar kind and would reject the bare object. The engine unwraps to a scalar, which it can only do because it drops the optional field. A consequence of the first entry.
- `unknown-empty-object` — an `unknown` node renders as the empty object, because the descriptor withholds the payload shape at that position and a projection that invented one would have stopped projecting the descriptor. The engine reflects the runtime content class instead and fills a required dict with a sample key/value pair whoever fills the template in then has to delete. The empty object round-trips through the shaper cleanly, so leaving it empty costs nothing.

Each entry carries the workspace-ledger item tracking the engine fix, or `null` where the difference is one of vantage rather than a defect — the file-leaf and unknown-empty entries are the descriptor's vantage, and the object-native one is a consequence of the optional-field entry rather than its own bug.

The templates are held to a second bar that is easy to lose sight of behind the byte parity: they must still **run**. A template is what someone fills in and hands back, so every slot of it has to survive the runtime's own input shaper. That is what separates a deliberate divergence from a projection bug — the file-leaf entry pins `{"url": ...}` because the shaper accepts exactly that wrapper, and the object-native entry keeps the envelope for the same reason. Where a class is retired, the corpus is regenerated and its entry disappears from the manifest on its own.

That bar is now measured rather than argued. The generator hands every projected template, in both shapes, to `InputShaper.shape` at capture time and writes the verdict into the manifest's `unshapeable` array — one entry per refused `(pipe_ref, shape)`, carrying the error's class name and the ledger item whose fix retires it — refusing to write a capture that holds a refusal nobody declared, or that declares one which has started shaping. Every entry this capture carries is blocked on `L-260830-191719`, the nested-list slot the shaper cannot take back.

The array is a statement the corpus makes about itself, and this repo cannot re-derive it: there is no input shaper on this side of the mirror, so the verdict is taken on the generator's authority. What `TestTheUnshapeableRecord` checks is that the record stays about *this* corpus — every entry keyed to a pipe and shape the manifest holds, one entry per key, each naming a real error type and a well-formed ledger id, and the array an exception list rather than the whole corpus. A consumer harness may read the entries to know which pinned templates it must not expect to run; nothing requires it to.

## Known engine drift in the descriptor and contract payloads

A different question from the template divergences above: this is about whether the two captured payloads match the pages the models mirror. Where the fixture and a page disagree, the page wins: the models mirror the pages, and the fixture is kept as captured. **This capture has no known divergence.** The three the previous one carried were all fixed in the engine before it was taken, and each is asserted positively by the suite now rather than merely absent:

- A `list`'s `item` carries no `name` member (`L-260826-0ed8dd`) — `test_every_node_but_a_list_item_is_named` walks every node of the capture and holds both halves.
- Description-only concepts (`Essay`, `Badge`, `PlainNote`, `StringNote`) no longer carry a fabricated `refines: ["native.Text"]` (`L-260826-0ed8dd`).
- `native.Date` and `native.Html` land on the page's `object` arm with fields derived from the pinned definitions, rather than as `date` / `prose` scalars (`L-260826-236839`), and `native.Html`'s `css_class` is optional as MTHDS v0.9.0 states it (`L-260826-3cea94`) — `test_a_pinned_native_structure_lands_on_the_object_arm` holds both.

## The `json_schema` projection is the producer's, not the page's

`pipe_io_contracts.json` carries pydantic's auto-generated titles — `"title": "Inner Html"`, `"title": "ImageContent"` — because the engine projects each slot's schema from its runtime pydantic content class. That is **not** a divergence, and it should not be re-filed as one:

- `docs/spec/pipe-io-contracts.md:124` says outright that a producer MAY carry the concept's identity or description inside the schema document as `title`, and that consumers MUST NOT depend on it — `concept_ref` is the authoritative statement.
- `:44` leaves the `json_schema` slot's content unfixed beyond the two rules in "The input schema"; the projection follows the concept model and the producer's chosen dialect.

What matters is that the projection agrees with the standard's pinned definitions, and as of `pipelex` #1155 that is machine-checked in a chain rather than assumed: `tests/unit/pipelex/codegen/test_native_expansion.py` holds each runtime content class to its pinned blueprint, and `tests/unit/pipelex/core/concepts/test_pinned_natives_vs_standard.py` holds the pinned blueprints to `mthds/docs/spec/native-concepts.md`, read unpinned at the standard's default branch by a CI job of its own.
