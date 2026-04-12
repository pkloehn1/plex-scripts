from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.devops.start_issue_work as mod
from scripts.devops.start_issue_work import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_USAGE,
    Issue,
    build_branch_name,
    build_git_branch_commands,
    default_scope_for_title,
    default_type_for_title,
    ensure_clean_working_tree,
    ensure_on_main,
    fetch_issue_via_gh_api_call,
    main,
    parse_conventional_title,
    print_next_steps,
    repo_root,
    slugify,
)

# -- slugify -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello World", "hello-world"),
        ("  multiple   spaces  ", "multiple-spaces"),
        ("special!@#chars$%^here", "special-chars-here"),
        ("", "work"),
        ("   ", "work"),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_slugify_max_words() -> None:
    assert slugify("one two three four", max_words=2) == "one-two"


def test_slugify_default_max_words_is_six() -> None:
    result = slugify("a b c d e f g h")
    assert result == "a-b-c-d-e-f"


# -- parse_conventional_title --------------------------------------------------


def test_parse_conventional_title_with_scope() -> None:
    typ, scope, summary = parse_conventional_title("feat(auth): add login")
    assert typ == "feat"
    assert scope == "auth"
    assert summary == "add login"


def test_parse_conventional_title_without_scope() -> None:
    typ, scope, summary = parse_conventional_title("fix: broken test")
    assert typ == "fix"
    assert scope is None
    assert summary == "broken test"


def test_parse_conventional_title_non_conventional() -> None:
    typ, scope, summary = parse_conventional_title("random commit message")
    assert typ is None
    assert scope is None
    assert summary == "random commit message"


def test_parse_conventional_title_empty() -> None:
    typ, scope, summary = parse_conventional_title("")
    assert typ is None
    assert scope is None
    assert summary == ""


def test_parse_conventional_title_no_space_after_colon() -> None:
    typ, scope, summary = parse_conventional_title("fix:no-space")
    assert (typ, scope, summary) == (None, None, "fix:no-space")


def test_parse_conventional_title_empty_scope() -> None:
    typ, scope, summary = parse_conventional_title("fix(): summary")
    assert (typ, scope, summary) == (None, None, "fix(): summary")


def test_parse_conventional_title_uppercase_type() -> None:
    typ, scope, summary = parse_conventional_title("FIX: summary")
    assert (typ, scope, summary) == (None, None, "FIX: summary")


def test_parse_conventional_title_numeric_type() -> None:
    typ, scope, summary = parse_conventional_title("123: summary")
    assert (typ, scope, summary) == (None, None, "123: summary")


def test_parse_conventional_title_no_colon() -> None:
    typ, scope, summary = parse_conventional_title("just a plain title")
    assert (typ, scope, summary) == (None, None, "just a plain title")


def test_parse_conventional_title_colon_then_no_content() -> None:
    # right = "" after split — hits "not right" branch at line 57
    typ, scope, summary = parse_conventional_title("fix:")
    assert (typ, scope, summary) == (None, None, "fix:")


def test_parse_conventional_title_empty_left_of_colon() -> None:
    typ, scope, summary = parse_conventional_title(": summary")
    assert (typ, scope, summary) == (None, None, ": summary")


# -- default_type_for_title ----------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Update docs for API", "docs"),
        ("Fix broken link", "fix"),
        ("Refactor auth module", "refactor"),
        ("Security patch for XSS", "security"),
        ("Add test for login", "test"),
        ("Bump dependencies", "chore"),
    ],
)
def test_default_type_for_title(title: str, expected: str) -> None:
    assert default_type_for_title(title) == expected


# -- default_scope_for_title ---------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Update pre-commit hooks", "ci"),
        ("Fix precommit config", "ci"),
        ("Add label automation", "ci"),
        ("Update workflow", "ci"),
        ("Fix GitHub action", "ci"),
        ("DevSecOps pipeline", "devsecops"),
        ("General improvement", "repo"),
    ],
)
def test_default_scope_for_title(title: str, expected: str) -> None:
    assert default_scope_for_title(title) == expected


# -- build_branch_name ---------------------------------------------------------


def test_build_branch_name_conventional() -> None:
    branch = build_branch_name(issue_number=42, issue_title="feat(auth): add login flow")
    assert branch.startswith("feat/42-")
    assert "auth" in branch
    assert "add-login-flow" in branch


def test_build_branch_name_non_conventional() -> None:
    branch = build_branch_name(issue_number=10, issue_title="Fix broken login page")
    assert branch.startswith("fix/10-")


# -- build_git_branch_commands -------------------------------------------------


def test_build_git_branch_commands() -> None:
    cmds = build_git_branch_commands(branch="feat/42-auth-login")
    assert len(cmds) == 1
    assert cmds[0] == ["git", "checkout", "-b", "feat/42-auth-login"]


# -- Issue dataclass -----------------------------------------------------------


