---
applyTo: "**/*.py"
---

# Python Instructions

Path-specific instructions for Python files.

## Core Rules

- Target Python 3.11+.
- Prefer small functions; isolate I/O.
- Use type hints.
- Never use bare `except:`.
- Use `pathlib.Path` over stringly-typed paths.
- Package directories MUST include an `__init__.py` with a module docstring.

## Structural Patterns

Source of truth: `docs/repository-standards/style-guides/python-style-guide.md`

### Repository Root Discovery

REQUIRE:

- Use `scripts.common.paths.repo_root()` for repository root discovery.
- NEVER compute `Path(__file__).resolve().parents[N]` manually — the parent index is fragile and silently breaks when files move.

### Typed Result Dataclasses

REQUIRE:

- Return frozen dataclasses from functions that produce structured results (not bare tuples, bools, or lists).
- Established examples: `GitResult`, `GhResult`, `DecisionResult`, `ChangedFilesResult`, `Finding`.
- When introducing a typed result to an existing function, add a new function returning the typed result and have the old function delegate to it (preserves backward compatibility).

### Protocol Pattern for Testability

REQUIRE:

- Define `Protocol` classes for external command runners (e.g., `GitRunner`, `GhRunner`) to enable test stubs without monkey-patching.
- Protocols live in the module that defines the runner (e.g., `scripts/common/git_runner.py`, `scripts/github/gh_cli.py`).
- NEVER use ABCs where a Protocol suffices.

### Finding Dataclass Conventions

REQUIRE:

- Linter findings MUST use `path: Path` (not `file_path`) as the field name.
- All `Finding` dataclasses MUST be `frozen=True`.

### GitHub API Automation

REQUIRE:

- Use `scripts/github/*` helpers for all GitHub API operations (issues, PRs, review comments, workflows, rulesets).
- NEVER construct raw `gh` commands or API calls manually — these helpers minimize trial/error and produce stable JSON outputs.
- All GitHub helpers are documented in `scripts/github/README.md` with examples and workflow diagrams.
- Run helpers as modules: `python -m scripts.github.<module>`, never as direct scripts.
- Common helpers: `pr_upsert`, `issue_upsert`, `list_unresolved_review_threads`, `reply_and_resolve_review_comment`, `fix_unsigned_commits`, `create_pr_review`.

## Testing

- Use TDD for non-trivial logic (write the failing test first).
- Maintain 100% test coverage across the repository.
- Always add `# pragma: no cover` to `if __name__ == "__main__":` entry-point guards.

## Dependencies

- Use `pyproject.toml` as the dependency source of truth (avoid introducing/expanding `requirements.txt`).

## Pre-commit Hooks (Python)

Source of truth: `.pre-commit-config.yaml`

These hooks run automatically on `git commit` and enforce Python code quality.
Violations block the commit — write code that satisfies these rules upfront.

### Python code quality hooks

| Hook | Scope | Rule |
| ---- | ----- | ---- |
| `check-short-identifier-names` | `*.py` | Variable and parameter names must be >= 3 characters. Approved exceptions: `_`, `f`, `i`, `pr`, `q1`, `q3` |
| `check-cognitive-complexity` | `scripts/*.py` | Functions must have cognitive complexity <= 15 |
| `check-init-docstrings` | `scripts/**/__init__.py` | Must have a module docstring (not a `#` comment); test packages must start with `"Tests for "` |
| `mypy` | `scripts/*.py` | Must pass mypy type checking (run from repo venv) |

### Commit workflow hooks

| Hook | Rule |
| ---- | ---- |
| `check-commit-grouping` | Commit tooling files (`scripts/precommit/`, `scripts/testing/hooks/`, `.pre-commit-config.yaml`) separately from other changes; `.pre-commit-config.yaml` must be committed alone |
| `check-commit-message` | Conventional commit format required (commit-msg stage) |

## Cross-Platform Tooling

- Python is the default choice for any tooling that doesn't have a hard requirement for OS-native scripting.
- Python provides cross-platform compatibility between Windows and Linux, making it the preferred language for repository automation and helper scripts.
- Prefer Python over shell scripts (bash/PowerShell) when cross-platform compatibility is needed, unless there's a specific requirement for OS-native scripting.
