.DEFAULT_GOAL := help
PYTHON ?= python3
VENV_PYTHON := .venv/bin/python

.PHONY: help setup paper-table verify-artifacts smoke test
help:
	@printf '%s\n' 'make paper-table        Verify the public bundle and print the paper percentages' 'make verify-artifacts  Verify all shipped bundle checksums' 'make setup             Install the pinned Python dependencies in .venv' 'make smoke             Run one new V2.1 synthetic seed after setup' 'make test              Run the focused public V2.1 tests after setup'

setup:
	$(PYTHON) -m venv .venv
	$(VENV_PYTHON) -m pip install -r requirements-v2.lock
	$(VENV_PYTHON) -m pip install -e .

paper-table:
	$(PYTHON) scripts/paper_artifacts.py

verify-artifacts:
	$(PYTHON) scripts/paper_artifacts.py --verify-only

smoke:
	@test -x $(VENV_PYTHON) || { echo 'Run make setup first.' >&2; exit 1; }
	@FISAT_RUN="results/local-v21-smoke-$$(date +%Y%m%d-%H%M%S)-$$$$"; \
	OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
	VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
	PYTHONPATH=src $(VENV_PYTHON) -m leakage_attack.v21_development_cli \
	  --seed 41001 --output "$$FISAT_RUN"

test:
	$(VENV_PYTHON) -m unittest discover -s tests -p 'test_public_checkpoint_v21*.py' -v
