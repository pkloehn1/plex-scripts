from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.common.encoding import ensure_utf8_stdio


class TestEnsureUtf8Stdio:
    def test_no_op_on_non_windows(self) -> None:
        with patch("scripts.common.encoding.sys") as mock_sys:
            mock_sys.platform = "linux"
            ensure_utf8_stdio()
            mock_sys.stdout.reconfigure.assert_not_called()

    def test_reconfigures_stdout_and_stderr_on_windows(self) -> None:
        mock_stdout = MagicMock()
        mock_stderr = MagicMock()
        with patch("scripts.common.encoding.sys") as mock_sys:
            mock_sys.platform = "win32"
            mock_sys.stdout = mock_stdout
            mock_sys.stderr = mock_stderr
            ensure_utf8_stdio()
        mock_stdout.reconfigure.assert_called_once_with(encoding="utf-8")
        mock_stderr.reconfigure.assert_called_once_with(encoding="utf-8")

    def test_skips_reconfigure_when_method_absent(self) -> None:
        mock_stdout = object()  # no reconfigure attribute
        mock_stderr = object()
        with patch("scripts.common.encoding.sys") as mock_sys:
            mock_sys.platform = "win32"
            mock_sys.stdout = mock_stdout
            mock_sys.stderr = mock_stderr
            # Should not raise even though reconfigure is missing
            ensure_utf8_stdio()
