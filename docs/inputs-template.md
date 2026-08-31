# The inputs-template projection

A pipe's **inputs template** is the fill-in document somebody hands back as that pipe's inputs: a person at a form, or an agent preparing a run. `mthds.protocol.inputs_template` projects one from the [input-form descriptor](https://mthds.ai/spec/input-form-descriptor/) the standard already defines, so a client holding the descriptor can offer a template for a method it does **not** have on disk — which is exactly what a `method_ref` address or a hosted `method_id` names.

```python
from mthds.protocol.input_form import InputForm
from mthds.protocol.inputs_template import InputsTemplateFormat, render_inputs_template

descriptor = input_form["legal.summarize_contract"]  # one entry of the `input_form` artifact

as_toml = render_inputs_template(descriptor=descriptor, explicit=False, output_format=InputsTemplateFormat.TOML)
as_json = render_inputs_template(descriptor=descriptor, explicit=True, output_format=InputsTemplateFormat.JSON)
```

`project_inputs_template(descriptor=…, explicit=…)` returns the same template as a `dict` when you want the structure rather than a serialization. A pipe declaring no inputs projects to `{}` — an empty form is a valid form, and the projection renders it rather than refusing it.

## Two shapes

The difference between them is what a runtime's input shaper can take back:

- **compact** (`explicit=False`) — the light form a smart-inputs run accepts directly: a bare string for a text slot, a bare URL for a file-ish one, the content mapping for a structured one. A slot whose bare value the shaper could *not* rebuild keeps its `{concept, content}` envelope, because a template that does not run is not a template.
- **explicit** (`explicit=True`) — every slot keeps the ceremonial `{concept, content}` envelope, whatever it holds.

In TOML the compact shape carries a `# concept: …` line above each key, in io-ref notation — `native.Text`, `native.Text!`, `native.Text?`, `legal.Clause[]`, `legal.Clause[2]`. That notation is rebuilt from the descriptor alone by `format_slot_signature`, from the concept reference, the `list` node's own `item_count` and the authored presence marker; JSON has no comments, which is one reason the explicit shape stays around.

## What it walks, and what it therefore differs from

**The projection walks the descriptor, never a runtime content class.** That is the whole difference from the reference engine's own renderer in `pipelex`: the engine reflects the pydantic class each input resolves to, so its template states what the *runtime* holds, where this states what the *method declares*. Three rules follow from having the descriptor and nothing else, and they are this projection's own:

- an `enum` takes its **first** choice, never a random one — these bytes are committed;
- an `unknown` node renders as an empty mapping, the escape hatch's only honest value;
- a fixed `Concept[N]` slot renders **N** elements.

Every difference between the two renderers is recorded, with worked sites, in `tests/fixtures/protocol/inputs_template/manifest.json`, and its README explains each one.

Every `match` over `FieldKind` in the module is exhaustive and carries no default arm, deliberately: a kind added to the standard breaks the module where the rule for it has to be written, rather than falling through to a guess.

## Byte parity with the TypeScript twin

The bar this is held to is **byte identity with the projection in the `mthds` npm package**, across every kind of the closed vocabulary, both shapes and both formats. That is what stops the JS/Python asymmetry the build-route retirement removed from being rebuilt one layer up, and it is measured rather than intended: `tests/fixtures/protocol/inputs_template/` holds the expected bytes, both repos commit the tree identically, `conformance` compares the two mirrors file by file, and each side runs the twin of `tests/unit/test_inputs_template_projection.py`.

TOML is the half where that is not free, so the TOML text comes from `mthds.protocol.toml_emitter` rather than from a TOML library. `smol-toml` on the TypeScript side emits no comments at all, and a library's layout choices are its own to change in a patch release, in one language and not the other. The emitter is a few dozen lines stating the layout outright:

- a table states its scalar members first, in authored order, then its table members, also in authored order — TOML cannot interleave a section with the keys of its parent, so the split is forced and the order within each half is the choice;
- a table whose members are **all** tables states no header of its own, and its children carry the whole dotted path (`[page_in.content.text_and_images]`); an empty table is not one of those, since it has no child to carry its path;
- a non-empty list of mappings is an array of tables, one `[[dotted.path]]` header per element, and an element always states its header;
- exactly one blank line before every header, and none before the first line of the document;
- TOML has no null, so a `None` becomes an empty string rather than being dropped — the key stays visible to whoever is filling the template in.

`tests/unit/test_toml_emitter.py` states each of those rules as bytes, on its own, so the rule that broke is named by the test that failed — and so the TypeScript twin has an executable statement of the contract rather than a paragraph of prose.

One caveat worth knowing when the corpus is regenerated: the generator in `pipelex` still renders the corpus TOML through `tomlkit`, which does **not** apply the blank-line rule uniformly and reorders a mapping's members when that mapping is an element of a list. The committed corpus exercises none of those shapes — the two agree on every byte of it today — but a bundle added to it could reach them, and the regenerated bytes would then carry the inconsistency and fail both projections at once. `L-260831-4031a7` tracks moving the generator onto this contract.
