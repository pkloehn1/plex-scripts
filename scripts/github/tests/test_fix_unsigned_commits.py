"""Tests for fix_unsigned_commits module."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.fix_unsigned_commits import (
    _build_parser,
    _print_json_output,
    _print_text_output,
    check_git_signing_config,
    fix_unsigned_commits,
    force_push_branch,
    get_current_branch,
    get_pr_branch_info,
    rebase_to_resign_commits,
    verify_commits_signed,
    verify_local_branch,
)
from scripts.github.gh_cli import GhCliError

_REPO = "octo/widgets"
_PR_NUMBER = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed_process(
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _raise_oserror(*_args: Any, **_kwargs: Any) -> None:
    raise OSError("mocked chmod failure")


def _pr_api_payload(
    head_ref: str = "fix/branch",
    base_ref: str = "main",
    head_sha: str = "abc1234",
) -> dict[str, Any]:
    return {
        "head": {"ref": head_ref, "sha": head_sha},
        "base": {"ref": base_ref},
    }


def _commit_entry(
    sha: str = "aaa1111",
    verified: bool = True,
    reason: str = "valid",
) -> dict[str, Any]:
    return {
        "sha": sha,
        "html_url": f"https://github.com/{_REPO}/commit/{sha}",
        "subject": "some commit",
        "verified": verified,
        "reason": reason,
        "signature": None,
        "payload": None,
        "verified_at": None,
        "author": {},
        "committer": {},
    }


# ---------------------------------------------------------------------------
# check_git_signing_config
# ---------------------------------------------------------------------------


class TestCheckGitSigningConfig:
    def test_configured_true(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        key_file = tmp_path / "id_ed25519.pub"
        key_file.write_text("ssh-ed25519 AAAA...")

        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.git_config_value",
            lambda key: {
                "commit.gpgsign": "true",
                "gpg.format": "ssh",
                "user.signingkey": str(key_file),
                "user.email": "dev@example.com",
                "user.name": "Dev",
            }[key],
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.find_signing_key_path",
            lambda _signingkey: key_file,
        )

        result = check_git_signing_config()

        assert result["configured"] is True
        assert result["commit_gpgsign"] == "true"
        assert result["gpg_format"] == "ssh"
        assert result["signingkey_path"] == str(key_file)

    def test_configured_false_missing_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.git_config_value",
            lambda key: {
                "commit.gpgsign": "true",
                "gpg.format": "ssh",
                "user.signingkey": None,
                "user.email": "dev@example.com",
                "user.name": "Dev",
            }[key],
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.find_signing_key_path",
            lambda _signingkey: None,
        )

        result = check_git_signing_config()

        assert result["configured"] is False
        assert result["signingkey_path"] is None

    def test_exception_populates_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.git_config_value",
            lambda _key: (_ for _ in ()).throw(OSError("git not found")),
        )

        result = check_git_signing_config()

        assert result["configured"] is False
        assert "git not found" in result["error"]


# ---------------------------------------------------------------------------
# get_pr_branch_info
# ---------------------------------------------------------------------------


class TestGetPrBranchInfo:
    def test_success(self) -> None:
        payload = _pr_api_payload(head_ref="feat/x", base_ref="main", head_sha="deadbeef")
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", f"/repos/octo/widgets/pulls/{_PR_NUMBER}"],
                    stdout=json.dumps(payload),
                ),
            ]
        )

        info = get_pr_branch_info(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)

        assert info["head_ref"] == "feat/x"
        assert info["base_ref"] == "main"
        assert info["head_sha"] == "deadbeef"
        runner.assert_exhausted()

    def test_non_dict_payload_raises(self) -> None:
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", f"/repos/octo/widgets/pulls/{_PR_NUMBER}"],
                    stdout=json.dumps([1, 2, 3]),
                ),
            ]
        )

        with pytest.raises(ValueError, match="Unexpected PR payload"):
            get_pr_branch_info(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)

    def test_missing_head_ref_raises(self) -> None:
        payload = {"head": {"ref": "", "sha": "abc"}, "base": {"ref": "main"}}
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", f"/repos/octo/widgets/pulls/{_PR_NUMBER}"],
                    stdout=json.dumps(payload),
                ),
            ]
        )

        with pytest.raises(ValueError, match="head ref"):
            get_pr_branch_info(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)

    def test_missing_base_ref_raises(self) -> None:
        payload = {"head": {"ref": "feat/x", "sha": "abc"}, "base": {"ref": ""}}
        runner = QueueRunner(
            [
                ExpectedCall(
                    argv=["gh", "api", f"/repos/octo/widgets/pulls/{_PR_NUMBER}"],
                    stdout=json.dumps(payload),
                ),
            ]
        )

        with pytest.raises(ValueError, match="base ref"):
            get_pr_branch_info(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)


# ---------------------------------------------------------------------------
# verify_local_branch
# ---------------------------------------------------------------------------


class TestVerifyLocalBranch:
    def test_branch_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(returncode=0),
        )
        assert verify_local_branch(branch="feat/x") is True

    def test_branch_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(returncode=1, stderr="not a valid ref"),
        )
        assert verify_local_branch(branch="no-such") is False


# ---------------------------------------------------------------------------
# get_current_branch
# ---------------------------------------------------------------------------


class TestGetCurrentBranch:
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(stdout="feat/x\n"),
        )
        assert get_current_branch() == "feat/x"

    def test_failure_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(returncode=128),
        )
        assert get_current_branch() is None


# ---------------------------------------------------------------------------
# rebase_to_resign_commits
# ---------------------------------------------------------------------------


class TestRebaseToResignCommits:
    def test_dry_run(self) -> None:
        result = rebase_to_resign_commits(base_ref="main", apply=False)

        assert result["status"] == "dry_run"
        assert "--apply" in result["message"]

    def test_apply_fetch_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(returncode=1, stderr="fetch failed"),
        )

        result = rebase_to_resign_commits(base_ref="main", apply=True)

        assert result["status"] == "error"
        assert "fetch failed" in result["error"]

    def test_apply_rebase_fail_with_conflict_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        def mock_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # fetch succeeds
                return _completed_process(returncode=0)
            # rebase fails
            return _completed_process(returncode=1, stderr="CONFLICT")

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.subprocess.run", mock_subprocess_run)

        # Monkeypatch Path.exists to simulate .git/rebase-merge existing,
        # avoiding filesystem manipulation that races with parallel test runners.
        _real_exists = Path.exists

        def _fake_exists(self: Path) -> bool:
            if self == Path(".git") / "rebase-merge":
                return True
            return _real_exists(self)

        monkeypatch.setattr(Path, "exists", _fake_exists)

        result = rebase_to_resign_commits(base_ref="main", apply=True)

        assert result["status"] == "conflict"
        assert "Rebase conflicts" in result["error"]

    def test_apply_rebase_fail_no_conflict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        def mock_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _completed_process(returncode=0)
            return _completed_process(returncode=1, stderr="rebase error")

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.subprocess.run", mock_subprocess_run)

        # Monkeypatch Path.exists to ensure rebase dirs report absent,
        # avoiding races with parallel test runners manipulating .git/.
        _real_exists = Path.exists

        def _fake_exists(self: Path) -> bool:
            if self == Path(".git") / "rebase-merge":
                return False
            if self == Path(".git") / "rebase-apply":
                return False
            return _real_exists(self)

        monkeypatch.setattr(Path, "exists", _fake_exists)

        result = rebase_to_resign_commits(base_ref="main", apply=True)
        assert result["status"] == "error"
        assert "rebase error" in result["error"]

    def test_apply_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = 0

        def mock_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _completed_process(returncode=0)
            return _completed_process(returncode=0)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.subprocess.run", mock_subprocess_run)

        result = rebase_to_resign_commits(base_ref="main", apply=True)

        assert result["status"] == "success"
        assert "re-signed" in result["message"]

    def test_apply_success_unix_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exercise the Unix chmod and shlex.quote branches."""
        call_count = 0

        def mock_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            return _completed_process(returncode=0)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.subprocess.run", mock_subprocess_run)
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.sys.platform", "linux")

        result = rebase_to_resign_commits(base_ref="main", apply=True)

        assert result["status"] == "success"

    def test_apply_unix_chmod_oserror_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify os.chmod OSError is silently caught on Unix."""
        call_count = 0

        def mock_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            return _completed_process(returncode=0)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.subprocess.run", mock_subprocess_run)
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.sys.platform", "linux")
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.os.chmod", _raise_oserror)

        result = rebase_to_resign_commits(base_ref="main", apply=True)

        assert result["status"] == "success"

    def test_apply_success_win32_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exercise the Windows list2cmdline branch."""
        call_count = 0

        def mock_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal call_count
            call_count += 1
            return _completed_process(returncode=0)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.subprocess.run", mock_subprocess_run)
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.sys.platform", "win32")

        result = rebase_to_resign_commits(base_ref="main", apply=True)

        assert result["status"] == "success"


