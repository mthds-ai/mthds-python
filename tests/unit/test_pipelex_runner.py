"""Unit tests for PipelexRunner (local CLI runner)."""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from pydantic import BaseModel, ValidationError
from pytest_mock import MockerFixture, MockType

from mthds.method_tree.file_entry import FileEntry, HashFileEntry
from mthds.runners.pipelex.runner import PipelexRunner, PipelexRunnerError
from tests.unit.test_data import CliWorkingMemoryDumps, MethodFileMaps

if TYPE_CHECKING:
    from mthds.protocol.pipeline_inputs import PipelineInputs


class _PydanticInput(BaseModel):
    question: str
    score: float


class TestPipelexRunner:
    @pytest.mark.parametrize(
        ("topic", "files", "expected_in_message"),
        [
            ("an empty map", {}, "holds no file"),
            (
                "a hash entry, with no blob store to resolve it",
                {"card.html": HashFileEntry(sha256=MethodFileMaps.CARD_SHA256, size=13)},
                "hash entries",
            ),
            ("a key climbing out of the tree", {"../escape.mthds": MethodFileMaps.BUNDLE}, "is not a tree path"),
            ("a dotfile", {".env": "KEY=value", "main.mthds": MethodFileMaps.BUNDLE}, "membership rule"),
            ("an entry that is no file entry", {"main.mthds": cast("FileEntry", object())}, "neither text nor a file entry"),
        ],
    )
    def test_a_files_map_this_runner_cannot_write_is_refused(
        self, mocker: MockerFixture, tmp_path: Path, topic: str, files: dict[str, FileEntry], expected_in_message: str
    ) -> None:
        """A map that is no method tree this runner can write is refused before anything is written or the CLI runs.

        An empty map would otherwise validate an empty directory and pass (greptile P1 on PR #25),
        a hash entry names bytes this runner, which keeps no blob store, does not hold, a key
        that is not a tree path would write outside the run's directory, and an entry the map cannot
        be written with is this runner's error rather than a bare serialization error.
        """
        mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
        mocker.patch("mthds.runners.pipelex.runner.tempfile.mkdtemp", return_value=str(tmp_path / "run"))
        run_subprocess = mocker.patch("mthds.runners.pipelex.runner.run_subprocess")

        for call in (PipelexRunner().validate(files=files), PipelexRunner().execute(pipe_code="answer", files=files)):
            with pytest.raises(PipelexRunnerError, match=expected_in_message):
                asyncio.run(call)

        run_subprocess.assert_not_called()
        assert list(tmp_path.rglob("*")) == [], topic

    def test_validate_writes_the_tree_and_validates_its_directory(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """The tree is written out as a directory, each file at its tree path, and `pipelex validate bundle` reads that directory."""
        mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
        mocker.patch("mthds.runners.pipelex.runner.tempfile.mkdtemp", return_value=str(tmp_path))
        mocker.patch("mthds.runners.pipelex.runner.shutil.rmtree")
        run_subprocess = mocker.patch("mthds.runners.pipelex.runner.run_subprocess")

        report = asyncio.run(PipelexRunner(library_dirs=["/libs"]).validate(files=MethodFileMaps.INLINE, allow_signatures=True))

        assert report.is_valid is True
        method_dir = tmp_path / "method"
        assert run_subprocess.call_args.args[0] == ["pipelex", "-L", "/libs", "validate", "bundle", str(method_dir), "--allow-signatures"]
        assert (method_dir / "main.mthds").read_text(encoding="utf-8") == MethodFileMaps.BUNDLE
        assert (method_dir / "templates" / "logo.png").read_bytes() == MethodFileMaps.LOGO
        assert sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()) == [
            "method/main.mthds",
            "method/templates/logo.png",
        ]

    def test_execute_writes_the_tree_beside_the_run_files(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """A run's tree is its own directory: the inputs, the working memory and the results sit beside it, never inside it."""
        run_subprocess = _patch_cli_writing_working_memory(mocker, tmp_path, CliWorkingMemoryDumps.REF_STRING)

        asyncio.run(
            PipelexRunner().execute(pipe_code="answer", files=MethodFileMaps.INLINE, inputs={"question": {"concept": "Text", "content": "why?"}})
        )

        method_dir = tmp_path / "method"
        assert run_subprocess.call_args.args[0] == [
            "pipelex",
            "run",
            "bundle",
            str(method_dir),
            "--pipe",
            "answer",
            "-i",
            str(tmp_path / "inputs.json"),
            "--working-memory-path",
            str(tmp_path / "working_memory.json"),
            "-o",
            str(tmp_path / "results"),
            "--no-pretty-print",
        ]
        assert sorted(path.relative_to(method_dir).as_posix() for path in method_dir.rglob("*") if path.is_file()) == [
            "main.mthds",
            "templates/logo.png",
        ]

    @pytest.mark.parametrize(
        ("kwargs", "expected_in_message"),
        [
            ({"output_name": "result"}, "output_name"),
            ({"output_multiplicity": 3}, "output_multiplicity"),
            ({"dynamic_output_concept_ref": "answer.Answer"}, "dynamic_output_concept_ref"),
        ],
    )
    def test_execute_rejects_unsupported_output_args(self, mocker: MockerFixture, kwargs: dict[str, Any], expected_in_message: str) -> None:
        """The CLI runner cannot honor protocol output args; it must fail fast
        instead of silently dropping them (greptile P1 on PR #26).
        """
        mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
        run_subprocess = mocker.patch("mthds.runners.pipelex.runner.run_subprocess")

        with pytest.raises(PipelexRunnerError, match=expected_in_message):
            asyncio.run(PipelexRunner().execute(pipe_code="answer", **kwargs))

        run_subprocess.assert_not_called()

    def test_execute_rejects_missing_target(self, mocker: MockerFixture) -> None:
        """With neither pipe_code nor files the CLI invocation would
        be malformed; the runner must reject upfront for parity with the API
        runner (greptile P2 on PR #26).
        """
        mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
        run_subprocess = mocker.patch("mthds.runners.pipelex.runner.run_subprocess")

        with pytest.raises(PipelexRunnerError, match="pipe_code or files"):
            asyncio.run(PipelexRunner().execute())

        run_subprocess.assert_not_called()

    def test_execute_serializes_pydantic_inputs(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """Inputs may carry pydantic BaseModel values (StuffContent, etc.); a
        plain json.dumps would TypeError. The runner uses pydantic-aware
        serialization so the same protocol input that works through the API
        runner also works locally (greptile P1 on PR #26).
        """
        mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
        # Pin tempfile to a controllable directory we can read back from.
        mocker.patch("mthds.runners.pipelex.runner.tempfile.mkdtemp", return_value=str(tmp_path))
        captured: dict[str, list[str]] = {}

        def capture(cmd: list[str], **_kwargs: Any) -> Any:
            captured["cmd"] = cmd
            # Mock a working memory file so the post-call read succeeds.
            (tmp_path / "working_memory.json").write_text('{"root": {}, "aliases": {}}', encoding="utf-8")

            class _Result:
                returncode = 0
                stdout = b""
                stderr = b""

            return _Result()

        mocker.patch("mthds.runners.pipelex.runner.run_subprocess", side_effect=capture)
        # rmtree on a tmp_path under pytest's tmp is fine; the cleanup happens after we read the inputs file.
        mocker.patch("mthds.runners.pipelex.runner.shutil.rmtree")

        payload = _PydanticInput(question="why?", score=0.5)
        asyncio.run(PipelexRunner().execute(pipe_code="answer", inputs=cast("PipelineInputs", {"input": payload})))

        inputs_path = tmp_path / "inputs.json"
        assert inputs_path.exists()
        on_disk = json.loads(inputs_path.read_text(encoding="utf-8"))
        assert on_disk == {"input": {"question": "why?", "score": 0.5}}

    def test_execute_maps_the_cli_working_memory(self, mocker: MockerFixture, tmp_path: Path) -> None:
        """The working memory the CLI writes maps onto the wire shape: each stuff keeps its
        concept ref and its content, and its runtime fields are dropped.
        """
        _patch_cli_writing_working_memory(mocker, tmp_path, CliWorkingMemoryDumps.REF_STRING)

        result = asyncio.run(PipelexRunner().execute(pipe_code="answer"))

        answer = result.pipe_output.working_memory.root["answer"]
        assert answer.concept == "answer.Answer"
        assert answer.content == {"text": "Because."}
        assert answer.model_extra == {}
        assert result.model_extra is not None
        assert result.model_extra["main_stuff_name"] == "answer"

    @pytest.mark.parametrize(
        ("topic", "malformed_stuff"),
        CliWorkingMemoryDumps.MALFORMED_CONCEPT_CASES,
    )
    def test_execute_refuses_a_stuff_without_a_concept_ref(
        self,
        mocker: MockerFixture,
        tmp_path: Path,
        topic: str,
        malformed_stuff: dict[str, Any],
    ) -> None:
        """A stuff whose concept is not its ref string fails validation at that stuff's `concept`,
        as on the API path, instead of reaching the caller under an invented ref.
        """
        working_memory = {"root": {"answer": malformed_stuff}, "aliases": {"main_stuff": "answer"}}
        _patch_cli_writing_working_memory(mocker, tmp_path, working_memory)

        with pytest.raises(ValidationError) as exc_info:
            asyncio.run(PipelexRunner().execute(pipe_code="answer"))

        errors = exc_info.value.errors()
        assert [(error["loc"], error["type"]) for error in errors] == [(("root", "answer", "concept"), "string_type")], topic


def _patch_cli_writing_working_memory(mocker: MockerFixture, tmp_path: Path, working_memory: dict[str, Any]) -> MockType:
    """Stand in for the `pipelex` CLI: a run that succeeds and writes `working_memory` where it was asked to; returns the stand-in."""
    mocker.patch("mthds.runners.pipelex.runner._ensure_pipelex", return_value="pipelex")
    mocker.patch("mthds.runners.pipelex.runner.tempfile.mkdtemp", return_value=str(tmp_path))
    mocker.patch("mthds.runners.pipelex.runner.shutil.rmtree")

    def write_working_memory(cmd: list[str], **_kwargs: Any) -> Any:
        working_memory_path = Path(cmd[cmd.index("--working-memory-path") + 1])
        working_memory_path.write_text(json.dumps(working_memory), encoding="utf-8")
        return mocker.Mock(returncode=0)

    return mocker.patch("mthds.runners.pipelex.runner.run_subprocess", side_effect=write_working_memory)
