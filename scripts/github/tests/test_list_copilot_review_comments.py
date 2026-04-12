"""Tests for list_copilot_review_comments module."""

from __future__ import annotations

from scripts.github.list_copilot_review_comments import main


def test_main_adds_copilot_default(monkeypatch) -> None:
    captured_argv: list[str] = []

    def fake_main_filtered() -> int:
        import sys

        captured_argv.extend(sys.argv)
        return 0

    monkeypatch.setattr(
        "scripts.github.list_copilot_review_comments._main_filtered",
        fake_main_filtered,
    )
    monkeypatch.setattr("sys.argv", ["prog", "--repo", "o/n", "--pr", "42"])
    assert main() == 0
    assert "--author-substring" in captured_argv
    assert "copilot" in captured_argv


def test_main_preserves_explicit_author(monkeypatch) -> None:
    import sys

    original = ["prog", "--repo", "o/n", "--pr", "42", "--author-substring", "cursor"]
    monkeypatch.setattr("sys.argv", list(original))

    def fake_main_filtered() -> int:
        assert "--author-substring" in sys.argv
        # Should still only have one --author-substring (the original)
        count = sys.argv.count("--author-substring")
        assert count == 1
        return 0

    monkeypatch.setattr(
        "scripts.github.list_copilot_review_comments._main_filtered",
        fake_main_filtered,
    )
    assert main() == 0


def test_main_value_error(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["prog"])

    def fake_main_filtered() -> int:
        raise ValueError("test error")

    monkeypatch.setattr(
        "scripts.github.list_copilot_review_comments._main_filtered",
        fake_main_filtered,
    )
    assert main() == 2