# ---------------------------------------------------------------------------
# verify_commits_signed
# ---------------------------------------------------------------------------


class TestVerifyCommitsSigned:
    def test_all_good_signatures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        signature_output = 'Good "git" signature for user@example.com\nGood "git" signature for user@example.com\n'
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(stdout=signature_output),
        )

        result = verify_commits_signed(count=2)

        assert result["status"] == "success"
        assert result["good_signatures"] == 2
        assert result["bad_signatures"] == 0

    def test_bad_signature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        signature_output = "BAD signature from user@example.com\n"
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(stdout=signature_output),
        )

        result = verify_commits_signed(count=1)

        assert result["status"] == "error"
        assert result["bad_signatures"] == 1

    def test_git_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(returncode=1, stderr="fatal: bad"),
        )

        result = verify_commits_signed(count=1)

        assert result["status"] == "error"
        assert "fatal: bad" in result["error"]

    def test_no_signature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        signature_output = "No signature\n"
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(stdout=signature_output),
        )

        result = verify_commits_signed(count=1)

        assert result["status"] == "error"
        assert result["no_signatures"] == 1


# ---------------------------------------------------------------------------
# force_push_branch
# ---------------------------------------------------------------------------


class TestForcePushBranch:
    def test_dry_run(self) -> None:
        result = force_push_branch(branch="feat/x", apply=False)

        assert result["status"] == "dry_run"
        assert "feat/x" in result["message"]

    def test_apply_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(returncode=0),
        )

        result = force_push_branch(branch="feat/x", apply=True)

        assert result["status"] == "success"
        assert "feat/x" in result["message"]

    def test_apply_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.subprocess.run",
            lambda *_args, **_kwargs: _completed_process(returncode=1, stderr="rejected"),
        )

        result = force_push_branch(branch="feat/x", apply=True)

        assert result["status"] == "error"
        assert "rejected" in result["error"]


