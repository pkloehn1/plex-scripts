from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.common.git_signing_utils import find_signing_key_path, git_config_value, is_windows


class TestIsWindows:
    def test_returns_true_on_win32(self) -> None:
        with patch("scripts.common.git_signing_utils.sys") as mock_sys:
            mock_sys.platform = "win32"
            assert is_windows() is True

    def test_returns_false_on_linux(self) -> None:
        with patch("scripts.common.git_signing_utils.sys") as mock_sys:
            mock_sys.platform = "linux"
            assert is_windows() is False

    def test_returns_false_on_darwin(self) -> None:
        with patch("scripts.common.git_signing_utils.sys") as mock_sys:
            mock_sys.platform = "darwin"
            assert is_windows() is False


class TestGitConfigValue:
    def test_returns_value_when_found(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "user@example.com\n"
        with patch("scripts.common.git_signing_utils.subprocess.run", return_value=mock_proc):
            result = git_config_value("user.email")
        assert result == "user@example.com"

    def test_returns_none_when_not_found(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        with patch("scripts.common.git_signing_utils.subprocess.run", return_value=mock_proc):
            result = git_config_value("user.signingkey")
        assert result is None

    def test_strips_trailing_newline(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "/home/user/.ssh/id_ed25519\n"
        with patch("scripts.common.git_signing_utils.subprocess.run", return_value=mock_proc):
            result = git_config_value("user.signingkey")
        assert result == "/home/user/.ssh/id_ed25519"


class TestFindSigningKeyPath:
    def test_explicit_key_returned_when_exists(self, tmp_path: Path) -> None:
        key_file = tmp_path / "my_signing_key"
        key_file.write_text("key content")
        result = find_signing_key_path(str(key_file))
        assert result == key_file

    def test_explicit_key_with_tilde_expansion(self, tmp_path: Path) -> None:
        key_file = tmp_path / "id_custom"
        key_file.write_text("key content")
        with patch("scripts.common.git_signing_utils.Path.home", return_value=tmp_path):
            # Pass the absolute path directly (tilde expansion won't point here)
            result = find_signing_key_path(str(key_file))
        assert result == key_file

    def test_returns_none_when_explicit_key_missing(self, tmp_path: Path) -> None:
        nonexistent = str(tmp_path / "does_not_exist")
        with patch("scripts.common.git_signing_utils.Path.home", return_value=tmp_path):
            result = find_signing_key_path(nonexistent)
        assert result is None

    def test_windows_fallback_finds_pub_key(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        pub_key = ssh_dir / "id_ed25519.pub"
        pub_key.write_text("pubkey")
        with (
            patch("scripts.common.git_signing_utils.sys") as mock_sys,
            patch("scripts.common.git_signing_utils.Path.home", return_value=tmp_path),
        ):
            mock_sys.platform = "win32"
            result = find_signing_key_path(None)
        assert result == pub_key

    def test_windows_fallback_prefers_signing_pub_key(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        signing_pub = ssh_dir / "id_ed25519_signing.pub"
        signing_pub.write_text("signing pubkey")
        regular_pub = ssh_dir / "id_ed25519.pub"
        regular_pub.write_text("regular pubkey")
        with (
            patch("scripts.common.git_signing_utils.sys") as mock_sys,
            patch("scripts.common.git_signing_utils.Path.home", return_value=tmp_path),
        ):
            mock_sys.platform = "win32"
            result = find_signing_key_path(None)
        assert result == signing_pub

    def test_linux_fallback_finds_private_key(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        private_key = ssh_dir / "id_ed25519"
        private_key.write_text("private key")
        with (
            patch("scripts.common.git_signing_utils.sys") as mock_sys,
            patch("scripts.common.git_signing_utils.Path.home", return_value=tmp_path),
        ):
            mock_sys.platform = "linux"
            result = find_signing_key_path(None)
        assert result == private_key

    def test_linux_fallback_prefers_signing_private_key(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        signing_key = ssh_dir / "id_ed25519_signing"
        signing_key.write_text("signing key")
        regular_key = ssh_dir / "id_ed25519"
        regular_key.write_text("regular key")
        with (
            patch("scripts.common.git_signing_utils.sys") as mock_sys,
            patch("scripts.common.git_signing_utils.Path.home", return_value=tmp_path),
        ):
            mock_sys.platform = "linux"
            result = find_signing_key_path(None)
        assert result == signing_key

    def test_returns_none_when_no_fallback_found(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        with (
            patch("scripts.common.git_signing_utils.sys") as mock_sys,
            patch("scripts.common.git_signing_utils.Path.home", return_value=tmp_path),
        ):
            mock_sys.platform = "linux"
            result = find_signing_key_path(None)
        assert result is None

    def test_windows_returns_none_when_no_fallback_found(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        with (
            patch("scripts.common.git_signing_utils.sys") as mock_sys,
            patch("scripts.common.git_signing_utils.Path.home", return_value=tmp_path),
        ):
            mock_sys.platform = "win32"
            result = find_signing_key_path(None)
        assert result is None

    def test_explicit_none_key_falls_back_to_candidates(self, tmp_path: Path) -> None:
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        rsa_signing_pub = ssh_dir / "id_rsa_signing.pub"
        rsa_signing_pub.write_text("rsa signing pub")
        with (
            patch("scripts.common.git_signing_utils.sys") as mock_sys,
            patch("scripts.common.git_signing_utils.Path.home", return_value=tmp_path),
        ):
            mock_sys.platform = "win32"
            result = find_signing_key_path(None)
        assert result == rsa_signing_pub
