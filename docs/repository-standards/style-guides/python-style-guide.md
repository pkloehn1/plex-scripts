# Python Style Guide

## Purpose

Normative rules for Python code in this repository.

## Runtime and Tooling

REQUIRE:

- Python 3.11+
- `pytest` for tests
- `ruff` for linting (and formatting when enabled)

## Code Style

### Typing

REQUIRE:

- Add type hints for new and modified functions.
- Prefer `from __future__ import annotations` for Python files that define types heavily.

NEVER:

- Use bare `except:`.

### Structure

REQUIRE:

- Prefer small, single-purpose functions.
- Isolate I/O (filesystem, subprocess, network) behind small helpers.
- Prefer `pathlib.Path` over stringly-typed paths.
- Package directories MUST include an `__init__.py` with a module docstring (tests packages: `"""Tests for <package>."""`).
- Use `scripts.common.paths.repo_root()` for repository root discovery. NEVER compute `Path(__file__).resolve().parents[N]` manually — the parent index is fragile and silently breaks when files move.

PREFER:

- Pure functions for parsing/validation logic.
- Returning structured data over printing from library code.

### Shared Patterns

These patterns are established in `scripts/common/` and should be followed when extending or creating new modules.

#### Typed Result Dataclasses

REQUIRE:

- Return frozen dataclasses from functions that produce structured results (not bare tuples, bools, or lists).
- Examples: `GitResult`, `GhResult`, `DecisionResult`, `ChangedFilesResult`, `Finding`.
- When introducing a typed result to an existing function, add a new function returning the typed result and have the old function delegate to it (preserves backward compatibility).

```python
# Good: typed result with delegation
def decide(changed_paths, relevant_globs) -> DecisionResult: ...
def should_run(changed_paths, relevant_globs) -> bool:
    return decide(changed_paths, relevant_globs).should_run
```

#### Protocol Pattern for Testability

REQUIRE:

- Define `Protocol` classes for external command runners (`GitRunner`, `GhRunner`) to enable test stubs without monkey-patching.
- Protocols live in the module that defines the runner (e.g., `scripts/common/git_runner.py`, `scripts/github/gh_cli.py`).

NEVER:

- Use ABCs where a Protocol suffices. Protocols (structural typing) are preferred over inheritance.

#### Finding Dataclass Naming

REQUIRE:

- Linter findings MUST use `path: Path` (not `file_path`) as the field name for the file path.
- All `Finding` dataclasses MUST be `frozen=True`.

### Hub/Spoke Composition

The hub repository provides shared types, helpers, and pure functions. Spoke repos extend via composition — not inheritance. Each hub module exposes a stable contract that spokes consume directly.

Four composition mechanisms exist in the codebase, each serving a different extension shape.

#### Shared Scaffold + Check List

The hub provides a CLI scaffold, typed results, and a check runner. Spokes define domain-specific check functions and pass them to the scaffold.

Hub contract (`scripts/linting/_lint_utils.py`):

- `Severity` enum, `LintResult` dataclass
- `run_check()` executes one check function and tags results with the source file
- `cli_main()` handles argument parsing, severity filtering, and output formatting

Spoke pattern (`scripts/linting/lint_swarm.py`, `scripts/linting/lint_compose.py`):

```python
from scripts.linting._lint_utils import LintResult, Severity, cli_main, run_check

def _check_resource_limits(compose: dict) -> list[LintResult]:
    """Domain-specific check function matching the hub signature."""
    ...

def lint_compose_file(file_path: Path) -> list[LintResult]:
    results = []
    for check_fn in swarm_checks:
        results.extend(run_check(file_path=file_path, compose=data, check=check_fn))
    return results
```

#### Decision Gate + Spoke Globs

The hub provides a pure `decide()` function and `DecisionResult`. Spokes define domain-specific glob patterns.

Hub contract (`scripts/ci/_decision_utils.py`):

- `DecisionResult` frozen dataclass (`should_run`, `reason`, `matched_paths`)
- `decide(changed_paths, relevant_globs)` performs glob matching
- `read_changed_files()` reads CI-generated file lists

Spoke pattern (`scripts/ci/should_run_lint_traefik_swarm.py`):