# ---------------------------------------------------------------------------
# fix_unsigned_commits (orchestrator)
# ---------------------------------------------------------------------------


def _make_commits_api_call(
    commits: list[dict[str, Any]],
) -> ExpectedCall:
    return ExpectedCall(
        argv=["gh", "api", "--paginate", f"/repos/octo/widgets/pulls/{_PR_NUMBER}/commits"],
        stdout=json.dumps(
            [
                {
                    "sha": commit_entry["sha"],
                    "html_url": commit_entry.get("html_url", ""),
                    "commit": {
                        "message": commit_entry.get("subject", "msg"),
                        "verification": {
                            "verified": commit_entry.get("verified"),
                            "reason": commit_entry.get("reason"),
                            "signature": None,
                            "payload": None,
                            "verified_at": None,
                        },
                        "author": {},
                        "committer": {},
                    },
                }
                for commit_entry in commits
            ]
        ),
    )


def _make_pr_info_call(
    head_ref: str = "feat/x",
    base_ref: str = "main",
) -> ExpectedCall:
    return ExpectedCall(
        argv=["gh", "api", f"/repos/octo/widgets/pulls/{_PR_NUMBER}"],
        stdout=json.dumps(_pr_api_payload(head_ref=head_ref, base_ref=base_ref)),
    )


