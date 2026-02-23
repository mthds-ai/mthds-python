SHELL := /bin/bash
.SHELLFLAGS := -o pipefail -c

ifeq ($(wildcard .env),.env)
include .env
export
endif
VIRTUAL_ENV := $(CURDIR)/.venv
PROJECT_NAME := $(shell grep '^name = ' pyproject.toml | sed -E 's/name = "(.*)"/\1/')

# The "?" is used to make the variable optional, so that it can be overridden by the user.
PYTHON_VERSION ?= 3.13

VENV_PYTHON := "$(VIRTUAL_ENV)/bin/python"
VENV_PYTEST := "$(VIRTUAL_ENV)/bin/pytest"
VENV_RUFF := "$(VIRTUAL_ENV)/bin/ruff"
VENV_PYRIGHT := "$(VIRTUAL_ENV)/bin/pyright"
VENV_MYPY := "$(VIRTUAL_ENV)/bin/mypy"
VENV_MIKE := "$(VIRTUAL_ENV)/bin/mike"
VENV_PYLINT := "$(VIRTUAL_ENV)/bin/pylint"

UV_MIN_VERSION = $(shell grep -m1 'required-version' pyproject.toml | sed -E 's/.*= *"([^<>=, ]+).*/\1/')


define PRINT_TITLE
    $(eval PROJECT_PART := [$(PROJECT_NAME)])
    $(eval TARGET_PART := ($@))
    $(eval MESSAGE_PART := $(1))
    $(if $(MESSAGE_PART),\
        $(eval FULL_TITLE := === $(PROJECT_PART) ===== $(TARGET_PART) ====== $(MESSAGE_PART) ),\
        $(eval FULL_TITLE := === $(PROJECT_PART) ===== $(TARGET_PART) ====== )\
    )
    $(eval TITLE_LENGTH := $(shell echo -n "$(FULL_TITLE)" | wc -c | tr -d ' '))
    $(eval PADDING_LENGTH := $(shell echo $$((126 - $(TITLE_LENGTH)))))
    $(eval PADDING := $(shell printf '%*s' $(PADDING_LENGTH) '' | tr ' ' '='))
    $(eval PADDED_TITLE := $(FULL_TITLE)$(PADDING))
    @echo ""
    @echo "$(PADDED_TITLE)"
endef

define HELP
Manage $(PROJECT_NAME) located in $(CURDIR).
Usage:

make env                      - Create python virtual env
make lock                     - Refresh uv.lock without updating anything
make install                  - Create local virtualenv & install all dependencies
make update                   - Upgrade dependencies via uv
make validate                 - Run the setup sequence to validate the config and libraries
make build                    - Build the wheels

make test                     - Run unit tests
make test-with-prints         - Run unit tests with prints
make t                        - Shorthand -> test
make tp                       - Shorthand -> test-with-prints

make format                   - format with ruff format
make lint                     - lint with ruff check
make pyright                  - Check types with pyright
make mypy                     - Check types with mypy

make up                       - Shorthand -> update-gateway-models up-kit-configs rules
make cleanenv                 - Remove virtual env and lock files
make cleanderived             - Remove extraneous compiled files, caches, logs, etc.
make cleanall                 - Remove all -> cleanenv + cleanderived

make merge-check-ruff-lint    - Run ruff merge check without updating files
make merge-check-ruff-format  - Run ruff merge check without updating files
make merge-check-mypy         - Run mypy merge check without updating files
make merge-check-pyright	  - Run pyright merge check without updating files

make check-unused-imports     - Check for unused imports without fixing
make fix-unused-imports       - Fix unused imports with ruff
make fui                      - Shorthand -> fix-unused-imports
make check-TODOs              - Check for TODOs

make check                    - Shorthand -> format lint mypy
make c                        - Shorthand -> check
make cc                       - Shorthand -> cleanderived check
make li                       - Shorthand -> lock install

endef
export HELP

.PHONY: all help env env-verbose check-uv check-uv-verbose lock install update build test test-with-prints t tp agent-test format lint pyright mypy pylint merge-check-ruff-format merge-check-ruff-lint merge-check-pyright merge-check-mypy merge-check-pylint check-unused-imports fix-unused-imports check-TODOs check-uv cleanderived cleanenv cleanall c cc li

all help:
	@echo "$$HELP"


##########################################################################################
### SETUP
##########################################################################################