def test_issue_frozen() -> None:
    issue = Issue(number=1, title="test", url=None)
    with pytest.raises(AttributeError):
        issue.number = 2  # type: ignore[misc]


# -- print_next_steps ----------------------------------------------------------


def test_print_next_steps_with_url(capsys: object) -> None:
    issue = Issue(number=42, title="My issue", url="https://example.com/42")
    print_next_steps(issue=issue, branch="feat/42-my-issue")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Issue #42" in captured.out
    assert "https://example.com/42" in captured.out
    assert "feat/42-my-issue" in captured.out
    assert "Next steps:" in captured.out


def test_print_next_steps_without_url(capsys: object) -> None:
    issue = Issue(number=1, title="No URL", url=None)
    print_next_steps(issue=issue, branch="fix/1-no-url")
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert "Issue #1" in captured.out
    assert "URL:" not in captured.out


# -- repo_root -----------------------------------------------------------------


def test_repo_root_returns_path() -> None:
    result = repo_root()
    assert isinstance(result, Path)
    assert result.exists()


# -- _run ----------------------------------------------------------------------


def test_run_success(tmp_path: Path) -> None:
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout = "output text\n"

    with patch("subprocess.run", return_value=fake_proc):
        result = mod._run(["git", "status"], cwd=tmp_path)

    assert result == "output text\n"


def test_run_failure_uses_stderr(tmp_path: Path) -> None:
    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.stderr = "fatal: not a git repo"
    fake_proc.stdout = ""

    with patch("subprocess.run", return_value=fake_proc), pytest.raises(RuntimeError, match="fatal: not a git repo"):
        mod._run(["git", "status"], cwd=tmp_path)


def test_run_failure_uses_stdout_when_no_stderr(tmp_path: Path) -> None:
    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.stderr = ""
    fake_proc.stdout = "some stdout output"

    with patch("subprocess.run", return_value=fake_proc), pytest.raises(RuntimeError, match="some stdout output"):
        mod._run(["git", "status"], cwd=tmp_path)


def test_run_failure_default_message(tmp_path: Path) -> None:
    fake_proc = MagicMock()
    fake_proc.returncode = 1
    fake_proc.stderr = ""
    fake_proc.stdout = ""

    with patch("subprocess.run", return_value=fake_proc), pytest.raises(RuntimeError, match="command failed"):
        mod._run(["git", "status"], cwd=tmp_path)


# -- ensure_clean_working_tree -------------------------------------------------


def test_ensure_clean_working_tree_clean(tmp_path: Path) -> None:
    with patch.object(mod, "_run", return_value=""):
        ensure_clean_working_tree(cwd=tmp_path)  # should not raise


def test_ensure_clean_working_tree_dirty(tmp_path: Path) -> None:
    with (
        patch.object(mod, "_run", return_value=" M some_file.py\n"),
        pytest.raises(RuntimeError, match="Working tree is not clean"),
    ):
        ensure_clean_working_tree(cwd=tmp_path)


# -- ensure_on_main ------------------------------------------------------------


def test_ensure_on_main_success(tmp_path: Path) -> None:
    with patch.object(mod, "_run", return_value="main\n"):
        ensure_on_main(cwd=tmp_path)  # should not raise


def test_ensure_on_main_wrong_branch(tmp_path: Path) -> None:
    with (
        patch.object(mod, "_run", return_value="feature/123-my-feature\n"),
        pytest.raises(RuntimeError, match="Refusing to branch from"),
    ):
        ensure_on_main(cwd=tmp_path)


# -- fetch_issue_via_gh_api_call -----------------------------------------------


def test_fetch_issue_via_gh_api_call_success(tmp_path: Path) -> None:
    payload = {
        "ok": True,
        "json": {
            "title": "feat(auth): add login",
            "html_url": "https://github.com/owner/repo/issues/42",
        },
    }
    with patch.object(mod, "_run", return_value=json.dumps(payload)):
        issue = fetch_issue_via_gh_api_call(repo="owner/repo", number=42, cwd=tmp_path)

    assert issue.number == 42
    assert issue.title == "feat(auth): add login"
    assert issue.url == "https://github.com/owner/repo/issues/42"


def test_fetch_issue_via_gh_api_call_no_url(tmp_path: Path) -> None:
    payload = {
        "ok": True,
        "json": {
            "title": "feat: something",
            "html_url": "",
        },
    }
    with patch.object(mod, "_run", return_value=json.dumps(payload)):
        issue = fetch_issue_via_gh_api_call(repo="owner/repo", number=7, cwd=tmp_path)

    assert issue.url is None


def test_fetch_issue_via_gh_api_call_not_ok(tmp_path: Path) -> None:
    payload = {"ok": False}
    with (
        patch.object(mod, "_run", return_value=json.dumps(payload)),
        pytest.raises(RuntimeError, match="Failed to fetch issue"),
    ):
        fetch_issue_via_gh_api_call(repo="owner/repo", number=1, cwd=tmp_path)


