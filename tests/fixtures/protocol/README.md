# Protocol parity fixtures

`input_form.json` and `pipe_io_contracts.json` are one real payload pair produced by the reference engine's own derivation, committed here **byte-for-byte** and committed identically in `mthds-js`. That identity is the Stage 2.3 parity of the input-form program (`wip/input-form/plan.md` at the workspace root): the same bytes parse strictly against `mthds.protocol` in Python and type-check against `mthds/protocol` in TypeScript, so the two clients mirror each other by measurement rather than by intent. Do not edit these files — a change is a new capture, landed in both repos.

## Provenance

- Bundles: `pipelex/tests/data/input_semantics/hinted_bundle.mthds` and `pipelex/tests/data/input_semantics/probe_bundle.mthds`.
- Command, run from the `pipelex` checkout: `pipelex-dev trace-input-semantics tests/data/input_semantics/hinted_bundle.mthds tests/data/input_semantics/probe_bundle.mthds`. The trace's hop-5 outputs, `hop5_input_form.json` and `hop5_pipe_io_contracts.json`, are these two files.
- Engine: `pipelex` 0.53.0 (its `pyproject.toml` version) at checkout `bc97dad0b`.
- Pages the models mirror: `mthds` v0.9.0, `docs/spec/pipe-io-contracts.md` and `docs/spec/input-form-descriptor.md` (the `hints` slot's shape from `docs/spec/intent-hints.md`).

## Known engine drift

Where the fixture and a page disagree, the page wins: the models mirror the pages, and the fixture is kept as captured. Each divergence below is a difference in content, not in shape, which is why the fixture still parses strictly and round-trips. All three are tracked in the workspace ledger against `pipelex`:

- `L-260826-236839` — `native.Date` (pipe `input_semantics_probe.probe_native_inputs`, slot `date_in`) is emitted as `kind: "date"` and `native.Html` (slot `html_in`) as `kind: "prose"`; the page's ordered kind-assignment table puts both on the `object` arm.
- `L-260826-0ed8dd` — description-only concepts (`Essay`, `Badge`, `PlainNote`, `StringNote`) carry a fabricated `refines: ["native.Text"]`, which the page says a producer must never invent; and every `list` node's `item` carries a `name` member, where the page says an item carries none at all.
