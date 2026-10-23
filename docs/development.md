# Developing mthds-python

## The Python interpreter

The development environment in `.venv` runs the Python version that `.python-version`, at the repository root, names. The Makefile reads that file and hands the version to every uv command it runs, and uv reads the same file on its own when you call it outside the Makefile, so the terminal, the editor and CI agree on one interpreter. An environment built on another Python moves back to the pinned one at the next `make install`, whose `uv sync` replaces a `.venv` that runs a version other than the one requested; the targets that only run tools out of `.venv`, such as `make test`, use it as they find it.

To try another version that `requires-python` in `pyproject.toml` allows, run `PYTHON_VERSION=3.11 make install`, or set `UV_PYTHON`, which the Makefile honours the same way, and a plain `make install` afterwards returns the environment to the pin. CI tests every supported version: each job of the lint and test matrices sets `UV_PYTHON` to its version for the whole job and ends by checking that `.venv` ran that version.
