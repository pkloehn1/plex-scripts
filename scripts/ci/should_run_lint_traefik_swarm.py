"""Decide whether the Traefik swarm linter should run based on changed files.

Reads ``changed-files.txt`` (written by :mod:`scripts.ci.write_changed_files`)
and checks whether any changed paths match the Traefik swarm compose globs.

Output contract:

- **stdout**: bare ``true`` or ``false`` (machine-readable for CI conditionals).
- **stderr**: reason and matched paths (human-readable diagnostics in CI logs).

Exit code is always 0 — the decision is communicated via stdout so CI workflows
can parse it without the step itself failing.
"""

from __future__ import annotations

import sys

from scripts.ci._decision_utils import decide, read_changed_files

_RELEVANT_GLOBS = (
    "stacks/*/docker-compose.yml",
    "stacks/*/docker-compose.yaml",
)


def main() -> int:  # nosonar: always returns 0 — decision gate, not validator
    """Run the Traefik swarm lint decision gate."""
    try:
        changed = read_changed_files()
    except OSError:
        print("true")
        print("fail-open: could not read changed files", file=sys.stderr)
        return 0

    result = decide(changed, _RELEVANT_GLOBS)
    print("true" if result.should_run else "false")
    print(f"reason={result.reason}", file=sys.stderr)
    if result.matched_paths:
        print(f"matched={', '.join(result.matched_paths)}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
