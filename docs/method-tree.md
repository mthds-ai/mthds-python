# The method tree

A method is the tree of files under its root: its bundles, and beside them the Python modules, templates, images, `requirements.txt` and `README.md` that travel with it. `mthds.method_tree` implements the standard's [method tree](https://mthds.ai/latest/spec/method-tree/): it lists a tree from a directory or a lone bundle, computes its digest, reads a tree sent as a map of file entries, resolves the file references written inside it, and locates a `PipeFunc`'s module in it.

```python
from pathlib import Path

from mthds.method_tree.lister import list_method_tree
from mthds.method_tree.models import TreeLimits
from mthds.method_tree.python_modules import locate_function
from mthds.method_tree.references import resolve_reference
from mthds.method_tree.vocabulary import ReferenceContext

tree = list_method_tree(Path("letters"), limits=TreeLimits(max_files=2000, max_total_bytes=50_000_000))
tree.digest  # "sha256:…", the same on every machine for the same files
tree.tree_paths  # ["METHODS.toml", "main.mthds", "templates/letter.html", …]

resolve_reference("../shared/logo.png", holder="templates/letter.html", context=ReferenceContext.URL, tree=tree)
# "shared/logo.png"

locate_function("funcs.text_utils.shout", tree=tree)
# FunctionLocation(module="funcs/text_utils.py", function="shout")
```

## Listing a tree

`list_method_tree(handed_over, limits=…)` takes what a caller hands over, a directory or a `.mthds` file named alone.

- **The root** is the nearest directory at or above it holding `METHODS.toml`, found by Manifest Discovery, which stops at a directory holding an entry named `.git` of any kind, a submodule's or a worktree's `.git` file and a symbolic link included. A directory with no manifest at or above it is its own root, and a `.mthds` file with none is a tree of that one file: nothing beside it is read, not even a `.gitignore` file, and a reference from it to another file is refused. `list_method_tree_at_root(root)` skips the discovery, for a tree rooted where its caller says, such as a fetched package.
- **The membership rule** keeps out a path segment starting with a dot; a `__pycache__` or `node_modules` directory; a directory holding a `pyvenv.cfg` regular file or symbolic link, the root included; a directory below the root holding a `.git` entry of any kind or its own `METHODS.toml`; a run's inputs file, a regular file or a symbolic link, never followed, named exactly `inputs.json` or `inputs.toml` at any depth; and what the tree's own `.gitignore` files and the manifest's `[package] exclude` patterns ignore. An excluded directory is pruned and never visited, so nothing inside it is ever an error. A listing records the rule that kept each entry out, `run_inputs` for a run's inputs file, and a reference refused as not in the tree names it in `excluded_by`.
- **Refusals** are `MethodTreeRefusedError`, whose `refusal` carries the stable `code` a consumer branches on, the `names` it cites, and for a reference what it `resolved` to and which rule kept that file out. The codes are the conformance corpus's: `symbolic_link`, `special_file`, `invalid_tree_path`, `normalization_collision`, `path_collision`, `empty_tree`, `lone_file_excluded` and `gitignore_not_utf8` for a listing. The wording of a message is not a contract.
- **A directory whose own tree is empty** is refused as `empty_tree` with `EmptyMethodTreeError`, a `MethodTreeRefusedError` that also carries what the listing kept out: its `root`, and `excluded_files`, `excluded_directories` and `raw_paths` as a listed tree holds them. A caller that lists a directory to find the packages and repositories nested in it, as a runtime does for a library directory, reads them from `excluded_directories`, whose nested package or nested repository names its own directory, whether or not the directory's own tree holds a file. The lister never returns an empty `MethodTree`, since the standard holds that a tree has at least one file, and the refusal's record stays the corpus's `{"code": "empty_tree", "names": []}`. A root that is itself a virtual environment is never walked, so its refusal keeps nothing out below it.

