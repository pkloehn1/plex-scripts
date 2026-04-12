"""Report a required status check context on a PR merge/head commit SHA.

Cross-platform Python replacement for ``report_status_context.sh`` and
``Set-CommitStatus.ps1``.  Called by the ``report-status-context``
composite action.

Required environment variables:
    GITHUB_REPOSITORY, PR_NUMBER, JOB_STATUS, STATUS_CONTEXT,
    TARGET_URL, GH_TOKEN.
"""

from __future__ import annotations

import json
import os
import sys

from scripts.github.gh_cli import GhRunner, SubprocessGhRunner

_REQUIRED_ENV_VARS = (
    "GITHUB_REPOSITORY",
    "PR_NUMBER",
    "JOB_STATUS",
    "STATUS_CONTEXT",
    "TARGET_URL",
    "GH_TOKEN",
)

_STATUS_MAP = {"success": "success", "failure": "failure"}


def _map_job_status(job_status: str) -> str:
    """Map a GitHub Actions job status to a commit status state."""
    return _STATUS_MAP.get(job_status, "error")


def _validate_env() -> dict[str, str]:
    """Validate required environment variables and return their values."""
    env: dict[str, str] = {}
    missing: list[str] = []
    for var in _REQUIRED_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if not value:
            missing.append(var)
        else:
            env[var] = value
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)
    return env


def _fetch_pr_sha(repo: str, pr_number: str, *, runner: GhRunner) -> str:
    """Fetch the merge or head commit SHA for a pull request."""
    result = runner.run(
        ["gh", "api", f"repos/{repo}/pulls/{pr_number}", "--jq", ".merge_commit_sha // .head.sha"],
    )
    sha = result.stdout.strip()
    if not sha or sha == "null":
        print(
            "No commit SHA available (merge_commit_sha/head.sha missing); cannot report required status context",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return sha


def _post_status(
    *,
    repo: str,
    sha: str,
    state: str,
    context: str,
    description: str,
    target_url: str,
    runner: GhRunner,
) -> None:
    """Post a commit status via the GitHub API."""
    payload = json.dumps(
        {
            "state": state,
            "context": context,
            "description": description,
            "target_url": target_url,
        }
    )
    runner.run(["gh", "api", "-X", "POST", f"repos/{repo}/statuses/{sha}", "--input", "-"], input_text=payload)


def _default_runner() -> GhRunner:  # pragma: no cover
    """Return the default subprocess-based GhRunner."""
    return SubprocessGhRunner()


def main() -> int:
    """Entry point for ``python -m scripts.ci.report_status_context``."""
    env = _validate_env()
    runner = _default_runner()

    sha = _fetch_pr_sha(env["GITHUB_REPOSITORY"], env["PR_NUMBER"], runner=runner)
    state = _map_job_status(env["JOB_STATUS"])

    _post_status(
        repo=env["GITHUB_REPOSITORY"],
        sha=sha,
        state=state,
        context=env["STATUS_CONTEXT"],
        description=f"Reported by GitHub Actions ({env['JOB_STATUS']})",
        target_url=env["TARGET_URL"],
        runner=runner,
    )

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
