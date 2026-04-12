from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.common.paths import repo_root
from scripts.testing.stub_factories import make_docker_runner_success, make_git_runner


@pytest.fixture(autouse=True)
def _set_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure the runner computes the correct repo root for tests.
    monkeypatch.chdir(repo_root())


def test_linux_prints_start_command_when_container_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.delenv("SUPER_LINTER_DEFAULT_BRANCH", raising=False)
    monkeypatch.delenv("SUPER_LINTER_VALIDATE_ALL_CODEBASE", raising=False)
    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "docker")

    seen: list[list[str]] = []

    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner())
    monkeypatch.setattr(runner.subprocess, "run", make_docker_runner_success(seen=seen))

    exit_code = runner._run_docker(Path.cwd())
    assert exit_code == 0

    # Sanity-check key docker run arguments are present.
    docker_run_cmds = [comprehension for comprehension in seen if comprehension[:2] == ["docker", "run"]]
    assert len(docker_run_cmds) == 1
    cmd = docker_run_cmds[0]
    assert "--rm" in cmd
    assert "--pull" in cmd
    assert runner.SUPER_LINTER_IMAGE_DEFAULT in cmd

    env_args = [value for value in cmd if value.startswith("DEFAULT_BRANCH=")]
    assert env_args == ["DEFAULT_BRANCH=origin/main"]

    linter_rules = [val for val in cmd if val.startswith("LINTER_RULES_PATH=")]
    assert linter_rules == ["LINTER_RULES_PATH=.github/linters"]

    md_config = [val for val in cmd if val.startswith("MARKDOWN_CONFIG_FILE=")]
    assert md_config == ["MARKDOWN_CONFIG_FILE=.markdownlint.yml"]


def test_docker_cmd_inserts_sudo_non_interactive_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "sudo docker")
    # Under pytest, stdio is typically not a TTY, so -n should be inserted.
    assert runner._docker_cmd()[:3] == ["sudo", "-n", "docker"]

    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "sudo -n docker")
    assert runner._docker_cmd()[:3] == ["sudo", "-n", "docker"]


def test_docker_cmd_allows_interactive_sudo_when_tty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "sudo docker")
    monkeypatch.setattr(runner.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(runner.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(runner.sys.stderr, "isatty", lambda: True)

    assert runner._docker_cmd()[:2] == ["sudo", "docker"]


def test_run_docker_prints_sudo_v_when_sudo_auth_required(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "sudo -n docker")

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:4] == ["sudo", "-n", "docker", "version"]:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="sudo: a password is required\n",
            )
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner())
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    exit_code = runner._run_docker(Path.cwd())
    assert exit_code != 0

    captured = capsys.readouterr()
    assert "sudo -v" in captured.err


def test_run_docker_fails_when_docker_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "docker")

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["docker", "version"]:
            raise FileNotFoundError("docker not found")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner())
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    exit_code = runner._run_docker(Path.cwd())
    assert exit_code == 127

    captured = capsys.readouterr()
    assert "Docker command not found" in captured.err


def test_run_docker_falls_back_to_validate_all_codebase_when_ref_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.delenv("SUPER_LINTER_DEFAULT_BRANCH", raising=False)
    monkeypatch.delenv("SUPER_LINTER_VALIDATE_ALL_CODEBASE", raising=False)
    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "docker")

    seen: list[list[str]] = []

    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner(ref_exists=False))
    monkeypatch.setattr(runner.subprocess, "run", make_docker_runner_success(seen=seen))

    exit_code = runner._run_docker(Path.cwd())
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "DEFAULT_BRANCH ref not found locally" in captured.err

    docker_run_cmds = [comprehension for comprehension in seen if comprehension[:2] == ["docker", "run"]]
    assert len(docker_run_cmds) == 1
    cmd = docker_run_cmds[0]
    assert "DEFAULT_BRANCH=origin/main" in cmd
    assert "VALIDATE_ALL_CODEBASE=true" in cmd