```python
from scripts.ci._decision_utils import decide, read_changed_files

_RELEVANT_GLOBS = (
    "stacks/*/docker-compose.yml",
    "stacks/*/docker-compose.yaml",
)

def main() -> int:
    changed = read_changed_files()
    result = decide(changed, _RELEVANT_GLOBS)
    print("true" if result.should_run else "false")
    return 0
```

#### Mapping Table Overrides

The hub provides pure decision functions with module-level mapping constants. Spoke repos override the mapping tables to adjust behavior for their service portfolio.

Hub contract (`scripts/ci/backfill_issue_priorities.py`):

- `compute_priority(title, body, labels)` returns a priority label string
- `_SERVICE_TIERS` maps `service/*` labels to numeric tiers (0-3)
- `_TIER_BUG_FLOOR` enforces priority floors per tier

Spokes override `_SERVICE_TIERS` with their own service list.

#### Utility Base Class

The hub provides a concrete utility class with shared methods for command execution and output formatting. Spokes instantiate or compose with the class.

Hub contract (`scripts/devops/health_check_base.py`):

- `BaseHealthCheckConfig` frozen dataclass (edge node, local mode, verbose)
- `BaseHealthChecker` provides `run_cmd()`, `docker_exec()`, and output formatting helpers
- No abstract methods — spokes compose with the class rather than inherit from it

No spoke repos extend this module yet.

#### Hub Module Requirements

REQUIRE:

- Export frozen dataclass result types for structured output.
- Expose pure functions for decision and validation logic.
- Provide a shared CLI scaffold (`cli_main()` or equivalent) when applicable.
- Include a module docstring that documents the extension point.

#### Spoke Module Requirements

REQUIRE:

- Import hub types directly — never redefine `LintResult`, `DecisionResult`, or other hub types.
- Define domain-specific functions matching hub call signatures.
- Pass domain functions to hub scaffolds (check lists, glob tuples).
- Include colocated tests under `scripts/**/tests/`.

#### File Guard Pattern

Optional spoke scripts use the `run_if_exists.py` guard in pre-commit hooks. Excluded scripts exit 0 via `sync-directives.yml`. See [Pre-commit Add-on Hooks](../pre-commit-add-ons.md).

### Maintainability --- Reducing Cognitive Complexity

Cognitive complexity measures how hard code is to understand. Every nested branch multiplies the mental effort to follow the logic. Apply these techniques to keep functions flat and readable.

Enforcement:

- Pre-commit enforces a cognitive complexity limit for `scripts/**/*.py`.
  - Default threshold: 15 per function.
  - Hook: `Check Cognitive Complexity (scripts)`.
  - Sonar rule: `python:S3776`.

#### 1. Guard Clauses (Inversion)

REQUIRE:

- Check error conditions and edge cases **first**, then return/raise immediately. This keeps the main logic at the top indentation level.

```python
# Bad — nested happy path
def process(data):
    if data is not None:
        if data.is_valid():
            return _do_work(data)
    return None

# Good — guard clauses exit early
def process(data):
    if data is None:
        return None
    if not data.is_valid():
        return None
    return _do_work(data)
```

#### 2. Extraction

REQUIRE:

- When a block of logic inside a conditional or loop is non-trivial, extract it into a named helper function. The function name replaces the need for a comment and the body stays flat.

```python
# Bad — inline complexity inside a loop
for issue in issues:
    if issue.labels & BUG_LABELS:
        if _service_tier(issue.labels) == 0:
            priority = "P1-high"
        else:
            priority = "P2-medium"
    ...

# Good — extracted to descriptive function
def _bug_priority_for_tier(tier: int) -> str:
    if tier == 0:
        return "P1-high"
    return "P2-medium"
```

#### 3. Merge Related Conditionals

PREFER:

- Combine related `if` statements that lead to the same outcome using boolean operators, keeping the merged condition readable.

```python
# Bad — separate checks with identical outcomes
if label_set & INCIDENT_LABELS:
    return "P0-critical"
if any(kw in body for kw in P0_KEYWORDS):
    return "P0-critical"

# Good — merged into one guard clause
if label_set & INCIDENT_LABELS or any(kw in body for kw in P0_KEYWORDS):
    return "P0-critical"
```

#### 4. Replace Nested Branches with Lookup Tables

PREFER:

- When conditionals map discrete inputs to outputs, use a dictionary lookup instead of chained `if/elif`.