```python
from mthds.method_tree.exceptions import EmptyMethodTreeError

try:
    trees = [list_method_tree(library_dir)]
    excluded_directories = trees[0].excluded_directories
except EmptyMethodTreeError as exc:
    trees = []
    excluded_directories = exc.excluded_directories  # {"invoicing": TreeExclusion(rule=NESTED_PACKAGE, directory="invoicing")}
```
- **A run's inputs file stays out of every tree.** A tool that runs a method from its directory may read the run's inputs from an `inputs.json` or `inputs.toml` file there, which holds one run's real data, so the membership rule keeps either file out wherever it lies, and sending or saving the method never carries that data along. The names match byte for byte, so `Inputs.json`, `inputs.jsonc` and `examples/invoice-inputs.json` are ordinary members, which is how a method ships example inputs for people and agents to read. A directory of either name excludes nothing, and a named pipe of either name is no run's inputs file, so it is refused as `special_file`.
- **Every special name is matched exactly**, letter case included: `methods.toml` is no manifest and `.GIT` is no repository, even on a case-insensitive file system, because a directory's entries are listed and compared rather than trusted by name. Manifest Discovery asks each ancestor for the special names first and lists it only when one answers, so an ancestor that may be searched but not read stands in the way only when it holds such an entry.
- **A `.mthds` file named alone is listed under the names the file system holds**, never the caller's spelling: on a case-insensitive file system, `Templates/Main.mthds` finds `templates/main.mthds`, and the tree path and digest are those of `templates/main.mthds`. When a directory holds several names equal to the one asked once case-folded, and none exactly, the listing is refused as a `TreeSourceError`.
- **A symbolic link** inside the tree is refused, never followed. A link handed over that names a directory is followed to it, since that is the directory the caller meant; a `.mthds` file named alone is never followed, so a link named so is refused like any other.

### Git's patterns, ported rather than borrowed

The `.gitignore` files and the `exclude` patterns are matched by a port of the pieces of git that define them, `dir.c` (how a file splits into patterns, and how a pattern is anchored, negated and given precedence) and `wildmatch.c` (the glob matcher), in `mthds/method_tree/gitignore.py`. Git matches the bytes of a path, so `?` matches one byte of a UTF-8 name rather than one character, and it takes a few shortcuts whose results a clean reimplementation does not share, such as comparing a pattern's literal prefix before globbing the rest. A gitignore library working on characters, such as `pathspec`, differs from git on those points, so this package depends on no such library. A pattern is normalized to NFC before it is matched, a `.gitignore` file is read as UTF-8 with a leading byte order mark skipped, and one whose bytes are not UTF-8 is refused as `gitignore_not_utf8`, naming its path.

### Limits

The standard bounds a tree path's length and nothing else, so a file's size, a tree's file count and its total size are the caller's policy. `TreeLimits(max_files=…, max_total_bytes=…, max_file_bytes=…)` makes the walk count files and sum their sizes from `stat` as it goes and stop at the first limit passed, before any file is hashed, raising `TreeLimitError` with the root, the limit and the count reached. A directory handed over by mistake is refused in moments rather than read in full.

## The tree digest

`tree.digest` is `sha256:` followed by the SHA-256 of the tree's listing, one `<sha256>  <path>` line per file sorted byte for byte on the path, which is what `LC_ALL=C sort` and `sha256sum` print, so anyone can recompute it with coreutils alone. `mthds.method_tree.digest` computes it from a listing or from bytes at hand.

## A tree in transit: the file entry

A tree travels as a JSON object mapping each tree path to a file entry: a string holding the file's text, `{"base64": "…"}` in canonical padded Base64, or `{"sha256": "…", "size": …}` naming bytes the receiver already holds. `encode_file_map(contents, held_by_receiver=…)` writes one as a `dict[str, FileEntry]`, each entry a `str`, a `Base64FileEntry` or a `HashFileEntry`, which `pydantic_core.to_json` writes in its wire form; `MethodFiles`, a read-only map of the same entries, is the type of the `files` a protocol client sends (see [Sending a method](./runners.md#sending-a-method-files-inline-or-by-hash) for how `MthdsAPIClient` builds one from a listed tree, inline or by hash). `read_file_map(document, blob_store=…)` reads one from its JSON text as a receiver does, refusing a key given twice in the map or inside an entry object, a key that is not a tree path or that the membership rule could never admit, such as one whose last segment is `inputs.json` or `inputs.toml`, refused as `excluded_name`, colliding keys, a malformed entry, and every hash entry whose bytes the blob store lacks. It reads the text rather than a decoded dictionary because a key given twice and a `size` written as `13.0` are only visible there. Text that is not JSON, holds `NaN` or `Infinity`, an integer longer than Python converts, or nesting deeper than `MAX_JSON_DEPTH` levels is a `TreeSourceError`, never a bare `ValueError` or `RecursionError`. That bound is the receiver's own, set below the depth at which any supported Python's decoder gives up, since that depth varies from one version to the next and Python 3.14's decoder has none, so a document gets the same answer on every supported Python. `Base64FileEntry` and `HashFileEntry` are the strict pydantic models of the object forms.