def test_run_docker_handles_missing_git(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.delenv("SUPER_LINTER_DEFAULT_BRANCH", raising=False)
    monkeypatch.delenv("SUPER_LINTER_VALIDATE_ALL_CODEBASE", raising=False)
    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "docker")

    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner(error="git not found on PATH"))
    monkeypatch.setattr(runner.subprocess, "run", make_docker_runner_success())

    exit_code = runner._run_docker(Path.cwd())
    assert exit_code == 0


def test_resolve_super_linter_image_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.delenv("SUPER_LINTER_IMAGE", raising=False)
    assert runner._resolve_super_linter_image() == runner.SUPER_LINTER_IMAGE_DEFAULT


def test_resolve_super_linter_image_slim_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_IMAGE", "ghcr.io/super-linter/super-linter:slim-v8")
    assert runner._resolve_super_linter_image() == runner.SUPER_LINTER_IMAGE_DEFAULT


def test_resolve_super_linter_image_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_IMAGE", "my-image:v1")
    assert runner._resolve_super_linter_image() == "my-image:v1"


def test_resolve_default_branch_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_DEFAULT_BRANCH", "develop")
    assert runner._resolve_default_branch(Path.cwd()) == "develop"


def test_candidate_refs_for_refs_prefix() -> None:
    import scripts.linting.run_super_linter as runner

    assert runner._candidate_refs_for("refs/heads/main") == ["refs/heads/main"]


def test_candidate_refs_for_with_remote() -> None:
    import scripts.linting.run_super_linter as runner

    result = runner._candidate_refs_for("origin/main")
    assert "refs/remotes/origin/main" in result
    assert "refs/heads/origin/main" in result


def test_maybe_append_default_filter_excludes_non_default_image() -> None:
    import scripts.linting.run_super_linter as runner

    env_pairs: list[tuple[str, str]] = []
    runner._maybe_append_default_filter_excludes(env_pairs, image="custom:v1")
    assert not any(key == "FILTER_REGEX_EXCLUDE" for key, _ in env_pairs)


def test_maybe_append_default_filter_excludes_already_set(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("FILTER_REGEX_EXCLUDE", "custom_pattern")
    env_pairs: list[tuple[str, str]] = []
    runner._maybe_append_default_filter_excludes(env_pairs, image=runner.SUPER_LINTER_IMAGE_DEFAULT)
    assert not any(key == "FILTER_REGEX_EXCLUDE" for key, _ in env_pairs)


def test_maybe_set_default_jscpd_non_default_image() -> None:
    import scripts.linting.run_super_linter as runner

    env_pairs: list[tuple[str, str]] = []
    runner._maybe_set_default_jscpd_config_file(env_pairs, image="custom:v1", repo_root=Path.cwd())
    assert not any(key == "JSCPD_LINTER_RULES" for key, _ in env_pairs)


def test_maybe_set_default_jscpd_env_already_set(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("JSCPD_LINTER_RULES", "/custom/path")
    env_pairs: list[tuple[str, str]] = []
    runner._maybe_set_default_jscpd_config_file(
        env_pairs, image=runner.SUPER_LINTER_IMAGE_DEFAULT, repo_root=Path.cwd()
    )
    assert not any(key == "JSCPD_LINTER_RULES" for key, _ in env_pairs)


def test_maybe_set_default_jscpd_no_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.delenv("JSCPD_LINTER_RULES", raising=False)
    monkeypatch.delenv("JSCPD_CONFIG_FILE", raising=False)
    env_pairs: list[tuple[str, str]] = []
    runner._maybe_set_default_jscpd_config_file(env_pairs, image=runner.SUPER_LINTER_IMAGE_DEFAULT, repo_root=tmp_path)
    assert not any(key == "JSCPD_LINTER_RULES" for key, _ in env_pairs)


def test_repo_root() -> None:
    import scripts.linting.run_super_linter as runner

    result = runner._repo_root()
    assert isinstance(result, Path)
    assert (result / "pyproject.toml").exists()


def test_is_docker_permission_denied() -> None:
    import scripts.linting.run_super_linter as runner

    assert (
        runner._is_docker_permission_denied("Got permission denied while trying to connect to the Docker daemon socket")
        is True
    )
    assert runner._is_docker_permission_denied("everything is fine") is False


def test_try_sudo_docker_cmd_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setattr(runner.sys, "platform", "win32")
    assert runner._try_sudo_docker_cmd(Path.cwd()) is None


def test_try_sudo_docker_cmd_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="Docker version", stderr="")

    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner._try_sudo_docker_cmd(Path.cwd())
    assert result == ["sudo", "-n", "docker"]


def test_try_sudo_docker_cmd_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="sudo: a password is required")

    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._try_sudo_docker_cmd(Path.cwd()) is None


