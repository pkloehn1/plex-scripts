"""Apply keyword-based and file-path-based labels to pull requests and issues.

This script is invoked by the Auto Labeler workflow on ``pull_request_target``
and ``issues`` events.  It reads the event payload from ``GITHUB_EVENT_PATH``,
inspects the title, body, author, and (for PRs) changed files, and applies
labels via the GitHub API using the ``gh`` CLI.

For issue events, only title/body-derived labels (``type/*``, ``area/*``,
swarm keywords, security keywords) are applied.  File-path-based and
compose/service labels are skipped since issues have no changed files.

Fail-open behavior: non-critical failures (e.g. unreadable Compose files) are
logged as warnings and do not abort the script.

Environment variables:

- ``GH_TOKEN``: GitHub token used by ``gh api`` for authentication.
- ``GITHUB_EVENT_PATH``: path to the JSON event payload (set by Actions).
- ``GITHUB_REPOSITORY``: ``owner/repo`` string (set by Actions).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re

from scripts.ci.event_payload import read_event_payload as _read_event_payload
from scripts.ci.image_service_map import is_compose_file, load_map, normalize_image_name
from scripts.github.gh_cli import GhCliError, GhRunner, SubprocessGhRunner, run_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, str] = {
    "bug": "type/bug",
    "chore": "type/chore",
    "docs": "type/docs",
    "enh": "type/enh",
    "feat": "type/feat",
    "fix": "type/fix",
    "perf": "type/perf",
    "refactor": "type/refactor",
    "security": "type/security",
    "test": "type/test",
}

_BOT_AUTHORS: frozenset[str] = frozenset(
    {
        "dependabot[bot]",
        "github-actions[bot]",
    }
)

_SECURITY_KEYWORDS: tuple[str, ...] = ("security", "cve-", "vulnerability")

_SECURITY_PATH_PREFIXES: tuple[str, ...] = (
    "app-config/coraza/",
    "app-config/fail2ban/",
)

_SWARM_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "swarm/networking",
        (
            "overlay",
            "routing mesh",
            "ingress",
            "swarm mode",
            "docker stack",
            "vip",
            "dnsrr",
            "endpoint_mode",
        ),
    ),
    (
        "swarm/scheduling",
        (
            "placement constraints",
            "deploy.placement.constraints",
            "node.labels",
            "global service",
            "mode: global",
            "deploy.mode",
            "deploy.replicas",
            "drain",
        ),
    ),
    (
        "swarm/secrets-configs",
        (
            "/run/secrets",
            "docker secret",
            "docker config",
            "docker stack",
            "secret_file",
            "stack deploy",
        ),
    ),
    (
        "swarm/storage",
        (
            "volume driver",
            "driver_opts",
            "bind mount",
            "nfs",
            "/opt/services/data",
            "/opt/services/app-data",
        ),
    ),
    (
        "swarm/updates-health",
        (
            "update_config",
            "rollback_config",
            "restart_policy",
            "monitor",
            "parallelism",
            "order: start-first",
        ),
    ),
)

_IMAGE_LINE_RE = re.compile(r"^\s*image:\s*['\"]?([^\s'\"#]+)", re.MULTILINE)

# Matches version bump pairs in Dependabot PR text.
# Prose format:  "from 2.33.7 to 2.38.1"
# Table format:  "`2025.12.3` | `2026.2`"
_BUMP_RE = re.compile(
    r"(?:"
    r"from\s+`?v?(\d+(?:\.\d+)*[^\s`]*)`?\s+to\s+`?v?(\d+(?:\.\d+)*[^\s`]*)`?"
    r"|"
    r"`v?(\d+(?:\.\d+)*[^\s`]*)`\s*\|\s*`v?(\d+(?:\.\d+)*[^\s`]*)`"
    r")",
)

# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def conventional_type_from_title(title: str) -> str | None:
    """Extract the conventional-commit type prefix from a PR title."""
    match = re.match(r"^([a-zA-Z]+)(\([^)]*\))?:\s+", title)
    if not match:
        return None
    return match.group(1).lower()


def contains_keyword(haystack: str, keyword: str) -> bool:
    """Check whether *keyword* appears in *haystack*.

    Multi-word phrases and tokens containing special characters (spaces, dots,
    slashes, colons, hyphens) use a plain substring check.  Single bare-word
    tokens use a word-boundary regex to avoid substring false positives.
    """
    normalized = keyword.lower().strip()
    if not normalized:
        return False
    haystack_lower = haystack.lower()
    if re.search(r"[\s.:/\-]", normalized):
        return normalized in haystack_lower
    return bool(re.search(rf"\b{re.escape(normalized)}\b", haystack_lower))


def _type_labels(title: str, full_text: str) -> set[str]:
    """Compute type/* labels from the PR title."""
    conv_type = conventional_type_from_title(title)
    if conv_type:
        mapped = _TYPE_MAP.get(conv_type)
        return {mapped} if mapped else set()
    if any(token in full_text for token in ("security", "cve-", "vuln")):
        return {"type/security"}
    return set()


def _file_path_labels(lower_files: list[str], full_text: str) -> set[str]:
    """Compute labels derived from changed file paths and PR text."""
    labels: set[str] = set()

    if any(path.startswith(".github/workflows/") or path.startswith(".github/actions/") for path in lower_files):
        labels.add("github-actions")

    if any(path.startswith("stacks/") for path in lower_files) or any("dockerfile" in path for path in lower_files):
        labels.add("docker")

    if any(path.endswith(".tf") or path.endswith(".tfvars") for path in lower_files):
        labels.add("terraform")
        labels.add("infrastructure")

    if (
        any(token in full_text for token in _SECURITY_KEYWORDS)
        or any(path.startswith(prefix) for path in lower_files for prefix in _SECURITY_PATH_PREFIXES)
        or any("/security/" in path for path in lower_files)
    ):
        labels.add("security")

    return labels


def _swarm_labels(full_text: str) -> set[str]:
    """Compute swarm/* labels from keyword matches in the PR text."""
    labels: set[str] = set()
    for label, keywords in _SWARM_RULES:
        if any(contains_keyword(full_text, term) for term in keywords):
            labels.add(label)
    return labels


def _sanitize_log_value(value: str) -> str:
    """Restrict logged values to a safe character allowlist.

    Prevents log injection (SonarCloud S5145) by replacing any character
    outside the allowlist with ``?``.  The allowlist covers characters that
    appear in Docker image references and label names.
    """
    return re.sub(r"[^a-zA-Z0-9._:/@-]", "?", value)


def _service_labels(
    compose_contents: dict[str, str],
    image_service_map: dict[str, str],
) -> set[str]:
    """Compute service/* labels from image names in Compose file contents."""
    labels: set[str] = set()
    for _path, content in compose_contents.items():
        for match in _IMAGE_LINE_RE.finditer(content):
            normalized = normalize_image_name(match.group(1))
            mapped_label = image_service_map.get(normalized)
            if mapped_label:
                labels.add(mapped_label)
                logger.info(
                    "Image %s -> %s -> %s",
                    _sanitize_log_value(match.group(1)),
                    _sanitize_log_value(normalized),
                    _sanitize_log_value(mapped_label),
                )
    return labels


def _is_major_bump(old_version: str, new_version: str) -> bool:
    """Return True when the first version segment differs between *old* and *new*."""
    old_major = old_version.lstrip("v").split(".")[0]
    new_major = new_version.lstrip("v").split(".")[0]
    return old_major != new_major


def _major_bump_labels(author: str, full_text: str) -> set[str]:
    """Detect major version bumps in Dependabot/bot PRs.

    Parses "from X to Y" prose and backtick-wrapped table pairs from the
    combined title+body text.  Returns ``{"major-version-bump"}``
    when at least one bump crosses a major version boundary.
    """
    if author.lower() not in _BOT_AUTHORS:
        return set()
    for match in _BUMP_RE.finditer(full_text):
        old = match.group(1) or match.group(3)
        new = match.group(2) or match.group(4)
        if old and new and _is_major_bump(old, new):
            return {"major-version-bump"}
    return set()


def compute_labels(
    *,
    title: str,
    body: str,
    author: str,
    changed_files: list[str],
    compose_contents: dict[str, str],
    image_service_map: dict[str, str],
) -> set[str]:
    """Compute the full set of labels to add given all inputs.

    This is a pure function with zero I/O.  All data is passed as arguments.
    """
    full_text = f"{title}\n{body}".lower()
    lower_files = [file.lower() for file in changed_files]

    labels = _type_labels(title, full_text)

    if author.lower() in _BOT_AUTHORS:
        labels.add("dependencies")

    labels |= _file_path_labels(lower_files, full_text)
    labels |= _swarm_labels(full_text)
    labels |= _service_labels(compose_contents, image_service_map)
    labels |= _major_bump_labels(author, full_text)

    return labels


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _paginate_changed_files(runner: GhRunner, repo: str, pr_number: int) -> list[str]:
    """Fetch all changed file paths for a PR, paginating through results."""
    files: list[str] = []
    page = 1
    while True:
        data = run_json(
            runner,
            [
                "gh",
                "api",
                f"/repos/{repo}/pulls/{pr_number}/files",
                "-f",
                "per_page=100",
                "-f",
                f"page={page}",
            ],
        )
        if not isinstance(data, list) or len(data) == 0:
            break
        for entry in data:
            filename = entry.get("filename") if isinstance(entry, dict) else None
            if filename:
                files.append(filename)
        if len(data) < 100:
            break
        page += 1
    return files


def list_changed_files(*, runner: GhRunner, repo: str, pr_number: int) -> list[str]:
    """List changed file paths for a PR via ``gh api`` with pagination.

    Returns an empty list on API failure so that keyword/type labels derived
    from the PR title and body can still be applied (fail-open).
    """
    try:
        return _paginate_changed_files(runner, repo, pr_number)
    except (GhCliError, OSError, json.JSONDecodeError):
        logger.warning(
            "Failed to list changed files for PR #%s in %s; continuing without file-based labels",
            pr_number,
            repo,
        )
        return []


def get_file_content(*, runner: GhRunner, repo: str, path: str, ref: str) -> str | None:
    """Fetch file content from a specific ref via ``gh api``.

    Returns the decoded UTF-8 content, or ``None`` on failure (fail-open).
    """
    try:
        data = run_json(
            runner,
            [
                "gh",
                "api",
                f"/repos/{repo}/contents/{path}",
                "-f",
                f"ref={ref}",
            ],
        )
    except (GhCliError, OSError, json.JSONDecodeError):
        logger.warning("Failed to fetch %s at ref %s", path, ref)
        return None

    if not isinstance(data, dict):
        return None
    content_b64 = data.get("content")
    if not content_b64:
        return None
    try:
        return base64.b64decode(content_b64).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        logger.warning("Failed to decode content for %s", path)
        return None


def fetch_compose_contents(
    *,
    runner: GhRunner,
    repo: str,
    ref: str,
    changed_files: list[str],
) -> dict[str, str]:
    """Fetch contents of changed Compose files from a specific ref.

    Returns a mapping of file path to decoded content.  Files that cannot be
    fetched are silently skipped (fail-open).
    """
    contents: dict[str, str] = {}
    for file_path in changed_files:
        if not is_compose_file(file_path):
            continue
        content = get_file_content(runner=runner, repo=repo, path=file_path, ref=ref)
        if content is not None:
            contents[file_path] = content
    return contents


def _load_image_service_map() -> dict[str, str]:
    """Load the image-service map, returning empty dict on failure (fail-open)."""
    try:
        return load_map()
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to load image-service map; continuing without service labels")
        return {}


def add_labels(*, runner: GhRunner, repo: str, pr_number: int, labels: set[str]) -> None:
    """Add labels to a PR/issue via ``gh api``."""
    label_list = sorted(labels)
    try:
        runner.run(
            [
                "gh",
                "api",
                "--method",
                "POST",
                f"/repos/{repo}/issues/{pr_number}/labels",
                "--input",
                "-",
            ],
            input_text=json.dumps({"labels": label_list}),
        )
    except (GhCliError, OSError) as exc:
        logger.warning("Failed to add labels to PR #%d: %s", pr_number, exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _fetch_pr_file_context(
    *,
    runner: GhRunner,
    pr: dict[str, object],
    repo: str,
    pr_number: int,
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    """Fetch changed files, compose contents, and image-service map for a PR."""
    head_sha: str = (pr.get("head") or {}).get("sha", "") or ""  # type: ignore[union-attr,attr-defined]
    head_repo: str = (  # type: ignore[union-attr,attr-defined]
        ((pr.get("head") or {}).get("repo") or {}).get("full_name") or repo  # type: ignore[union-attr,attr-defined]
    )
    changed_files = list_changed_files(runner=runner, repo=repo, pr_number=pr_number)
    compose_contents = fetch_compose_contents(
        runner=runner,
        repo=head_repo,
        ref=head_sha,
        changed_files=changed_files,
    )
    image_service_map = _load_image_service_map()
    return changed_files, compose_contents, image_service_map


def main() -> int:
    """Entry point for ``python -m scripts.ci.keyword_labeler``."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    payload = _read_event_payload()

    # Determine context: pull_request or issue payload.
    pr = payload.get("pull_request")
    issue = payload.get("issue")

    if isinstance(pr, dict):
        item = pr
    elif isinstance(issue, dict):
        item = issue
    else:
        logger.info("No pull_request or issue in event payload; exiting.")
        return 0

    repo_full = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo_full:
        logger.error("GITHUB_REPOSITORY not set")
        return 1

    item_number: int = item.get("number", 0)
    title: str = item.get("title", "") or ""
    body: str = item.get("body", "") or ""
    author: str = (item.get("user") or {}).get("login", "") or ""

    runner = SubprocessGhRunner()

    if isinstance(pr, dict):
        changed_files, compose_contents, image_service_map = _fetch_pr_file_context(
            runner=runner,
            pr=pr,
            repo=repo_full,
            pr_number=item_number,
        )
    else:
        changed_files, compose_contents, image_service_map = [], {}, {}

    labels = compute_labels(
        title=title,
        body=body,
        author=author,
        changed_files=changed_files,
        compose_contents=compose_contents,
        image_service_map=image_service_map,
    )

    if not labels:
        logger.info("No keyword/file-based labels to add.")
        return 0

    logger.info("Adding labels: %s", sorted(labels))
    add_labels(runner=runner, repo=repo_full, pr_number=item_number, labels=labels)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
