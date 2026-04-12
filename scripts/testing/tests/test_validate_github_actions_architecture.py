from __future__ import annotations

from pathlib import Path

import pytest

from scripts.testing.validate_github_actions_architecture import (
    Violation,
    _format_violation,
    _iter_workflow_files,
    _repo_root,
    main,
    validate_action_pinning,
    validate_job_permissions,
    validate_orchestrator_purity,
    validate_repo,
    validate_reusable_workflow_call,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "workflows"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Happy path: zero-trust workflow-level + job-level permissions
# ---------------------------------------------------------------------------


def test_validate_repo_passes_with_zero_trust_permissions(tmp_path: Path) -> None:
    """Canonical pattern: `permissions: {}` at workflow + explicit job-level."""
    root = tmp_path
    content = (_FIXTURES / "zero-trust-permissions.yml").read_text(encoding="utf-8")

    _write(root / ".github/workflows/super-linter.yml", content)

    violations = validate_repo(root)
    assert violations == []


def test_validate_repo_passes_with_multiline_workflow_permissions(tmp_path: Path) -> None:
    """Legacy pattern: multi-line workflow-level permissions still passes PERM001."""
    root = tmp_path
    content = (_FIXTURES / "multiline-workflow-permissions.yml").read_text(
        encoding="utf-8",
    )

    _write(root / ".github/workflows/ci.yml", content)

    violations = validate_repo(root)
    assert violations == []


# ---------------------------------------------------------------------------
# PERM001: Missing top-level permissions
# ---------------------------------------------------------------------------


def test_perm001_missing_top_level_permissions(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "missing-top-level-permissions.yml").read_text(
        encoding="utf-8",
    )
    _write(root / ".github/workflows/workflow.yml", content)

    violations = validate_repo(root)
    codes = {vio.code for vio in violations}
    assert codes == {"PERM001"}


# ---------------------------------------------------------------------------
# PERM002: Job missing permissions
# ---------------------------------------------------------------------------


def test_perm002_job_missing_permissions(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "job-missing-permissions.yml").read_text(encoding="utf-8")
    _write(root / ".github/workflows/workflow.yml", content)

    violations = validate_repo(root)
    codes = {vio.code for vio in violations}
    assert codes == {"PERM002"}


def test_perm002_one_job_missing_permissions_of_two(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "one-job-missing-permissions.yml").read_text(
        encoding="utf-8",
    )
    _write(root / ".github/workflows/workflow.yml", content)

    violations = validate_repo(root)
    perm002 = [vio for vio in violations if vio.code == "PERM002"]
    assert len(perm002) == 1
    assert "deploy" in perm002[0].message


def test_perm002_all_jobs_have_permissions(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "all-jobs-have-permissions.yml").read_text(encoding="utf-8")
    _write(root / ".github/workflows/workflow.yml", content)

    violations = validate_repo(root)
    assert violations == []


# ---------------------------------------------------------------------------
# PERM001 + PERM002: Both missing
# ---------------------------------------------------------------------------


def test_perm001_and_perm002_both_missing(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "both-permissions-missing.yml").read_text(encoding="utf-8")
    _write(root / ".github/workflows/workflow.yml", content)

    violations = validate_repo(root)
    codes = {vio.code for vio in violations}
    assert codes == {"PERM001", "PERM002"}


# ---------------------------------------------------------------------------
# PIN001 / PIN002: Action pinning
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture_name", "expected_codes"),
    [
        ("action-no-version.yml", {"PIN001"}),
        ("action-semver-range.yml", {"PIN002"}),
    ],
)
def test_validate_repo_finds_expected_violations(tmp_path: Path, fixture_name: str, expected_codes: set[str]) -> None:
    root = tmp_path
    content = (_FIXTURES / fixture_name).read_text(encoding="utf-8")
    _write(root / ".github/workflows/workflow.yml", content)

    violations = validate_repo(root)
    codes = {vio.code for vio in violations}
    assert codes == expected_codes


# ---------------------------------------------------------------------------
# REUSE001: Reusable workflows must define workflow_call
# ---------------------------------------------------------------------------


def test_reusable_workflow_requires_workflow_call(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "reusable-missing-workflow-call.yml").read_text(
        encoding="utf-8",
    )
    _write(root / ".github/workflows/reusable/reuse.yml", content)

    violations = validate_repo(root)
    assert any(vio.code == "REUSE001" for vio in violations)


# ---------------------------------------------------------------------------
# PLACE002: Root workflows must not be reusable-only
# ---------------------------------------------------------------------------


def test_root_workflow_must_not_contain_workflow_call(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "root-workflow-call.yml").read_text(encoding="utf-8")
    _write(root / ".github/workflows/root.yml", content)

    violations = validate_repo(root)
    assert any(vio.code == "PLACE002" for vio in violations)


# ---------------------------------------------------------------------------
# SYNC001: sync-labels: true causes flapping
# ---------------------------------------------------------------------------


