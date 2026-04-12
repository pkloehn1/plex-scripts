"""Tests for scripts.testing.hooks.check_git_signing."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

import scripts.testing.hooks.check_git_signing as mod


def _patch_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    commit: str | None = "true",
    gpg: str | None = "ssh",
    key: str | None = "~/.ssh/id_ed25519_signing.pub",
) -> None:
    values = {
        "commit.gpgsign": commit,
        "gpg.format": gpg,
        "user.signingkey": key,
    }
    monkeypatch.setattr(mod, "git_config_value", lambda key_name: values.get(key_name))


def _clear_skip_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKIP_GIT_SIGNING_CHECK", raising=False)


def _patch_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point HOME / USERPROFILE / Path.home() at *tmp_path*."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)


def test_main_skip_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SKIP_GIT_SIGNING_CHECK", "1")
    assert mod.main() == 0
    monkeypatch.delenv("SKIP_GIT_SIGNING_CHECK", raising=False)


def test_main_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_skip_env(monkeypatch)
    _patch_config(monkeypatch)
    monkeypatch.setattr(mod, "_test_signing", lambda _path: (True, "ok"))
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key_path = ssh_dir / "id_ed25519_signing.pub"
    key_path.write_text("ssh-ed25519 AAAA test\n")
    _patch_home(monkeypatch, tmp_path)
    assert mod.main() == 0


def test_main_missing_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_skip_env(monkeypatch)
    _patch_config(monkeypatch)
    (tmp_path / ".ssh").mkdir()
    _patch_home(monkeypatch, tmp_path)
    result_code = mod.main()
    assert result_code == 1


def test_main_not_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear_skip_env(monkeypatch)
    _patch_config(monkeypatch, commit=None, gpg=None, key=None)
    _patch_home(monkeypatch, tmp_path)
    result_code = mod.main()
    assert result_code == 1


# -- Signing smoke test (_test_signing) --


def test_test_signing_success(tmp_path: Path) -> None:
    """_test_signing returns (True, ...) when ssh-keygen succeeds."""
    fake_key = tmp_path / "key"
    fake_key.write_text("fake")
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch.object(mod.subprocess, "run", return_value=completed) as mock_run:
        sign_ok, msg = mod._test_signing(fake_key)
    assert sign_ok is True
    assert "verified" in msg.lower()
    # Verify ssh-keygen was called with the key path
    call_args = mock_run.call_args[0][0]
    assert str(fake_key) in call_args


def test_test_signing_failure(tmp_path: Path) -> None:
    """_test_signing returns (False, ...) when ssh-keygen fails."""
    fake_key = tmp_path / "key"
    fake_key.write_text("fake")
    completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="agent refused operation")
    with patch.object(mod.subprocess, "run", return_value=completed):
        sign_ok, msg = mod._test_signing(fake_key)
    assert sign_ok is False
    assert "agent refused operation" in msg


def test_test_signing_timeout(tmp_path: Path) -> None:
    """_test_signing returns (False, ...) when ssh-keygen hangs on stale socket."""
    fake_key = tmp_path / "key"
    fake_key.write_text("fake")
    with patch.object(
        mod.subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd="ssh-keygen", timeout=10),
    ):
        sign_ok, msg = mod._test_signing(fake_key)
    assert sign_ok is False
    assert "timed out" in msg.lower()
    assert "SSH_AUTH_SOCK" in msg


def test_test_signing_missing_ssh_keygen(tmp_path: Path) -> None:
    """_test_signing returns (False, ...) when ssh-keygen is not installed."""
    fake_key = tmp_path / "key"
    fake_key.write_text("fake")
    with patch.object(mod.subprocess, "run", side_effect=FileNotFoundError("ssh-keygen")):
        sign_ok, msg = mod._test_signing(fake_key)
    assert sign_ok is False
    assert "ssh-keygen not found" in msg


def test_main_fails_when_signing_smoke_test_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """main() returns 1 when config is correct but signing smoke test fails."""
    _clear_skip_env(monkeypatch)
    _patch_config(monkeypatch)
    monkeypatch.setattr(mod, "_test_signing", lambda _path: (False, "agent refused operation"))
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key_path = ssh_dir / "id_ed25519_signing.pub"
    key_path.write_text("ssh-ed25519 AAAA test\n")
    _patch_home(monkeypatch, tmp_path)
    assert mod.main() == 1


# -- Windows + 1Password (gpg.ssh.program) --


def _patch_config_with_ssh_program(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ssh_program: str | None = r"C:\Program Files\1Password\app\8\op-ssh-sign.exe",
    commit: str | None = "true",
    gpg: str | None = "ssh",
    key: str | None = "~/.ssh/id_ed25519_signing.pub",
) -> None:
    values = {
        "commit.gpgsign": commit,
        "gpg.format": gpg,
        "user.signingkey": key,
        "gpg.ssh.program": ssh_program,
    }
    monkeypatch.setattr(mod, "git_config_value", lambda key_name: values.get(key_name))


def test_check_passes_when_gpg_ssh_program_configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When gpg.ssh.program is set and exists, skip ssh-keygen smoke test."""
    _clear_skip_env(monkeypatch)
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key_path = ssh_dir / "id_ed25519_signing.pub"
    key_path.write_text("ssh-ed25519 AAAA test\n")
    _patch_home(monkeypatch, tmp_path)
    fake_program = tmp_path / "op-ssh-sign.exe"
    fake_program.write_text("fake")
    _patch_config_with_ssh_program(monkeypatch, ssh_program=str(fake_program))
    signing_ok, _msg = mod.check_git_signing()
    assert signing_ok is True


