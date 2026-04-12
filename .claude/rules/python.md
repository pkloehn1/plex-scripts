---
paths:
  - "**/*.py"
---

# Python Rules

- Target Python 3.11+. Use type hints. Never use bare `except:`.
- Use `pathlib.Path` over stringly-typed paths.
- Use `scripts.common.paths.repo_root()` for repository root discovery.
- Return frozen dataclasses from functions that produce structured results.
- Define `Protocol` classes for external command runners (e.g., `GitRunner`, `GhRunner`).
- Use TDD for non-trivial logic. Maintain 100% test coverage.
- Add `# pragma: no cover` to `if __name__ == "__main__":` guards.
- Package directories MUST include an `__init__.py` with a module docstring.
- Pre-commit hooks (`.pre-commit-config.yaml`) enforce at commit time:
  - `check-short-identifier-names`: variable and parameter names >= 3 chars (exceptions: `_`, `f`, `i`, `pr`, `q1`, `q3`)
  - `check-cognitive-complexity`: max 15 for `scripts/*.py`
  - `check-init-docstrings`: `scripts/**/__init__.py` requires module docstrings
  - `mypy`: type checking on `scripts/*.py`
- Source of truth: `docs/repository-standards/style-guides/python-style-guide.md`
