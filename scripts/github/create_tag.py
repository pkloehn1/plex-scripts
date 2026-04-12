#!/usr/bin/env python3
"""Create an annotated tag on GitHub via the REST API.

Why this exists:
- Repo policy is to interact with GitHub via ``scripts/github/*`` helpers rather than
    calling ``gh`` directly.
- Used by the CalVer tagging workflow to create release tags.

Implementation:
- Creates an annotated tag object via POST /repos/{owner}/{repo}/git/tags
- Creates the tag ref via POST /repos/{owner}/{repo}/git/refs
"""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

from scripts.github.cli_utils import resolve_repo
from scripts.github.gh_cli import (
    ActionableArgumentParser,
    GhCliError,
    GhRunner,
    SubprocessGhRunner,
    parse_repo,
    print_actionable_cli_error,
    run_json,
)

_TAG_RE = re.compile(r"^v\d{4}\.(0[1-9]|1[0-2])\.\d+$")


def _validate_tag(tag: str) -> str:
    tag_name = tag.strip()
    if not tag_name:
        raise ValueError("tag is required")
    if not _TAG_RE.fullmatch(tag_name):
        raise ValueError(f"tag must match CalVer pattern (vYYYY.MM.MICRO): {tag_name!r}")
    return tag_name


def _validate_sha(sha: str) -> str:
    sha_clean = sha.strip()
    if not sha_clean:
        raise ValueError("sha is required")
    if not re.fullmatch(r"[0-9a-f]{40}", sha_clean):
        raise ValueError(f"sha must be a 40-character hex string: {sha_clean!r}")
    return sha_clean


def create_tag(
    *,
    runner: GhRunner,
    repo: str,
    tag: str,
    sha: str,
    message: str,
) -> dict[str, Any]:
    """Create an annotated tag on GitHub.

    Steps:
    1. POST /git/tags to create the tag object (annotated).
    2. POST /git/refs to create the ref pointing to the tag object.
    """
    owner, name = parse_repo(repo)
    tag_name = _validate_tag(tag)
    sha_clean = _validate_sha(sha)

    # Step 1: Create annotated tag object
    tag_endpoint = f"/repos/{owner}/{name}/git/tags"
    tag_body = json.dumps(
        {
            "tag": tag_name,
            "message": message,
            "object": sha_clean,
            "type": "commit",
        }
    )
    tag_argv = [
        "gh",
        "api",
        "--method",
        "POST",
        tag_endpoint,
        "--input",
        "-",
    ]
    tag_obj = run_json(runner, tag_argv, input_text=tag_body)
    tag_sha = tag_obj.get("sha", "")
    if not isinstance(tag_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", tag_sha):
        raise ValueError(f"POST /git/tags returned invalid SHA: {tag_sha!r}")

    # Step 2: Create ref pointing to the tag object
    ref_endpoint = f"/repos/{owner}/{name}/git/refs"
    ref_body = json.dumps(
        {
            "ref": f"refs/tags/{tag_name}",
            "sha": tag_sha,
        }
    )
    ref_argv = [
        "gh",
        "api",
        "--method",
        "POST",
        ref_endpoint,
        "--input",
        "-",
    ]
    run_json(runner, ref_argv, input_text=ref_body)

    return {
        "ok": True,
        "repo": repo,
        "tag": tag_name,
        "sha": sha_clean,
        "tag_object_sha": tag_sha,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = ActionableArgumentParser(description="Create an annotated tag on GitHub.")
    parser.add_argument("--repo", default=None, help="Repo owner/name (default: auto-detect)")
    parser.add_argument("--tag", required=True, help="Tag name (e.g., v2026.03.0)")
    parser.add_argument("--sha", required=True, help="Commit SHA to tag")
    parser.add_argument("--message", required=True, help="Tag message")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def main() -> int:  # pragma: no cover
    parser = _build_parser()
    args = parser.parse_args()
    runner = SubprocessGhRunner()

    try:
        repo = resolve_repo(args, runner)
        payload = create_tag(runner=runner, repo=repo, tag=args.tag, sha=args.sha, message=args.message)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Created tag {args.tag} on {args.sha[:12]} in {repo}.")
        return 0
    except (GhCliError, ValueError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print_actionable_cli_error(
                exc,
                parser=parser,
                examples=[
                    "python -m scripts.github.create_tag --repo owner/name --tag v2026.03.0 --sha abc123... --message 'Release v2026.03.0'",
                ],
                see_also=["scripts/github/README.md"],
            )
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