```python
# Bad — chained conditionals
if tier == 0:
    floor = 1
elif tier == 1:
    floor = 2
else:
    floor = 3

# Good — lookup table
_TIER_BUG_FLOOR = {0: 1, 1: 2}
floor = _TIER_BUG_FLOOR.get(tier, 3)
```

#### 5. Limit Nesting Depth

REQUIRE:

- Functions MUST NOT exceed three levels of indentation (function body counts as level one). If a branch or loop pushes beyond three levels, apply extraction or inversion to flatten it.

PREFER:

- Early `continue` in loops to skip irrelevant iterations rather than wrapping the loop body in a conditional.

### Code Quality Principles

These principles keep code readable, maintainable, and debuggable.

#### Naming Conventions

REQUIRE:

- Use descriptive names that reveal intent. A reader should understand what a function does or what a variable holds without reading the implementation.
- Prefix boolean-returning functions with `is_` or `has_` to make the return type obvious at the call site.
- Use `_private_name` for module-internal helpers.

```python
# Bad — ambiguous
def check(labels, title):
    ...

# Good — intent is clear
def _is_security_type(title: str, label_set: set[str]) -> bool:
    ...
```

#### Self-Documenting Code and Comments

REQUIRE:

- Write code that reads naturally; avoid belaboured comments that restate what the code already says.
- Comments explain **why** a choice was made, not **what** the code does. If the "what" is not obvious, rename variables or extract a function instead of adding a comment.
- Place comments on the line **above** the code they describe, never on the same line (inline trailing comments). Be consistent.

```python
# Bad — restates the obvious
x = x + 1  # increment x

# Good — explains a non-obvious choice
# YAML 1.1 parses bare `on` as boolean True; map it back to "on"
if key is True:
    present_keys.add("on")
```

#### Consistent Formatting

REQUIRE:

- Run `ruff format` and `ruff check` before committing. Pre-commit hooks enforce this automatically via the Super-Linter hook.
- Let the formatter own whitespace, line length, and import ordering.
  Do not fight the tools.

#### DRY Business Logic

REQUIRE:

- Do not duplicate decision logic. When two functions need the same rule, extract the shared logic into a single source of truth and call it from both places.
- After extracting, add or update tests to cover the shared function.

NEVER:

- Copy-paste blocks of conditional logic. If JSCPD flags a clone, refactor it.

#### Avoid Magic Values

REQUIRE:

- Declare named constants for any literal that carries domain meaning.
  Module-level `_UPPER_SNAKE` constants are preferred.

PREFER:

- Lookup tables (dicts, tuples) over repeated `if/elif` chains when mapping discrete inputs to outputs.

```python
_TIER_BUG_FLOOR = {0: 1, 1: 2}
floor = _TIER_BUG_FLOOR.get(tier, 3)
```

#### Single Responsibility

REQUIRE:

- Each function does one thing. Prefer pure functions (no side effects) for parsing, validation, and decision logic.
- Separate I/O from computation. A function that fetches data should not also transform it.

NEVER:

- Mix network calls with business logic in the same function.

#### Avoid Overly Clever Code

NEVER:

- Write dense one-liners that require mental unpacking. Readability beats brevity. Extract comprehensions that nest generators or span multiple lines into loops or helpers.

```python
# Bad — requires rewriting to debug
result = {k: [v for v in vs if v > t] for k, vs in data.items() if k in keys}

# Good — explicit and debuggable
result = {}
for key, values in data.items():
    if key not in keys:
        continue
    result[key] = [val for val in values if val > threshold]
```

#### No Premature Optimisation

PREFER:

- Write clear, correct code first. Optimise only when profiling identifies an actual bottleneck.
- Simplicity and readability are more valuable than micro-performance gains in a homelab automation codebase.

### Error Handling Patterns

This repository uses two error handling strategies, selected by error class. The boundary between them is whether the error indicates a code defect or an external runtime condition.

#### Pattern 1: Fail-fast for programming errors

REQUIRE:

- `ValueError`, `TypeError`, `AssertionError` propagate uncaught through utility functions.
- These errors indicate a code defect and must surface immediately during development and CI.
- Only catch at CLI entry points (`main()`, `run_actionable_main()`) for user-facing error formatting.

