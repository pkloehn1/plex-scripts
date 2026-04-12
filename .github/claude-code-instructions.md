# Claude Code Tool Extensions

Claude Code-specific tool and workflow directives. These extend the primary directives in `CLAUDE.md`.

## Task Management (TodoWrite)

REQUIRE:

- Use TodoWrite proactively for multi-step tasks (3+ steps) or complex implementations.
- Mark tasks as `in_progress` BEFORE starting work (exactly one task in_progress at a time).
- Mark tasks as `completed` IMMEDIATELY after finishing (do not batch completions).
- Only mark completed when fully accomplished (no errors, tests passing, validation done).
- If blocked or encountering errors, keep task `in_progress` and create new task for resolution.

## Specialized Agents (Task Tool)

Use the Task tool with specialized sub-agents for:

- **Explore agent**: Codebase discovery, understanding structure, finding patterns
  - Use for "Where is X implemented?" or "How does Y work?" questions
  - Use instead of running multiple Grep/Glob commands manually
  - Specify thoroughness: "quick", "medium", or "very thorough"
- **Plan agent**: Complex implementation planning before coding
  - Use EnterPlanMode for non-trivial implementations requiring architectural decisions
  - Get user approval on approach before writing code
- **Bash agent**: Complex git operations, multi-step command sequences

## Tool Selection Discipline

REQUIRE:

- **Read tool** for file reading (NOT cat/head/tail via Bash)
- **Edit tool** for file modifications (NOT sed/awk via Bash)
- **Write tool** for new files (NOT echo/cat with heredoc via Bash)
- **Grep tool** for content search (NOT grep/rg via Bash)
- **Glob tool** for file pattern matching (NOT find via Bash)
- **Bash tool** ONLY for actual terminal operations (git, npm, docker, etc.)

## Parallel Execution

REQUIRE:

- Execute independent tool calls in parallel within a single message.
- Run multiple Read calls in parallel when examining multiple files.
- Run multiple Grep/Glob calls in parallel for exploratory searches.
- DO NOT run dependent operations in parallel (use sequential calls instead).

## Context Management

REQUIRE:

- Read files before editing them (Edit/Write tools require prior Read).
- Use Explore agent for open-ended codebase exploration (not manual Grep loops).
- Verify via codebase retrieval before inventing files, APIs, or config syntax.
- Keep diffs minimal and focused.
