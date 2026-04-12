from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _format_command_for_error(argv: list[str]) -> str:
    if not argv:
        return ""

    if argv[0] != "ssh":
        return " ".join(argv)

    redacted = argv.copy()

    # Redact identity file path (often contains usernames or local paths).
    for idx, value in enumerate(redacted):
        if value == "-i" and idx + 1 < len(redacted):
            redacted[idx + 1] = "<identity_file>"

    # Redact targets like 'user@host'.
    for idx, value in enumerate(redacted):
        if value and not value.startswith("-") and "@" in value:
            redacted[idx] = "<target>"

    return " ".join(redacted)


def run_local(argv: list[str], *, stdin_text: str | None = None) -> str:
    result = subprocess.run(
        argv,
        input=stdin_text,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        cmd = _format_command_for_error(argv)
        if "Host key verification failed." in stderr and argv and argv[0] == "ssh":
            raise RuntimeError(
                "SSH host key verification failed.\n"
                "Fix: add the host key to your SSH known_hosts, then retry.\n"
                "Options:\n"
                "- Run once interactively: ssh USER@HOST (accept the prompt), then rerun this script\n"
                "- If the host was rebuilt/changed keys: ssh-keygen -R HOST (then ssh USER@HOST again)\n"
                f"Command failed ({result.returncode}): {cmd}\n{stderr}"
            )
        raise RuntimeError(f"Command failed ({result.returncode}): {cmd}\n{stderr}")
    return result.stdout


def run_remote(
    *,
    host: str,
    user: str,
    port: int | None,
    identity_file: Path | None,
    remote_cmd: str,
    stdin_text: str | None = None,
) -> str:
    ssh_argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=5",
        "-o",
        "ConnectionAttempts=1",
        "-o",
        "ServerAliveInterval=5",
        "-o",
        "ServerAliveCountMax=1",
    ]
    if port is not None:
        ssh_argv.extend(["-p", str(port)])
    if identity_file is not None:
        ssh_argv.extend(["-i", str(identity_file)])

    ssh_argv.append(f"{user}@{host}")
    ssh_argv.append(remote_cmd)
    return run_local(ssh_argv, stdin_text=stdin_text)


class Runner:
    def __init__(self, host: str | None, user: str, port: int | None, identity_file: Path | None) -> None:
        self._host = host
        self._user = user
        self._port = port
        self._identity_file = identity_file

    def run(self, remote_cmd: str) -> str:
        if self._host is None:
            bash = shutil.which("bash")
            if bash is None:
                raise RuntimeError(
                    "Local collection requires 'bash' (WSL/Git Bash). "
                    "On Windows, prefer using --host to collect via SSH."
                )
            return run_local([bash, "-lc", remote_cmd])

        return run_remote(
            host=self._host,
            user=self._user,
            port=self._port,
            identity_file=self._identity_file,
            remote_cmd=remote_cmd,
        )

    def check_alive(self) -> None:
        if self._host is None:
            return
        run_remote(
            host=self._host,
            user=self._user,
            port=self._port,
            identity_file=self._identity_file,
            remote_cmd="true",
        )

    def run_remote_python(self, python_code: str, *, sudo: bool) -> str:
        if self._host is None:
            raise RuntimeError("Remote python execution requires --host")
        remote_cmd = "python3 -"
        if sudo:
            remote_cmd = "sudo -n python3 -"
        return run_remote(
            host=self._host,
            user=self._user,
            port=self._port,
            identity_file=self._identity_file,
            remote_cmd=remote_cmd,
            stdin_text=python_code,
        )
