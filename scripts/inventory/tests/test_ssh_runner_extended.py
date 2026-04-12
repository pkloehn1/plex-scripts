from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.inventory import ssh_runner


@dataclass
class _FakeProcess:
    returncode: int
    stderr: str
    stdout: str = ""


def test_format_command_for_error_empty_argv() -> None:
    result = ssh_runner._format_command_for_error([])
    assert result == ""


def test_format_command_for_error_non_ssh_command() -> None:
    result = ssh_runner._format_command_for_error(["python3", "script.py"])
    assert result == "python3 script.py"


def test_run_local_raises_host_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return _FakeProcess(returncode=255, stderr="Host key verification failed.")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="SSH host key verification failed"):
        ssh_runner.run_local(["ssh", "user@host", "true"])


def test_run_local_raises_generic_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return _FakeProcess(returncode=1, stderr="some error")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Command failed"):
        ssh_runner.run_local(["ls", "/nonexistent"])


def test_run_local_returns_stdout_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args, **kwargs):
        del args, kwargs
        return _FakeProcess(returncode=0, stderr="", stdout="hello\n")

    monkeypatch.setattr(ssh_runner.subprocess, "run", fake_run)

    result = ssh_runner.run_local(["echo", "hello"])
    assert result == "hello\n"


def test_run_remote_includes_port_and_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def fake_run_local(argv: list[str], *, stdin_text: str | None = None) -> str:
        del stdin_text
        captured.append(argv)
        return "ok"

    monkeypatch.setattr(ssh_runner, "run_local", fake_run_local)

    result = ssh_runner.run_remote(
        host="myhost",
        user="bob",
        port=2222,
        identity_file=Path("/home/bob/.ssh/id_rsa"),
        remote_cmd="hostname",
    )

    assert result == "ok"
    argv = captured[0]
    assert "-p" in argv
    assert "2222" in argv
    assert "-i" in argv
    identity_idx = argv.index("-i")
    assert "id_rsa" in argv[identity_idx + 1]
    assert "bob@myhost" in argv


def test_run_remote_no_port_no_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[list[str]] = []

    def fake_run_local(argv: list[str], *, stdin_text: str | None = None) -> str:
        del stdin_text
        captured.append(argv)
        return "output"

    monkeypatch.setattr(ssh_runner, "run_local", fake_run_local)

    ssh_runner.run_remote(
        host="myhost",
        user="root",
        port=None,
        identity_file=None,
        remote_cmd="true",
    )

    argv = captured[0]
    assert "-p" not in argv
    assert "-i" not in argv
    assert "root@myhost" in argv


def test_runner_run_with_host(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_run_remote(**kwargs) -> str:
        calls.append(kwargs["remote_cmd"])
        return "result"

    monkeypatch.setattr(ssh_runner, "run_remote", fake_run_remote)

    runner = ssh_runner.Runner("myhost", "user", None, None)
    result = runner.run("hostname")

    assert result == "result"
    assert "hostname" in calls


def test_runner_run_local_no_host_bash_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssh_runner.shutil, "which", lambda _: "/usr/bin/bash")

    captured: list[list[str]] = []

    def fake_run_local(argv: list[str], *, stdin_text: str | None = None) -> str:
        del stdin_text
        captured.append(argv)
        return "local output"

    monkeypatch.setattr(ssh_runner, "run_local", fake_run_local)

    runner = ssh_runner.Runner(None, "user", None, None)
    result = runner.run("hostname")

    assert result == "local output"
    assert captured[0][0] == "/usr/bin/bash"


def test_runner_run_local_no_bash_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ssh_runner.shutil, "which", lambda _: None)

    runner = ssh_runner.Runner(None, "user", None, None)
    with pytest.raises(RuntimeError, match="Local collection requires"):
        runner.run("hostname")


def test_runner_check_alive_with_host(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_run_remote(**kwargs) -> str:
        calls.append(kwargs["remote_cmd"])
        return ""

    monkeypatch.setattr(ssh_runner, "run_remote", fake_run_remote)

    runner = ssh_runner.Runner("myhost", "user", None, None)
    runner.check_alive()

    assert calls == ["true"]


def test_runner_check_alive_no_host_is_noop() -> None:
    runner = ssh_runner.Runner(None, "user", None, None)
    runner.check_alive()  # must not raise


def test_runner_run_remote_python_no_host_raises() -> None:
    runner = ssh_runner.Runner(None, "user", None, None)
    with pytest.raises(RuntimeError, match="Remote python execution requires --host"):
        runner.run_remote_python("print('hi')", sudo=False)


def test_runner_run_remote_python_with_sudo(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    def fake_run_remote(**kwargs) -> str:
        captured.append(kwargs)
        return '{"result": "ok"}'

    monkeypatch.setattr(ssh_runner, "run_remote", fake_run_remote)

    runner = ssh_runner.Runner("myhost", "user", None, None)
    result = runner.run_remote_python("print('hi')", sudo=True)

    assert result == '{"result": "ok"}'
    assert captured[0]["remote_cmd"] == "sudo -n python3 -"
    assert captured[0]["stdin_text"] == "print('hi')"


def test_runner_run_remote_python_no_sudo(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    def fake_run_remote(**kwargs) -> str:
        captured.append(kwargs)
        return '{"result": "ok"}'

    monkeypatch.setattr(ssh_runner, "run_remote", fake_run_remote)

    runner = ssh_runner.Runner("myhost", "user", None, None)
    runner.run_remote_python("print('hi')", sudo=False)

    assert captured[0]["remote_cmd"] == "python3 -"
