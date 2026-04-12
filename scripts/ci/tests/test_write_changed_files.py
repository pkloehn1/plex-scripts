#!/usr/bin/env python3
"""Tests for changed-files discovery and writing.

Covers the git/event-specific logic in scripts.ci.write_changed_files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import write_changed_files as wcf

_FAKE_BASE = "a" * 40
_FAKE_HEAD = "b" * 40
_FAKE_BEFORE = "c" * 40
_FAKE_AFTER = "d" * 40
_FAKE_MERGE = "e" * 40
_FAKE_PARENT1 = "f" * 40
_FAKE_PARENT2 = "0" * 39 + "1"


class _FakeGit:
    def __init__(self, mapping: dict[tuple[tuple[str, ...], str | None], str]):
        self._mapping = mapping
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    def __call__(self, args: list[str], *, input_text: str | None = None) -> str:
        key = (tuple(args), input_text)
        self.calls.append(key)
        if key not in self._mapping:
            raise AssertionError(f"Unexpected git call: args={args}, input_text={input_text!r}")
        return self._mapping[key]


@pytest.mark.parametrize(
    "value",
    [
        "--exec",
        "-n",
        "-delete",
        "",
        "abc",
        "g" * 40,
        "A" * 40,
    ],
)
def test_is_valid_sha_rejects_non_sha_values(value: str) -> None:
    """_is_valid_sha rejects option-like strings, too-short, non-hex, and uppercase."""
    assert wcf._is_valid_sha(value) is False


def test_is_valid_sha_rejects_none() -> None:
    assert wcf._is_valid_sha(None) is False


def test_is_valid_sha_accepts_valid_lowercase_hex() -> None:
    assert wcf._is_valid_sha("a" * 40) is True


@pytest.mark.parametrize("subcommand", ["diff", "push", "remote", "checkout", "--exec", ""])
def test_run_git_rejects_disallowed_subcommands(subcommand: str) -> None:
    with pytest.raises(ValueError, match="git subcommand not allowed"):
        wcf._run_git([subcommand])


def test_run_git_rejects_empty_args() -> None:
    with pytest.raises(ValueError, match="git subcommand not allowed"):
        wcf._run_git([])


@pytest.mark.parametrize("bad_arg", [_FAKE_BASE, "--exec", "/etc/passwd", "-delete"])
def test_run_git_rejects_non_allowlisted_args(bad_arg: str) -> None:
    """_run_git rejects any argument not in the static allowlist."""
    with pytest.raises(ValueError, match=r"git argument.*not in allowlist"):
        wcf._run_git(["diff-tree", bad_arg])


@pytest.mark.parametrize("event_name", ["pull_request", "merge_group"])
def test_get_changed_files_uses_merge_parents(
    monkeypatch: pytest.MonkeyPatch,
    event_name: str,
) -> None:
    fake_git = _FakeGit(
        {
            (("rev-list", "--parents", "-n", "1", "HEAD"), None): (f"{_FAKE_MERGE} {_FAKE_PARENT1} {_FAKE_PARENT2}\n"),
            (
                ("diff-tree", "--stdin", "-r", "--name-only", "--no-commit-id"),
                f"{_FAKE_PARENT1} {_FAKE_PARENT2}\n",
            ): "stacks/edge/docker-compose.yml\nREADME.md\n",
        }
    )
    monkeypatch.setattr(wcf, "_run_git", fake_git)
    monkeypatch.setattr(wcf, "_read_event_payload", lambda: {})
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)

    assert wcf.get_changed_files() == [
        "stacks/edge/docker-compose.yml",
        "README.md",
    ]


@pytest.mark.parametrize(
    ("event_name", "payload"),
    [
        ("pull_request", {"pull_request": {"base": {"sha": _FAKE_BASE}, "head": {"sha": _FAKE_HEAD}}}),
        ("merge_group", {"base_sha": _FAKE_BASE, "head_sha": _FAKE_HEAD}),
    ],
)
def test_get_changed_files_falls_back_to_payload_shas(
    monkeypatch: pytest.MonkeyPatch,
    event_name: str,
    payload: dict,
) -> None:
    fake_git = _FakeGit(
        {
            (
                ("diff-tree", "--stdin", "-r", "--name-only", "--no-commit-id"),
                f"{_FAKE_BASE} {_FAKE_HEAD}\n",
            ): "stacks/control/docker-compose.yml\n",
        }
    )

    def run_git(args: list[str], *, input_text: str | None = None) -> str:
        if args[:2] == ["rev-list", "--parents"]:
            raise wcf.subprocess.CalledProcessError(returncode=1, cmd=["git"])  # type: ignore[arg-type]
        return fake_git(args, input_text=input_text)

    monkeypatch.setattr(wcf, "_run_git", run_git)
    monkeypatch.setattr(wcf, "_read_event_payload", lambda: payload)
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)

    assert wcf.get_changed_files() == ["stacks/control/docker-compose.yml"]


def test_get_changed_files_push_initial_commit_uses_diff_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_git = _FakeGit(
        {
            (
                ("diff-tree", "--stdin", "-r", "--name-only", "--no-commit-id"),
                f"{_FAKE_AFTER}\n",
            ): "README.md\n",
        }
    )
    monkeypatch.setattr(wcf, "_run_git", fake_git)
    monkeypatch.setattr(
        wcf,
        "_read_event_payload",
        lambda: {"before": "0" * 40, "after": _FAKE_AFTER},
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    assert wcf.get_changed_files() == ["README.md"]


def test_get_changed_files_push_normal_uses_diff_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_git = _FakeGit(
        {
            (
                ("diff-tree", "--stdin", "-r", "--name-only", "--no-commit-id"),
                f"{_FAKE_BEFORE} {_FAKE_AFTER}\n",
            ): "stacks/edge/docker-compose.yaml\n",
        }
    )
    monkeypatch.setattr(wcf, "_run_git", fake_git)
    monkeypatch.setattr(
        wcf,
        "_read_event_payload",
        lambda: {"before": _FAKE_BEFORE, "after": _FAKE_AFTER},
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    assert wcf.get_changed_files() == ["stacks/edge/docker-compose.yaml"]


def test_get_changed_files_fail_open_on_git_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_called_process_error(_args: list[str], **_kwargs: object) -> str:
        raise wcf.subprocess.CalledProcessError(returncode=1, cmd=["git"])  # type: ignore[arg-type]

    monkeypatch.setattr(wcf, "_run_git", raise_called_process_error)
    monkeypatch.setattr(wcf, "_read_event_payload", lambda: {})
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    assert wcf.get_changed_files() == ["stacks/__unknown__/docker-compose.yml"]


def test_write_changed_files_writes_trailing_newline(tmp_path: Path) -> None:
    out_path = wcf.write_changed_files(tmp_path, ["a", "b"])
    assert out_path.read_text(encoding="utf-8") == "a\nb\n"


def test_write_changed_files_writes_empty_file_for_empty_list(tmp_path: Path) -> None:
    out_path = wcf.write_changed_files(tmp_path, [])
    assert out_path.read_text(encoding="utf-8") == ""


def test_get_changed_files_push_invalid_payload_falls_back_to_ls_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_path = tmp_path / "event.json"
    payload_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(payload_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    fake_git = _FakeGit({(("ls-files",), None): "README.md\nstacks/control/docker-compose.yml\n"})
    monkeypatch.setattr(wcf, "_run_git", fake_git)

    assert wcf.get_changed_files() == ["README.md", "stacks/control/docker-compose.yml"]


def test_get_changed_files_unknown_event_falls_back_to_ls_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setattr(wcf, "_read_event_payload", lambda: {})
    fake_git = _FakeGit({(("ls-files",), None): "README.md\n"})
    monkeypatch.setattr(wcf, "_run_git", fake_git)
    assert wcf.get_changed_files() == ["README.md"]


def test_main_writes_changed_files_txt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(wcf, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(wcf.os, "chdir", lambda _dir: None)
    monkeypatch.setattr(wcf, "get_changed_files", lambda: ["README.md"])

    assert wcf.main() == 0
    out = capsys.readouterr().out
    assert "Wrote 1 changed file paths" in out
    assert (tmp_path / "changed-files.txt").read_text(encoding="utf-8") == "README.md\n"


def test_discover_changed_files_returns_typed_result_for_pull_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """discover_changed_files() returns ChangedFilesResult with strategy metadata."""
    fake_git = _FakeGit(
        {
            (("rev-list", "--parents", "-n", "1", "HEAD"), None): (f"{_FAKE_MERGE} {_FAKE_PARENT1} {_FAKE_PARENT2}\n"),
            (
                ("diff-tree", "--stdin", "-r", "--name-only", "--no-commit-id"),
                f"{_FAKE_PARENT1} {_FAKE_PARENT2}\n",
            ): "README.md\n",
        }
    )
    monkeypatch.setattr(wcf, "_run_git", fake_git)
    monkeypatch.setattr(wcf, "_read_event_payload", lambda: {})
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    result = wcf.discover_changed_files()
    assert result.files == ("README.md",)
    assert result.is_fail_open is False
    assert result.strategy == "pull_request"


def test_discover_changed_files_returns_fail_open_result_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """discover_changed_files() marks is_fail_open=True when sentinel returned."""

    def raise_error(_args: list[str], **_kwargs: object) -> str:
        raise wcf.subprocess.CalledProcessError(returncode=1, cmd=["git"])  # type: ignore[arg-type]

    monkeypatch.setattr(wcf, "_run_git", raise_error)
    monkeypatch.setattr(wcf, "_read_event_payload", lambda: {})
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    result = wcf.discover_changed_files()
    assert result.files == ("stacks/__unknown__/docker-compose.yml",)
    assert result.is_fail_open is True
    # Strategy is still pull_request since error was caught internally by helper
    assert result.strategy == "pull_request"


def test_discover_changed_files_returns_push_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """discover_changed_files() uses 'push' strategy for push events."""
    fake_git = _FakeGit(
        {
            (
                ("diff-tree", "--stdin", "-r", "--name-only", "--no-commit-id"),
                f"{_FAKE_BEFORE} {_FAKE_AFTER}\n",
            ): "README.md\n",
        }
    )
    monkeypatch.setattr(wcf, "_run_git", fake_git)
    monkeypatch.setattr(
        wcf,
        "_read_event_payload",
        lambda: {"before": _FAKE_BEFORE, "after": _FAKE_AFTER},
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    result = wcf.discover_changed_files()
    assert result.strategy == "push"
    assert result.is_fail_open is False


def test_discover_changed_files_returns_ls_files_strategy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """discover_changed_files() uses 'ls-files' strategy for unknown events."""
    fake_git = _FakeGit({(("ls-files",), None): "README.md\nstacks/control/docker-compose.yml\n"})
    monkeypatch.setattr(wcf, "_run_git", fake_git)
    monkeypatch.setattr(wcf, "_read_event_payload", lambda: {})
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    result = wcf.discover_changed_files()
    assert result.strategy == "ls-files"
    assert result.is_fail_open is False
    assert len(result.files) == 2


def test_run_git_raises_called_process_error_from_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_git propagates CalledProcessError raised by subprocess.run."""
    error = wcf.subprocess.CalledProcessError(returncode=128, cmd=["git", "ls-files"])  # type: ignore[arg-type]

    def fake_subprocess_run(*_args: object, **_kwargs: object) -> object:
        raise error

    monkeypatch.setattr(wcf.subprocess, "run", fake_subprocess_run)

    with pytest.raises(wcf.subprocess.CalledProcessError):
        wcf._run_git(["ls-files"])


