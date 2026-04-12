# Project shortcuts — run from repo root
# Usage: make lint | make fix | make test | make cov
#
# Hub/spoke compatible: spoke repos inherit this file via sync-directives.
# Spoke-specific targets go in Makefile.<repo> (e.g., Makefile.docker-swarm-homelab).
# Override VENV_BIN to match the spoke's Python environment layout.
# On Linux/macOS the venv binary directory is .venv/bin; on Windows it
# is .venv/Scripts.  The default auto-detects based on directory existence.

# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

# Auto-detect venv bin path and executable suffix (Linux/macOS vs Windows)
ifneq ($(wildcard .venv/bin/python),)
	VENV_BIN ?= .venv/bin
	EXE :=
else
	VENV_BIN ?= .venv/Scripts
	EXE := .exe
endif

PYTHON  := $(VENV_BIN)/python$(EXE)
RUFF    := $(VENV_BIN)/ruff$(EXE)
PYTEST  := $(PYTHON) -m pytest

# Spoke repos can override the default coverage target package.
# Example: COV_PACKAGE=scripts.myapp make cov
COV_PACKAGE ?= scripts

# ---------------------------------------------------------------------------
# Lint / Format
# ---------------------------------------------------------------------------

.PHONY: lint
lint: ## Run ruff check + format --check
	$(RUFF) check .
	$(RUFF) format --check .

.PHONY: fix
fix: ## Auto-fix ruff lint issues and reformat
	$(RUFF) check --fix .
	$(RUFF) format .

# ---------------------------------------------------------------------------
# Test / Coverage
# ---------------------------------------------------------------------------

.PHONY: test
test: ## Run all tests (fast, no coverage)
	$(PYTEST) -q --tb=short

.PHONY: cov
cov: ## Run tests with coverage (COV_PACKAGE=scripts)
	$(PYTEST) --cov=$(COV_PACKAGE) --cov-report=term-missing --tb=short

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

.DEFAULT_GOAL := help

# Spoke extension: add the spoke-specific Makefile below when created.
# These files are not synced and can override variables or add
# repo-specific targets (e.g., deploy, compose-up).
# -include Makefile.local
