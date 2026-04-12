"""Tests for scripts.ci.triage_issue_priority."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

from scripts.ci.triage_issue_priority import (
    _extract_label_names,
    triage_issue,
)
from scripts.github.gh_cli import GhResult

# ---------------------------------------------------------------------------
# _extract_label_names
# ---------------------------------------------------------------------------


class TestExtractLabelNames:
    def test_dict_labels(self):
        issue = {"labels": [{"name": "type/bug"}, {"name": "service/traefik"}]}
        assert _extract_label_names(issue) == ["service/traefik", "type/bug"]

    def test_string_labels(self):
        issue = {"labels": ["type/bug", "service/traefik"]}
        assert _extract_label_names(issue) == ["service/traefik", "type/bug"]

    def test_mixed_labels(self):
        issue = {"labels": [{"name": "type/bug"}, "service/traefik"]}
        assert _extract_label_names(issue) == ["service/traefik", "type/bug"]

    def test_empty_labels(self):
        issue = {"labels": []}
        assert _extract_label_names(issue) == []

    def test_missing_labels_key(self):
        issue = {}
        assert _extract_label_names(issue) == []

    def test_labels_not_a_list(self):
        issue = {"labels": "not-a-list"}
        assert _extract_label_names(issue) == []

    def test_malformed_dict_label(self):
        """Dict label missing 'name' key is skipped."""
        issue = {"labels": [{"id": 123}, {"name": "valid"}]}
        assert _extract_label_names(issue) == ["valid"]

    def test_empty_string_label_skipped(self):
        issue = {"labels": [{"name": ""}, {"name": "valid"}]}
        assert _extract_label_names(issue) == ["valid"]

    def test_non_dict_non_string_item_skipped(self):
        issue = {"labels": [42, None, {"name": "valid"}]}
        assert _extract_label_names(issue) == ["valid"]


# ---------------------------------------------------------------------------
# triage_issue
# ---------------------------------------------------------------------------


def _runner_with_triage_comment(priority: str) -> MagicMock:
    """Mock runner whose GET /comments returns a triage comment for *priority*."""
    runner = MagicMock()
    comments = json.dumps([{"body": f"Triaged as **{priority}** (link)."}])

    def _run(cmd_args, **_kwargs):
        # GET comments (no --method flag) vs POST/DELETE (has --method)
        if "--method" not in cmd_args and any("comments" in str(arg) for arg in cmd_args):
            return GhResult(stdout=comments, stderr="")
        return GhResult(stdout="", stderr="")

    runner.run.side_effect = _run
    return runner


class TestTriageIssue:
    def test_adds_label_and_posts_comment(self):
        runner = MagicMock()
        result = triage_issue(
            runner=runner,
            repo="owner/name",
            issue_number=42,
            title="bug: traefik crash",
            body="",
            labels=["type/bug", "service/traefik"],
            server_url="https://github.com",
        )
        assert result == "P1-high"
        # Expect two API calls: add label, post comment
        assert runner.run.call_count == 2

        # Verify add-label call
        add_call = runner.run.call_args_list[0]
        argv = add_call[0][0]
        assert "/repos/owner/name/issues/42/labels" in argv
        assert "POST" in argv

        # Verify comment call
        comment_call = runner.run.call_args_list[1]
        argv = comment_call[0][0]
        assert "/repos/owner/name/issues/42/comments" in argv
        assert "POST" in argv

    def test_returns_none_when_no_priority(self):
        runner = MagicMock()
        result = triage_issue(
            runner=runner,
            repo="owner/name",
            issue_number=42,
            title="untitled",
            body="no info",
            labels=[],
            server_url="https://github.com",
        )
        assert result is None
        runner.run.assert_not_called()

    def test_strips_existing_priority_before_computing(self):
        """Existing workflow-applied priority is stripped so compute_priority re-evaluates."""
        runner = _runner_with_triage_comment("P3-low")
        result = triage_issue(
            runner=runner,
            repo="owner/name",
            issue_number=10,
            title="bug: crash",
            body="",
            labels=["P3-low", "type/bug"],
            server_url="https://github.com",
        )
        # type/bug → P2-medium, which differs from existing P3-low
        assert result == "P2-medium"
        # 4 calls: check comments, remove old label, add new label, post comment
        assert runner.run.call_count == 4

    def test_no_change_when_recomputed_matches_existing(self):
        """When recomputed priority matches existing label, no label changes."""
        runner = _runner_with_triage_comment("P3-low")
        result = triage_issue(
            runner=runner,
            repo="owner/name",
            issue_number=10,
            title="chore: cleanup",
            body="",
            labels=["P3-low", "type/chore"],
            server_url="https://github.com",
        )
        assert result is None
        # 1 call: check comments (no label changes)
        assert runner.run.call_count == 1

    def test_removes_old_priority_when_different(self):
        """When recomputed priority differs, old label is removed."""
        runner = _runner_with_triage_comment("P3-low")
        result = triage_issue(
            runner=runner,
            repo="owner/name",
            issue_number=10,
            title="bug: crash",
            body="",
            labels=["P3-low", "type/bug"],
            server_url="https://github.com",
        )
        assert result == "P2-medium"
        # 4 calls: check comments, remove old label, add new label, post comment
        assert runner.run.call_count == 4

        # Verify remove-label call (index 1, after comments check at 0)
        remove_call = runner.run.call_args_list[1]
        argv = remove_call[0][0]
        assert "DELETE" in argv
        assert "P3-low" in " ".join(argv)

    def test_skips_human_applied_priority(self):
        """When existing priority has no triage comment, treat as human override."""
        runner = MagicMock()
        # No triage comments exist — label was human-applied
        runner.run.return_value = GhResult(stdout="[]", stderr="")
        result = triage_issue(
            runner=runner,
            repo="owner/name",
            issue_number=10,
            title="chore: cleanup",
            body="",
            labels=["P0-critical", "type/chore"],
            server_url="https://github.com",
        )
        assert result is None
        # 1 call: check comments only, no label changes
        assert runner.run.call_count == 1

    def test_skips_when_comments_api_returns_non_list(self):
        """When the comments API returns a non-list JSON (e.g. error object), treat as human-applied."""
        runner = MagicMock()
        # API returns a JSON object instead of a list
        runner.run.return_value = GhResult(stdout='{"message": "Not Found"}', stderr="")
        result = triage_issue(
            runner=runner,
            repo="owner/name",
            issue_number=10,
            title="chore: cleanup",
            body="",
            labels=["P0-critical", "type/chore"],
            server_url="https://github.com",
        )
        assert result is None
        assert runner.run.call_count == 1

    def test_comment_includes_framework_link(self):
        runner = MagicMock()
        triage_issue(
            runner=runner,
            repo="owner/name",
            issue_number=42,
            title="bug: traefik crash",
            body="",
            labels=["type/bug", "service/traefik"],
            server_url="https://github.com",
        )
        comment_call = runner.run.call_args_list[-1]
        input_text = comment_call[1].get("input_text", "")
        assert "priority-decision-framework.md" in input_text
        assert "P1-high" in input_text


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_no_issue_in_payload(self, mock_payload):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {}
        assert main() == 0

    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_skips_self_triggered_labeled_event(self, mock_payload):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {
            "action": "labeled",
            "label": {"name": "P2-medium"},
            "issue": {"number": 10, "title": "test", "body": "", "labels": []},
        }
        assert main() == 0

    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_skips_self_triggered_unlabeled_event(self, mock_payload):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {
            "action": "unlabeled",
            "label": {"name": "P3-low"},
            "issue": {"number": 10, "title": "test", "body": "", "labels": []},
        }
        assert main() == 0

    @patch("scripts.ci.triage_issue_priority.SubprocessGhRunner")
    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_proceeds_for_non_priority_labeled_event(self, mock_payload, mock_runner_cls):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {
            "action": "labeled",
            "label": {"name": "service/traefik"},
            "issue": {
                "number": 42,
                "title": "bug: crash",
                "body": "",
                "labels": [{"name": "type/bug"}, {"name": "service/traefik"}],
            },
        }
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            result = main()
        assert result == 0
        assert mock_runner.run.call_count >= 1

    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_missing_github_repository(self, mock_payload):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {"issue": {"number": 1, "title": "test", "body": "", "labels": []}}
        with patch.dict(os.environ, {}, clear=True):
            # Ensure GITHUB_REPOSITORY is not set
            os.environ.pop("GITHUB_REPOSITORY", None)
            assert main() == 1

    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_invalid_issue_number_returns_one(self, mock_payload):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {"issue": {"number": 0, "title": "test", "body": "", "labels": []}}
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            assert main() == 1

    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_missing_issue_number_returns_one(self, mock_payload):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {"issue": {"title": "test", "body": "", "labels": []}}
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            assert main() == 1

    @patch("scripts.ci.triage_issue_priority.SubprocessGhRunner")
    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_value_error_returns_one(self, mock_payload, mock_runner_cls):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {
            "issue": {
                "number": 42,
                "title": "bug: crash",
                "body": "",
                "labels": [{"name": "type/bug"}],
            }
        }
        mock_runner = MagicMock()
        mock_runner.run.side_effect = ValueError("bad repo format")
        mock_runner_cls.return_value = mock_runner
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            result = main()
        assert result == 1

    @patch("scripts.ci.triage_issue_priority.SubprocessGhRunner")
    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_valid_payload_calls_triage(self, mock_payload, mock_runner_cls):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {
            "issue": {
                "number": 42,
                "title": "bug: crash",
                "body": "details",
                "labels": [{"name": "type/bug"}],
            }
        }
        mock_runner = MagicMock()
        mock_runner_cls.return_value = mock_runner
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            result = main()
        assert result == 0
        assert mock_runner.run.call_count >= 1

    @patch("scripts.ci.triage_issue_priority.SubprocessGhRunner")
    @patch("scripts.ci.triage_issue_priority.read_event_payload")
    def test_gh_cli_error_returns_one(self, mock_payload, mock_runner_cls):
        from scripts.ci.triage_issue_priority import main

        mock_payload.return_value = {
            "issue": {
                "number": 42,
                "title": "bug: crash",
                "body": "",
                "labels": [{"name": "type/bug"}],
            }
        }
        from scripts.github.gh_cli import GhCliError

        mock_runner = MagicMock()
        mock_runner.run.side_effect = GhCliError("fail", argv=["gh"], returncode=1, stdout="", stderr="error")
        mock_runner_cls.return_value = mock_runner
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            result = main()
        assert result == 1