# Quiet check-uv: only shows output if uv is missing (needs install)
check-uv:
	@command -v uv >/dev/null 2>&1 || { \
		echo ""; \
		echo "=== [$(PROJECT_NAME)] ===== (check-uv) ====== Ensuring uv ≥ $(UV_MIN_VERSION) =========="; \
		echo "uv not found – installing latest …"; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	}
	@uv self update >/dev/null 2>&1 || true

# Verbose check-uv: always shows output (for setup commands)
check-uv-verbose:
	$(call PRINT_TITLE,"Ensuring uv ≥ $(UV_MIN_VERSION)")
	@command -v uv >/dev/null 2>&1 || { \
		echo "uv not found – installing latest …"; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	}
	@uv self update >/dev/null 2>&1 || true

# Quiet env: only shows output if venv needs to be created
env: check-uv
	@if [ ! -d "$(VIRTUAL_ENV)" ]; then \
		echo ""; \
		echo "=== [$(PROJECT_NAME)] ===== (env) ====== Creating virtual environment ================="; \
		echo "Creating Python virtual env in \`${VIRTUAL_ENV}\`"; \
		uv venv "$(VIRTUAL_ENV)" --python $(PYTHON_VERSION); \
		echo "Using Python: $$($(VENV_PYTHON) --version) from $$(readlink $(VENV_PYTHON) 2>/dev/null || echo $(VENV_PYTHON))"; \
	fi

# Verbose env: always shows output (for setup commands like install, lock, update)
env-verbose: check-uv-verbose
	$(call PRINT_TITLE,"Creating virtual environment")
	@if [ ! -d "$(VIRTUAL_ENV)" ]; then \
		echo "Creating Python virtual env in \`${VIRTUAL_ENV}\`"; \
		uv venv "$(VIRTUAL_ENV)" --python $(PYTHON_VERSION); \
	else \
		echo "Python virtual env already exists in \`${VIRTUAL_ENV}\`"; \
	fi
	@echo "Using Python: $$($(VENV_PYTHON) --version) from $$(readlink $(VENV_PYTHON) 2>/dev/null || echo $(VENV_PYTHON))"

install: env-verbose
	$(call PRINT_TITLE,"Installing dependencies")
	@. "$(VIRTUAL_ENV)/bin/activate" && \
	uv sync --all-extras && \
	echo "Installed mthds dependencies in ${VIRTUAL_ENV} with all extras.";

lock: env
	$(call PRINT_TITLE,"Resolving dependencies without update")
	@uv lock && \
	echo uv lock without update;

update: env
	$(call PRINT_TITLE,"Updating all dependencies")
	@uv lock --upgrade && \
	uv sync --all-extras && \
	echo "Updated dependencies in ${VIRTUAL_ENV}";


build: env
	$(call PRINT_TITLE,"Building the wheels")
	@uv build

##########################################################################################
### CLEANING
##########################################################################################

cleanderived:
	$(call PRINT_TITLE,"Erasing derived files and directories")
	@find . -name '.coverage' -delete && \
	find . -wholename '**/*.pyc' -delete && \
	find . -type d -wholename '__pycache__' -exec rm -rf {} + && \
	find . -type d -wholename './.cache' -exec rm -rf {} + && \
	find . -type d -wholename './.mypy_cache' -exec rm -rf {} + && \
	find . -type d -wholename './.ruff_cache' -exec rm -rf {} + && \
	find . -type d -name '.pytest_cache' -exec rm -rf {} + && \
	find . -type d -wholename './logs/*.log' -exec rm -rf {} + && \
	find . -type d -wholename './.reports/*' -exec rm -rf {} + && \
	echo "Cleaned up derived files and directories";

cleanenv:
	$(call PRINT_TITLE,"Erasing virtual environment")
	find . -name 'uv.lock' -delete && \
	rm -rf "$(VIRTUAL_ENV)" && \
	echo "Cleaned up virtual env and dependency lock files";

cleanall: cleanderived cleanenv
	@echo "Cleaned up all derived files and directories";

##########################################################################################
### TESTING
##########################################################################################

test: env
	$(call PRINT_TITLE,"Unit testing")
	@if [ -n "$(TEST)" ]; then \
		$(VENV_PYTEST) -o log_cli=true -o log_level=WARNING -k "$(TEST)" $(if $(filter 1,$(VERBOSE)),-v,$(if $(filter 2,$(VERBOSE)),-vv,$(if $(filter 3,$(VERBOSE)),-vvv,))); \
	else \
		$(VENV_PYTEST) -o log_cli=true -o log_level=WARNING $(if $(filter 1,$(VERBOSE)),-v,$(if $(filter 2,$(VERBOSE)),-vv,$(if $(filter 3,$(VERBOSE)),-vvv,))); \
	fi

