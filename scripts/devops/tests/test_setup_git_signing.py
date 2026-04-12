from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import scripts.devops.setup_git_signing as mod


def test_find_existing_signing_key_prefers_existing(monkeypatch, tmp_path: Path) -> None:
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    key = ssh_dir / "id_ed25519_signing.pub"
    key.write_text("ssh-ed25519 AAAA test\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert mod.find_existing_signing_key() == key


def test_check_only_mode(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mod, "check_git_config", lambda: {"a": "b"})
    monkeypatch.setattr(mod, "get_github_email", lambda: "x@y.z")

    # Build args equivalent: --check-only --key-path <tmp>/id_ed25519_signing.pub
    def fake_args():
        class FakeArgs:
            check_only = True
            key_path = tmp_path / "id_ed25519_signing.pub"
            email = None
            force = False
            passphrase = "test-passphrase"
            no_passphrase = False

        return FakeArgs()

    monkeypatch.setattr(mod, "_parse_args", fake_args)
    exit_code = mod.main()
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Current Git signing configuration" in out


def test_configure_git_signing_skips_when_already_configured(monkeypatch: Any, tmp_path: Path) -> None:
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    (ssh_dir / "id_ed25519_signing.pub").write_text("ssh-ed25519 AAAA test\n")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(
        os.path,
        "expanduser",
        lambda path_value: str(path_value).replace("~", str(tmp_path)),
    )

    def fail_if_called(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("_configure_git should not run when already configured")

    monkeypatch.setattr(mod, "_configure_git", fail_if_called)
    monkeypatch.setattr(
        mod,
        "check_git_config",
        lambda: {
            mod.GIT_CONFIG_COMMIT_GPGSIGN: "true",
            mod.GIT_CONFIG_GPG_FORMAT: "ssh",
            mod.GIT_CONFIG_USER_SIGNINGKEY: "~/.ssh/id_ed25519_signing.pub",
            mod.GIT_CONFIG_GPG_SSH_ALLOWED_SIGNERS: None,
        },
    )
    assert mod.configure_git_signing(key_path=Path("x.pub"), email=None, force=False) is True


def test_email_from_gh_payload_prefers_email() -> None:
    payload = {"email": "dev@example.com", "login": "octocat"}
    assert mod._email_from_gh_payload(payload) == "dev@example.com"


def test_email_from_gh_payload_uses_noreply_when_missing_email() -> None:
    payload = {"email": None, "login": "octocat"}
    assert mod._email_from_gh_payload(payload) == "octocat@users.noreply.github.com"


def test_email_from_git_config_accepts_valid_email(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "git_config_value", lambda _key: "dev@example.com")
    assert mod._email_from_git_config() == "dev@example.com"


def test_email_from_git_config_rejects_invalid_email(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "git_config_value", lambda _key: "invalid-email")
    assert mod._email_from_git_config() is None


# -- OS-aware _resolve_signing_key tests --


def test_resolve_signing_key_linux_uses_private_key(monkeypatch: Any, tmp_path: Path) -> None:
    """On Linux, _resolve_signing_key returns the private key path."""
    monkeypatch.setattr(mod, "is_windows", lambda: False)
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    private_key = ssh_dir / "id_ed25519_signing"
    private_key.write_text("contains PRIVATE KEY material for testing\n")
    public_key = ssh_dir / "id_ed25519_signing.pub"
    public_key.write_text("ssh-ed25519 AAAA test\n")
    result = mod._resolve_signing_key(public_key)
    assert result == private_key


def test_resolve_signing_key_linux_fails_without_private_key(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    """On Linux, _resolve_signing_key returns None when only .pub exists."""
    monkeypatch.setattr(mod, "is_windows", lambda: False)
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    public_key = ssh_dir / "id_ed25519_signing.pub"
    public_key.write_text("ssh-ed25519 AAAA test\n")
    result = mod._resolve_signing_key(public_key)
    assert result is None
    assert "Private key not found" in capsys.readouterr().out


def test_resolve_signing_key_windows_uses_public_key(monkeypatch: Any, tmp_path: Path) -> None:
    """On Windows, _resolve_signing_key returns the public key path."""
    monkeypatch.setattr(mod, "is_windows", lambda: True)
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    private_key = ssh_dir / "id_ed25519_signing"
    private_key.write_text("contains PRIVATE KEY material for testing\n")
    public_key = ssh_dir / "id_ed25519_signing.pub"
    public_key.write_text("ssh-ed25519 AAAA test\n")
    result = mod._resolve_signing_key(public_key)
    assert result == public_key


def test_resolve_signing_key_windows_fails_without_public_key(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    """On Windows, _resolve_signing_key returns None when .pub is missing."""
    monkeypatch.setattr(mod, "is_windows", lambda: True)
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    private_key = ssh_dir / "id_ed25519_signing"
    private_key.write_text("contains PRIVATE KEY material for testing\n")
    public_key = ssh_dir / "id_ed25519_signing.pub"
    # public_key intentionally not created
    result = mod._resolve_signing_key(public_key)
    assert result is None
    assert "Public key not found" in capsys.readouterr().out


def test_resolve_signing_key_windows_rejects_private_key_material_in_pub(
    monkeypatch: Any, tmp_path: Path, capsys
) -> None:
    """On Windows, _resolve_signing_key rejects .pub containing private key material."""
    monkeypatch.setattr(mod, "is_windows", lambda: True)
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    public_key = ssh_dir / "id_ed25519_signing.pub"
    public_key.write_text("contains PRIVATE KEY material for testing\n")
    result = mod._resolve_signing_key(public_key)
    assert result is None
    assert "private key material" in capsys.readouterr().out


# -- get_ssh_dir ---------------------------------------------------------------


def test_get_ssh_dir(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert mod.get_ssh_dir() == tmp_path / ".ssh"


# -- _split_key_paths ----------------------------------------------------------


def test_split_key_paths_with_pub_suffix(tmp_path: Path) -> None:
    pub = tmp_path / "id_ed25519.pub"
    priv, pub_out = mod._split_key_paths(pub)
    assert priv == tmp_path / "id_ed25519"
    assert pub_out == pub


def test_split_key_paths_without_pub_suffix(tmp_path: Path) -> None:
    priv_path = tmp_path / "id_ed25519"
    priv, pub_out = mod._split_key_paths(priv_path)
    assert priv == priv_path
    assert pub_out == tmp_path / "id_ed25519.pub"


# -- _looks_like_private_key ---------------------------------------------------


def test_looks_like_private_key_true(tmp_path: Path) -> None:
    key_file = tmp_path / "id_ed25519"
    key_file.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n")
    assert mod._looks_like_private_key(key_file) is True


def test_looks_like_private_key_false(tmp_path: Path) -> None:
    key_file = tmp_path / "id_ed25519.pub"
    key_file.write_text("ssh-ed25519 AAAA test\n")
    assert mod._looks_like_private_key(key_file) is False


def test_looks_like_private_key_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent"
    assert mod._looks_like_private_key(missing) is False


# -- _regenerate_public_key ----------------------------------------------------


def test_regenerate_public_key_success(tmp_path: Path, capsys) -> None:
    private_key = tmp_path / "id_ed25519"
    private_key.write_text("fake private key")
    public_key = tmp_path / "id_ed25519.pub"

    fake_result = MagicMock()
    fake_result.stdout = "ssh-ed25519 AAAA test"

    with patch("subprocess.run", return_value=fake_result) as mock_run:
        result = mod._regenerate_public_key(private_key, public_key)

    assert result is True
    assert public_key.read_text() == "ssh-ed25519 AAAA test\n"
    mock_run.assert_called_once()
    assert "Regenerated public key" in capsys.readouterr().out


def test_regenerate_public_key_called_process_error(tmp_path: Path, capsys) -> None:
    private_key = tmp_path / "id_ed25519"
    public_key = tmp_path / "id_ed25519.pub"

    err = subprocess.CalledProcessError(1, "ssh-keygen", stderr="permission denied")
    with patch("subprocess.run", side_effect=err):
        result = mod._regenerate_public_key(private_key, public_key)

    assert result is False
    assert "Failed to regenerate public key" in capsys.readouterr().out


def test_regenerate_public_key_called_process_error_no_stderr(tmp_path: Path, capsys) -> None:
    private_key = tmp_path / "id_ed25519"
    public_key = tmp_path / "id_ed25519.pub"

    err = subprocess.CalledProcessError(1, "ssh-keygen", stderr="")
    with patch("subprocess.run", side_effect=err):
        result = mod._regenerate_public_key(private_key, public_key)

    assert result is False
    assert "Failed to regenerate public key" in capsys.readouterr().out


def test_regenerate_public_key_not_found(tmp_path: Path, capsys) -> None:
    private_key = tmp_path / "id_ed25519"
    public_key = tmp_path / "id_ed25519.pub"

    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = mod._regenerate_public_key(private_key, public_key)

    assert result is False
    assert "ssh-keygen not found" in capsys.readouterr().out


# -- _generate_signing_key -----------------------------------------------------


def test_generate_signing_key_success(tmp_path: Path, capsys) -> None:
    private_key = tmp_path / "id_ed25519_signing"

    with patch("subprocess.run", return_value=MagicMock()) as mock_run:
        result = mod._generate_signing_key(private_key, passphrase="secret")

    assert result is True
    mock_run.assert_called_once()
    assert "Created signing key" in capsys.readouterr().out


def test_generate_signing_key_called_process_error(tmp_path: Path, capsys) -> None:
    private_key = tmp_path / "id_ed25519_signing"

    err = subprocess.CalledProcessError(1, "ssh-keygen", stderr="bad passphrase")
    with patch("subprocess.run", side_effect=err):
        result = mod._generate_signing_key(private_key, passphrase="bad")

    assert result is False
    assert "Failed to create key" in capsys.readouterr().out


def test_generate_signing_key_called_process_error_no_stderr(tmp_path: Path, capsys) -> None:
    private_key = tmp_path / "id_ed25519_signing"

    err = subprocess.CalledProcessError(1, "ssh-keygen", stderr="")
    with patch("subprocess.run", side_effect=err):
        result = mod._generate_signing_key(private_key, passphrase="")

    assert result is False
    assert "Failed to create key" in capsys.readouterr().out


def test_generate_signing_key_not_found(tmp_path: Path, capsys) -> None:
    private_key = tmp_path / "id_ed25519_signing"

    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = mod._generate_signing_key(private_key, passphrase="")

    assert result is False
    assert "ssh-keygen not found" in capsys.readouterr().out


# -- create_signing_key --------------------------------------------------------


def test_create_signing_key_already_exists(tmp_path: Path, capsys) -> None:
    key = tmp_path / "id_ed25519_signing.pub"
    key.write_text("ssh-ed25519 AAAA test\n")
    result = mod.create_signing_key(key, passphrase="secret")
    assert result is True
    assert "Key already exists" in capsys.readouterr().out


def test_create_signing_key_private_exists_no_pub(tmp_path: Path, monkeypatch: Any) -> None:
    """When private key exists but .pub does not, delegates to _regenerate_public_key."""
    private_key = tmp_path / "id_ed25519_signing"
    private_key.write_text("fake private key")
    # Pass the .pub path so key_path.exists() is False, but private_key.exists() is True
    pub_key = tmp_path / "id_ed25519_signing.pub"
    # pub_key intentionally not created

    monkeypatch.setattr(mod, "_regenerate_public_key", lambda priv, pub: True)
    result = mod.create_signing_key(pub_key, passphrase="secret")
    assert result is True


def test_create_signing_key_generates_new(tmp_path: Path, monkeypatch: Any) -> None:
    """When no key exists, delegates to _generate_signing_key."""
    private_key = tmp_path / "id_ed25519_signing"
    # Neither private nor public exist

    monkeypatch.setattr(mod, "_generate_signing_key", lambda priv, passphrase: True)
    result = mod.create_signing_key(private_key, passphrase="secret")
    assert result is True


# -- _email_from_git_config ----------------------------------------------------


def test_email_from_git_config_returns_none_on_exception(monkeypatch: Any) -> None:
    def raise_exc(_key: str) -> None:
        raise RuntimeError("git not found")

    monkeypatch.setattr(mod, "git_config_value", raise_exc)
    assert mod._email_from_git_config() is None


def test_email_from_git_config_returns_none_for_empty(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "git_config_value", lambda _key: "")
    assert mod._email_from_git_config() is None


def test_email_from_git_config_accepts_noreply(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "git_config_value", lambda _key: "user@users.noreply.github.com")
    assert mod._email_from_git_config() == "user@users.noreply.github.com"


# -- _email_from_gh_payload edge cases ----------------------------------------


def test_email_from_gh_payload_no_login_no_email() -> None:
    assert mod._email_from_gh_payload({}) is None


def test_email_from_gh_payload_empty_email_no_login() -> None:
    assert mod._email_from_gh_payload({"email": "", "login": ""}) is None


# -- _email_from_gh_cli --------------------------------------------------------


def test_email_from_gh_cli_success(monkeypatch: Any) -> None:
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = '{"email": "user@example.com", "login": "user"}'

    with patch("subprocess.run", return_value=fake_result):
        result = mod._email_from_gh_cli()

    assert result == "user@example.com"


def test_email_from_gh_cli_nonzero_returncode(monkeypatch: Any) -> None:
    fake_result = MagicMock()
    fake_result.returncode = 1

    with patch("subprocess.run", return_value=fake_result):
        result = mod._email_from_gh_cli()

    assert result is None


def test_email_from_gh_cli_exception(monkeypatch: Any) -> None:
    with patch("subprocess.run", side_effect=OSError("no gh")):
        result = mod._email_from_gh_cli()

    assert result is None


def test_email_from_gh_cli_invalid_json(monkeypatch: Any) -> None:
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "not json"

    with patch("subprocess.run", return_value=fake_result):
        result = mod._email_from_gh_cli()

    assert result is None


def test_email_from_gh_cli_non_dict_json(monkeypatch: Any) -> None:
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = '["list", "not", "dict"]'

    with patch("subprocess.run", return_value=fake_result):
        result = mod._email_from_gh_cli()

    assert result is None


# -- get_github_email ----------------------------------------------------------


def test_get_github_email_from_git_config(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "_email_from_git_config", lambda: "git@example.com")
    monkeypatch.setattr(mod, "_email_from_gh_cli", lambda: "cli@example.com")
    assert mod.get_github_email() == "git@example.com"


def test_get_github_email_falls_back_to_gh_cli(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "_email_from_git_config", lambda: None)
    monkeypatch.setattr(mod, "_email_from_gh_cli", lambda: "cli@example.com")
    assert mod.get_github_email() == "cli@example.com"


# -- check_git_config ----------------------------------------------------------


def test_check_git_config_returns_values(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "git_config_value", lambda key: "val_" + key)
    config = mod.check_git_config()
    assert config[mod.GIT_CONFIG_COMMIT_GPGSIGN] == "val_" + mod.GIT_CONFIG_COMMIT_GPGSIGN


def test_check_git_config_handles_exceptions(monkeypatch: Any) -> None:
    def raise_exc(_key: str) -> None:
        raise RuntimeError("no git")

    monkeypatch.setattr(mod, "git_config_value", raise_exc)
    config = mod.check_git_config()
    assert all(val is None for val in config.values())


# -- _configure_git ------------------------------------------------------------


def test_configure_git_success(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mod, "is_windows", lambda: False)
    private_key = tmp_path / "id_ed25519_signing"
    private_key.write_text("fake key content")
    public_key = tmp_path / "id_ed25519_signing.pub"
    public_key.write_text("ssh-ed25519 AAAA test\n")

    with patch("subprocess.run", return_value=MagicMock()) as mock_run:
        result = mod._configure_git(public_key)

    assert result is True
    assert mock_run.call_count == 3
    assert "Configured Git for SSH signing" in capsys.readouterr().out


def test_configure_git_fails_when_key_missing(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mod, "is_windows", lambda: False)
    public_key = tmp_path / "id_ed25519_signing.pub"
    public_key.write_text("ssh-ed25519 AAAA test\n")
    # private key does not exist

    result = mod._configure_git(public_key)
    assert result is False


def test_configure_git_called_process_error(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mod, "is_windows", lambda: False)
    private_key = tmp_path / "id_ed25519_signing"
    private_key.write_text("fake key content")
    public_key = tmp_path / "id_ed25519_signing.pub"
    public_key.write_text("ssh-ed25519 AAAA test\n")

    err = subprocess.CalledProcessError(1, "git")
    with patch("subprocess.run", side_effect=err):
        result = mod._configure_git(public_key)

    assert result is False
    assert "Failed to configure Git" in capsys.readouterr().out


# -- _configure_allowed_signers ------------------------------------------------


def test_configure_allowed_signers_no_email(tmp_path: Path, capsys) -> None:
    """When email is None, function returns immediately without writing anything."""
    mod._configure_allowed_signers(tmp_path / "id_ed25519.pub", None)
    assert capsys.readouterr().out == ""


def test_configure_allowed_signers_missing_public_key(tmp_path: Path, capsys) -> None:
    pub = tmp_path / "id_ed25519.pub"
    # pub not created
    mod._configure_allowed_signers(pub, "user@example.com")
    assert "Cannot configure allowed signers" in capsys.readouterr().out


def test_configure_allowed_signers_malformed_key(tmp_path: Path, capsys) -> None:
    pub = tmp_path / "id_ed25519.pub"
    pub.write_text("justonepart\n")

    with patch.object(Path, "home", return_value=tmp_path):
        mod._configure_allowed_signers(pub, "user@example.com")

    assert "malformed" in capsys.readouterr().out


def test_configure_allowed_signers_success(tmp_path: Path, capsys) -> None:
    pub = tmp_path / "id_ed25519.pub"
    pub.write_text("ssh-ed25519 AAAA test comment\n")

    with patch.object(Path, "home", return_value=tmp_path), patch("subprocess.run", return_value=MagicMock()):
        mod._configure_allowed_signers(pub, "user@example.com")

    out = capsys.readouterr().out
    assert "Configured allowed signers file" in out
    signers_file = tmp_path / ".config" / "git" / "allowed_signers"
    assert signers_file.exists()
    content = signers_file.read_text()
    assert "user@example.com" in content
    assert "ssh-ed25519" in content


def test_configure_allowed_signers_exception(tmp_path: Path, capsys) -> None:
    pub = tmp_path / "id_ed25519.pub"
    pub.write_text("ssh-ed25519 AAAA test\n")

    with (
        patch.object(Path, "home", return_value=tmp_path),
        patch("subprocess.run", side_effect=OSError("git not found")),
    ):
        mod._configure_allowed_signers(pub, "user@example.com")

    assert "Could not configure allowed signers file" in capsys.readouterr().out


# -- configure_git_signing -----------------------------------------------------


def test_configure_git_signing_force_reconfigures(monkeypatch: Any, tmp_path: Path) -> None:
    """With force=True, skip the already-configured check and call _configure_git."""
    configure_called = []

    def fake_configure_git(key_path: Path) -> bool:
        configure_called.append(key_path)
        return True

    monkeypatch.setattr(mod, "_configure_git", fake_configure_git)
    monkeypatch.setattr(mod, "_configure_allowed_signers", lambda _key, _email: None)
    monkeypatch.setattr(
        mod,
        "check_git_config",
        lambda: {
            mod.GIT_CONFIG_COMMIT_GPGSIGN: "true",
            mod.GIT_CONFIG_GPG_FORMAT: "ssh",
            mod.GIT_CONFIG_USER_SIGNINGKEY: str(tmp_path / "id_ed25519_signing.pub"),
            mod.GIT_CONFIG_GPG_SSH_ALLOWED_SIGNERS: None,
        },
    )

    key_path = tmp_path / "id_ed25519_signing.pub"
    result = mod.configure_git_signing(key_path=key_path, email=None, force=True)
    assert result is True
    assert len(configure_called) == 1


def test_configure_git_signing_configure_fails(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "_configure_git", lambda _key: False)
    monkeypatch.setattr(mod, "check_git_config", lambda: {})
    key_path = tmp_path / "id_ed25519_signing.pub"
    result = mod.configure_git_signing(key_path=key_path, email=None, force=False)
    assert result is False


def test_configure_git_signing_already_configured_key_missing(monkeypatch: Any, tmp_path: Path) -> None:
    """When already-configured key path doesn't exist on disk, reconfigure."""
    configure_called = []

    def fake_configure_git(key_path: Path) -> bool:
        configure_called.append(key_path)
        return True

    monkeypatch.setattr(mod, "_configure_git", fake_configure_git)
    monkeypatch.setattr(mod, "_configure_allowed_signers", lambda _key, _email: None)
    missing_key = str(tmp_path / "nonexistent.pub")
    monkeypatch.setattr(
        mod,
        "check_git_config",
        lambda: {
            mod.GIT_CONFIG_COMMIT_GPGSIGN: "true",
            mod.GIT_CONFIG_GPG_FORMAT: "ssh",
            mod.GIT_CONFIG_USER_SIGNINGKEY: missing_key,
            mod.GIT_CONFIG_GPG_SSH_ALLOWED_SIGNERS: None,
        },
    )

    key_path = tmp_path / "id_ed25519_signing.pub"
    result = mod.configure_git_signing(key_path=key_path, email=None, force=False)
    assert result is True
    assert len(configure_called) == 1


# -- _verify_key_exists --------------------------------------------------------


def test_verify_key_exists_found(tmp_path: Path, capsys) -> None:
    key = tmp_path / "id_ed25519.pub"
    key.write_text("ssh-ed25519 AAAA test\n")
    assert mod._verify_key_exists(key) is True
    assert "Signing key exists" in capsys.readouterr().out


def test_verify_key_exists_not_found(tmp_path: Path, capsys) -> None:
    key = tmp_path / "missing.pub"
    assert mod._verify_key_exists(key) is False
    assert "Signing key not found" in capsys.readouterr().out


# -- _verify_git_config --------------------------------------------------------


def test_verify_git_config_all_correct(capsys) -> None:
    config = {
        mod.GIT_CONFIG_COMMIT_GPGSIGN: "true",
        mod.GIT_CONFIG_GPG_FORMAT: "ssh",
        mod.GIT_CONFIG_USER_SIGNINGKEY: "/home/user/.ssh/id_ed25519_signing",
    }
    assert mod._verify_git_config(config) is True


def test_verify_git_config_gpgsign_wrong(capsys) -> None:
    config = {
        mod.GIT_CONFIG_COMMIT_GPGSIGN: "false",
        mod.GIT_CONFIG_GPG_FORMAT: "ssh",
        mod.GIT_CONFIG_USER_SIGNINGKEY: "/home/user/.ssh/id_ed25519_signing",
    }
    assert mod._verify_git_config(config) is False
    assert mod.GIT_CONFIG_COMMIT_GPGSIGN in capsys.readouterr().out


def test_verify_git_config_format_wrong(capsys) -> None:
    config = {
        mod.GIT_CONFIG_COMMIT_GPGSIGN: "true",
        mod.GIT_CONFIG_GPG_FORMAT: "openpgp",
        mod.GIT_CONFIG_USER_SIGNINGKEY: "/home/user/.ssh/id_ed25519_signing",
    }
    assert mod._verify_git_config(config) is False
    assert mod.GIT_CONFIG_GPG_FORMAT in capsys.readouterr().out


def test_verify_git_config_no_signing_key(capsys) -> None:
    config = {
        mod.GIT_CONFIG_COMMIT_GPGSIGN: "true",
        mod.GIT_CONFIG_GPG_FORMAT: "ssh",
        mod.GIT_CONFIG_USER_SIGNINGKEY: None,
    }
    assert mod._verify_git_config(config) is False
    assert mod.GIT_CONFIG_USER_SIGNINGKEY in capsys.readouterr().out


# -- _verify_signature_capability ----------------------------------------------


def test_verify_signature_capability_good_signature(capsys) -> None:
    fake_result = MagicMock()
    fake_result.stdout = "Good signature from user\n"

    with patch("subprocess.run", return_value=fake_result):
        mod._verify_signature_capability()

    assert "Git can verify signatures" in capsys.readouterr().out


def test_verify_signature_capability_no_signature(capsys) -> None:
    fake_result = MagicMock()
    fake_result.stdout = "No signature\n"

    with patch("subprocess.run", return_value=fake_result):
        mod._verify_signature_capability()

    assert "Git can verify signatures" in capsys.readouterr().out


def test_verify_signature_capability_other_output(capsys) -> None:
    fake_result = MagicMock()
    fake_result.stdout = "commit abc123\n"

    with patch("subprocess.run", return_value=fake_result):
        mod._verify_signature_capability()

    assert capsys.readouterr().out == ""


def test_verify_signature_capability_exception(capsys) -> None:
    with patch("subprocess.run", side_effect=OSError("git not found")):
        mod._verify_signature_capability()  # should not raise


# -- verify_setup --------------------------------------------------------------


def test_verify_setup_success(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mod, "is_windows", lambda: False)
    private_key = tmp_path / "id_ed25519_signing"
    private_key.write_text("fake key content")
    pub = tmp_path / "id_ed25519_signing.pub"
    pub.write_text("ssh-ed25519 AAAA test\n")

    monkeypatch.setattr(
        mod,
        "check_git_config",
        lambda: {
            mod.GIT_CONFIG_COMMIT_GPGSIGN: "true",
            mod.GIT_CONFIG_GPG_FORMAT: "ssh",
            mod.GIT_CONFIG_USER_SIGNINGKEY: str(private_key),
        },
    )

    with patch("subprocess.run", return_value=MagicMock(stdout="No signature")):
        result = mod.verify_setup(pub)

    assert result is True


def test_verify_setup_key_missing(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mod, "is_windows", lambda: False)
    pub = tmp_path / "id_ed25519_signing.pub"
    pub.write_text("ssh-ed25519 AAAA test\n")
    # private key not created

    result = mod.verify_setup(pub)
    assert result is False


def test_verify_setup_bad_config(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mod, "is_windows", lambda: False)
    private_key = tmp_path / "id_ed25519_signing"
    private_key.write_text("fake key content")
    pub = tmp_path / "id_ed25519_signing.pub"
    pub.write_text("ssh-ed25519 AAAA test\n")

    monkeypatch.setattr(
        mod,
        "check_git_config",
        lambda: {
            mod.GIT_CONFIG_COMMIT_GPGSIGN: "false",
        },
    )

    result = mod.verify_setup(pub)
    assert result is False


# -- print_next_steps and sub-helpers ------------------------------------------


def test_print_ssh_add_instruction(tmp_path: Path, capsys) -> None:
    pub = tmp_path / "id_ed25519_signing.pub"
    mod._print_ssh_add_instruction(pub)
    out = capsys.readouterr().out
    assert "ssh-add" in out
    assert "id_ed25519_signing" in out


def test_print_github_registration_instruction(tmp_path: Path, capsys) -> None:
    pub = tmp_path / "id_ed25519_signing.pub"
    mod._print_github_registration_instruction(pub)
    out = capsys.readouterr().out
    assert "github.com/settings/keys" in out
    assert "id_ed25519_signing.pub" in out


def test_print_display_key_instruction_non_windows(tmp_path: Path, capsys, monkeypatch: Any) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    pub = tmp_path / "id_ed25519_signing.pub"
    mod._print_display_key_instruction(pub)
    out = capsys.readouterr().out
    assert "cat" in out
    assert "Get-Content" not in out


def test_print_display_key_instruction_windows(tmp_path: Path, capsys, monkeypatch: Any) -> None:
    monkeypatch.setattr("sys.platform", "win32")
    pub = tmp_path / "id_ed25519_signing.pub"
    mod._print_display_key_instruction(pub)
    out = capsys.readouterr().out
    assert "Get-Content" in out


def test_print_next_steps(tmp_path: Path, capsys, monkeypatch: Any) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    pub = tmp_path / "id_ed25519_signing.pub"
    mod.print_next_steps(pub)
    out = capsys.readouterr().out
    assert "Next steps" in out
    assert "ssh-add" in out


# -- _resolve_key_path ---------------------------------------------------------


def test_resolve_key_path_explicit(tmp_path: Path) -> None:
    explicit = tmp_path / "mykey.pub"
    result = mod._resolve_key_path(explicit)
    assert result == explicit.expanduser().resolve()


def test_resolve_key_path_finds_existing(monkeypatch: Any, tmp_path: Path) -> None:
    existing = tmp_path / "id_ed25519_signing.pub"
    existing.write_text("ssh-ed25519 AAAA test\n")
    monkeypatch.setattr(mod, "find_existing_signing_key", lambda: existing)
    result = mod._resolve_key_path(None)
    assert result == existing


def test_resolve_key_path_defaults_to_new(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "find_existing_signing_key", lambda: None)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = mod._resolve_key_path(None)
    assert result == tmp_path / ".ssh" / "id_ed25519_signing.pub"


# -- _handle_check_only --------------------------------------------------------


def test_handle_check_only_false() -> None:
    assert mod._handle_check_only(False, Path("dummy")) is False


def test_handle_check_only_true_key_exists(tmp_path: Path, capsys, monkeypatch: Any) -> None:
    key = tmp_path / "id_ed25519_signing.pub"
    key.write_text("ssh-ed25519 AAAA test\n")
    monkeypatch.setattr(mod, "check_git_config", lambda: {mod.GIT_CONFIG_COMMIT_GPGSIGN: "true"})
    result = mod._handle_check_only(True, key)
    assert result is True
    out = capsys.readouterr().out
    assert "Current Git signing configuration" in out
    assert "exists" in out


def test_handle_check_only_true_key_missing(tmp_path: Path, capsys, monkeypatch: Any) -> None:
    key = tmp_path / "missing.pub"
    monkeypatch.setattr(mod, "check_git_config", lambda: {mod.GIT_CONFIG_COMMIT_GPGSIGN: "true"})
    result = mod._handle_check_only(True, key)
    assert result is True
    out = capsys.readouterr().out
    assert "not found" in out


# -- _resolve_email ------------------------------------------------------------


def test_resolve_email_explicit(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "get_github_email", lambda: "other@example.com")
    assert mod._resolve_email("explicit@example.com") == "explicit@example.com"


def test_resolve_email_falls_back_to_github(monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "get_github_email", lambda: "detected@example.com")
    assert mod._resolve_email(None) == "detected@example.com"


def test_resolve_email_warns_when_missing(monkeypatch: Any, capsys) -> None:
    monkeypatch.setattr(mod, "get_github_email", lambda: None)
    result = mod._resolve_email(None)
    assert result is None
    assert "Could not determine GitHub email" in capsys.readouterr().out


# -- _ensure_signing_key -------------------------------------------------------


def test_ensure_signing_key_exists(tmp_path: Path) -> None:
    key = tmp_path / "id_ed25519_signing.pub"
    key.write_text("ssh-ed25519 AAAA test\n")
    assert mod._ensure_signing_key(key, passphrase="secret") is True


def test_ensure_signing_key_no_passphrase(tmp_path: Path, capsys) -> None:
    key = tmp_path / "id_ed25519_signing.pub"
    # key not created
    result = mod._ensure_signing_key(key, passphrase=None)
    assert result is False
    assert "Passphrase is required" in capsys.readouterr().out


def test_ensure_signing_key_creates_new(tmp_path: Path, monkeypatch: Any) -> None:
    key = tmp_path / "id_ed25519_signing.pub"
    # key not created
    monkeypatch.setattr(mod, "create_signing_key", lambda _path, passphrase: True)
    result = mod._ensure_signing_key(key, passphrase="secret")
    assert result is True


# -- _resolve_passphrase -------------------------------------------------------


def test_resolve_passphrase_no_passphrase_flag() -> None:
    class FakeArgs(argparse.Namespace):
        no_passphrase = True
        passphrase = None

    assert mod._resolve_passphrase(FakeArgs()) == ""


def test_resolve_passphrase_provided() -> None:
    class FakeArgs(argparse.Namespace):
        no_passphrase = False
        passphrase = "mysecret"

    assert mod._resolve_passphrase(FakeArgs()) == "mysecret"


def test_resolve_passphrase_missing(capsys) -> None:
    class FakeArgs(argparse.Namespace):
        no_passphrase = False
        passphrase = None

    result = mod._resolve_passphrase(FakeArgs())
    assert result is None
    assert "Passphrase is required" in capsys.readouterr().out


# -- main() end-to-end tests ---------------------------------------------------


def test_main_success(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    private_key = tmp_path / "id_ed25519_signing"
    private_key.write_text("fake key content")
    pub_key = tmp_path / "id_ed25519_signing.pub"
    pub_key.write_text("ssh-ed25519 AAAA test\n")

    class FakeArgs:
        check_only = False
        key_path = pub_key
        email = "user@example.com"
        force = False
        passphrase = "secret"
        no_passphrase = False

    monkeypatch.setattr(mod, "_parse_args", lambda: FakeArgs())
    monkeypatch.setattr(mod, "_resolve_key_path", lambda _: pub_key)
    monkeypatch.setattr(mod, "_handle_check_only", lambda _cfg, _key: False)
    monkeypatch.setattr(mod, "_resolve_email", lambda _: "user@example.com")
    monkeypatch.setattr(mod, "_ensure_signing_key", lambda _key, passphrase: True)
    monkeypatch.setattr(mod, "configure_git_signing", lambda **_kwargs: True)
    monkeypatch.setattr(mod, "verify_setup", lambda _key: True)
    monkeypatch.setattr(mod, "print_next_steps", lambda _key: None)

    result = mod.main()
    assert result == 0
    assert "Git signing setup complete" in capsys.readouterr().out


def test_main_returns_0_when_check_only(monkeypatch: Any, tmp_path: Path) -> None:
    class FakeArgs:
        check_only = True
        key_path = tmp_path / "id_ed25519_signing.pub"
        email = None
        force = False
        passphrase = None
        no_passphrase = False

    monkeypatch.setattr(mod, "_parse_args", lambda: FakeArgs())
    monkeypatch.setattr(mod, "_resolve_key_path", lambda _: FakeArgs.key_path)
    monkeypatch.setattr(mod, "_handle_check_only", lambda _cfg, _key: True)

    result = mod.main()
    assert result == 0


def test_main_fails_passphrase_required(monkeypatch: Any, tmp_path: Path, capsys) -> None:
    key = tmp_path / "id_ed25519_signing.pub"
    # key does not exist — passphrase required

    class FakeArgs:
        check_only = False
        key_path = key
        email = "user@example.com"
        force = False
        passphrase = None
        no_passphrase = False

    monkeypatch.setattr(mod, "_parse_args", lambda: FakeArgs())
    monkeypatch.setattr(mod, "_resolve_key_path", lambda _: key)
    monkeypatch.setattr(mod, "_handle_check_only", lambda _cfg, _key: False)
    monkeypatch.setattr(mod, "_resolve_passphrase", lambda _args: None)

    result = mod.main()
    assert result == 1


def test_main_ensure_signing_key_fails(monkeypatch: Any, tmp_path: Path) -> None:
    key = tmp_path / "id_ed25519_signing.pub"

    class FakeArgs:
        check_only = False
        key_path = key
        email = "user@example.com"
        force = False
        passphrase = "secret"
        no_passphrase = False

    monkeypatch.setattr(mod, "_parse_args", lambda: FakeArgs())
    monkeypatch.setattr(mod, "_resolve_key_path", lambda _: key)
    monkeypatch.setattr(mod, "_handle_check_only", lambda _cfg, _key: False)
    monkeypatch.setattr(mod, "_resolve_passphrase", lambda _args: "secret")
    monkeypatch.setattr(mod, "_resolve_email", lambda _: "user@example.com")
    monkeypatch.setattr(mod, "_ensure_signing_key", lambda _key, passphrase: False)

    result = mod.main()
    assert result == 1


def test_main_configure_fails(monkeypatch: Any, tmp_path: Path) -> None:
    key = tmp_path / "id_ed25519_signing.pub"
    key.write_text("ssh-ed25519 AAAA test\n")

    class FakeArgs:
        check_only = False
        key_path = key
        email = "user@example.com"
        force = False
        passphrase = None
        no_passphrase = False

    monkeypatch.setattr(mod, "_parse_args", lambda: FakeArgs())
    monkeypatch.setattr(mod, "_resolve_key_path", lambda _: key)
    monkeypatch.setattr(mod, "_handle_check_only", lambda _cfg, _key: False)
    monkeypatch.setattr(mod, "_resolve_email", lambda _: "user@example.com")
    monkeypatch.setattr(mod, "_ensure_signing_key", lambda _key, passphrase: True)
    monkeypatch.setattr(mod, "configure_git_signing", lambda **_kwargs: False)

    result = mod.main()
    assert result == 1


def test_main_verify_fails(monkeypatch: Any, tmp_path: Path) -> None:
    key = tmp_path / "id_ed25519_signing.pub"
    key.write_text("ssh-ed25519 AAAA test\n")

    class FakeArgs:
        check_only = False
        key_path = key
        email = "user@example.com"
        force = False
        passphrase = None
        no_passphrase = False

    monkeypatch.setattr(mod, "_parse_args", lambda: FakeArgs())
    monkeypatch.setattr(mod, "_resolve_key_path", lambda _: key)
    monkeypatch.setattr(mod, "_handle_check_only", lambda _cfg, _key: False)
    monkeypatch.setattr(mod, "_resolve_email", lambda _: "user@example.com")
    monkeypatch.setattr(mod, "_ensure_signing_key", lambda _key, passphrase: True)
    monkeypatch.setattr(mod, "configure_git_signing", lambda **_kwargs: True)
    monkeypatch.setattr(mod, "verify_setup", lambda _key: False)

    result = mod.main()
    assert result == 1