def test_fetch_issue_via_gh_api_call_non_dict_payload(tmp_path: Path) -> None:
    payload = {"ok": True, "json": ["not", "a", "dict"]}
    with (
        patch.object(mod, "_run", return_value=json.dumps(payload)),
        pytest.raises(RuntimeError, match="Unexpected issue payload"),
    ):
        fetch_issue_via_gh_api_call(repo="owner/repo", number=1, cwd=tmp_path)


def test_fetch_issue_via_gh_api_call_missing_title(tmp_path: Path) -> None:
    payload = {"ok": True, "json": {"html_url": "https://example.com"}}
    with (
        patch.object(mod, "_run", return_value=json.dumps(payload)),
        pytest.raises(RuntimeError, match="Issue payload missing title"),
    ):
        fetch_issue_via_gh_api_call(repo="owner/repo", number=1, cwd=tmp_path)


def test_fetch_issue_via_gh_api_call_blank_title(tmp_path: Path) -> None:
    payload = {"ok": True, "json": {"title": "   ", "html_url": "https://example.com"}}
    with (
        patch.object(mod, "_run", return_value=json.dumps(payload)),
        pytest.raises(RuntimeError, match="Issue payload missing title"),
    ):
        fetch_issue_via_gh_api_call(repo="owner/repo", number=1, cwd=tmp_path)


def test_fetch_issue_via_gh_api_call_non_string_title(tmp_path: Path) -> None:
    payload = {"ok": True, "json": {"title": 123, "html_url": "https://example.com"}}
    with (
        patch.object(mod, "_run", return_value=json.dumps(payload)),
        pytest.raises(RuntimeError, match="Issue payload missing title"),
    ):
        fetch_issue_via_gh_api_call(repo="owner/repo", number=1, cwd=tmp_path)


# -- main() --------------------------------------------------------------------


def test_main_invalid_issue_number(capsys) -> None:
    result = main(["--repo", "owner/repo", "--issue", "0"])
    assert result == EXIT_USAGE
    captured = capsys.readouterr()
    assert "--issue must be a positive integer" in captured.err


def test_main_dry_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "ensure_clean_working_tree", lambda cwd: None)
    monkeypatch.setattr(mod, "ensure_on_main", lambda cwd: None)

    issue = Issue(number=5, title="feat(ci): add pipeline", url="https://example.com/5")
    monkeypatch.setattr(mod, "fetch_issue_via_gh_api_call", lambda repo, number, cwd: issue)

    result = main(["--repo", "owner/repo", "--issue", "5", "--dry-run"])
    assert result == EXIT_OK


def test_main_success_creates_branch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "ensure_clean_working_tree", lambda cwd: None)
    monkeypatch.setattr(mod, "ensure_on_main", lambda cwd: None)

    issue = Issue(number=10, title="fix(auth): broken login", url=None)
    monkeypatch.setattr(mod, "fetch_issue_via_gh_api_call", lambda repo, number, cwd: issue)

    run_calls = []

    def fake_run(argv: list[str], cwd: Path) -> str:
        run_calls.append(argv)
        return ""

    monkeypatch.setattr(mod, "_run", fake_run)

    result = main(["--repo", "owner/repo", "--issue", "10"])
    assert result == EXIT_OK
    assert any("checkout" in cmd for cmd in run_calls)


def test_main_allow_non_main(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "ensure_clean_working_tree", lambda cwd: None)

    ensure_on_main_called = []
    monkeypatch.setattr(mod, "ensure_on_main", lambda cwd: ensure_on_main_called.append(True))

    issue = Issue(number=3, title="chore: cleanup", url=None)
    monkeypatch.setattr(mod, "fetch_issue_via_gh_api_call", lambda repo, number, cwd: issue)
    monkeypatch.setattr(mod, "_run", lambda argv, cwd: "")

    result = main(["--repo", "owner/repo", "--issue", "3", "--allow-non-main"])
    assert result == EXIT_OK
    assert len(ensure_on_main_called) == 0


def test_main_runtime_error(tmp_path: Path, monkeypatch, capsys) -> None:
    def _raise_dirty(**_kwargs: object) -> None:
        raise RuntimeError("dirty")

    monkeypatch.setattr(mod, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "ensure_clean_working_tree", _raise_dirty)

    result = main(["--repo", "owner/repo", "--issue", "1"])
    assert result == EXIT_FAILED
    assert "dirty" in capsys.readouterr().err


def test_main_json_decode_error(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "repo_root", lambda: tmp_path)
    monkeypatch.setattr(mod, "ensure_clean_working_tree", lambda cwd: None)
    monkeypatch.setattr(mod, "ensure_on_main", lambda cwd: None)

    def bad_fetch(repo: str, number: int, cwd: Path) -> Issue:
        raise json.JSONDecodeError("bad", "", 0)

    monkeypatch.setattr(mod, "fetch_issue_via_gh_api_call", bad_fetch)

    result = main(["--repo", "owner/repo", "--issue", "99"])
    assert result == EXIT_FAILED