def test_resolve_usable_docker_cmd_permission_denied_sudo_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.linting.run_super_linter as runner

    call_count = 0

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal call_count
        call_count += 1
        if cmd[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="Got permission denied while trying to connect to the Docker daemon socket",
            )
        if cmd[:4] == ["sudo", "-n", "docker", "version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="Docker version", stderr="")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result_cmd, ret = runner._resolve_usable_docker_cmd(Path.cwd(), ["docker"])
    assert result_cmd == ["sudo", "-n", "docker"]
    assert ret == 0


def test_resolve_usable_docker_cmd_permission_denied_no_sudo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(
                cmd,
                1,
                stdout="",
                stderr="Got permission denied while trying to connect to the Docker daemon socket",
            )
        if cmd[:4] == ["sudo", "-n", "docker", "version"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="sudo: a password is required")
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(runner.sys, "platform", "linux")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result_cmd, _ret = runner._resolve_usable_docker_cmd(Path.cwd(), ["docker"])
    assert result_cmd is None
    captured = capsys.readouterr()
    assert "Docker access denied" in captured.err


def test_resolve_usable_docker_cmd_generic_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="some other error")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result_cmd, _ret = runner._resolve_usable_docker_cmd(Path.cwd(), ["docker"])
    assert result_cmd is None
    captured = capsys.readouterr()
    assert "Docker is not usable" in captured.err


def test_resolve_validate_all_codebase_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_VALIDATE_ALL_CODEBASE", "TRUE")
    assert runner._resolve_validate_all_codebase(Path.cwd(), "main") == "true"


def test_resolve_pull_policy_invalid(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_PULL_POLICY", "invalid")
    assert runner._resolve_pull_policy() is None
    captured = capsys.readouterr()
    assert "Invalid SUPER_LINTER_PULL_POLICY" in captured.err


def test_run_docker_invalid_pull_policy(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "docker")
    monkeypatch.setenv("SUPER_LINTER_PULL_POLICY", "invalid")

    seen: list[list[str]] = []
    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner())
    monkeypatch.setattr(runner.subprocess, "run", make_docker_runner_success(seen=seen))

    exit_code = runner._run_docker(Path.cwd())
    assert exit_code == 2


def test_run_docker_with_fcntl_locking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "docker")

    seen: list[list[str]] = []
    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner())
    monkeypatch.setattr(runner.subprocess, "run", make_docker_runner_success(seen=seen))

    # Create a mock fcntl module
    flock_calls: list[tuple[int, int]] = []

    class FakeFcntl:
        LOCK_EX = 2
        LOCK_UN = 8

        @staticmethod
        def flock(file_desc: int, operation: int) -> None:
            flock_calls.append((file_desc, operation))

    monkeypatch.setattr(runner, "fcntl", FakeFcntl)

    exit_code = runner._run_docker(repo_root())
    assert exit_code == 0
    # Verify both lock and unlock were called
    assert len(flock_calls) == 2
    assert flock_calls[0][1] == FakeFcntl.LOCK_EX
    assert flock_calls[1][1] == FakeFcntl.LOCK_UN


def test_main_calls_run_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setattr(runner, "_run_docker", lambda _root: 42)
    assert runner.main() == 42


# --- Image freshness check tests ---