## A tree written out

`write_tree(tree, destination=…)` writes a listed tree's files as a new directory, each at its tree path with its permission bits and nothing else. It writes into a hidden sibling directory renamed to `destination` once every file is written, so an interrupted write never leaves a partial tree under that name, and it refuses a `destination` that already holds files rather than mixing two trees. `read_written_tree(directory)` reads such a copy back as written: every regular file is a file of the tree, and the membership rule is not applied again. A copy holding two spellings of one name equal in NFC is refused as `normalization_collision`, as a listing is. The package cache stores a fetched package this way, so its cached copy is its tree; storing over a cached copy moves the old one aside in one rename and deletes it before the new one is written, and until a store completes, `is_cached` answers false.

The cache's layout is versioned: a package lives at `{cache_root}/v2/{address}/{version}/`, where `CACHE_LAYOUT` in `mthds/package/package_cache.py` names the version. Copies written before standard `7.0.0` sit at `{cache_root}/{address}/{version}/` and hold the whole clone minus `.git/`, which is not the package's tree, so they are never read: a package found only there is fetched again, and those copies can be deleted.

## Resolving a file reference

A file reference is a path written in a file of the tree, its holder, that names another file of the same tree: a bundle field naming a file (path context) or a relative URL in a template, such as an image's `src` (URL context). `resolve_reference(reference, holder=…, context=…, tree=…)` resolves one by the standard's [resolution steps](https://mthds.ai/latest/spec/method-tree/#file-references), against the directory of the holder, and returns the tree path it names. A URL naming a scheme, holding an authority or with no path is no file reference: the call returns None and the caller leaves the URL exactly as written. A refused reference raises `MethodTreeRefusedError`, whose `refusal.code` is that of the first step that fails: `reference_invalid`, `reference_not_a_tree_path`, `reference_leaves_tree`, `reference_not_in_tree` or, in the one-file tree of a bundle named alone, `reference_in_one_file_tree`. A refusal as not in the tree names the path the reference resolved to, `.` for the root, and, for a tree listed from a directory, the rule that kept the file out. Whether a reference names a file is decided by a lookup in the tree's set of paths, and the file it names is never opened.

```python
from mthds.method_tree.references import resolve_reference_in_paths
from mthds.method_tree.vocabulary import ReferenceContext

tree_paths = frozenset({"main.mthds", "templates/letter.html", "shared/logo.png"})

resolve_reference_in_paths("../shared/logo.png", holder="templates/letter.html", context=ReferenceContext.URL, tree_paths=tree_paths)
# "shared/logo.png"
resolve_reference_in_paths("shared/logo.png", holder=None, context=ReferenceContext.PATH, tree_paths=tree_paths)
# "shared/logo.png", resolved from the root
```

`resolve_reference_in_paths(reference, holder=…, context=…, tree_paths=…, is_one_file_tree=…)` runs the same steps in a set of tree paths rather than a `MethodTree`, for a runtime that holds a tree's listing and nothing else of where it came from, such as one reading a method's files from a store that keys them by hash. Its `holder` may be None, for a reference written in no file of the tree, such as one in a bundle sent as text beside the files of its tree: it resolves from the root, exactly as a reference written in a file at the root does. `is_one_file_tree` says the paths are those of the one-file tree of a `.mthds` file named alone, so that a reference reaching for another file is refused as `reference_in_one_file_tree` with the advice to hand over the method's directory. A set of paths records no membership rule, so a refusal as not in the tree names none. The two functions share one implementation of the steps, and `resolve_reference` adds only the rule that kept a file out. In both, a holder that is not one of the tree's paths raises `ValueError`, a caller's mistake rather than a refusal.

Three steps are public on their own, for a runtime that takes a reference apart itself:

- `url_path_of(reference)` is step 1 in URL context: the URL's path, what is left once its fragment and then its query are dropped. Tabs and line breaks are kept, so that the result check can refuse them.
- `percent_decode_url_path(url_path)` is step 3: it splits the path at each `/`, then percent-decodes each segment once as UTF-8, so `%2E%2E` decodes to `..` while `%2F` never becomes a separator and `%252F` decodes to `%2F`. It refuses as `reference_invalid`, naming the path, a `%` not followed by two hexadecimal digits, a backslash written or decoded, bytes that are not UTF-8, and an escape that decodes to a `/` or to a control character. It leaves a leading `/` for the form check of step 2 and a control character written as is for the result check of step 6, and it does not normalize to NFC, which is step 4.
- `lexical_join(holder=…, path=…)` is step 5: the path joined to the holder's directory, the root when `holder` is None, each `.` dropped and each `..` removing the segment before it, or None when a `..` climbs above the root.

## The lock records tree digests

A `methods.lock` entry records the package's `digest`, the tree digest of its cached copy read back as written, which `verify_lock_file` recomputes and compares. A lock written before standard `7.0.0` records a `hash` instead, from an algorithm that concatenated paths and contents with no separator, so two different directories could share one hash; `parse_lock_file` refuses such an entry, saying that running `lock` regenerates it, and never verifies the old hash.

## The conformance corpus

The shared corpus of the `conformance` repository (`conformance/specs/mthds-method-tree.md`) is the contract every implementation agrees on byte for byte. This package runs every part of it:

- **the tree cases**, each materialized in a fresh directory, listed, and checked for its root, entry, files, hashes, sizes and digest or its refusal, then for each reference it resolves and each function name it locates;
- **the map cases**, read by `read_file_map` against a blob store holding the case's blobs;
- **the path cases**, checked by `is_tree_path` and `check_tree_path`.

A tree case needing a capability the host's file system lacks is skipped, never passed: on macOS, whose default file system folds letter case and Unicode normalization, the cases needing `case_sensitive_names` and `normalization_sensitive_names` are skipped, and Linux runs them all. Point pytest at a case-sensitive volume (`--basetemp=<directory on it>`) to run the letter-case cases on a Mac.

The corpus is vendored byte for byte as `tests/fixtures/method_tree_corpus.json`, never edited by hand, beside a sidecar, `method_tree_corpus.source.json`, recording the conformance commit it came from and the SHA-256 of the file, which `tests/unit/method_tree/test_method_tree_corpus_parity.py` checks the copy against. To refresh it, run `make vendor-tree-corpus CONFORMANCE=<path to a conformance checkout>`, which copies the corpus committed at that checkout's `HEAD` and rewrites the sidecar. A case this package disagrees with is changed in `conformance`, or reported against the standard, never patched here.

## Choices the standard leaves open

- A normalization collision is judged among the names on the way to a kept file, so two spellings of one name inside an excluded directory, or of an empty directory, are no error.
- A reference refused as not in the tree names the rule that kept its file out only when a file, a link or another non-directory entry is really there: one the listing visited carries its rule, and one inside a pruned directory is looked up on disk, comparing names in NFC, before the directory's rule is given.
- A file that is not a `.mthds` bundle, handed over alone, is a `TreeSourceError` rather than a refusal of the standard's, which defines only a bundle named alone.
- A map of file entries holding an integer longer than Python converts, such as a `size` of thousands of digits, is a `TreeSourceError` rather than a `malformed_entry` or `missing_blob` refusal, since the text cannot be decoded at all.
- A `METHODS.toml` at a package's root that is a symbolic link or another entry that is not a regular file is refused rather than taken for the absence of a manifest.