def test_check_git_signing_logs_config_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """check_git_signing writes diagnostic lines to stderr at each step."""
    _clear_skip_env(monkeypatch)
    fake_program = tmp_path / "op-ssh-sign.exe"
    fake_program.write_text("fake")
    _patch_config_with_ssh_program(monkeypatch, ssh_program=str(fake_program))
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_ed25519_signing.pub").write_text("ssh-ed25519 AAAA test\n")
    _patch_home(monkeypatch, tmp_path)
    mod.check_git_signing()
    err = capsys.readouterr().err
    assert "[check-git-signing] commit.gpgsign" in err
    assert "[check-git-signing] gpg.format" in err
    assert "[check-git-signing] user.signingkey" in err
    assert "[check-git-signing] gpg.ssh.program: found at" in err


def test_check_wrong_gpg_format(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_skip_env(monkeypatch)
    _patch_config(monkeypatch, gpg="gpg")
    signing_ok, msg = mod.check_git_signing()
    assert signing_ok is False
    assert "gpg.format" in msg


def test_check_missing_signingkey(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_skip_env(monkeypatch)
    _patch_config(monkeypatch, key=None)
    signing_ok, msg = mod.check_git_signing()
    assert signing_ok is False
    assert "user.signingkey" in msg


def test_check_git_config_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_skip_env(monkeypatch)

    def _raise(_key: str) -> None:
        raise OSError("boom")

    monkeypatch.setattr(mod, "git_config_value", _raise)
    signing_ok, msg = mod.check_git_signing()
    assert signing_ok is False
    assert "boom" in msg


def test_check_fails_when_gpg_ssh_program_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When gpg.ssh.program is set but the executable doesn't exist, fail."""
    _clear_skip_env(monkeypatch)
    _patch_config_with_ssh_program(monkeypatch, ssh_program=r"C:\nonexistent\op-ssh-sign.exe")
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key_path = ssh_dir / "id_ed25519_signing.pub"
    key_path.write_text("ssh-ed25519 AAAA test\n")
    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(mod.shutil, "which", lambda _prog: None)
    signing_ok, _msg = mod.check_git_signing()
    assert signing_ok is False


def test_check_passes_when_gpg_ssh_program_on_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When gpg.ssh.program is a bare name found via PATH, pass."""
    _clear_skip_env(monkeypatch)
    _patch_config_with_ssh_program(monkeypatch, ssh_program="op-ssh-sign")
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key_path = ssh_dir / "id_ed25519_signing.pub"
    key_path.write_text("ssh-ed25519 AAAA test\n")
    _patch_home(monkeypatch, tmp_path)
    monkeypatch.setattr(mod.shutil, "which", lambda _prog: "/usr/bin/op-ssh-sign")
    signing_ok, _msg = mod.check_git_signing()
    assert signing_ok is True
