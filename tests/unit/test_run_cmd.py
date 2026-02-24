"""Tests for file-vs-pipe detection in _run_with_api."""

from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mthds.cli.commands.run_cmd import _run_with_api  # noqa: PLC2701


class _CapturedApiCall:
    """Captures arguments passed to MthdsAPIClient.execute_pipeline."""

    pipe_code: str | None = None
    mthds_content: str | None = None


class TestRunWithApiFileDetection:
    """Test that _run_with_api correctly distinguishes .mthds files from pipe codes."""

    @pytest.fixture(autouse=True)
    def _patch_api(self, mocker: MockerFixture) -> _CapturedApiCall:
        """Patch MthdsAPIClient so we capture what gets passed."""
        captured = _CapturedApiCall()

        mock_response = mocker.MagicMock()
        mock_response.model_dump.return_value = {"status": "ok"}

        async def fake_execute(  # noqa: RUF029
            pipe_code: str | None = None,
            mthds_content: str | None = None,
            inputs: object = None,  # noqa: ARG001
        ) -> object:
            captured.pipe_code = pipe_code
            captured.mthds_content = mthds_content
            return mock_response

        mock_client = mocker.MagicMock()
        mock_client.execute_pipeline = fake_execute

        async def fake_close() -> None:
            pass

        mock_client.close = fake_close

        mocker.patch(
            "mthds.cli.commands.run_cmd.MthdsAPIClient",
            return_value=mock_client,
        )
        mocker.patch("mthds.cli.commands.run_cmd.get_console")

        self._captured = captured
        return captured

    def test_existing_mthds_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An existing .mthds file is read and passed as mthds_content."""
        mthds_file = tmp_path / "my_pipe.mthds"
        mthds_file.write_text("pipe content here", encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        _run_with_api(str(mthds_file), inputs_file=None, inputs_json=None)

        assert self._captured.mthds_content == "pipe content here"
        assert self._captured.pipe_code is None

    def test_dotted_pipe_code(self) -> None:
        """A dotted pipe code like 'org.my_pipe' is treated as a pipe code, not a file."""
        _run_with_api("org.my_pipe", inputs_file=None, inputs_json=None)

        assert self._captured.pipe_code == "org.my_pipe"
        assert self._captured.mthds_content is None

    def test_nonexistent_mthds_path_falls_back_to_pipe_code(self) -> None:
        """A .mthds path that doesn't exist on disk falls back to pipe code."""
        _run_with_api("nonexistent.mthds", inputs_file=None, inputs_json=None)

        assert self._captured.pipe_code == "nonexistent.mthds"
        assert self._captured.mthds_content is None

    def test_simple_pipe_code(self) -> None:
        """A simple pipe code without dots is treated as a pipe code."""
        _run_with_api("my_pipe", inputs_file=None, inputs_json=None)

        assert self._captured.pipe_code == "my_pipe"
        assert self._captured.mthds_content is None