def test_get_local_repo_digest_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            cmd, 0, stdout="ghcr.io/super-linter/super-linter@sha256:abc123\n", stderr=""
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner._get_local_repo_digest(["docker"], "img:v8", cwd=Path.cwd())
    assert result == "sha256:abc123"


def test_get_local_repo_digest_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="No such image")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._get_local_repo_digest(["docker"], "img:v8", cwd=Path.cwd()) is None


def test_get_local_repo_digest_no_at_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="malformed-output", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._get_local_repo_digest(["docker"], "img:v8", cwd=Path.cwd()) is None


def test_get_remote_repo_digest_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    import scripts.linting.run_super_linter as runner

    manifest = b'{"schemaVersion": 2}'
    expected = "sha256:" + hashlib.sha256(manifest).hexdigest()

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 0, stdout=manifest, stderr=b"")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner._get_remote_repo_digest(["docker"], "img:v8", cwd=Path.cwd())
    assert result == expected


def test_get_remote_repo_digest_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"not found")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._get_remote_repo_digest(["docker"], "img:v8", cwd=Path.cwd()) is None


def test_get_local_image_id_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="sha256:imgid999\n", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._get_local_image_id(["docker"], "img:v8", cwd=Path.cwd()) == "sha256:imgid999"


def test_get_local_image_id_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._get_local_image_id(["docker"], "img:v8", cwd=Path.cwd()) is None


def test_pull_image_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._pull_image(["docker"], "img:v8", cwd=Path.cwd()) == 0


def test_pull_image_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._pull_image(["docker"], "img:v8", cwd=Path.cwd()) == 1


