from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.testing.fixture_utils import ensure_executable


def test_ensure_executable_noop_on_windows(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("x", encoding="utf-8")
    with patch("scripts.testing.fixture_utils.os.name", "nt"):
        ensure_executable(path)


def test_ensure_executable_sets_posix_mode() -> None:
    mock_path = MagicMock(spec=Path)
    mock_stat = MagicMock()
    mock_stat.st_mode = 0o644
    mock_path.stat.return_value = mock_stat
    with patch("scripts.testing.fixture_utils.os.name", "posix"):
        ensure_executable(mock_path)
    expected = 0o644 | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    mock_path.chmod.assert_called_once_with(expected)
