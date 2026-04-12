"""Dynamic pytest runner that auto-discovers test targets from changed files.

Replaces static per-package ``pytest-*-scripts`` hooks with a single
``pytest-affected`` hook.  Maps changed file paths to ``scripts/<pkg>``
packages, discovers which test directories exist, and runs pytest.

Wrapper chain::

    run_python -> run_in_repo_venv.py -> run_if_exists.py
        -> pytest_affected.py <changed_files...>
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from scripts.common.paths import normalize_path, repo_root

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Special file patterns that map to specific packages.
_EXTRA_CI_PATTERNS: tuple[str, ...] = (
    "stacks/",
    ".github/image-service-map.json",
)

# Package whose tests live alongside the code (no separate tests/ subdir).
_SELF_TESTING_PACKAGE = "testing/hooks"

# Coverage config for packages that need non-default omit patterns.
_PACKAGE_COV_CONFIG: dict[str, str] = {
    "testing": ".github/coverage/testing.toml",
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SuiteTarget:
    """A discovered test suite and its source package."""

    package: str  # e.g. "ci", "github", "testing/hooks"
    test_dir: str  # absolute path to test directory


@dataclass(frozen=True)
class AffectedResult:
    """Mapping result from changed files to test targets."""

    packages: frozenset[str]
    targets: tuple[SuiteTarget, ...]
    skipped_packages: tuple[str, ...] = field(default=())


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def _is_ci_trigger(normalized: str) -> bool:
    """Check whether a normalized path triggers the ``ci`` package."""
    return any(normalized.startswith(pat) or normalized == pat.rstrip("/") for pat in _EXTRA_CI_PATTERNS)


def _extract_package(normalized: str) -> str | None:
    """Extract a package name from a normalized ``scripts/...`` path."""
    if not normalized.startswith("scripts/") or not normalized.endswith(".py"):
        return None
    parts = normalized.split("/")
    if len(parts) < 3:
        return None
    if len(parts) >= 4 and parts[1] == "testing" and parts[2] == "hooks":
        return _SELF_TESTING_PACKAGE
    return parts[1]


def map_files_to_packages(changed_files: list[str]) -> set[str]:
    """Map changed file paths to package names.

    Rules:
    - ``scripts/<pkg>/**/*.py`` maps to ``<pkg>``
    - ``scripts/testing/hooks/**/*.py`` maps to ``testing/hooks``
    - ``stacks/**`` and ``.github/image-service-map.json`` map to ``ci``
    """
    packages: set[str] = set()
    for filepath in changed_files:
        normalized = normalize_path(filepath)
        if _is_ci_trigger(normalized):
            packages.add("ci")
        package = _extract_package(normalized)
        if package is not None:
            packages.add(package)
    return packages


def _resolve_test_target(package: str, root: Path) -> SuiteTarget | None:
    """Resolve a package name to a test target, if the test dir exists."""
    if package == _SELF_TESTING_PACKAGE:
        test_dir = root / "scripts" / "testing" / "hooks"
    else:
        test_dir = root / "scripts" / package / "tests"

    if not test_dir.is_dir():
        return None

    return SuiteTarget(package=package, test_dir=str(test_dir))


def discover_test_targets(packages: set[str]) -> AffectedResult:
    """Discover existing test directories for the given packages."""
    if "testing" in packages:
        packages = packages | {_SELF_TESTING_PACKAGE}
    root = repo_root()
    targets: list[SuiteTarget] = []
    skipped: list[str] = []

    for package in sorted(packages):
        target = _resolve_test_target(package, root)
        if target is not None:
            targets.append(target)
        else:
            skipped.append(package)

    return AffectedResult(
        packages=frozenset(packages),
        targets=tuple(targets),
        skipped_packages=tuple(skipped),
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _is_merge_mode() -> bool:
    """Check whether coverage merge mode is active.

    When ``COVERAGE_MERGE_MODE=1`` is set, the threshold check is deferred
    to a downstream merge job and the coverage file is preserved.
    """
    return os.environ.get("COVERAGE_MERGE_MODE") == "1"


def build_pytest_args(targets: tuple[SuiteTarget, ...], *, merge_mode: bool = False) -> list[str]:
    """Build a pytest command-line from discovered targets."""
    args = ["-m", "pytest", "-q"]
    for target in targets:
        args.extend([f"--cov=scripts/{target.package}", target.test_dir])
        cov_config = _PACKAGE_COV_CONFIG.get(target.package)
        if cov_config:
            args.append(f"--cov-config={cov_config}")
    if not merge_mode:
        args.append("--cov-fail-under=100")
    return args


def run_pytest(targets: tuple[SuiteTarget, ...]) -> int:
    """Execute pytest for the given targets."""
    merge_mode = _is_merge_mode()
    args = build_pytest_args(targets, merge_mode=merge_mode)
    cmd = [sys.executable, *args]
    if merge_mode:
        cov_path = str(repo_root() / ".coverage")
    else:
        with tempfile.NamedTemporaryFile(suffix=".coverage", delete=False) as tmp:
            cov_path = tmp.name
    env = {**os.environ, "COVERAGE_FILE": cov_path}
    try:
        result = subprocess.run(cmd, check=False, env=env)
    finally:
        if not merge_mode:
            Path(cov_path).unlink(missing_ok=True)
    return result.returncode


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    """Entry point: receives changed file paths as arguments."""
    changed_files = argv[1:]
    if not changed_files:
        return 0

    packages = map_files_to_packages(changed_files)
    if not packages:
        return 0

    result = discover_test_targets(packages)
    if not result.targets:
        return 0

    for skipped in result.skipped_packages:
        if skipped == _SELF_TESTING_PACKAGE:
            skipped_path = f"scripts/{skipped}"
        else:
            skipped_path = f"scripts/{skipped}/tests"
        print(f"Skipped: {skipped_path} does not exist")

    return run_pytest(result.targets)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))  # pragma: no cover
