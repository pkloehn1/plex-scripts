#!/usr/bin/env python3

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_README_BASENAME = "README.md"


_PY_FILENAME_RE = re.compile(r"^[a-z0-9_]+\.py$")

_SH_FILENAME_RE = re.compile(r"^[a-z0-9_]+\.sh$")

_YAML_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.(?:yml|yaml)$")

# Allow optional underscore prefix for internal/template files (e.g., _template-group.md).
_MD_FILENAME_RE = re.compile(r"^_?[a-z0-9]+(?:[.-][a-z0-9]+)*\.md$")

# Allow dot-separated qualifiers like nodes.report.jsonc
_JSON_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*\.(?:json|jsonc)$")

# PowerShell scripts: Verb-Noun.ps1 (PascalCase).
_PS1_VERB_NOUN_RE = re.compile(r"^[A-Z][A-Za-z0-9]*-[A-Z][A-Za-z0-9]*\.ps1$")

# Directory naming
_DIR_SCRIPTS_RE = re.compile(r"^[a-z0-9_]+$")
_DIR_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DIR_FAIL2BAN_RE = re.compile(r"^(?:[a-z0-9]+\.[a-z0-9]+|[a-z0-9]+(?:-[a-z0-9]+)*)$")


@dataclass(frozen=True)
class Finding:
    path: Path
    message: str


def is_valid_python_filename(filename: str) -> bool:
    """Return True if a Python filename matches repo conventions.

    Convention (enforced): snake_case, lowercase, digits and underscores only.

    Examples:
    - ok: run_super_linter.py
    - bad: run-super-linter.py
    """
    return bool(_PY_FILENAME_RE.fullmatch(filename))


def is_valid_shell_filename(filename: str) -> bool:
    """Return True if a shell script filename matches repo conventions.

    Convention (enforced): lowercase snake_case.

    Examples:
    - ok: migrate.sh
    - ok: run_super_linter.sh
    - bad: Run-Thing.sh
    - bad: run-super-linter.sh
    """
    return bool(_SH_FILENAME_RE.fullmatch(filename))


def is_valid_yaml_filename(filename: str) -> bool:
    """Return True if a YAML filename matches repo conventions (kebab-case)."""
    return bool(_YAML_FILENAME_RE.fullmatch(filename))


def is_valid_markdown_filename(filename: str) -> bool:
    """Return True if a Markdown filename matches repo conventions.

    Notes:
    - Allow README.md anywhere.
    - Otherwise enforce kebab-case.
    """
    if filename == _README_BASENAME:
        return True
    return bool(_MD_FILENAME_RE.fullmatch(filename))


def is_valid_json_filename(filename: str) -> bool:
    """Return True if a JSON/JSONC filename matches repo conventions."""
    return bool(_JSON_FILENAME_RE.fullmatch(filename))


def is_valid_powershell_filename(filename: str) -> bool:
    """Return True if a PowerShell filename matches repo conventions.

    Convention (enforced):
    - Required: Verb-Noun.ps1 (PascalCase), aligns with PowerShell naming.
    """
    return bool(_PS1_VERB_NOUN_RE.fullmatch(filename))


def normalized_stem_for_collision(stem: str) -> str:
    return stem.lower().replace("-", "_")