def test_sync_labels_true_triggers_sync001(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "sync-labels-true.yml").read_text(encoding="utf-8")
    _write(root / ".github/workflows/labeler.yml", content)

    violations = validate_repo(root)
    assert any(vio.code == "SYNC001" for vio in violations)


def test_sync_labels_false_passes(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "sync-labels-false.yml").read_text(encoding="utf-8")
    _write(root / ".github/workflows/labeler.yml", content)

    violations = validate_repo(root)
    assert not any(vio.code == "SYNC001" for vio in violations)


# ---------------------------------------------------------------------------
# ORCH001: Orchestrator purity
# ---------------------------------------------------------------------------


def test_orchestrator_must_not_use_run_or_shell(tmp_path: Path) -> None:
    root = tmp_path
    content = (_FIXTURES / "orchestrator-with-run.yml").read_text(encoding="utf-8")
    _write(root / ".github/workflows/orchestrators/orch.yml", content)

    violations = validate_repo(root)
    assert any(vio.code == "ORCH001" for vio in violations)


def test_orchestrator_clean_passes(tmp_path: Path) -> None:
    content = (
        "on: workflow_dispatch\n"
        "permissions: {}\n"
        "jobs:\n"
        "  call:\n"
        "    permissions:\n"
        "      contents: read\n"
        "    uses: ./.github/workflows/reusable/build.yml\n"
    )
    _write(tmp_path / ".github/workflows/orchestrators/clean.yml", content)
    violations = validate_repo(tmp_path)
    assert not any(vio.code == "ORCH001" for vio in violations)


# ---------------------------------------------------------------------------
# _repo_root
# ---------------------------------------------------------------------------


def test_repo_root_with_explicit_path(tmp_path: Path) -> None:
    result = _repo_root(str(tmp_path))
    assert result == tmp_path.resolve()


def test_repo_root_without_explicit_path() -> None:
    from scripts.common.paths import repo_root

    result = _repo_root(None)
    assert result == repo_root()


# ---------------------------------------------------------------------------
# _iter_workflow_files
# ---------------------------------------------------------------------------


def test_iter_workflow_files_missing_dir(tmp_path: Path) -> None:
    result = _iter_workflow_files(tmp_path / "nonexistent")
    assert result == []


# ---------------------------------------------------------------------------
# validate_job_permissions — no jobs section
# ---------------------------------------------------------------------------


def test_validate_job_permissions_no_jobs_section() -> None:
    text = "on: push\npermissions: {}\n"
    violations = validate_job_permissions(Path("test.yml"), text)
    assert violations == []


# ---------------------------------------------------------------------------
# validate_action_pinning — local and docker skips
# ---------------------------------------------------------------------------


def test_validate_action_pinning_skips_local_action() -> None:
    text = "    - uses: ./local-action\n"
    violations = validate_action_pinning(Path("test.yml"), text)
    assert violations == []


def test_validate_action_pinning_skips_docker_action() -> None:
    text = "    - uses: docker://alpine:3.18\n"
    violations = validate_action_pinning(Path("test.yml"), text)
    assert violations == []


# ---------------------------------------------------------------------------
# validate_reusable_workflow_call — workflow_call present
# ---------------------------------------------------------------------------


def test_validate_reusable_workflow_call_present() -> None:
    text = "on:\n  workflow_call:\n"
    violations = validate_reusable_workflow_call(Path("test.yml"), text)
    assert violations == []


# ---------------------------------------------------------------------------
# validate_orchestrator_purity — clean orchestrator
# ---------------------------------------------------------------------------


def test_validate_orchestrator_purity_clean() -> None:
    text = "jobs:\n  call:\n    uses: ./.github/workflows/reusable/build.yml\n"
    violations = validate_orchestrator_purity(Path("test.yml"), text)
    assert violations == []


# ---------------------------------------------------------------------------
# _format_violation
# ---------------------------------------------------------------------------


def test_format_violation_without_line() -> None:
    vio = Violation(code="TEST001", path=Path("file.yml"), message="msg")
    assert _format_violation(vio) == "TEST001: file.yml: msg"


def test_format_violation_with_line() -> None:
    vio = Violation(code="TEST001", path=Path("file.yml"), message="msg", line=42)
    assert _format_violation(vio) == "TEST001: file.yml:42: msg"


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------


def test_main_returns_zero_on_clean_repo(tmp_path: Path) -> None:
    content = (
        "on: push\n"
        "permissions: {}\n"
        "jobs:\n"
        "  build:\n"
        "    permissions:\n"
        "      contents: read\n"
        "    uses: actions/checkout@v4\n"
    )
    _write(tmp_path / ".github/workflows/ci.yml", content)
    assert main(["--root", str(tmp_path)]) == 0


def test_main_returns_one_on_violations(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    content = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
    _write(tmp_path / ".github/workflows/ci.yml", content)
    assert main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert "PERM001" in captured.out


def test_main_no_args_uses_repo_root() -> None:
    result = main([])
    assert result in (0, 1)