def _signing_config_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    key_file = tmp_path / "key.pub"
    key_file.write_text("ssh-ed25519 AAAA...")
    monkeypatch.setattr(
        "scripts.github.fix_unsigned_commits.git_config_value",
        lambda key: {
            "commit.gpgsign": "true",
            "gpg.format": "ssh",
            "user.signingkey": str(key_file),
            "user.email": "dev@example.com",
            "user.name": "Dev",
        }[key],
    )
    monkeypatch.setattr(
        "scripts.github.fix_unsigned_commits.find_signing_key_path",
        lambda _signingkey: key_file,
    )


class TestFixUnsignedCommits:
    def test_no_action_needed(self) -> None:
        all_valid = [_commit_entry(verified=True, reason="valid")]
        runner = QueueRunner([_make_commits_api_call(all_valid)])

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)

        assert result["status"] == "no_action_needed"
        runner.assert_exhausted()

    def test_signing_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        runner = QueueRunner([_make_commits_api_call(unsigned)])

        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.git_config_value",
            lambda key: {
                "commit.gpgsign": "false",
                "gpg.format": None,
                "user.signingkey": None,
                "user.email": "dev@example.com",
                "user.name": "Dev",
            }[key],
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.find_signing_key_path",
            lambda _signingkey: None,
        )

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)

        assert result["status"] == "error"
        assert "not properly configured" in result["error"]

    def test_branch_info_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        # commits call succeeds, PR info call returns non-dict
        runner = QueueRunner(
            [
                _make_commits_api_call(unsigned),
                ExpectedCall(
                    argv=["gh", "api", f"/repos/octo/widgets/pulls/{_PR_NUMBER}"],
                    stdout=json.dumps("not-a-dict"),
                ),
            ]
        )
        _signing_config_ok(monkeypatch, tmp_path)

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)

        assert result["status"] == "error"
        assert "branch info" in result["error"]

    def test_wrong_branch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        runner = QueueRunner(
            [
                _make_commits_api_call(unsigned),
                _make_pr_info_call(head_ref="feat/x"),
            ]
        )
        _signing_config_ok(monkeypatch, tmp_path)

        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.get_current_branch",
            lambda: "different-branch",
        )

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)

        assert result["status"] == "error"
        assert "does not match" in result["error"]

    def test_branch_not_found(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        runner = QueueRunner(
            [
                _make_commits_api_call(unsigned),
                _make_pr_info_call(head_ref="feat/x"),
            ]
        )
        _signing_config_ok(monkeypatch, tmp_path)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.get_current_branch", lambda: "feat/x")
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.verify_local_branch", lambda *, branch: False)

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER)

        assert result["status"] == "error"
        assert "not found locally" in result["error"]

    def test_dry_run(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        runner = QueueRunner(
            [
                _make_commits_api_call(unsigned),
                _make_pr_info_call(head_ref="feat/x"),
            ]
        )
        _signing_config_ok(monkeypatch, tmp_path)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.get_current_branch", lambda: "feat/x")
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.verify_local_branch", lambda *, branch: True)
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.rebase_to_resign_commits",
            lambda *, base_ref, apply: {"status": "dry_run", "message": "Would rebase"},
        )

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, apply=False)

        assert result["status"] == "dry_run"
        assert "Dry run" in result["message"]

    def test_rebase_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        runner = QueueRunner(
            [
                _make_commits_api_call(unsigned),
                _make_pr_info_call(head_ref="feat/x"),
            ]
        )
        _signing_config_ok(monkeypatch, tmp_path)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.get_current_branch", lambda: "feat/x")
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.verify_local_branch", lambda *, branch: True)
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.rebase_to_resign_commits",
            lambda *, base_ref, apply: {"status": "error", "error": "rebase boom"},
        )

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, apply=True)

        assert result["status"] == "error"

    def test_conflict(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        runner = QueueRunner(
            [
                _make_commits_api_call(unsigned),
                _make_pr_info_call(head_ref="feat/x"),
            ]
        )
        _signing_config_ok(monkeypatch, tmp_path)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.get_current_branch", lambda: "feat/x")
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.verify_local_branch", lambda *, branch: True)
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.rebase_to_resign_commits",
            lambda *, base_ref, apply: {"status": "conflict", "error": "conflicts"},
        )

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, apply=True)

        assert result["status"] == "conflict"

    def test_verify_fail(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        runner = QueueRunner(
            [
                _make_commits_api_call(unsigned),
                _make_pr_info_call(head_ref="feat/x"),
            ]
        )
        _signing_config_ok(monkeypatch, tmp_path)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.get_current_branch", lambda: "feat/x")
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.verify_local_branch", lambda *, branch: True)
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.rebase_to_resign_commits",
            lambda *, base_ref, apply: {"status": "success", "message": "ok"},
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.verify_commits_signed",
            lambda *, count: {"status": "error", "error": "unsigned remain"},
        )

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, apply=True)

        assert result["status"] == "error"
        assert "not verified as signed" in result["error"]

    def test_push_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        runner = QueueRunner(
            [
                _make_commits_api_call(unsigned),
                _make_pr_info_call(head_ref="feat/x"),
            ]
        )
        _signing_config_ok(monkeypatch, tmp_path)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.get_current_branch", lambda: "feat/x")
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.verify_local_branch", lambda *, branch: True)
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.rebase_to_resign_commits",
            lambda *, base_ref, apply: {"status": "success", "message": "ok"},
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.verify_commits_signed",
            lambda *, count: {"status": "success", "good_signatures": 1, "bad_signatures": 0, "no_signatures": 0},
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.force_push_branch",
            lambda *, branch, apply: {"status": "error", "error": "push rejected"},
        )

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, apply=True)

        assert result["status"] == "error"

    def test_full_success(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        unsigned = [_commit_entry(verified=False, reason="unsigned")]
        runner = QueueRunner(
            [
                _make_commits_api_call(unsigned),
                _make_pr_info_call(head_ref="feat/x"),
            ]
        )
        _signing_config_ok(monkeypatch, tmp_path)

        monkeypatch.setattr("scripts.github.fix_unsigned_commits.get_current_branch", lambda: "feat/x")
        monkeypatch.setattr("scripts.github.fix_unsigned_commits.verify_local_branch", lambda *, branch: True)
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.rebase_to_resign_commits",
            lambda *, base_ref, apply: {"status": "success", "message": "ok"},
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.verify_commits_signed",
            lambda *, count: {"status": "success", "good_signatures": 1, "bad_signatures": 0, "no_signatures": 0},
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.force_push_branch",
            lambda *, branch, apply: {"status": "success", "message": f"pushed {branch}"},
        )

        result = fix_unsigned_commits(runner=runner, repo=_REPO, pr_number=_PR_NUMBER, apply=True)

        assert result["status"] == "success"
        assert "feat/x" in result["message"]


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_returns_argument_parser(self) -> None:
        parser = _build_parser()

        assert isinstance(parser, argparse.ArgumentParser)

    def test_parses_all_flags(self) -> None:
        parser = _build_parser()
        parsed = parser.parse_args(["--repo", "o/n", "--pr", "7", "--apply", "--json"])

        assert parsed.repo == "o/n"
        assert parsed.pr == 7
        assert parsed.apply is True
        assert parsed.json is True


