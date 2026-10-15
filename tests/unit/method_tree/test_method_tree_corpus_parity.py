import hashlib
import json

from tests.unit.method_tree.test_data import MethodTreeCorpus


class TestMethodTreeCorpusParity:
    def test_vendored_bytes_match_the_sidecar(self):
        """The vendored corpus is byte for byte the file the sidecar records, so a hand edit or a partial re-vendor fails here."""
        sidecar = json.loads(MethodTreeCorpus.SIDECAR_PATH.read_text(encoding="utf-8"))
        assert sidecar["source_repository"] == "Pipelex/conformance"
        assert sidecar["source_path"] == "tests/method_tree/fixtures/method-tree-corpus.json"
        assert len(sidecar["source_commit"]) == 40
        assert sidecar["files"] == {MethodTreeCorpus.CORPUS_PATH.name: hashlib.sha256(MethodTreeCorpus.CORPUS_PATH.read_bytes()).hexdigest()}

    def test_corpus_is_the_format_this_library_reads(self):
        """The vendored file is the method-tree corpus in the format the corpus tests consume."""
        assert MethodTreeCorpus.DOCUMENT["corpus"] == MethodTreeCorpus.CORPUS_NAME
        assert MethodTreeCorpus.DOCUMENT["format"] == MethodTreeCorpus.SUPPORTED_FORMAT
        assert MethodTreeCorpus.TREE_CASES
        assert MethodTreeCorpus.MAP_CASES
        assert MethodTreeCorpus.PATH_CASES
