#!/usr/bin/env python3
"""Download and emit GitHub Actions run logs via `gh run view`.

Use case:
- Fetch job logs for a specific workflow run without hand-crafting endpoints.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    current_repo,
    print_actionable_cli_error,
    run_json,
    run_text,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Download GitHub Actions run logs and emit them as JSON.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--run-id", type=int, required=True, help="Actions run id")
    parser.add_argument(
        "--job-name",
        default=None,
        help="Optional substring to match a job name (case-insensitive)",
    )
    return parser


def _download_logs(
    *,
    runner: GhRunner,
    repo: str,
    run_id: int,
    job_name: str | None,
) -> list[dict[str, Any]]:
    job_id = _resolve_job_id(
        runner=runner,
        repo=repo,
        run_id=run_id,
        job_name=job_name,
    )

    argv = [
        "gh",
        "run",
        "view",
        str(run_id),
        "--repo",
        repo,
        "--log",
    ]
    if job_id:
        argv.extend(["--job", str(job_id)])
    content = run_text(runner, argv)
    return [{"path": job_name or "all-jobs", "content": content}]


def _resolve_job_id(
    *,
    runner: GhRunner,
    repo: str,
    run_id: int,
    job_name: str | None,
) -> int | None:
    if not job_name:
        return None

    data = run_json(
        runner,
        [
            "gh",
            "run",
            "view",
            str(run_id),
            "--repo",
            repo,
            "--json",
            "jobs",
        ],
    )
    if not isinstance(data, dict):
        raise ValueError("Unexpected gh run view payload")
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("Missing jobs payload for run")

    needle = job_name.casefold()
    matches = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        name = job.get("name")
        if isinstance(name, str) and needle in name.casefold():
            matches.append(job)

    if not matches:
        available = [job.get("name") for job in jobs if isinstance(job, dict) and isinstance(job.get("name"), str)]
        raise ValueError(f"Job name not found in run. Requested={job_name!r} available={available}")
    if len(matches) > 1:
        names = [job.get("name") for job in matches]
        raise ValueError(f"Job name is ambiguous. Requested={job_name!r} matches={names}")

    job_id = matches[0].get("databaseId")
    if not isinstance(job_id, int) or job_id <= 0:
        raise ValueError("Missing job databaseId for matched job")
    return job_id


def main() -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args()
        runner = SubprocessGhRunner()

        repo = args.repo or current_repo(runner)
        logs = _download_logs(runner=runner, repo=repo, run_id=args.run_id, job_name=args.job_name)
        print(
            json.dumps(
                {"ok": True, "repo": repo, "run_id": args.run_id, "logs": logs},
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (GhCliError, ValueError) as exc:
        print_actionable_cli_error(
            exc,
            parser=parser,
            examples=[
                "python -m scripts.github.action_run_logs --repo owner/name --run-id 123",
                "python -m scripts.github.action_run_logs --repo owner/name --run-id 123 --job-name pre-commit",
            ],
            see_also=["scripts/github/README.md"],
        )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
