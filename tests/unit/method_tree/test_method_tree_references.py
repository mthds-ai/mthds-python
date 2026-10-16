import re

import pytest

from mthds.method_tree.exceptions import MethodTreeRefusedError
from mthds.method_tree.models import MethodTree, TreeFile
from mthds.method_tree.references import lexical_join, percent_decode_url_path, resolve_reference, resolve_reference_in_paths, url_path_of
from mthds.method_tree.vocabulary import ReferenceContext, TreeRefusalCode
from tests.unit.method_tree.test_data import ReferenceTree


def _outcome_in_paths(reference: str, *, holder: str | None, context: ReferenceContext) -> str | tuple[TreeRefusalCode, str | None] | None:
    """What resolving in the reference tree answers: the tree path, None for no file reference, or the refusal's code and resolved path."""
    try:
        return resolve_reference_in_paths(reference, holder=holder, context=context, tree_paths=ReferenceTree.TREE_PATHS)
    except MethodTreeRefusedError as exc:
        return exc.refusal.code, exc.refusal.resolved


class TestMethodTreeReferences:
    @pytest.mark.parametrize(
        ("reference", "holder", "context", "expected"),
        [
            pytest.param("templates/letter.html", None, ReferenceContext.PATH, "templates/letter.html", id="root holder, path"),
            pytest.param("./shared/logo.png", None, ReferenceContext.PATH, "shared/logo.png", id="root holder, path with a dot segment"),
            pytest.param("templates/partials/../logo.png", None, ReferenceContext.PATH, "templates/logo.png", id="root holder, path climbing back"),
            pytest.param("assets/100%.txt", None, ReferenceContext.PATH, "assets/100%.txt", id="root holder, path never percent-decoded"),
            pytest.param("assets/cafe\u0301.txt", None, ReferenceContext.PATH, "assets/caf\u00e9.txt", id="root holder, path normalized to NFC"),
            pytest.param("templates/logo.png?v=2#top", None, ReferenceContext.URL, "templates/logo.png", id="root holder, URL query and fragment"),
            pytest.param("assets/100%25.txt", None, ReferenceContext.URL, "assets/100%.txt", id="root holder, URL percent-decoded"),
            pytest.param("assets/my%20logo.png", None, ReferenceContext.URL, "assets/my logo.png", id="root holder, URL encoded space"),
            pytest.param("logo.png", ReferenceTree.TEMPLATE, ReferenceContext.PATH, "templates/logo.png", id="nested holder, path beside it"),
            pytest.param("../shared/logo.png", ReferenceTree.TEMPLATE, ReferenceContext.PATH, "shared/logo.png", id="nested holder, path climbing"),
            pytest.param("../shared/logo.png", ReferenceTree.TEMPLATE, ReferenceContext.URL, "shared/logo.png", id="nested holder, URL climbing"),
            pytest.param(
                "%2E%2E/shared/logo.png", ReferenceTree.TEMPLATE, ReferenceContext.URL, "shared/logo.png", id="nested holder, encoded dot-dot"
            ),
            pytest.param(
                "../assets/cafe%CC%81.txt", ReferenceTree.TEMPLATE, ReferenceContext.URL, "assets/caf\u00e9.txt", id="nested holder, decoded to NFC"
            ),
            pytest.param(
                "../../shared/logo.png", ReferenceTree.PARTIAL, ReferenceContext.URL, "shared/logo.png", id="deeper holder, URL climbing twice"
            ),
            pytest.param("main.mthds", ReferenceTree.BUNDLE, ReferenceContext.PATH, "main.mthds", id="holder at the root naming itself"),
        ],
    )
    def test_reference_resolves_from_its_holder_or_the_root(self, reference: str, holder: str | None, context: ReferenceContext, expected: str):
        """A reference resolves against its holder's directory, or the root when it has none, to a path of the set."""
        assert resolve_reference_in_paths(reference, holder=holder, context=context, tree_paths=ReferenceTree.TREE_PATHS) == expected

    @pytest.mark.parametrize("holder", [pytest.param(None, id="root holder"), pytest.param(ReferenceTree.TEMPLATE, id="nested holder")])
    @pytest.mark.parametrize(
        "reference",
        [
            pytest.param("https://cdn.example.com/logo.png", id="https"),
            pytest.param("data:image/png;base64,iVBORw0KGgo=", id="data"),
            pytest.param("mailto:someone@example.com", id="mailto"),
            pytest.param("//cdn.example.com/logo.png", id="authority"),
            pytest.param("#top", id="fragment"),
            pytest.param("?v=2", id="query"),
            pytest.param("", id="empty"),
        ],
    )
    def test_url_that_is_no_file_reference_is_left_as_written(self, reference: str, holder: str | None):
        """A URL with a scheme, an authority or no path names no file of the tree, whoever holds it."""
        assert resolve_reference_in_paths(reference, holder=holder, context=ReferenceContext.URL, tree_paths=ReferenceTree.TREE_PATHS) is None

    @pytest.mark.parametrize(
        ("reference", "holder", "context", "code", "resolved"),
        [
            pytest.param(
                "../logo.png", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_LEAVES_TREE, None, id="root holder, path climbing out"
            ),
            pytest.param("..", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_LEAVES_TREE, None, id="root holder, path dot-dot alone"),
            pytest.param(
                "templates/../../x.png",
                None,
                ReferenceContext.PATH,
                TreeRefusalCode.REFERENCE_LEAVES_TREE,
                None,
                id="root holder, path climbing back out",
            ),
            pytest.param("../logo.png", None, ReferenceContext.URL, TreeRefusalCode.REFERENCE_LEAVES_TREE, None, id="root holder, URL climbing out"),
            pytest.param(
                "%2E%2E/logo.png",
                None,
                ReferenceContext.URL,
                TreeRefusalCode.REFERENCE_LEAVES_TREE,
                None,
                id="root holder, encoded dot-dot climbing out",
            ),
            pytest.param(
                "../../logo.png",
                ReferenceTree.TEMPLATE,
                ReferenceContext.URL,
                TreeRefusalCode.REFERENCE_LEAVES_TREE,
                None,
                id="nested holder, URL climbing out",
            ),
            pytest.param(
                "../../../x.png",
                ReferenceTree.PARTIAL,
                ReferenceContext.PATH,
                TreeRefusalCode.REFERENCE_LEAVES_TREE,
                None,
                id="deeper holder, path climbing out",
            ),
            pytest.param("/etc/passwd", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_INVALID, None, id="absolute path"),
            pytest.param("/etc/passwd", None, ReferenceContext.URL, TreeRefusalCode.REFERENCE_INVALID, None, id="root-relative URL"),
            pytest.param("file:///etc/passwd", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_INVALID, None, id="scheme in path context"),
            pytest.param("C:/templates/logo.png", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_INVALID, None, id="drive letter"),
            pytest.param("..\\..\\x.png", ReferenceTree.TEMPLATE, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_INVALID, None, id="backslashes"),
            pytest.param(
                "..%2F..%2Fetc%2Fpasswd", ReferenceTree.TEMPLATE, ReferenceContext.URL, TreeRefusalCode.REFERENCE_INVALID, None, id="encoded slashes"
            ),
            pytest.param("..%5Cx.png", ReferenceTree.TEMPLATE, ReferenceContext.URL, TreeRefusalCode.REFERENCE_INVALID, None, id="encoded backslash"),
            pytest.param("", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_NOT_A_TREE_PATH, None, id="empty path"),
            pytest.param("templates/", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_NOT_A_TREE_PATH, "templates/", id="trailing slash"),
            pytest.param(
                "templates/a:b.png",
                None,
                ReferenceContext.URL,
                TreeRefusalCode.REFERENCE_NOT_A_TREE_PATH,
                "templates/a:b.png",
                id="colon in a segment",
            ),
            pytest.param(".", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_NOT_IN_TREE, ".", id="the root, as a path"),
            pytest.param("./", None, ReferenceContext.URL, TreeRefusalCode.REFERENCE_NOT_IN_TREE, ".", id="the root, as a URL"),
            pytest.param("..", ReferenceTree.TEMPLATE, ReferenceContext.URL, TreeRefusalCode.REFERENCE_NOT_IN_TREE, ".", id="the root, climbed to"),
            pytest.param("templates", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_NOT_IN_TREE, "templates", id="a directory"),
            pytest.param(
                "missing.png",
                ReferenceTree.TEMPLATE,
                ReferenceContext.URL,
                TreeRefusalCode.REFERENCE_NOT_IN_TREE,
                "templates/missing.png",
                id="absent",
            ),
            pytest.param(".env", None, ReferenceContext.PATH, TreeRefusalCode.REFERENCE_NOT_IN_TREE, ".env", id="a file no listing names"),
        ],
    )
    def test_refused_reference_names_its_step(
        self, reference: str, holder: str | None, context: ReferenceContext, code: TreeRefusalCode, resolved: str | None
    ):
        """A reference the standard refuses, an escape from the tree among them, is refused by the first step that fails."""
        with pytest.raises(MethodTreeRefusedError) as refused:
            resolve_reference_in_paths(reference, holder=holder, context=context, tree_paths=ReferenceTree.TREE_PATHS)
        assert refused.value.refusal.code == code
        assert refused.value.refusal.names == [reference]
        assert refused.value.refusal.resolved == resolved
        assert refused.value.refusal.excluded_by is None
        assert refused.value.refusal.excluded_directory is None

    @pytest.mark.parametrize(
        ("holder", "where"),
        [
            pytest.param(None, "written at the root of its tree", id="root holder"),
            pytest.param(ReferenceTree.TEMPLATE, "in 'templates/letter.html'", id="nested holder"),
        ],
    )
    def test_refusal_names_where_the_reference_is_written(self, holder: str | None, where: str):
        """A refusal names the reference's holder, or says it was written at the root."""
        with pytest.raises(MethodTreeRefusedError) as refused:
            resolve_reference_in_paths("../../x.png", holder=holder, context=ReferenceContext.URL, tree_paths=ReferenceTree.TREE_PATHS)
        assert refused.value.message == f"The file reference '../../x.png' {where} climbs above the root of its method tree."

    @pytest.mark.parametrize("context", [pytest.param(ReferenceContext.PATH, id="path"), pytest.param(ReferenceContext.URL, id="url")])
    @pytest.mark.parametrize(
        "reference",
        [
            "templates/logo.png",
            "./templates/./logo.png",
            "templates/partials/../logo.png",
            "assets/100%25.txt",
            "assets/my logo.png",
            "../logo.png",
            "templates/../..",
            ".",
            "./",
            "templates//logo.png",
            "templates//../logo.png",
            "templates/logo.png/.",
            "missing.png",
            "/logo.png",
            "%2E%2E",
            "templates%2Flogo.png",
            "logo%zz.png",
            "templates/logo\t.png",
            "",
            "https://example.com/logo.png",
        ],
    )
    def test_root_holder_resolves_as_a_file_at_the_root(self, reference: str, context: ReferenceContext):
        """With no holder, a reference resolves as one written in a file at the root, whatever it answers."""
        assert _outcome_in_paths(reference, holder=None, context=context) == _outcome_in_paths(
            reference, holder=ReferenceTree.BUNDLE, context=context
        )

    @pytest.mark.parametrize("holder", [pytest.param(ReferenceTree.LONE_BUNDLE, id="the lone bundle"), pytest.param(None, id="root holder")])
    @pytest.mark.parametrize(
        ("reference", "is_one_file_tree", "expected", "advised"),
        [
            pytest.param("greet.mthds", True, "greet.mthds", False, id="the lone file itself"),
            pytest.param("README.md", True, TreeRefusalCode.REFERENCE_IN_ONE_FILE_TREE, True, id="a file beside it, one-file tree"),
            pytest.param("README.md", False, TreeRefusalCode.REFERENCE_NOT_IN_TREE, False, id="a file beside it, tree of one file"),
            pytest.param("./", True, TreeRefusalCode.REFERENCE_IN_ONE_FILE_TREE, True, id="the root, one-file tree"),
            pytest.param("../notes/README.md", True, TreeRefusalCode.REFERENCE_LEAVES_TREE, False, id="climbing out first"),
            pytest.param("assets//logo.png", True, TreeRefusalCode.REFERENCE_NOT_A_TREE_PATH, False, id="no tree path first"),
        ],
    )
    def test_one_file_tree_refuses_a_file_beside_its_bundle(
        self, reference: str, is_one_file_tree: bool, expected: str | TreeRefusalCode, advised: bool, holder: str | None
    ):
        """In the one-file tree of a bundle named alone, a reference reaching for another file gets the one-file advice, after the earlier steps."""
        tree_paths = frozenset({ReferenceTree.LONE_BUNDLE})
        outcome: str | TreeRefusalCode | None
        message = ""
        try:
            outcome = resolve_reference_in_paths(
                reference, holder=holder, context=ReferenceContext.PATH, tree_paths=tree_paths, is_one_file_tree=is_one_file_tree
            )
        except MethodTreeRefusedError as exc:
            outcome = exc.refusal.code
            message = exc.message
        assert outcome == expected
        assert ("Hand over the method's directory instead." in message) is advised

    def test_holder_must_be_a_file_of_the_tree(self):
        """A holder the set of paths does not name is a caller's error, not a refusal, for either entry point."""
        with pytest.raises(ValueError, match=re.escape("'templates/other.html' is not a file of the tree")):
            resolve_reference_in_paths("logo.png", holder="templates/other.html", context=ReferenceContext.URL, tree_paths=ReferenceTree.TREE_PATHS)

    @pytest.mark.parametrize(
        ("reference", "expected"),
        [
            pytest.param("logo.png?v=2#top", "logo.png", id="query and fragment"),
            pytest.param("logo.png#a?b", "logo.png", id="question mark inside the fragment"),
            pytest.param("logo.png?a#b", "logo.png", id="hash inside the query"),
            pytest.param("logo\t.png?v=2", "logo\t.png", id="tab kept"),
            pytest.param("?v=2", "", id="no path"),
            pytest.param("https://cdn.example.com/a.png?v=1", "https://cdn.example.com/a.png", id="absolute URL taken as written"),
        ],
    )
    def test_url_path_of_drops_the_fragment_then_the_query(self, reference: str, expected: str):
        """Step 1 in URL context keeps the path exactly as written, tabs and line breaks included."""
        assert url_path_of(reference) == expected

    @pytest.mark.parametrize(
        ("url_path", "expected"),
        [
            pytest.param("my%20logo.png", "my logo.png", id="encoded space"),
            pytest.param("100%25.txt", "100%.txt", id="encoded percent"),
            pytest.param("%252F", "%2F", id="decoded once only"),
            pytest.param("%2E%2E/x.png", "../x.png", id="encoded dots decoded, not resolved"),
            pytest.param("caf%C3%A9.txt", "caf\u00e9.txt", id="UTF-8 bytes"),
            pytest.param("%e2%82%ac", "\u20ac", id="lowercase hexadecimal"),
            pytest.param("cafe%CC%81.txt", "cafe\u0301.txt", id="not normalized to NFC"),
            pytest.param("what%3F/a%23b", "what?/a#b", id="encoded query and fragment marks"),
            pytest.param("a//b", "a//b", id="empty segment kept for the result check"),
            pytest.param("/abs", "/abs", id="leading slash kept for the form check"),
            pytest.param("a\tb", "a\tb", id="control character written as is kept for the result check"),
            pytest.param("", "", id="empty"),
        ],
    )
    def test_percent_decode_url_path_decodes_each_segment(self, url_path: str, expected: str):
        """Step 3 decodes each segment once, leaving a leading slash, an empty segment or a written control character to other steps."""
        assert percent_decode_url_path(url_path) == expected

    @pytest.mark.parametrize(
        "url_path",
        [
            pytest.param("a%2Fb", id="encoded slash"),
            pytest.param("a%2fb", id="encoded slash in lowercase"),
            pytest.param("logo%0A.png", id="encoded line feed"),
            pytest.param("logo%00.png", id="encoded NUL"),
            pytest.param("logo%7F.png", id="encoded DEL"),
            pytest.param("logo%C2%85.png", id="encoded next line, a C1 control"),
            pytest.param("logo%FF.png", id="not UTF-8"),
            pytest.param("caf%E9.txt", id="Latin-1"),
            pytest.param("%C0%AF", id="overlong encoding of a slash"),
            pytest.param("%ED%A0%80", id="encoded surrogate"),
            pytest.param("100%.png", id="bare percent"),
            pytest.param("logo%zz.png", id="non-hexadecimal escape"),
            pytest.param("logo.png%4", id="short escape"),
            pytest.param("ok/%", id="percent alone in the last segment"),
        ],
    )
    def test_percent_decode_url_path_refuses_what_step_three_refuses(self, url_path: str):
        """A malformed escape, bytes that are not UTF-8, or a decoded slash or control character is malformed."""
        with pytest.raises(MethodTreeRefusedError) as refused:
            percent_decode_url_path(url_path)
        assert refused.value.refusal.code == TreeRefusalCode.REFERENCE_INVALID
        assert refused.value.refusal.names == [url_path]

    @pytest.mark.parametrize(
        ("url_path", "explanation"),
        [
            pytest.param("a\\b", "holds a backslash.", id="backslash written as is"),
            pytest.param("a%5Cb", "percent-decodes to a '/', a backslash or a control character, which no segment may hold.", id="encoded backslash"),
            pytest.param(
                "a%5cb", "percent-decodes to a '/', a backslash or a control character, which no segment may hold.", id="encoded in lowercase"
            ),
        ],
    )
    def test_percent_decode_url_path_words_a_written_and_a_decoded_backslash_apart(self, url_path: str, explanation: str):
        """A backslash written as is and one an escape decodes to are both malformed, each refused in its own words."""
        with pytest.raises(MethodTreeRefusedError) as refused:
            percent_decode_url_path(url_path)
        assert refused.value.refusal.code == TreeRefusalCode.REFERENCE_INVALID
        assert refused.value.refusal.names == [url_path]
        assert refused.value.message == f"The URL path {url_path!r} {explanation}"

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            pytest.param("a/./b", ["a", "b"], id="dot dropped"),
            pytest.param("a/../b", ["b"], id="dot-dot removes the segment before it"),
            pytest.param("a/..", [], id="the root"),
            pytest.param("..", None, id="climbing out"),
            pytest.param("a//b", ["a", "", "b"], id="empty segment kept"),
        ],
    )
    def test_lexical_join_from_the_root(self, path: str, expected: list[str] | None):
        """With no holder, the join starts at the root, as it does from a file at the root."""
        assert lexical_join(holder=None, path=path) == expected
        assert lexical_join(holder=ReferenceTree.BUNDLE, path=path) == expected

    def test_resolve_reference_still_refuses_a_holder_outside_the_tree(self):
        """`resolve_reference` keeps its contract for a holder its tree does not hold."""
        tree = MethodTree(files=[TreeFile(path=ReferenceTree.TEMPLATE, sha256="0" * 64, size=0)], digest="sha256:" + "0" * 64)
        with pytest.raises(ValueError, match=re.escape("'templates/other.html' is not a file of the tree")):
            resolve_reference("logo.png", holder="templates/other.html", context=ReferenceContext.URL, tree=tree)
