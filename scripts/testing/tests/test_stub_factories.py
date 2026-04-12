"""Tests for scripts.testing.stub_factories."""

from __future__ import annotations

import hashlib
import json

import pytest

from scripts.testing.stub_factories import (
    FAKE_MANIFEST_BYTES,
    FAKE_MANIFEST_DIGEST,
    make_docker_runner_success,
    make_git_runner,
)

# --- Constants ----------------------------------------------------------------


class TestConstants:
    def test_fake_manifest_digest_matches_bytes(self) -> None:
        expected = "sha256:" + hashlib.sha256(FAKE_MANIFEST_BYTES).hexdigest()
        assert expected == FAKE_MANIFEST_DIGEST

    def test_fake_manifest_bytes_is_valid_json(self) -> None:
        parsed = json.loads(FAKE_MANIFEST_BYTES)
        assert isinstance(parsed, dict)


# --- make_git_runner ----------------------------------------------------------


class TestMakeGitRunner:
    def test_symbolic_ref_returns_head_ref(self) -> None:
        runner = make_git_runner()
        result = runner(["symbolic-ref", "refs/remotes/origin/HEAD"])
        assert result.returncode == 0
        assert result.stdout.strip() == "refs/remotes/origin/main"

    def test_custom_head_ref(self) -> None:
        runner = make_git_runner(head_ref="refs/remotes/origin/develop")
        result = runner(["symbolic-ref", "refs/remotes/origin/HEAD"])
        assert result.stdout.strip() == "refs/remotes/origin/develop"

    def test_show_ref_exists(self) -> None:
        runner = make_git_runner(ref_exists=True)
        result = runner(["show-ref", "--verify", "--quiet", "refs/heads/main"])
        assert result.returncode == 0

    def test_show_ref_not_exists(self) -> None:
        runner = make_git_runner(ref_exists=False)
        result = runner(["show-ref", "--verify", "--quiet", "refs/heads/gone"])
        assert result.returncode == 1

    def test_error_returns_failure(self) -> None:
        runner = make_git_runner(error="fatal: not a git repository")
        result = runner(["symbolic-ref", "refs/remotes/origin/HEAD"])
        assert result.returncode == 127
        assert result.stderr == "fatal: not a git repository"

    def test_unexpected_args_returns_failure(self) -> None:
        runner = make_git_runner()
        result = runner(["status"])
        assert result.returncode == 1
        assert result.stderr == "unexpected git args"


# --- make_docker_runner_success -----------------------------------------------


class TestMakeDockerRunnerSuccess:
    def test_docker_version(self) -> None:
        runner = make_docker_runner_success()
        result = runner(["docker", "version"])
        assert result.returncode == 0

    def test_docker_run(self) -> None:
        runner = make_docker_runner_success()
        result = runner(["docker", "run", "--rm", "image:tag"])
        assert result.returncode == 0

    def test_image_inspect_repo_digests(self) -> None:
        runner = make_docker_runner_success()
        result = runner(["docker", "image", "inspect", "--format", "{{.RepoDigests}}", "myimage:v1"])
        assert result.returncode == 0
        assert isinstance(result.stdout, str)
        assert f"myimage:v1@{FAKE_MANIFEST_DIGEST}" in result.stdout

    def test_image_inspect_without_repo_digests(self) -> None:
        runner = make_docker_runner_success()
        result = runner(["docker", "image", "inspect", "--format", "{{.Id}}", "myimage:v1"])
        assert result.returncode == 0
        assert result.stdout == "sha256:localid"

    def test_buildx_imagetools_inspect(self) -> None:
        runner = make_docker_runner_success()
        result = runner(["docker", "buildx", "imagetools", "inspect", "myimage:v1", "--raw"])
        assert result.returncode == 0
        assert result.stdout == FAKE_MANIFEST_BYTES

    def test_docker_pull(self) -> None:
        runner = make_docker_runner_success()
        result = runner(["docker", "pull", "myimage:v1"])
        assert result.returncode == 0

    def test_docker_rmi(self) -> None:
        runner = make_docker_runner_success()
        result = runner(["docker", "rmi", "myimage:v1"])
        assert result.returncode == 0

    def test_unexpected_command_raises(self) -> None:
        runner = make_docker_runner_success()
        with pytest.raises(AssertionError, match="Unexpected command"):
            runner(["docker", "network", "ls"])

    def test_seen_list_tracks_commands(self) -> None:
        seen: list[list[str]] = []
        runner = make_docker_runner_success(seen=seen)
        runner(["docker", "version"])
        runner(["docker", "run", "--rm", "img:v1"])
        assert len(seen) == 2
        assert seen[0] == ["docker", "version"]

    def test_custom_manifest_bytes(self) -> None:
        custom_bytes = b'{"custom": "manifest"}'
        runner = make_docker_runner_success(manifest_bytes=custom_bytes)
        result = runner(["docker", "buildx", "imagetools", "inspect", "img:v1", "--raw"])
        assert result.stdout == custom_bytes

    def test_custom_manifest_digest(self) -> None:
        custom_digest = "sha256:abc123"
        runner = make_docker_runner_success(manifest_digest=custom_digest)
        result = runner(["docker", "image", "inspect", "--format", "{{.RepoDigests}}", "img:v1"])
        assert isinstance(result.stdout, str)
        assert f"img:v1@{custom_digest}" in result.stdout

    def test_passes_kwargs_without_error(self) -> None:
        runner = make_docker_runner_success()
        result = runner(["docker", "version"], capture_output=True, text=True)
        assert result.returncode == 0