```python
# Good — utility raises, CLI catches
def parse_repo(repo: str) -> tuple[str, str]:
    if "/" not in repo:
        raise ValueError(f"Expected owner/name format, got: {repo}")
    owner, name = repo.split("/", 1)
    return owner, name

def main() -> int:
    try:
        owner, name = parse_repo(args.repo)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
```

NEVER:

- Catch `ValueError`/`TypeError`/`AssertionError` in utility functions to return a default value. This hides bugs.

```python
# Bad — swallows programming error
def _get_tier(labels: set[str]) -> int:
    try:
        return _TIER_MAP[next(l for l in labels if l.startswith("tier/"))]
    except (KeyError, StopIteration):
        return 3  # hides the real problem
```

**Documented exception — input parsing:** Catching `ValueError` from `int()` or `fromisoformat()` is acceptable when the function validates external input. Return a sentinel or re-raise.

```python
# Acceptable — parsing external input is the function's purpose
def _parse_timeout_seconds(env_value: str) -> int:
    try:
        return int(env_value)
    except ValueError:
        return 50_000  # safe default for env var
```

#### Pattern 2: Fail-open for runtime errors

REQUIRE:

- `subprocess.CalledProcessError`, `OSError`, `json.JSONDecodeError` caught at utility boundaries closest to the I/O call.
- Return safe defaults (empty dicts, empty lists, sentinel paths) so callers do not need defensive checks.

```python
# Good — catches at the I/O boundary, returns safe default
def read_event_payload() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH", "")
    try:
        with Path(path).open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
```

NEVER:

- Catch `Exception` or bare `except:` in utility functions. Always specify the exception types.
- Mix fail-fast and fail-open exceptions in the same `except` clause without justification.

#### Shell error handling

REQUIRE:

- All shell scripts must include `set -Eeuo pipefail` near the top.
- `-E` ensures ERR traps propagate through functions.
- `-e` exits on error, `-u` treats unset variables as errors, `-o pipefail` catches failures in pipelines.

#### CI workflow error handling

PREFER:

- Hard failure (no `continue-on-error`) for linting, security scans, and test steps.
- `continue-on-error: true` only for non-blocking advisory checks (e.g., Copilot review requests).
- Treat scripts as CLI entry points; keep most logic importable and testable.

## Testing

REQUIRE:

- Use TDD for non-trivial logic (write the failing test first).
- Maintain 100% test coverage across the repository.
- Add/extend targeted unit tests for non-trivial logic.
- Prefer tests colocated under `scripts/**/tests/` when testing script helpers.
- Test both the happy path and the rejection path. When widening a validation (e.g., relaxing a regex), include negative boundary tests that prove inputs which should fail still fail.
- Always add `# pragma: no cover` to `if __name__ == "__main__":` entry-point guards — these lines are unreachable from test imports and would otherwise create uncoverable gaps.
- Annotate pytest fixture parameters with their correct types:
  - `tmp_path: Path` — the `tmp_path` fixture returns a `pathlib.Path`. Do not annotate it as `pytest.TempPathFactory`.
  - `tmp_path_factory: pytest.TempPathFactory` — use only when the factory fixture is needed (e.g., session-scoped temporary directories).

### Per-Package Coverage Configs

Coverage configs live under `.github/coverage/` as TOML files. Each config defines `[run]` source/omit patterns and `[report]` exclusions for a specific package.

The `_PACKAGE_COV_CONFIG` dict in `scripts/precommit/pytest_affected.py` maps package names to config paths. When `pytest_affected` runs tests for a package, it passes `--cov-config` if a mapping exists.

REQUIRE:

- Add a `.github/coverage/<package>.toml` when a package needs custom source/omit patterns (e.g., excluding CLI wrappers, SSH scripts, or integration tests from measurement).
- Register the new config in `_PACKAGE_COV_CONFIG` so the pre-commit hook applies it.
- Spoke-specific coverage configs (e.g., `ci.toml`, `inventory.toml`) remain in the spoke repo. Only configs needed by hub-synced packages belong in the hub template.

## Dependencies

REQUIRE:

- Use `pyproject.toml` as the dependency source of truth (avoid introducing/expanding `requirements.txt`).
- Avoid adding large dependency chains for small tasks.

## See Also

- [Documentation Standards](../documentation-standards.md)
