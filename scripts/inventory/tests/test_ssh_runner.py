from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts.inventory import ssh_runner


@dataclass
class _FakeCompletedProcess:
    returncode: int
    stderr: str
    stdout: str = ""


def test_run_local_redacts_ssh_target_and_identity_file_in_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return _FakeCompletedProcess(returncode=255, stderr="Permission denied")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as excinfo:
        ssh_runner.run_local(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-i",
                "/home/alice/.ssh/id_ed25519",
                "alice@node-a.internal",
                "python3 -",
            ]
        )

    message = str(excinfo.value)
    assert "alice@node-a.internal" not in message
    assert "/home/alice/.ssh/id_ed25519" not in message
    assert "ssh" in message
    assert "<target>" in message
    assert "<identity_file>" in message
