"""Tests for pytest_affected module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.precommit.pytest_affected import (
    SuiteTarget,
    _is_merge_mode,
    build_pytest_args,
    discover_test_targets,
    main,
    map_files_to_packages,
    run_pytest,
)

# -- map_files_to_packages ----------------------------------------------------


def test_map_standard_package() -> None:
    files = ["scripts/ci/some_module.py"]
    assert map_files_to_packages(files) == {"ci"}


def test_map_multiple_packages() -> None:
    files = [
        "scripts/ci/foo.py",
        "scripts/github/bar.py",
        "scripts/linting/baz.py",
    ]
    assert map_files_to_packages(files) == {"ci", "github", "linting"}


def test_map_testing_hooks_special_case() -> None:
    files = ["scripts/testing/hooks/check_something.py"]
    assert map_files_to_packages(files) == {"testing/hooks"}


def test_map_stacks_triggers_ci() -> None:
    files = ["stacks/foo/docker-compose.yml"]
    assert map_files_to_packages(files) == {"ci"}


def test_map_image_service_map_triggers_ci() -> None:
    files = [".github/image-service-map.json"]
    assert map_files_to_packages(files) == {"ci"}


def test_map_non_python_files_ignored() -> None:
    files = ["scripts/ci/README.md", "docs/something.md"]
    assert map_files_to_packages(files) == set()


def test_map_shallow_scripts_path_ignored() -> None:
    files = ["scripts/__init__.py"]
    assert map_files_to_packages(files) == set()


def test_map_empty_input() -> None:
    assert map_files_to_packages([]) == set()


def test_map_windows_paths_normalized() -> None:
    files = ["scripts\\github\\pr_upsert.py"]
    assert map_files_to_packages(files) == {"github"}


def test_map_dot_slash_prefix_stripped() -> None:
    files = ["./stacks/foo/docker-compose.yml"]
    assert map_files_to_packages(files) == {"ci"}


# -- discover_test_targets ----------------------------------------------------


def test_discover_existing_package(tmp_path: Path) -> None:
    test_dir = tmp_path / "scripts" / "ci" / "tests"
    test_dir.mkdir(parents=True)
    with patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path):
        result = discover_test_targets({"ci"})
    assert len(result.targets) == 1
    assert result.targets[0].package == "ci"
    assert result.skipped_packages == ()


def test_discover_missing_package(tmp_path: Path) -> None:
    with patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path):
        result = discover_test_targets({"nonexistent"})
    assert len(result.targets) == 0
    assert result.skipped_packages == ("nonexistent",)


def test_discover_testing_hooks(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "scripts" / "testing" / "hooks"
    hooks_dir.mkdir(parents=True)
    with patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path):
        result = discover_test_targets({"testing/hooks"})
    assert len(result.targets) == 1
    assert result.targets[0].package == "testing/hooks"


def test_discover_testing_includes_hooks(tmp_path: Path) -> None:
    """When 'testing' is in packages, 'testing/hooks' is auto-included."""
    tests_dir = tmp_path / "scripts" / "testing" / "tests"
    tests_dir.mkdir(parents=True)
    hooks_dir = tmp_path / "scripts" / "testing" / "hooks"
    hooks_dir.mkdir(parents=True)
    with patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path):
        result = discover_test_targets({"testing"})
    packages = {target.package for target in result.targets}
    assert "testing" in packages
    assert "testing/hooks" in packages


def test_discover_mixed_existing_and_missing(tmp_path: Path) -> None:
    ci_tests = tmp_path / "scripts" / "ci" / "tests"
    ci_tests.mkdir(parents=True)
    with patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path):
        result = discover_test_targets({"ci", "missing_pkg"})
    assert len(result.targets) == 1
    assert result.skipped_packages == ("missing_pkg",)


# -- _is_merge_mode -----------------------------------------------------------


def test_merge_mode_off_by_default() -> None:
    with patch.dict("os.environ", {}, clear=True):
        assert _is_merge_mode() is False


def test_merge_mode_on_when_set() -> None:
    with patch.dict("os.environ", {"COVERAGE_MERGE_MODE": "1"}):
        assert _is_merge_mode() is True


def test_merge_mode_off_for_other_values() -> None:
    with patch.dict("os.environ", {"COVERAGE_MERGE_MODE": "0"}):
        assert _is_merge_mode() is False


# -- build_pytest_args --------------------------------------------------------


def test_build_pytest_args_single_target() -> None:
    targets = (SuiteTarget(package="ci", test_dir="scripts/ci/tests"),)
    args = build_pytest_args(targets)
    assert args == [
        "-m",
        "pytest",
        "-q",
        "--cov=scripts/ci",
        "scripts/ci/tests",
        "--cov-fail-under=100",
    ]


def test_build_pytest_args_multiple_targets() -> None:
    targets = (
        SuiteTarget(package="ci", test_dir="scripts/ci/tests"),
        SuiteTarget(package="github", test_dir="scripts/github/tests"),
    )
    args = build_pytest_args(targets)
    assert args == [
        "-m",
        "pytest",
        "-q",
        "--cov=scripts/ci",
        "scripts/ci/tests",
        "--cov=scripts/github",
        "scripts/github/tests",
        "--cov-fail-under=100",
    ]


def test_build_pytest_args_merge_mode_omits_threshold() -> None:
    targets = (SuiteTarget(package="ci", test_dir="scripts/ci/tests"),)
    args = build_pytest_args(targets, merge_mode=True)
    assert "--cov-fail-under=100" not in args


def test_build_pytest_args_testing_package_uses_cov_config() -> None:
    targets = (SuiteTarget(package="testing", test_dir="scripts/testing/tests"),)
    args = build_pytest_args(targets)
    assert "--cov-config=.github/coverage/testing.toml" in args


def test_build_pytest_args_non_testing_package_no_cov_config() -> None:
    targets = (SuiteTarget(package="ci", test_dir="scripts/ci/tests"),)
    args = build_pytest_args(targets)
    assert all("--cov-config" not in arg for arg in args)


# -- run_pytest ---------------------------------------------------------------


def test_run_pytest_delegates_to_subprocess() -> None:
    targets = (SuiteTarget(package="ci", test_dir="scripts/ci/tests"),)
    with patch("scripts.precommit.pytest_affected.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        assert run_pytest(targets) == 0
        call_kwargs = mock_run.call_args
        assert "COVERAGE_FILE" in call_kwargs.kwargs["env"]
        assert call_kwargs.kwargs["env"]["COVERAGE_FILE"].endswith(".coverage")


def test_run_pytest_uses_temp_coverage_file() -> None:
    targets = (SuiteTarget(package="ci", test_dir="scripts/ci/tests"),)
    with patch("scripts.precommit.pytest_affected.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        run_pytest(targets)
        cov_path = mock_run.call_args.kwargs["env"]["COVERAGE_FILE"]
    assert not Path(cov_path).exists()


def test_run_pytest_propagates_failure() -> None:
    targets = (SuiteTarget(package="ci", test_dir="scripts/ci/tests"),)
    with patch("scripts.precommit.pytest_affected.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        assert run_pytest(targets) == 1


def test_run_pytest_merge_mode_preserves_coverage(tmp_path: Path) -> None:
    targets = (SuiteTarget(package="ci", test_dir="scripts/ci/tests"),)
    sentinel = tmp_path / ".coverage"
    sentinel.write_text("sentinel")
    with (
        patch.dict("os.environ", {"COVERAGE_MERGE_MODE": "1"}),
        patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path),
        patch("scripts.precommit.pytest_affected.subprocess.run") as mock_run,
    ):
        mock_run.return_value.returncode = 0
        run_pytest(targets)
        cov_path = mock_run.call_args.kwargs["env"]["COVERAGE_FILE"]
    assert cov_path == str(sentinel)
    assert sentinel.exists(), "merge mode must not delete the coverage file"


# -- main ---------------------------------------------------------------------


def test_main_no_files() -> None:
    assert main(["pytest_affected.py"]) == 0


def test_main_no_matching_packages() -> None:
    assert main(["pytest_affected.py", "docs/readme.md"]) == 0


def test_main_no_existing_test_dirs(tmp_path: Path) -> None:
    with patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path):
        assert main(["pytest_affected.py", "scripts/missing/foo.py"]) == 0


def test_main_prints_skipped_packages(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ci_tests = tmp_path / "scripts" / "ci" / "tests"
    ci_tests.mkdir(parents=True)
    with (
        patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path),
        patch("scripts.precommit.pytest_affected.run_pytest", return_value=0),
    ):
        exit_code = main(
            ["pytest_affected.py", "scripts/ci/foo.py", "scripts/missing/bar.py"],
        )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Skipped: scripts/missing/tests does not exist" in captured.out


def test_main_skip_message_testing_hooks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ci_tests = tmp_path / "scripts" / "ci" / "tests"
    ci_tests.mkdir(parents=True)
    with (
        patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path),
        patch("scripts.precommit.pytest_affected.run_pytest", return_value=0),
    ):
        exit_code = main(
            [
                "pytest_affected.py",
                "scripts/ci/foo.py",
                "scripts/testing/hooks/check_something.py",
            ],
        )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Skipped: scripts/testing/hooks does not exist" in captured.out


def test_main_runs_pytest(tmp_path: Path) -> None:
    test_dir = tmp_path / "scripts" / "ci" / "tests"
    test_dir.mkdir(parents=True)
    with (
        patch("scripts.precommit.pytest_affected.repo_root", return_value=tmp_path),
        patch("scripts.precommit.pytest_affected.run_pytest", return_value=0) as mock_run,
    ):
        exit_code = main(["pytest_affected.py", "scripts/ci/some.py"])
    assert exit_code == 0
    mock_run.assert_called_once()
