#!/usr/bin/env python3
"""Pull SonarCloud findings and duplication metrics for the current project.

Use case:
- Let AI agents surface SonarCloud issues (bugs, code smells, vulnerabilities,
    security hotspots) and code duplication metrics without leaving the terminal.

SonarCloud API docs: https://sonarcloud.io/web_api/api/issues

Authentication:
- Uses ``SONAR_TOKEN`` from the environment.  The token is never logged.
- Preferred access mode: 1Password CLI (``op``).  Login with ``op signin``,
    then inject the token inline::

        SONAR_TOKEN=$(op read "op://Private/SonarQube Cloud claude-code Token/credential") \
            .venv/bin/python -m scripts.github.sonarcloud_issues

Security notes:
- All query parameters (``project_key``, ``branch``, ``pull_request``,
    ``file_key``) are validated against an allowlist pattern before use.
- Authentication uses stdlib ``urllib`` with an ``Authorization`` header,
    keeping the token out of process argument lists.

Live validation commands (require ``SONAR_TOKEN`` via ``op read``)::

    # Set token for the session
    export SONAR_TOKEN=$(op read "op://Private/SonarQube Cloud claude-code Token/credential")

    # Duplication metrics (JSON)
    .venv/bin/python -m scripts.github.sonarcloud_issues --duplications --format json

    # Duplication metrics (summary)
    .venv/bin/python -m scripts.github.sonarcloud_issues --duplications --format summary

    # PR-scoped duplications
    .venv/bin/python -m scripts.github.sonarcloud_issues --duplications --pull-request 367 --format summary

    # Duplications with block-level detail
    .venv/bin/python -m scripts.github.sonarcloud_issues --duplications --block-details --format summary

    # Issues mode (existing)
    .venv/bin/python -m scripts.github.sonarcloud_issues --format json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from scripts.common.json_utils import parse_json_object

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SONARCLOUD_API = "https://sonarcloud.io/api"
_DEFAULT_TIMEOUT_S = 30

_VALID_TYPES = frozenset({"BUG", "VULNERABILITY", "CODE_SMELL", "SECURITY_HOTSPOT"})
_VALID_SEVERITIES = frozenset(
    {"INFO", "MINOR", "MAJOR", "CRITICAL", "BLOCKER"},
)
_VALID_STATUSES = frozenset(
    {"OPEN", "CONFIRMED", "REOPENED", "RESOLVED", "CLOSED"},
)

_VALID_HOTSPOT_STATUSES = frozenset({"TO_REVIEW", "REVIEWED"})
_VALID_HOTSPOT_RESOLUTIONS = frozenset({"FIXED", "SAFE", "ACKNOWLEDGED"})


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SonarIssue:
    """Normalised representation of one SonarCloud issue."""

    key: str
    rule: str
    severity: str
    issue_type: str
    message: str
    component: str
    line: int | None
    status: str
    effort: str


@dataclass(frozen=True)
class DuplicationMetrics:
    """Project-level duplication measures from /api/measures/component."""

    duplicated_lines: int
    duplicated_blocks: int
    duplicated_files: int
    duplicated_lines_density: float
    new_duplicated_lines: int
    new_duplicated_blocks: int
    new_duplicated_lines_density: float


@dataclass(frozen=True)
class FileDuplication:
    """Per-file duplication breakdown from /api/measures/component_tree."""

    path: str
    duplicated_lines: int
    duplicated_lines_density: float
    duplicated_blocks: int


@dataclass(frozen=True)
class DuplicationBlockRef:
    """One side of a duplicated code block from /api/duplications/show."""

    file_key: str
    file_name: str
    from_line: int
    size: int


@dataclass(frozen=True)
class DuplicationGroup:
    """A group of duplicated blocks that share identical code."""

    blocks: tuple[DuplicationBlockRef, ...]


@dataclass(frozen=True)
class SecurityHotspot:
    """Normalised representation of one SonarCloud security hotspot."""

    key: str
    rule_key: str
    message: str
    component: str
    security_category: str
    vulnerability_probability: str
    status: str
    line: int | None


def _issue_from_raw(raw: dict[str, Any]) -> SonarIssue:
    return SonarIssue(
        key=raw.get("key", ""),
        rule=raw.get("rule", ""),
        severity=raw.get("severity", ""),
        issue_type=raw.get("type", ""),
        message=raw.get("message", ""),
        component=raw.get("component", ""),
        line=raw.get("line"),
        status=raw.get("status", ""),
        effort=raw.get("effort", ""),
    )


def _hotspot_from_raw(raw: dict[str, Any]) -> SecurityHotspot:
    return SecurityHotspot(
        key=raw.get("key", ""),
        rule_key=raw.get("ruleKey", ""),
        message=raw.get("message", ""),
        component=raw.get("component", ""),
        security_category=raw.get("securityCategory", ""),
        vulnerability_probability=raw.get("vulnerabilityProbability", ""),
        status=raw.get("status", ""),
        line=raw.get("line"),
    )


# ---------------------------------------------------------------------------
# API interaction
# ---------------------------------------------------------------------------


_SAFE_PARAM_RE = re.compile(r"^[\w.:/-]+$")


def _validate_param(value: str, label: str) -> str:
    """Validate a query-string parameter against unsafe characters."""
    if not _SAFE_PARAM_RE.match(value):
        raise ValueError(f"Invalid {label}: {value!r} contains unsafe characters")
    return value


def _validate_csv(value: str, allowed: frozenset[str], label: str) -> str:
    """Validate a comma-separated list against *allowed* values.

    Returns the normalised string with whitespace stripped from each item.
    """
    items: list[str] = []
    for raw in value.split(","):
        item = raw.strip()
        if item and item not in allowed:
            raise ValueError(f"Invalid {label} {item!r}. Allowed: {sorted(allowed)}")
        if item:
            items.append(item)
    return ",".join(items)


def _http_get(url: str, token: str, *, timeout: int = _DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Execute an authenticated GET request and return parsed JSON.

    Uses :mod:`urllib.request` with HTTP Basic auth.  The token is sent via
    the ``Authorization`` header, keeping it out of process argument lists.
    """
    credentials = base64.b64encode(f"{token}:".encode()).decode()
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Basic {credentials}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_json_object(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace").strip()
        raise RuntimeError(f"SonarCloud API request failed (HTTP {exc.code}): {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"SonarCloud API request failed: {exc.reason}") from exc


def fetch_issues(
    *,
    project_key: str,
    token: str,
    types: str | None = None,
    severities: str | None = None,
    statuses: str | None = None,
    branch: str | None = None,
    pull_request: str | None = None,
    page_size: int = 100,
) -> list[SonarIssue]:
    """Fetch issues from SonarCloud."""
    _validate_param(project_key, "project_key")
    if branch:
        _validate_param(branch, "branch")
    if pull_request:
        _validate_param(pull_request, "pull_request")
    params: list[str] = [
        f"componentKeys={project_key}",
        f"ps={page_size}",
    ]
    if types:
        _validate_csv(types, _VALID_TYPES, "type")
        params.append(f"types={types}")
    if severities:
        _validate_csv(severities, _VALID_SEVERITIES, "severity")
        params.append(f"severities={severities}")
    if statuses:
        _validate_csv(statuses, _VALID_STATUSES, "status")
        params.append(f"statuses={statuses}")
    if branch:
        params.append(f"branch={branch}")
    if pull_request:
        params.append(f"pullRequest={pull_request}")

    url = f"{SONARCLOUD_API}/issues/search?{'&'.join(params)}"
    payload = _http_get(url, token)
    raw_issues: list[dict[str, Any]] = payload.get("issues", [])
    return [_issue_from_raw(raw) for raw in raw_issues]


def fetch_hotspots(
    *,
    project_key: str,
    token: str,
    statuses: str | None = None,
    resolution: str | None = None,
    branch: str | None = None,
    pull_request: str | None = None,
    page_size: int = 100,
) -> list[SecurityHotspot]:
    """Fetch security hotspots from SonarCloud via /api/hotspots/search."""
    _validate_param(project_key, "project_key")
    if branch:
        _validate_param(branch, "branch")
    if pull_request:
        _validate_param(pull_request, "pull_request")
    params: list[str] = [
        f"projectKey={project_key}",
        f"ps={page_size}",
    ]
    if statuses:
        _validate_csv(statuses, _VALID_HOTSPOT_STATUSES, "hotspot status")
        params.append(f"status={statuses}")
    if resolution:
        _validate_csv(resolution, _VALID_HOTSPOT_RESOLUTIONS, "hotspot resolution")
        params.append(f"resolution={resolution}")
    if branch:
        params.append(f"branch={branch}")
    if pull_request:
        params.append(f"pullRequest={pull_request}")

    url = f"{SONARCLOUD_API}/hotspots/search?{'&'.join(params)}"
    payload = _http_get(url, token)
    raw_hotspots: list[dict[str, Any]] = payload.get("hotspots", [])
    return [_hotspot_from_raw(raw) for raw in raw_hotspots]


# -- Duplication metric keys -------------------------------------------------

_PROJECT_DUPLICATION_METRICS = (
    "duplicated_lines",
    "duplicated_blocks",
    "duplicated_files",
    "duplicated_lines_density",
    "new_duplicated_lines",
    "new_duplicated_blocks",
    "new_duplicated_lines_density",
)

_FILE_DUPLICATION_METRICS = (
    "duplicated_lines",
    "duplicated_lines_density",
    "duplicated_blocks",
)


def _measures_to_dict(measures: list[dict[str, Any]]) -> dict[str, str]:
    """Convert a SonarCloud measures array to {metric: value}."""
    return {entry["metric"]: entry.get("value", "0") for entry in measures}


def fetch_duplications(
    *,
    project_key: str,
    token: str,
    pull_request: str | None = None,
) -> DuplicationMetrics:
    """Fetch project-level duplication measures via /api/measures/component."""
    _validate_param(project_key, "project_key")
    if pull_request:
        _validate_param(pull_request, "pull_request")
    keys = ",".join(_PROJECT_DUPLICATION_METRICS)
    params = f"component={project_key}&metricKeys={keys}"
    if pull_request:
        params += f"&pullRequest={pull_request}"
    url = f"{SONARCLOUD_API}/measures/component?{params}"
    payload = _http_get(url, token)
    vals = _measures_to_dict(payload.get("component", {}).get("measures", []))
    return DuplicationMetrics(
        duplicated_lines=int(vals.get("duplicated_lines", "0")),
        duplicated_blocks=int(vals.get("duplicated_blocks", "0")),
        duplicated_files=int(vals.get("duplicated_files", "0")),
        duplicated_lines_density=float(vals.get("duplicated_lines_density", "0.0")),
        new_duplicated_lines=int(vals.get("new_duplicated_lines", "0")),
        new_duplicated_blocks=int(vals.get("new_duplicated_blocks", "0")),
        new_duplicated_lines_density=float(vals.get("new_duplicated_lines_density", "0.0")),
    )


def fetch_file_duplications(
    *,
    project_key: str,
    token: str,
    pull_request: str | None = None,
) -> list[FileDuplication]:
    """Fetch per-file duplication via /api/measures/component_tree."""
    _validate_param(project_key, "project_key")
    if pull_request:
        _validate_param(pull_request, "pull_request")
    keys = ",".join(_FILE_DUPLICATION_METRICS)
    params = (
        f"component={project_key}&metricKeys={keys}"
        f"&qualifiers=FIL&s=metric&metricSort=duplicated_lines_density&asc=false"
    )
    if pull_request:
        params += f"&pullRequest={pull_request}"
    url = f"{SONARCLOUD_API}/measures/component_tree?{params}"
    payload = _http_get(url, token)
    result: list[FileDuplication] = []
    for comp in payload.get("components", []):
        vals = _measures_to_dict(comp.get("measures", []))
        dup_lines = int(vals.get("duplicated_lines", "0"))
        if dup_lines == 0:
            continue
        path = comp.get("path", comp.get("key", ""))
        result.append(
            FileDuplication(
                path=path,
                duplicated_lines=dup_lines,
                duplicated_lines_density=float(vals.get("duplicated_lines_density", "0.0")),
                duplicated_blocks=int(vals.get("duplicated_blocks", "0")),
            )
        )
    return result


def fetch_duplication_blocks(
    *,
    file_key: str,
    token: str,
    pull_request: str | None = None,
) -> list[DuplicationGroup]:
    """Fetch block-level duplication via /api/duplications/show."""
    _validate_param(file_key, "file_key")
    if pull_request:
        _validate_param(pull_request, "pull_request")
    params = f"key={file_key}"
    if pull_request:
        params += f"&pullRequest={pull_request}"
    url = f"{SONARCLOUD_API}/duplications/show?{params}"
    payload = _http_get(url, token)
    files_map: dict[str, dict[str, str]] = payload.get("files", {})
    groups: list[DuplicationGroup] = []
    for dup in payload.get("duplications", []):
        refs: list[DuplicationBlockRef] = []
        for block in dup.get("blocks", []):
            ref_id = str(block.get("_ref", ""))
            file_info = files_map.get(ref_id, {})
            refs.append(
                DuplicationBlockRef(
                    file_key=file_info.get("key", ""),
                    file_name=file_info.get("name", ""),
                    from_line=int(block.get("from", 0)),
                    size=int(block.get("size", 0)),
                )
            )
        groups.append(DuplicationGroup(blocks=tuple(refs)))
    return groups


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _escape_md_table(text: str) -> str:
    """Escape characters that break Markdown table cells."""
    return text.replace("|", r"\|").replace("\n", " ")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def format_json(issues: list[SonarIssue]) -> str:
    """Serialize issues to indented JSON."""
    return json.dumps(
        {
            "count": len(issues),
            "issues": [
                {
                    "key": issue.key,
                    "rule": issue.rule,
                    "severity": issue.severity,
                    "type": issue.issue_type,
                    "message": issue.message,
                    "component": issue.component,
                    "line": issue.line,
                    "status": issue.status,
                    "effort": issue.effort,
                }
                for issue in issues
            ],
        },
        indent=2,
        sort_keys=True,
    )


def format_summary(issues: list[SonarIssue]) -> str:
    """Return a human-readable Markdown summary."""
    if not issues:
        return "No SonarCloud issues found."

    lines: list[str] = [f"## SonarCloud Issues ({len(issues)})", ""]
    lines.append("| Severity | Type | File | Line | Message |")
    lines.append("|----------|------|------|------|---------|")
    for issue in issues:
        component = issue.component.split(":")[-1] if ":" in issue.component else issue.component
        line_str = str(issue.line) if issue.line else "—"
        msg = _escape_md_table(issue.message)
        lines.append(f"| {issue.severity} | {issue.issue_type} | `{component}` | {line_str} | {msg} |")
    return "\n".join(lines)


def format_hotspots_json(hotspots: list[SecurityHotspot]) -> str:
    """Serialize security hotspots to indented JSON."""
    return json.dumps(
        {
            "count": len(hotspots),
            "hotspots": [
                {
                    "key": hotspot.key,
                    "rule_key": hotspot.rule_key,
                    "message": hotspot.message,
                    "component": hotspot.component,
                    "security_category": hotspot.security_category,
                    "vulnerability_probability": hotspot.vulnerability_probability,
                    "status": hotspot.status,
                    "line": hotspot.line,
                }
                for hotspot in hotspots
            ],
        },
        indent=2,
        sort_keys=True,
    )


def format_hotspots_summary(hotspots: list[SecurityHotspot]) -> str:
    """Return a human-readable Markdown summary of security hotspots."""
    if not hotspots:
        return "No SonarCloud security hotspots found."

    lines: list[str] = [f"## SonarCloud Security Hotspots ({len(hotspots)})", ""]
    lines.append("| Probability | Category | File | Line | Status | Message |")
    lines.append("|-------------|----------|------|------|--------|---------|")
    for hotspot in hotspots:
        component = hotspot.component.split(":")[-1] if ":" in hotspot.component else hotspot.component
        line_str = str(hotspot.line) if hotspot.line else "\u2014"
        msg = _escape_md_table(hotspot.message)
        lines.append(
            f"| {hotspot.vulnerability_probability} | {hotspot.security_category} "
            f"| `{component}` | {line_str} | {hotspot.status} | {msg} |"
        )
    return "\n".join(lines)


def format_duplications_json(
    metrics: DuplicationMetrics,
    files: list[FileDuplication],
    blocks: dict[str, list[DuplicationGroup]] | None = None,
) -> str:
    """Serialize duplication data to indented JSON."""
    file_entries = []
    for dup in files:
        entry: dict[str, Any] = {
            "path": dup.path,
            "duplicated_lines": dup.duplicated_lines,
            "duplicated_lines_density": dup.duplicated_lines_density,
            "duplicated_blocks": dup.duplicated_blocks,
        }
        if blocks and dup.path in blocks:
            entry["block_details"] = [
                {
                    "blocks": [
                        {
                            "file_key": ref.file_key,
                            "file_name": ref.file_name,
                            "from_line": ref.from_line,
                            "size": ref.size,
                        }
                        for ref in group.blocks
                    ]
                }
                for group in blocks[dup.path]
            ]
        file_entries.append(entry)
    return json.dumps(
        {
            "metrics": {
                "duplicated_lines": metrics.duplicated_lines,
                "duplicated_blocks": metrics.duplicated_blocks,
                "duplicated_files": metrics.duplicated_files,
                "duplicated_lines_density": metrics.duplicated_lines_density,
                "new_duplicated_lines": metrics.new_duplicated_lines,
                "new_duplicated_blocks": metrics.new_duplicated_blocks,
                "new_duplicated_lines_density": metrics.new_duplicated_lines_density,
            },
            "files": file_entries,
        },
        indent=2,
        sort_keys=True,
    )


def _format_block_details(
    files: list[FileDuplication],
    blocks: dict[str, list[DuplicationGroup]],
) -> list[str]:
    """Render the block-detail section of the duplications summary."""
    lines: list[str] = ["", "### Block Details"]
    for dup in files:
        file_blocks = blocks.get(dup.path, [])
        if not file_blocks:
            continue
        lines.append("")
        lines.append(f"**`{dup.path}`**")
        lines.append("")
        for idx, group in enumerate(file_blocks, 1):
            lines.append(f"- Group {idx}:")
            for ref in group.blocks:
                lines.append(f"  - `{ref.file_name}` lines {ref.from_line}\u2013{ref.from_line + ref.size - 1}")
    return lines


def format_duplications_summary(
    metrics: DuplicationMetrics,
    files: list[FileDuplication],
    blocks: dict[str, list[DuplicationGroup]] | None = None,
) -> str:
    """Return a human-readable Markdown summary of duplication data."""
    lines: list[str] = ["## SonarCloud Duplications", ""]
    lines.append(f"- **Duplicated lines:** {metrics.duplicated_lines} ({metrics.duplicated_lines_density}%)")
    lines.append(f"- **Duplicated blocks:** {metrics.duplicated_blocks}")
    lines.append(f"- **Duplicated files:** {metrics.duplicated_files}")
    if metrics.new_duplicated_lines > 0 or metrics.new_duplicated_lines_density > 0:
        lines.append("")
        lines.append("### New Code")
        lines.append(f"- **New duplicated lines:** {metrics.new_duplicated_lines}")
        lines.append(f"- **New duplicated blocks:** {metrics.new_duplicated_blocks}")
        lines.append(f"- **New duplicated lines density:** {metrics.new_duplicated_lines_density}%")
    if files:
        lines.append("")
        lines.append("### Files with Duplications")
        lines.append("")
        lines.append("| File | Dup Lines | Density | Blocks |")
        lines.append("|------|-----------|---------|--------|")
        for dup in files:
            lines.append(
                f"| `{dup.path}` | {dup.duplicated_lines} | {dup.duplicated_lines_density}% | {dup.duplicated_blocks} |"
            )
        if blocks:
            lines.extend(_format_block_details(files, blocks))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Pull SonarCloud findings for a project.",
    )
    parser.add_argument(
        "--project-key",
        default=None,
        help="SonarCloud project key (default: read from sonar-project.properties)",
    )
    parser.add_argument(
        "--types",
        default=None,
        help="Comma-separated issue types: BUG,VULNERABILITY,CODE_SMELL,SECURITY_HOTSPOT",
    )
    parser.add_argument(
        "--severities",
        default=None,
        help="Comma-separated severities: INFO,MINOR,MAJOR,CRITICAL,BLOCKER",
    )
    parser.add_argument(
        "--statuses",
        default=None,
        help="Comma-separated statuses: OPEN,CONFIRMED,REOPENED,RESOLVED,CLOSED",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Branch name to scope findings to",
    )
    parser.add_argument(
        "--pull-request",
        default=None,
        help="PR number to scope findings to",
    )
    parser.add_argument(
        "--duplications",
        action="store_true",
        default=False,
        help="Query duplication measures instead of issues",
    )
    parser.add_argument(
        "--block-details",
        action="store_true",
        default=False,
        help="Include per-file block-level duplication detail (requires --duplications)",
    )
    parser.add_argument(
        "--hotspots",
        action="store_true",
        default=False,
        help="Query security hotspots instead of issues",
    )
    parser.add_argument(
        "--hotspot-statuses",
        default=None,
        help="Comma-separated hotspot statuses: TO_REVIEW,REVIEWED (requires --hotspots)",
    )
    parser.add_argument(
        "--hotspot-resolution",
        default=None,
        help="Hotspot resolution filter: FIXED,SAFE,ACKNOWLEDGED (requires --hotspots)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "summary"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )
    return parser


def _read_project_key() -> str | None:
    """Read project key from ``sonar-project.properties`` if present."""
    try:
        from scripts.common.paths import repo_root

        props_path = repo_root() / "sonar-project.properties"
    except (ImportError, FileNotFoundError):
        props_path = None

    if props_path is None or not props_path.is_file():
        return None

    with props_path.open(encoding="utf-8") as props_file:
        for raw_line in props_file:
            line = raw_line.strip()
            if line.startswith("sonar.projectKey="):
                return line.split("=", 1)[1].strip()
    return None


def _fetch_all_blocks(
    files: list[FileDuplication],
    project_key: str,
    token: str,
    pull_request: str | None = None,
) -> dict[str, list[DuplicationGroup]]:
    """Fetch block-level duplication detail for each duplicated file."""
    blocks: dict[str, list[DuplicationGroup]] = {}
    for dup in files:
        file_key = f"{project_key}:{dup.path}" if ":" not in dup.path else dup.path
        groups = fetch_duplication_blocks(file_key=file_key, token=token, pull_request=pull_request)
        if groups:
            blocks[dup.path] = groups
    return blocks


def _run_duplications(args: argparse.Namespace, project_key: str, token: str) -> str:
    """Fetch and format duplication data based on CLI args."""
    metrics = fetch_duplications(
        project_key=project_key,
        token=token,
        pull_request=args.pull_request,
    )
    files = fetch_file_duplications(
        project_key=project_key,
        token=token,
        pull_request=args.pull_request,
    )
    blocks = _fetch_all_blocks(files, project_key, token, args.pull_request) if files and args.block_details else None
    if args.output_format == "json":
        return format_duplications_json(metrics, files, blocks)
    return format_duplications_summary(metrics, files, blocks)


def _run_issues(args: argparse.Namespace, project_key: str, token: str) -> str:
    """Fetch and format issue data based on CLI args."""
    issues = fetch_issues(
        project_key=project_key,
        token=token,
        types=args.types,
        severities=args.severities,
        statuses=args.statuses,
        branch=args.branch,
        pull_request=args.pull_request,
    )
    if args.output_format == "json":
        return format_json(issues)
    return format_summary(issues)


def _run_hotspots(args: argparse.Namespace, project_key: str, token: str) -> str:
    """Fetch and format security hotspot data based on CLI args."""
    hotspots = fetch_hotspots(
        project_key=project_key,
        token=token,
        statuses=args.hotspot_statuses,
        resolution=args.hotspot_resolution,
        branch=args.branch,
        pull_request=args.pull_request,
    )
    if args.output_format == "json":
        return format_hotspots_json(hotspots)
    return format_hotspots_summary(hotspots)


_ISSUE_ONLY_FLAGS = ("types", "severities", "statuses")
_HOTSPOT_ONLY_FLAGS = ("hotspot_statuses", "hotspot_resolution")


def _used_flags(flags: tuple[str, ...], args: argparse.Namespace) -> list[str]:
    """Return CLI-formatted names of *flags* that are set on *args*."""
    return [f"--{flag.replace('_', '-')}" for flag in flags if getattr(args, flag, None)]


def _validate_mode_flags(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Enforce mutual-exclusivity rules across issue/duplication/hotspot modes."""
    if args.duplications and args.hotspots:
        parser.error("--duplications and --hotspots cannot be combined")
    if args.duplications:
        used = _used_flags(_ISSUE_ONLY_FLAGS, args)
        if args.branch:
            used.append("--branch")
        if used:
            parser.error(f"{', '.join(used)} cannot be combined with --duplications")
    if args.hotspots:
        used = _used_flags(_ISSUE_ONLY_FLAGS, args)
        if used:
            parser.error(f"{', '.join(used)} cannot be combined with --hotspots")
    if not args.hotspots:
        used = _used_flags(_HOTSPOT_ONLY_FLAGS, args)
        if used:
            parser.error(f"{', '.join(used)} requires --hotspots")
    if args.block_details and not args.duplications:
        parser.error("--block-details requires --duplications")


def main() -> int:
    """Entry point for ``python -m scripts.github.sonarcloud_issues``."""
    parser = _build_parser()
    args = parser.parse_args()
    _validate_mode_flags(parser, args)

    project_key = args.project_key or _read_project_key()
    if not project_key:
        print(
            "Error: --project-key not provided and sonar.projectKey not found in sonar-project.properties.",
            file=sys.stderr,
        )
        return 2

    token = os.environ.get("SONAR_TOKEN", "").strip()
    if not token:
        print(
            "Error: SONAR_TOKEN environment variable is not set.",
            file=sys.stderr,
        )
        return 2

    try:
        if args.hotspots:
            output = _run_hotspots(args, project_key, token)
        elif args.duplications:
            output = _run_duplications(args, project_key, token)
        else:
            output = _run_issues(args, project_key, token)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    print(output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
