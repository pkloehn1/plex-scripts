"""Tests for check_commit_message hook."""

from __future__ import annotations

import scripts.testing.hooks.check_commit_message as mod

# ---------------------------------------------------------------------------
# validate_commit_message
# ---------------------------------------------------------------------------


class TestValidateCommitMessage:
    """Tests for validate_commit_message()."""

    def test_empty_message(self) -> None:
        is_valid, reason = mod.validate_commit_message("")
        assert not is_valid
        assert "empty" in reason.lower()

    def test_whitespace_only_message(self) -> None:
        is_valid, reason = mod.validate_commit_message("   \n\n  ")
        assert not is_valid
        assert "empty" in reason.lower()

    def test_leading_newlines_stripped(self) -> None:
        """Leading whitespace is stripped; first real line becomes subject."""
        is_valid, reason = mod.validate_commit_message("\nfeat: real subject")
        assert is_valid
        assert reason == "Conventional commit"

    def test_merge_commit(self) -> None:
        is_valid, reason = mod.validate_commit_message("Merge branch 'feature' into main")
        assert is_valid
        assert reason == "Merge commit"

    def test_merge_pull_request(self) -> None:
        is_valid, reason = mod.validate_commit_message("Merge pull request #42 from owner/branch")
        assert is_valid
        assert reason == "Merge commit"

    def test_dependabot_bump_the(self) -> None:
        is_valid, reason = mod.validate_commit_message("Bump the dependency-updates group with 1 updates")
        assert is_valid
        assert reason == "Dependabot commit"

    def test_dependabot_bump_package(self) -> None:
        is_valid, reason = mod.validate_commit_message("Bump actions/checkout from 3 to 4")
        assert is_valid
        assert reason == "Dependabot commit"

    def test_conventional_type_only(self) -> None:
        is_valid, reason = mod.validate_commit_message("fix: resolve crash on startup")
        assert is_valid
        assert reason == "Conventional commit"

    def test_conventional_type_with_scope(self) -> None:
        is_valid, reason = mod.validate_commit_message("feat(ci): add auto-summary generator")
        assert is_valid
        assert reason == "Conventional commit"

    def test_conventional_with_body(self) -> None:
        msg = "docs: update README\n\nAdded new section for auto-summary."
        is_valid, reason = mod.validate_commit_message(msg)
        assert is_valid
        assert reason == "Conventional commit"

    def test_non_conventional_rejected(self) -> None:
        is_valid, reason = mod.validate_commit_message("Update README")
        assert not is_valid
        assert "conventional commit format" in reason.lower()
        assert "'Update README'" in reason

    def test_non_conventional_shows_examples(self) -> None:
        is_valid, reason = mod.validate_commit_message("Fix bug")
        assert not is_valid
        assert "feat(ci):" in reason
        assert "fix:" in reason

    def test_uppercase_type_rejected(self) -> None:
        """Conventional commit types must be lowercase."""
        is_valid, _reason = mod.validate_commit_message("Fix: resolve crash")
        assert not is_valid


# ---------------------------------------------------------------------------
# main (CLI entry point)
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for main() CLI entry point."""

    def test_missing_argument(self, monkeypatch, capsys) -> None:
        monkeypatch.setattr("sys.argv", ["check_commit_message.py"])
        assert mod.main() == 2
        err = capsys.readouterr().err
        assert "Usage" in err

    def test_missing_file(self, monkeypatch, capsys, tmp_path) -> None:
        missing = tmp_path / "nonexistent"
        monkeypatch.setattr("sys.argv", ["check_commit_message.py", str(missing)])
        assert mod.main() == 2
        err = capsys.readouterr().err
        assert "not found" in err

    def test_valid_message_returns_zero(self, monkeypatch, tmp_path) -> None:
        msg_file = tmp_path / "COMMIT_EDITMSG"
        msg_file.write_text("feat: add new feature\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["check_commit_message.py", str(msg_file)])
        assert mod.main() == 0

    def test_invalid_message_returns_one(self, monkeypatch, capsys, tmp_path) -> None:
        msg_file = tmp_path / "COMMIT_EDITMSG"
        msg_file.write_text("Bad commit message\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["check_commit_message.py", str(msg_file)])
        assert mod.main() == 1
        err = capsys.readouterr().err
        assert "FAIL" in err

    def test_dependabot_message_returns_zero(self, monkeypatch, tmp_path) -> None:
        msg_file = tmp_path / "COMMIT_EDITMSG"
        msg_file.write_text("Bump the dependency-updates group with 1 updates\n", encoding="utf-8")
        monkeypatch.setattr("sys.argv", ["check_commit_message.py", str(msg_file)])
        assert mod.main() == 0