def find_python_filename_violations(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if path.suffix != ".py":
            continue
        if not is_valid_python_filename(path.name):
            findings.append(
                Finding(
                    path=path,
                    message=("Python filename must be lowercase snake_case (letters/digits/underscores only)."),
                )
            )
    return findings


def find_shell_filename_violations(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if path.suffix != ".sh":
            continue
        if not is_valid_shell_filename(path.name):
            findings.append(
                Finding(
                    path=path,
                    message="Shell script filename must be lowercase snake_case.",
                )
            )
    return findings


def find_yaml_filename_violations(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if path.suffix not in {".yml", ".yaml"}:
            continue
        if not is_valid_yaml_filename(path.name):
            findings.append(
                Finding(
                    path=path,
                    message="YAML filename must be lowercase kebab-case.",
                )
            )
    return findings


def find_markdown_filename_violations(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if path.suffix != ".md":
            continue
        if not is_valid_markdown_filename(path.name):
            findings.append(
                Finding(
                    path=path,
                    message="Markdown filename must be README.md or lowercase kebab-case.",
                )
            )
    return findings


def find_json_filename_violations(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if path.suffix not in {".json", ".jsonc"}:
            continue
        if not is_valid_json_filename(path.name):
            findings.append(
                Finding(
                    path=path,
                    message=("JSON/JSONC filename must be lowercase and use '-' or '.' separators."),
                )
            )
    return findings


def find_powershell_filename_violations(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if path.suffix != ".ps1":
            continue
        if not is_valid_powershell_filename(path.name):
            findings.append(
                Finding(
                    path=path,
                    message=("PowerShell filename must be Verb-Noun.ps1 (PascalCase)."),
                )
            )
    return findings


def _is_collision_candidate(path: Path) -> bool:
    return path.is_file() and path.suffix in {
        ".py",
        ".sh",
        ".ps1",
        ".yml",
        ".yaml",
        ".md",
    }


def _group_by_normalized_stem(paths: list[Path]) -> dict[Path, dict[str, list[Path]]]:
    by_dir: dict[Path, dict[str, list[Path]]] = {}

    for path in paths:
        if not _is_collision_candidate(path):
            continue

        directory = path.parent
        norm = normalized_stem_for_collision(path.stem)
        by_dir.setdefault(directory, {}).setdefault(norm, []).append(path)

    return by_dir


def _has_dash_and_underscore(group_paths: list[Path]) -> bool:
    has_dash = any("-" in path.stem for path in group_paths)
    has_underscore = any("_" in path.stem for path in group_paths)
    return has_dash and has_underscore


def _distinct_names(group_paths: list[Path]) -> set[str]:
    return {path.name for path in group_paths}


def _is_cross_platform_script_group(group_paths: list[Path]) -> bool:
    extensions = {path.suffix.lower() for path in group_paths}
    if ".ps1" not in extensions:
        return False
    return ".sh" in extensions or ".py" in extensions


def find_dash_underscore_collisions(paths: list[Path]) -> list[Finding]:
    """Detect confusing pairs like foo-bar.py vs foo_bar.py within the same directory."""
    by_dir = _group_by_normalized_stem(paths)
    findings: list[Finding] = []

    for directory, groups in by_dir.items():
        for norm, group_paths in groups.items():
            if len(group_paths) < 2:
                continue

            names = _distinct_names(group_paths)
            if len(names) < 2:
                continue

            if _has_dash_and_underscore(group_paths) and not _is_cross_platform_script_group(group_paths):
                pretty = ", ".join(sorted(str(path.relative_to(directory)) for path in group_paths))
                findings.append(
                    Finding(
                        path=directory,
                        message=(f"Confusing dash/underscore filename collision for '{norm}' in {directory}: {pretty}"),
                    )
                )

    return findings


def _is_dir_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _directory_rule_for_path(path: Path, repo_root: Path) -> tuple[re.Pattern[str], str] | None:
    scripts_root = repo_root / "scripts"
    docs_root = repo_root / "docs"
    app_config_root = repo_root / "app-config"
    fail2ban_root = app_config_root / "fail2ban"

    if _is_dir_under(path, scripts_root):
        return (
            _DIR_SCRIPTS_RE,
            "scripts/ directory names must be lowercase with underscores only.",
        )

    if _is_dir_under(path, docs_root) or _is_dir_under(path, app_config_root):
        if _is_dir_under(path, fail2ban_root):
            return (
                _DIR_FAIL2BAN_RE,
                "app-config/fail2ban directory names must be lowercase and may use kebab-case or '*.d' (fail2ban convention).",
            )
        return (
            _DIR_KEBAB_RE,
            "docs/ and app-config/ directory names must be lowercase kebab-case.",
        )

    return None


def find_directory_name_violations(paths: list[Path], repo_root: Path) -> list[Finding]:
    """Validate directory naming conventions and forbid spaces.

    Rules are scoped by top-level area to match how the repo is structured:
    - scripts/**: must be valid Python-package-friendly (lowercase, underscores ok, no dashes).
    - docs/**, app-config/**: kebab-case.
    - All checked dirs: no spaces.
    """
    findings: list[Finding] = []
    for path in paths:
        if not path.is_dir():
            continue

        name = path.name
        if " " in name:
            findings.append(Finding(path=path, message="Directory names must not contain spaces."))
            continue

        rule = _directory_rule_for_path(path, repo_root=repo_root)
        if rule is None:
            continue

        pattern, message = rule
        if not pattern.fullmatch(name):
            findings.append(Finding(path=path, message=message))

    return findings


def find_path_space_violations(paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if " " in path.name:
            findings.append(
                Finding(
                    path=path,
                    message="File and directory names must not contain spaces.",
                )
            )
    return findings


def _iter_tree(root: Path) -> list[Path]:
    if not root.exists():
        return []
    # Include both files and directories.
    return list(root.rglob("*"))


def collect_candidate_paths(repo_root: Path) -> list[Path]:
    # Scope to key repo content (avoid scanning tool/venv directories).
    paths: list[Path] = []

    for rel in ("scripts", "docs", "stacks", "app-config"):
        paths.extend(_iter_tree(repo_root / rel))

    # Include key top-level files for naming checks.
    for rel in ("README.md", "docker-compose.yml"):
        top_level_path = repo_root / rel
        if top_level_path.exists():
            paths.append(top_level_path)

    # Keep only paths inside repo root.
    return [path for path in paths if path.exists()]


def main() -> int:
    from scripts.common.paths import repo_root as _find_repo_root

    repo_root = _find_repo_root()
    paths = collect_candidate_paths(repo_root)

    findings: list[Finding] = []

    # Generic path constraints
    findings.extend(find_path_space_violations(paths))
    findings.extend(find_directory_name_violations(paths, repo_root=repo_root))

    # Filetype-specific checks
    findings.extend(find_python_filename_violations(paths))
    findings.extend(find_shell_filename_violations(paths))
    findings.extend(find_powershell_filename_violations(paths))
    findings.extend(find_yaml_filename_violations(paths))
    findings.extend(find_markdown_filename_violations(paths))
    findings.extend(find_json_filename_violations(paths))

    # Confusion prevention
    findings.extend(find_dash_underscore_collisions(paths))

    if not findings:
        return 0

    for finding in findings:
        try:
            rel = finding.path.relative_to(repo_root)
        except ValueError:
            rel = finding.path
        print(f"{rel}: {finding.message}")

    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