def test_remove_old_image(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.linting.run_super_linter as runner

    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner._remove_old_image(["docker"], "sha256:old123", cwd=Path.cwd())
    assert seen == [["docker", "rmi", "sha256:old123"]]


def test_ensure_image_fresh_missing_pull_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.linting.run_super_linter as runner

    call_idx = 0

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal call_idx
        call_idx += 1
        if cmd[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        if cmd[1:2] == ["pull"]:
            return subprocess.CompletedProcess(cmd, 0)
        raise AssertionError(f"Unexpected: {cmd}")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._ensure_image_fresh(["docker"], "img:v8", cwd=Path.cwd()) == 0
    captured = capsys.readouterr()
    assert "not found locally" in captured.err
    assert "image pulled" in captured.err


def test_ensure_image_fresh_missing_pull_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        if cmd[1:2] == ["pull"]:
            return subprocess.CompletedProcess(cmd, 1)
        raise AssertionError(f"Unexpected: {cmd}")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._ensure_image_fresh(["docker"], "img:v8", cwd=Path.cwd()) == 1
    captured = capsys.readouterr()
    assert "Failed to pull" in captured.err


def test_ensure_image_fresh_digests_match(monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib

    import scripts.linting.run_super_linter as runner

    manifest = b'{"test": true}'
    digest = "sha256:" + hashlib.sha256(manifest).hexdigest()

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        if cmd[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"img:v8@{digest}", stderr="")
        if cmd[1:4] == ["buildx", "imagetools", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=manifest, stderr=b"")
        raise AssertionError(f"Unexpected: {cmd}")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._ensure_image_fresh(["docker"], "img:v8", cwd=Path.cwd()) == 0


def test_ensure_image_fresh_stale_pulls_and_removes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.linting.run_super_linter as runner

    seen: list[list[str]] = []

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        seen.append(cmd)
        if cmd[1:3] == ["image", "inspect"]:
            if any("RepoDigests" in arg for arg in cmd):
                return subprocess.CompletedProcess(cmd, 0, stdout="img:v8@sha256:old_digest", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="sha256:oldid", stderr="")
        if cmd[1:4] == ["buildx", "imagetools", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"different-manifest", stderr=b"")
        if cmd[1:2] == ["pull"]:
            return subprocess.CompletedProcess(cmd, 0)
        if cmd[1:2] == ["rmi"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected: {cmd}")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._ensure_image_fresh(["docker"], "img:v8", cwd=Path.cwd()) == 0
    captured = capsys.readouterr()
    assert "stale" in captured.err.lower()
    assert "updated" in captured.err.lower()
    rmi_cmds = [cmd for cmd in seen if cmd[1:2] == ["rmi"]]
    assert len(rmi_cmds) == 1
    assert rmi_cmds[0][2] == "sha256:oldid"


def test_ensure_image_fresh_remote_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        if cmd[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="img:v8@sha256:abc", stderr="")
        if cmd[1:4] == ["buildx", "imagetools", "inspect"]:
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"network error")
        raise AssertionError(f"Unexpected: {cmd}")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._ensure_image_fresh(["docker"], "img:v8", cwd=Path.cwd()) == 0
    captured = capsys.readouterr()
    assert "Cannot check registry" in captured.err


def test_ensure_image_fresh_stale_pull_fails_uses_cache(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import scripts.linting.run_super_linter as runner

    def fake_run(
        cmd: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        if cmd[1:3] == ["image", "inspect"]:
            if any("RepoDigests" in arg for arg in cmd):
                return subprocess.CompletedProcess(cmd, 0, stdout="img:v8@sha256:old", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="sha256:oldid", stderr="")
        if cmd[1:4] == ["buildx", "imagetools", "inspect"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=b"new-manifest", stderr=b"")
        if cmd[1:2] == ["pull"]:
            return subprocess.CompletedProcess(cmd, 1)
        raise AssertionError(f"Unexpected: {cmd}")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._ensure_image_fresh(["docker"], "img:v8", cwd=Path.cwd()) == 0
    captured = capsys.readouterr()
    assert "Using cached image" in captured.err


def test_run_docker_always_policy_uses_pull_never(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.delenv("SUPER_LINTER_DEFAULT_BRANCH", raising=False)
    monkeypatch.delenv("SUPER_LINTER_VALIDATE_ALL_CODEBASE", raising=False)
    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "docker")
    monkeypatch.setenv("SUPER_LINTER_PULL_POLICY", "always")

    seen: list[list[str]] = []
    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner())
    monkeypatch.setattr(runner.subprocess, "run", make_docker_runner_success(seen=seen))

    exit_code = runner._run_docker(Path.cwd())
    assert exit_code == 0

    docker_run_cmds = [cmd for cmd in seen if cmd[:2] == ["docker", "run"]]
    assert len(docker_run_cmds) == 1
    cmd = docker_run_cmds[0]
    pull_idx = cmd.index("--pull")
    assert cmd[pull_idx + 1] == "never"


def test_run_docker_always_policy_freshness_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "docker")
    monkeypatch.setenv("SUPER_LINTER_PULL_POLICY", "always")

    def fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ["docker", "version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        # Image missing locally + pull fails → _ensure_image_fresh returns 1
        if cmd[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        if cmd[1:2] == ["pull"]:
            return subprocess.CompletedProcess(cmd, 1)
        raise AssertionError(f"Unexpected: {cmd}")

    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner())
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    exit_code = runner._run_docker(Path.cwd())
    assert exit_code == 1


def test_run_docker_missing_policy_uses_pull_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.linting.run_super_linter as runner

    monkeypatch.delenv("SUPER_LINTER_DEFAULT_BRANCH", raising=False)
    monkeypatch.delenv("SUPER_LINTER_VALIDATE_ALL_CODEBASE", raising=False)
    monkeypatch.setenv("SUPER_LINTER_DOCKER_CMD", "docker")
    monkeypatch.setenv("SUPER_LINTER_PULL_POLICY", "missing")

    seen: list[list[str]] = []
    monkeypatch.setattr(runner.git_runner, "run_git", make_git_runner())
    monkeypatch.setattr(runner.subprocess, "run", make_docker_runner_success(seen=seen))

    exit_code = runner._run_docker(Path.cwd())
    assert exit_code == 0

    docker_run_cmds = [cmd for cmd in seen if cmd[:2] == ["docker", "run"]]
    assert len(docker_run_cmds) == 1
    cmd = docker_run_cmds[0]
    pull_idx = cmd.index("--pull")
    assert cmd[pull_idx + 1] == "missing"