test-with-prints: env
	$(call PRINT_TITLE,"Unit testing with prints")
	@if [ -n "$(TEST)" ]; then \
		$(VENV_PYTEST) -s -k "$(TEST)" $(if $(filter 1,$(VERBOSE)),-v,$(if $(filter 2,$(VERBOSE)),-vv,$(if $(filter 3,$(VERBOSE)),-vvv,))); \
	else \
		$(VENV_PYTEST) -s $(if $(filter 1,$(VERBOSE)),-v,$(if $(filter 2,$(VERBOSE)),-vv,$(if $(filter 3,$(VERBOSE)),-vvv,))); \
	fi

t: test
	@echo "> done: t = test"

tp: test-with-prints
	@echo "> done: tp = test-with-prints"

agent-test: env
	@echo "• Running unit tests..."
	@tmpfile=$$(mktemp); \
	$(VENV_PYTEST) -o log_level=WARNING --tb=short -q > "$$tmpfile" 2>&1; \
	exit_code=$$?; \
	if [ $$exit_code -ne 0 ]; then cat "$$tmpfile"; fi; \
	rm -f "$$tmpfile"; \
	if [ $$exit_code -eq 0 ]; then echo "• All tests passed."; fi; \
	exit $$exit_code

##########################################################################################
### LINTING
##########################################################################################

format: env
	$(call PRINT_TITLE,"Formatting with ruff")
	$(VENV_RUFF) format . --config pyproject.toml

lint: env
	$(call PRINT_TITLE,"Linting with ruff")
	$(VENV_RUFF) check . --fix --config pyproject.toml

pyright: env
	$(call PRINT_TITLE,"Typechecking with pyright")
	$(VENV_PYRIGHT) --pythonpath $(VENV_PYTHON) --project pyproject.toml

mypy: env
	$(call PRINT_TITLE,"Typechecking with mypy")
	$(VENV_MYPY) --config-file pyproject.toml

pylint: env
	$(call PRINT_TITLE,"Linting with pylint")
	$(VENV_PYLINT) --rcfile pyproject.toml mthds


##########################################################################################
### MERGE CHECKS
##########################################################################################

merge-check-ruff-format: env
	$(call PRINT_TITLE,"Formatting with ruff")
	$(VENV_RUFF) format --check . --config pyproject.toml

merge-check-ruff-lint: env check-unused-imports
	$(call PRINT_TITLE,"Linting with ruff without fixing files")
	$(VENV_RUFF) check . --config pyproject.toml

merge-check-pyright: env
	$(call PRINT_TITLE,"Typechecking with pyright")
	$(VENV_PYRIGHT) --pythonpath $(VENV_PYTHON) --project pyproject.toml

merge-check-mypy: env
	$(call PRINT_TITLE,"Typechecking with mypy")
	$(VENV_MYPY) --config-file pyproject.toml

merge-check-pylint: env
	$(call PRINT_TITLE,"Linting with pylint")
	$(VENV_PYLINT) --rcfile pyproject.toml .

##########################################################################################
### MISCELLANEOUS
##########################################################################################

check-unused-imports: env
	$(call PRINT_TITLE,"Checking for unused imports without fixing")
	$(VENV_RUFF) check --select=F401 --no-fix .

fix-unused-imports: env
	$(call PRINT_TITLE,"Fixing unused imports")
	$(VENV_RUFF) check --select=F401 --fix .

fui: fix-unused-imports
	@echo "> done: fui = fix-unused-imports"

check-TODOs: env
	$(call PRINT_TITLE,"Checking for TODOs")
	@$(VENV_RUFF) check --select=TD -v .

##########################################################################################
### SHORTHANDS
##########################################################################################

c: format lint pyright mypy
	@echo "> done: c = check"

cc: cleanderived c
	@echo "> done: cc = cleanderived format lint pyright pylint mypy"

check: cc check-unused-imports pylint
	@echo "> done: check"

agent-check: fix-unused-imports format lint pyright mypy
	@echo "> done: agent-check"

li: lock install
	@echo "> done: lock install"
