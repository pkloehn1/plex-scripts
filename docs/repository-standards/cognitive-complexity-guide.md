# Cognitive Complexity Guide

## Purpose

- Provide a single source of truth for how Cognitive Complexity is evaluated in this repository.
- Align local checks with SonarSource guidance and make expectations explicit for reviewers and contributors.

## Scope

- Applies to all Python code under `scripts/**/*.py`.
- Enforced by the pre-commit hook `Check Cognitive Complexity (scripts)` with a default per-function threshold of 15.
- Reference rule: Sonar `python:S3776`.

## Alignment with SonarSource

- Counting model follows the SonarSource Cognitive Complexity whitepaper (see Appendices A and B for the detailed rules used by our checker).
- Focus areas:
  - Penalize flow-breaking constructs (+ nesting).
  - Avoid counting readability helpers (early returns, context managers) as complexity.
  - Record recursion once per function to highlight self-referential flows.
  - Treat boolean operator mixing as additional cognitive load.
- Python-specific notes (see Appendix B):
  - `with` / `async with` do **not** add complexity; their bodies are evaluated without extra nesting.
  - Pattern matching (`match`/`case`) is treated like `switch` with per-case bodies nested by one level.
  - Direct recursion adds a single fundamental increment per function.
  - `break` / `continue` currently mirror SonarPython behavior and are not counted separately.

## Default expectations for contributors

- Keep functions small and single-purpose; prefer early `return`/`continue` to reduce nesting.
- When complexity approaches 15, extract helpers or simplify branching (e.g., guard clauses, mapping tables, or small parsing utilities).
- New code should include targeted tests for complex control-flow paths.

## Implementation mapping (checker → Sonar rules)

- `if` / `elif` / `else`: +1 for each branch; `else` adds a branch but not extra nesting beyond the surrounding level.
- Loops (`for`, `async for`, `while`): +1 plus nesting of contained statements.
- `try` / `except`: +1 for the `try`, +1 for each handler; `else`/`finally` bodies inherit nesting but add no fundamental increment.
- Ternary expressions (`a if cond else b`): +1.
- Boolean operators: each additional operator beyond the first adds +1; mixing `and`/`or` adds +1 per mix.
- Pattern matching (`match`): +1 for the match, each `case` body is evaluated at `nesting + 1`.
- Direct recursion: first self-call adds +1 per function (no additional nesting cost).
- Nested functions/classes: skipped from the parent's score; each is scored independently.
- Parsing failures count as violations to avoid hiding unreadable code.

## Appendix A — Counting rules checklist

- Add +1 for every flow-breaking structure: `if`/`elif`/`else`, loops, `try`, each `except`, ternary, `match`.
- Add +1 for boolean operator count beyond the first in a chain.
- Add +1 when boolean operators are mixed (`and` vs `or`) within the same condition.
- Add +1 once per function for direct recursion.
- Apply nesting: each flow-breaking structure inside another adds its nesting level to the increment.
- Do **not** add complexity for:
  - Function/class declarations (beyond scoring the declared function itself).
  - `return`, `yield`, or early exits.
  - Context managers (`with` / `async with`).
  - `break` / `continue` (mirrors current SonarPython behavior).
  - `match` cases themselves (only the enclosing `match` counts).

## Appendix B — Python examples and detractors

- Low complexity (score 1):

  ```python
  def guard(x):
      if x < 0:
          return 0
      return x
  ```

- Boolean mixing (score 3):

  ```python
  def mixed(a, b, c):
      if a and b or c:  # +1 for if, +1 for second operator, +1 for mixing and/or
          return True
      return False
  ```

- Recursion (score 2):

  ```python
  def fact(n):
      if n <= 1:  # +1
          return 1
      return n * fact(n - 1)  # +1 for first recursive call
  ```

- Context manager is free (score 0):

  ```python
  def read_first(path):
      with open(path) as fh:  # no increment
          return fh.readline()
  ```

- Guidance for detractors:
  - Prefer guard clauses to avoid deep `if`/`else` nesting.
  - Split long boolean expressions or encapsulate them in helper functions with descriptive names.
  - Replace large `match`/`if` ladders with dispatch tables where practical.
