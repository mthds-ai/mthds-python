# The manifest

`mthds.package.manifest` reads and writes a package's `METHODS.toml`, as the standard's [manifest format](https://mthds.ai/latest/spec/manifest-format/) defines it. That page is the reference for what each key means; this one says what this package does with them.

`parse_methods_toml` returns a validated `MethodsManifest`. It raises `ManifestParseError` when the text is not valid TOML and `ManifestValidationError` when the manifest breaks a rule of the format, a key or a section the format does not define included, since the model is closed. `serialize_manifest_to_toml` writes a manifest back, leaving out an optional key that holds nothing.

Two keys have a page of their own here: `mthds_version` in [versioning](./versioning.md), and `exclude` in [the method tree](./method-tree.md).

## Categories

```toml
[package]
address     = "github.com/acme/legal-tools"
version     = "0.3.0"
description = "Legal document analysis"
categories  = ["legal", "customer-support"]
```

```python
from mthds.package.manifest.parser import parse_methods_toml

manifest = parse_methods_toml(methods_toml_text)
manifest.categories  # ["legal", "customer-support"]
```

`categories` declares the categories a method belongs to, so that a catalog can offer it to a person browsing by category.

- **An entry must match the standard's pattern as a whole**, `^[a-z0-9]+(-[a-z0-9]+)*$`: runs of lowercase ASCII letters and digits, joined by single hyphens. An entry that does not, such as `Legal`, `customer_support` or `-legal`, refuses the manifest with `ManifestValidationError`, and so does a value that is not an array of strings. `is_valid_category`, in `mthds.package.manifest.schema`, checks one value.
- **The values belong to each catalog.** The standard lists none, so this package has no list either: any value that matches the pattern is accepted, and deciding which ones mean something is the catalog's work.
- **Repeats and order mean nothing and stay as written.** `["legal", "legal"]` is accepted and reads back as that same list, so the package neither sorts nor removes anything, and a reader that needs a set makes one. A manifest rewritten with `serialize_manifest_to_toml` carries the entries as they were.
- **An empty array declares no category**, as leaving the key out does. Both read as `[]`, and neither is written back.