def test_get_changed_files_for_pull_request_both_diffs_fail_falls_back_to_ls_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falls back to ls-files when both merge-parent diff and payload SHA diff fail."""
    payload = {"pull_request": {"base": {"sha": _FAKE_BASE}, "head": {"sha": _FAKE_HEAD}}}

    def run_git(args: list[str], *, input_text: str | None = None) -> str:
        if args[:2] == ["rev-list", "--parents"]:
            raise wcf.subprocess.CalledProcessError(returncode=1, cmd=["git"])  # type: ignore[arg-type]
        if args[0] == "diff-tree":
            raise wcf.subprocess.CalledProcessError(returncode=1, cmd=["git"])  # type: ignore[arg-type]
        if args[0] == "ls-files":
            return "README.md\nstacks/control/docker-compose.yml\n"
        raise AssertionError(f"Unexpected git call: {args}")

    monkeypatch.setattr(wcf, "_run_git", run_git)
    monkeypatch.setattr(wcf, "_read_event_payload", lambda: payload)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")

    assert wcf.get_changed_files() == ["README.md", "stacks/control/docker-compose.yml"]


def test_get_changed_files_push_initial_commit_diff_tree_fails_falls_back_to_ls_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initial commit push falls back to ls-files when diff-tree raises CalledProcessError."""

    def run_git(args: list[str], *, input_text: str | None = None) -> str:
        if args[0] == "diff-tree":
            raise wcf.subprocess.CalledProcessError(returncode=1, cmd=["git"])  # type: ignore[arg-type]
        if args[0] == "ls-files":
            return "README.md\n"
        raise AssertionError(f"Unexpected git call: {args}")

    monkeypatch.setattr(wcf, "_run_git", run_git)
    monkeypatch.setattr(
        wcf,
        "_read_event_payload",
        lambda: {"before": "0" * 40, "after": _FAKE_AFTER},
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    assert wcf.get_changed_files() == ["README.md"]


def test_get_changed_files_push_normal_diff_tree_fails_falls_back_to_ls_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal push falls back to ls-files when diff-tree raises CalledProcessError."""

    def run_git(args: list[str], *, input_text: str | None = None) -> str:
        if args[0] == "diff-tree":
            raise wcf.subprocess.CalledProcessError(returncode=1, cmd=["git"])  # type: ignore[arg-type]
        if args[0] == "ls-files":
            return "stacks/edge/docker-compose.yaml\n"
        raise AssertionError(f"Unexpected git call: {args}")

    monkeypatch.setattr(wcf, "_run_git", run_git)
    monkeypatch.setattr(
        wcf,
        "_read_event_payload",
        lambda: {"before": _FAKE_BEFORE, "after": _FAKE_AFTER},
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")

    assert wcf.get_changed_files() == ["stacks/edge/docker-compose.yaml"]


def test_discover_changed_files_outer_try_catches_called_process_error_for_ls_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """discover_changed_files() catches CalledProcessError from ls-files strategy."""

    def raise_error(_args: list[str], **_kwargs: object) -> str:
        raise wcf.subprocess.CalledProcessError(returncode=1, cmd=["git"])  # type: ignore[arg-type]

    monkeypatch.setattr(wcf, "_run_git", raise_error)
    monkeypatch.setattr(wcf, "_read_event_payload", lambda: {})
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")

    result = wcf.discover_changed_files()
    assert result.files == ("stacks/__unknown__/docker-compose.yml",)
    assert result.is_fail_open is True
    assert result.strategy == "fail-open"


def test_run_git_returns_stdout_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_run_git returns subprocess stdout on successful execution."""
    fake_result = wcf.subprocess.CompletedProcess(
        args=["git", "ls-files"], returncode=0, stdout="file.txt\n", stderr=""
    )
    monkeypatch.setattr(wcf.subprocess, "run", lambda *_args, **_kwargs: fake_result)
    assert wcf._run_git(["ls-files"]) == "file.txt\n"
