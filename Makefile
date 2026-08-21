# Pac-Man - "Ghosts! More ghosts!" (42)
# Mandatory targets: install, run, debug, clean, lint, lint-strict.

VENV    := .venv
PY      := $(VENV)/bin/python
# --isolated ignores any global pip config (e.g. a forced --user) and env vars.
PIP     := $(PY) -m pip --isolated
CONFIG  ?= config.json

MYPY_FLAGS := --warn-return-any --warn-unused-ignores --ignore-missing-imports \
             --disallow-untyped-defs --check-untyped-defs

.PHONY: install run debug lint lint-strict test clean fclean re help

## install: create the venv and install all dependencies
install:
	@command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	git submodule update --init --recursive
	$(PIP) install -r requirements.txt
	@echo "Pre-warming the Reflex/node build (so first run is instant)…"
	-$(VENV)/bin/reflex export --frontend-only --no-zip >/dev/null 2>&1 || true
	@echo "Done. Launch with:  make run"

## run: launch the game (python3 pac-man.py config.json)
run:
	$(PY) pac-man.py $(CONFIG)

## debug: launch under the Python debugger
debug:
	$(PY) -m pdb pac-man.py $(CONFIG)

## lint: flake8 + mypy with the mandated flags
lint:
	$(PY) -m flake8 .
	$(PY) -m mypy . $(MYPY_FLAGS)

## lint-strict: flake8 + mypy --strict
lint-strict:
	$(PY) -m flake8 .
	$(PY) -m mypy . --strict

## test: run the test suite
test:
	$(PY) -m pytest -q

## clean: remove caches and Python artifacts
clean:
	find . -path ./$(VENV) -prune -o -path ./venv -prune -o \
		-type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .pytest_cache
	find . -path ./$(VENV) -prune -o -name '*.py[co]' -exec rm -f {} + 2>/dev/null || true

## fclean: clean + remove the venv, build output and runtime files
fclean: clean
	rm -rf $(VENV) venv .web reflex.lock
	rm -f highscores.json.bak highscores.json.tmp

## re: full rebuild
re: fclean install

## help: list targets
help:
	@grep -E '^## ' $(MAKEFILE_LIST) | sed 's/## //'