# ---------------------------------------------------------------------------
# _print_json_output
# ---------------------------------------------------------------------------


class TestPrintJsonOutput:
    def test_error_returns_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = _print_json_output({"status": "error", "error": "boom"})

        assert exit_code == 1
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "error"

    def test_conflict_returns_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = _print_json_output({"status": "conflict"})

        assert exit_code == 2

    def test_success_returns_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = _print_json_output({"status": "success"})

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "success"

    def test_dry_run_returns_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = _print_json_output({"status": "dry_run"})

        assert exit_code == 0


# ---------------------------------------------------------------------------
# _print_text_output
# ---------------------------------------------------------------------------


class TestPrintTextOutput:
    @staticmethod
    def _namespace(**kwargs: Any) -> argparse.Namespace:
        defaults = {"repo": _REPO, "pr": _PR_NUMBER, "apply": False, "json": False}
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def test_error_with_error_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        result_data = {"status": "error", "error": "something broke"}
        exit_code = _print_text_output(result_data, self._namespace())

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "something broke" in captured.err

    def test_error_status_without_error_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        result_data = {"status": "error"}
        exit_code = _print_text_output(result_data, self._namespace())

        assert exit_code == 1

    def test_conflict(self, capsys: pytest.CaptureFixture[str]) -> None:
        result_data = {"status": "conflict"}
        exit_code = _print_text_output(result_data, self._namespace())

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "conflicts" in captured.err.lower()

    def test_dry_run(self, capsys: pytest.CaptureFixture[str]) -> None:
        result_data = {"status": "dry_run", "message": "Dry run complete"}
        exit_code = _print_text_output(result_data, self._namespace(apply=False))

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "--apply" in captured.out

    def test_success_with_unsigned_count(self, capsys: pytest.CaptureFixture[str]) -> None:
        result_data = {
            "status": "success",
            "message": "Fixed 2 commits",
            "unsigned_count": 2,
            "total_commits": 5,
        }
        exit_code = _print_text_output(result_data, self._namespace(apply=True))

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Unsigned commits: 2 of 5" in captured.out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_json_output(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["fix_unsigned_commits", "--repo", _REPO, "--pr", str(_PR_NUMBER), "--json"],
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.SubprocessGhRunner",
            lambda: QueueRunner([]),
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.fix_unsigned_commits",
            lambda *, runner, repo, pr_number, apply: {"status": "success", "message": "done"},
        )

        from scripts.github.fix_unsigned_commits import main

        exit_code = main()

        assert exit_code == 0
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "success"

    def test_text_output(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["fix_unsigned_commits", "--repo", _REPO, "--pr", str(_PR_NUMBER)],
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.SubprocessGhRunner",
            lambda: QueueRunner([]),
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.fix_unsigned_commits",
            lambda *, runner, repo, pr_number, apply: {"status": "dry_run", "message": "dry run"},
        )

        from scripts.github.fix_unsigned_commits import main

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "dry_run" in captured.out

    def test_gh_cli_error_with_json_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["fix_unsigned_commits", "--repo", _REPO, "--pr", str(_PR_NUMBER), "--json"],
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.SubprocessGhRunner",
            lambda: QueueRunner([]),
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.fix_unsigned_commits",
            _raise_gh_cli_error,
        )

        from scripts.github.fix_unsigned_commits import main

        exit_code = main()

        assert exit_code == 1
        output = json.loads(capsys.readouterr().out)
        assert output["status"] == "error"

    def test_gh_cli_error_without_json_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["fix_unsigned_commits", "--repo", _REPO, "--pr", str(_PR_NUMBER)],
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.SubprocessGhRunner",
            lambda: QueueRunner([]),
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.fix_unsigned_commits",
            _raise_gh_cli_error,
        )

        from scripts.github.fix_unsigned_commits import main

        exit_code = main()

        assert exit_code == 2
        captured = capsys.readouterr()
        assert "gh command failed" in captured.err.lower() or "error" in captured.err.lower()

    def test_value_error_without_json_flag(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["fix_unsigned_commits", "--repo", _REPO, "--pr", str(_PR_NUMBER)],
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.SubprocessGhRunner",
            lambda: QueueRunner([]),
        )
        monkeypatch.setattr(
            "scripts.github.fix_unsigned_commits.fix_unsigned_commits",
            _raise_value_error,
        )

        from scripts.github.fix_unsigned_commits import main

        exit_code = main()

        assert exit_code == 2


def _raise_gh_cli_error(**_kwargs: Any) -> None:
    raise GhCliError("gh command failed", argv=["gh"], returncode=1, stdout="", stderr="gh command failed")


def _raise_value_error(**_kwargs: Any) -> None:
    raise ValueError("bad input")
