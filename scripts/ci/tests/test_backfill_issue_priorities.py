"""Tests for scripts.ci.backfill_issue_priorities — 100% coverage target."""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import scripts.ci.backfill_issue_priorities as mod
from scripts.ci.backfill_issue_priorities import (
    _blast_radius_bump,
    _build_recommendations,
    _is_bug_or_security_type,
    _is_security_type,
    _issue_type_rank,
    _priority_from_rank,
    _service_tier,
    _tier_floor_rank,
    compute_priority,
)

# ---------------------------------------------------------------------------
# _priority_from_rank
# ---------------------------------------------------------------------------


class TestPriorityFromRank:
    def test_rank_0(self):
        assert _priority_from_rank(0) == "P0-critical"

    def test_rank_1(self):
        assert _priority_from_rank(1) == "P1-high"

    def test_rank_2(self):
        assert _priority_from_rank(2) == "P2-medium"

    def test_rank_3(self):
        assert _priority_from_rank(3) == "P3-low"

    def test_clamp_negative(self):
        assert _priority_from_rank(-5) == "P0-critical"

    def test_clamp_above(self):
        assert _priority_from_rank(99) == "P3-low"


# ---------------------------------------------------------------------------
# _is_bug_or_security_type / _is_security_type
# ---------------------------------------------------------------------------


class TestTypeCheckers:
    def test_bug_label(self):
        assert _is_bug_or_security_type("chore: foo", {"type/bug"}) is True

    def test_fix_label(self):
        assert _is_bug_or_security_type("chore: foo", {"type/fix"}) is True

    def test_security_label(self):
        assert _is_bug_or_security_type("chore: foo", {"type/security"}) is True

    def test_bug_title_prefix(self):
        assert _is_bug_or_security_type("bug: something", set()) is True

    def test_fix_title_prefix(self):
        assert _is_bug_or_security_type("fix: something", set()) is True

    def test_security_title_prefix(self):
        assert _is_bug_or_security_type("security: something", set()) is True

    def test_no_match(self):
        assert _is_bug_or_security_type("feat: new feature", set()) is False

    def test_is_security_label(self):
        assert _is_security_type("chore: foo", {"type/security"}) is True

    def test_is_security_title(self):
        assert _is_security_type("security: harden auth", set()) is True

    def test_is_security_no_match(self):
        assert _is_security_type("bug: crash", {"type/bug"}) is False


# ---------------------------------------------------------------------------
# _issue_type_rank
# ---------------------------------------------------------------------------


class TestIssueTypeRank:
    def test_incident_label(self):
        assert _issue_type_rank("some title", {"incident"}, "body") == 0

    def test_severity_critical_label(self):
        assert _issue_type_rank("title", {"severity-critical"}, "body") == 0

    def test_p0_keyword_production_down_in_title(self):
        assert _issue_type_rank("production down now", set(), "body") == 0

    def test_p0_keyword_data_loss_in_title(self):
        assert _issue_type_rank("data loss detected", set(), "body") == 0

    def test_p0_keyword_security_breach_in_title(self):
        assert _issue_type_rank("security breach found", set(), "body") == 0

    def test_p0_keyword_in_body_only_not_p0(self):
        """P0 keywords in body but not title must not trigger rank 0."""
        result = _issue_type_rank("normal title", set(), "data loss risk in body")
        assert result is None

    def test_security_label(self):
        assert _issue_type_rank("title", {"type/security"}, "body") == 1

    def test_security_title(self):
        assert _issue_type_rank("security: harden", set(), "body") == 1

    def test_bug_label(self):
        assert _issue_type_rank("title", {"type/bug"}, "body") == 2

    def test_fix_label(self):
        assert _issue_type_rank("title", {"type/fix"}, "body") == 2

    def test_fix_title(self):
        assert _issue_type_rank("fix: broken", set(), "body") == 2

    def test_feat_label(self):
        assert _issue_type_rank("title", {"type/feat"}, "body") == 2

    def test_enh_label(self):
        assert _issue_type_rank("title", {"type/enh"}, "body") == 2

    def test_feat_title(self):
        assert _issue_type_rank("feat: new thing", set(), "body") == 2

    def test_chore_label(self):
        assert _issue_type_rank("title", {"type/chore"}, "body") == 3

    def test_docs_label(self):
        assert _issue_type_rank("title", {"type/docs"}, "body") == 3

    def test_chore_title(self):
        assert _issue_type_rank("chore: cleanup", set(), "body") == 3

    def test_body_keyword_blocking(self):
        assert _issue_type_rank("untitled", set(), "this is blocking us") == 1

    def test_body_keyword_regression(self):
        assert _issue_type_rank("untitled", set(), "regression in v2") == 1

    def test_body_keyword_broken(self):
        assert _issue_type_rank("untitled", set(), "the ui is broken") == 2

    def test_body_keyword_improvement(self):
        assert _issue_type_rank("untitled", set(), "an improvement to caching") == 2

    def test_body_keyword_enhancement(self):
        assert _issue_type_rank("untitled", set(), "enhancement request") == 2

    def test_body_keyword_workaround(self):
        assert _issue_type_rank("untitled", set(), "applied a workaround") == 2

    def test_no_signal(self):
        assert _issue_type_rank("untitled", set(), "no signals here") is None


# ---------------------------------------------------------------------------
# _service_tier
# ---------------------------------------------------------------------------


class TestServiceTier:
    def test_tier_0(self):
        assert _service_tier({"service/traefik"}) == 0

    def test_tier_1(self):
        assert _service_tier({"service/portainer"}) == 1

    def test_tier_2(self):
        assert _service_tier({"service/sonarr"}) == 2

    def test_tier_3(self):
        assert _service_tier({"service/uptime-kuma"}) == 3

    def test_multiple_tiers_picks_lowest(self):
        assert _service_tier({"service/sonarr", "service/traefik"}) == 0

    def test_no_service_labels(self):
        assert _service_tier({"type/bug"}) is None

    def test_empty(self):
        assert _service_tier(set()) is None


# ---------------------------------------------------------------------------
# _blast_radius_bump
# ---------------------------------------------------------------------------


class TestBlastRadiusBump:
    def test_single_service(self):
        assert _blast_radius_bump({"service/traefik"}) == 0

    def test_two_services(self):
        assert _blast_radius_bump({"service/traefik", "stack/edge"}) == 1

    def test_three_mixed(self):
        assert _blast_radius_bump({"service/traefik", "stack/edge", "system/dns"}) == 1

    def test_four_services(self):
        labels = {"service/traefik", "service/sonarr", "stack/edge", "system/dns"}
        assert _blast_radius_bump(labels) == 2

    def test_cross_stack_two_stacks_bumps_two(self):
        assert _blast_radius_bump({"stack/edge", "stack/servarr"}) == 2

    def test_cross_stack_with_service(self):
        assert _blast_radius_bump({"service/traefik", "stack/edge", "stack/servarr"}) == 2

    def test_single_stack_no_cross_stack_bump(self):
        assert _blast_radius_bump({"service/traefik", "stack/edge"}) == 1

    def test_non_matching_labels(self):
        assert _blast_radius_bump({"type/bug", "area/ci"}) == 0

    def test_empty(self):
        assert _blast_radius_bump(set()) == 0


# ---------------------------------------------------------------------------
# _tier_floor_rank
# ---------------------------------------------------------------------------


class TestTierFloorRank:
    def test_security_tier_0_forces_p0(self):
        assert _tier_floor_rank("security: harden", set(), 0) == 0

    def test_security_label_tier_0_forces_p0(self):
        assert _tier_floor_rank("chore: foo", {"type/security"}, 0) == 0

    def test_bug_tier_0_floor_p1(self):
        assert _tier_floor_rank("bug: crash", {"type/bug"}, 0) == 1

    def test_bug_tier_1_floor_p2(self):
        assert _tier_floor_rank("fix: error", {"type/fix"}, 1) == 2

    def test_bug_tier_2_no_floor(self):
        assert _tier_floor_rank("bug: minor", {"type/bug"}, 2) == 3

    def test_feat_tier_0_no_floor(self):
        assert _tier_floor_rank("feat: new feature", set(), 0) == 3

    def test_no_type_no_floor(self):
        assert _tier_floor_rank("some title", set(), 1) == 3


# ---------------------------------------------------------------------------
# compute_priority — integration
# ---------------------------------------------------------------------------


class TestComputePriority:
    def test_already_has_priority_label(self):
        assert compute_priority(title="bug: crash", body="", labels=["P1-high"]) is None

    def test_incident_label_forces_p0(self):
        assert compute_priority(title="title", body="", labels=["incident"]) == "P0-critical"

    def test_severity_critical_forces_p0(self):
        result = compute_priority(title="title", body="", labels=["severity-critical"])
        assert result == "P0-critical"

    def test_p0_keyword_in_title(self):
        result = compute_priority(title="production down in prod", body="", labels=[])
        assert result == "P0-critical"

    def test_p0_keyword_in_body_only_not_p0(self):
        """P0 keywords in body only must not trigger P0 (title-only signal)."""
        result = compute_priority(title="title", body="production down", labels=[])
        assert result is None

    def test_doc_only_capped_at_p3(self):
        result = compute_priority(title="docs: update readme", body="", labels=["type/docs"])
        assert result == "P3-low"

    def test_doc_with_bug_not_capped(self):
        result = compute_priority(title="docs: update", body="", labels=["type/docs", "type/bug"])
        assert result != "P3-low"

    def test_no_signals_returns_none(self):
        assert compute_priority(title="untitled", body="no info", labels=[]) is None

    def test_blast_radius_only_uses_default_rank(self):
        result = compute_priority(
            title="untitled",
            body="",
            labels=["stack/edge", "stack/servarr"],
        )
        assert result == "P1-high"

    def test_cross_stack_bumps_two_levels(self):
        result = compute_priority(
            title="bug: cross-stack",
            body="",
            labels=["type/bug", "stack/edge", "stack/servarr"],
        )
        assert result == "P0-critical"

    def test_bug_with_tier_0_service(self):
        result = compute_priority(title="bug: traefik crash", body="", labels=["type/bug", "service/traefik"])
        assert result == "P1-high"

    def test_security_with_tier_0_service(self):
        result = compute_priority(
            title="security: auth bypass",
            body="",
            labels=["type/security", "service/authentik"],
        )
        assert result == "P0-critical"

    def test_bug_with_tier_1_service(self):
        result = compute_priority(
            title="bug: portainer error",
            body="",
            labels=["type/bug", "service/portainer"],
        )
        assert result == "P2-medium"

    def test_feat_default_priority(self):
        result = compute_priority(title="feat: add dark mode", body="", labels=["type/feat"])
        assert result == "P2-medium"

    def test_chore_default_priority(self):
        result = compute_priority(title="chore: cleanup", body="", labels=["type/chore"])
        assert result == "P3-low"

    def test_blast_radius_bumps_priority(self):
        result = compute_priority(
            title="bug: widespread",
            body="",
            labels=["type/bug", "service/sonarr", "service/radarr", "stack/servarr"],
        )
        assert result == "P1-high"

    def test_blast_radius_double_bump(self):
        result = compute_priority(
            title="bug: everything broken",
            body="",
            labels=[
                "type/bug",
                "service/sonarr",
                "service/radarr",
                "service/lidarr",
                "service/prowlarr",
            ],
        )
        assert result == "P0-critical"

    def test_body_keyword_blocking_with_tier(self):
        result = compute_priority(
            title="untitled issue",
            body="this is blocking deployment",
            labels=["service/traefik"],
        )
        assert result == "P1-high"

    def test_type_rank_only_no_tier(self):
        result = compute_priority(title="fix: broken test", body="", labels=["type/fix"])
        assert result == "P2-medium"

    def test_tier_only_no_type_rank(self):
        """When only tier is present (no type signal), default rank applies."""
        result = compute_priority(title="untitled", body="", labels=["service/traefik"])
        assert result == "P3-low"

    def test_p0_keyword_data_loss_in_title(self):
        result = compute_priority(title="data loss detected", body="", labels=[])
        assert result == "P0-critical"

    def test_p0_keyword_data_loss_in_body_only(self):
        """Body-only 'data loss' must not trigger P0."""
        result = compute_priority(title="title", body="data loss risk", labels=[])
        assert result is None

    def test_p0_keyword_security_breach_in_title(self):
        result = compute_priority(title="security breach!", body="", labels=[])
        assert result == "P0-critical"

    def test_p0_keyword_security_breach_in_body_only(self):
        """Body-only 'security breach' must not trigger P0."""
        result = compute_priority(title="title", body="security breach!", labels=[])
        assert result is None


# ---------------------------------------------------------------------------
# _build_recommendations
# ---------------------------------------------------------------------------


class TestBuildRecommendations:
    def test_filters_none_priorities(self):
        issues = [
            {"number": 1, "title": "bug: crash", "body": "", "labels": ["type/bug"]},
            {"number": 2, "title": "untitled", "body": "no info", "labels": []},
        ]
        recs = _build_recommendations(issues)
        assert len(recs) == 1
        assert recs[0]["number"] == 1
        assert recs[0]["recommended_priority"] == "P2-medium"

    def test_empty_issues(self):
        assert _build_recommendations([]) == []

    def test_all_already_labeled(self):
        issues = [
            {"number": 1, "title": "bug: crash", "body": "", "labels": ["P1-high"]},
        ]
        assert _build_recommendations(issues) == []

    def test_missing_body_key(self):
        issues = [{"number": 1, "title": "incident: outage", "labels": ["incident"]}]
        recs = _build_recommendations(issues)
        assert len(recs) == 1
        assert recs[0]["recommended_priority"] == "P0-critical"


# ---------------------------------------------------------------------------
# _resolve_repo
# ---------------------------------------------------------------------------


class TestResolveRepo:
    def test_uses_arg_when_provided(self):
        args = MagicMock()
        args.repo = "owner/repo"
        runner = MagicMock()
        assert mod._resolve_repo(args, runner) == "owner/repo"

    def test_falls_back_to_current_repo(self):
        args = MagicMock()
        args.repo = None
        runner = MagicMock()
        with patch(
            "scripts.ci.backfill_issue_priorities.current_repo",
            return_value="auto/detected",
        ) as mock_cr:
            result = mod._resolve_repo(args, runner)
        assert result == "auto/detected"
        mock_cr.assert_called_once_with(runner)


# ---------------------------------------------------------------------------
# _run (integration via main-like path)
# ---------------------------------------------------------------------------


class TestRun:
    def _make_args(self, *, repo="owner/repo", apply_flag=False, json_output=False):
        args = MagicMock()
        args.repo = repo
        args.apply = apply_flag
        args.json_output = json_output
        return args

    @patch("scripts.ci.backfill_issue_priorities.list_issues", return_value=[])
    def test_no_issues_exits_zero(self, mock_list, capsys):
        result = mod._run(self._make_args(), MagicMock(), MagicMock())
        assert result == 0
        mock_list.assert_called_once()

    @patch(
        "scripts.ci.backfill_issue_priorities.list_issues",
        return_value=[
            {"number": 1, "title": "bug: crash", "body": "", "labels": ["type/bug"]},
        ],
    )
    def test_dry_run_emits_hint(self, _mock_list, caplog):
        with caplog.at_level(logging.INFO, logger="scripts.ci.backfill_issue_priorities"):
            result = mod._run(self._make_args(), MagicMock(), MagicMock())
        assert result == 0
        assert "--apply" in caplog.text

    @patch(
        "scripts.ci.backfill_issue_priorities.list_issues",
        return_value=[
            {"number": 1, "title": "bug: crash", "body": "", "labels": ["type/bug"]},
        ],
    )
    def test_json_output(self, _mock_list, capsys):
        result = mod._run(self._make_args(json_output=True), MagicMock(), MagicMock())
        assert result == 0
        output = capsys.readouterr().out
        parsed = json.loads(output)
        assert len(parsed) == 1
        assert parsed[0]["recommended_priority"] == "P2-medium"

    @patch("scripts.ci.backfill_issue_priorities.upsert_issue")
    @patch(
        "scripts.ci.backfill_issue_priorities.list_issues",
        return_value=[
            {"number": 42, "title": "bug: crash", "body": "", "labels": ["type/bug"]},
        ],
    )
    def test_apply_calls_upsert(self, _mock_list, mock_upsert):
        runner = MagicMock()
        result = mod._run(self._make_args(apply_flag=True), MagicMock(), runner)
        assert result == 0
        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs.kwargs["number"] == 42
        assert call_kwargs.kwargs["labels"] == ["P2-medium"]
        assert call_kwargs.kwargs["merge_existing"] is True

    @patch(
        "scripts.ci.backfill_issue_priorities.list_issues",
        return_value=[
            {"number": 1, "title": "untitled", "body": "no info", "labels": []},
        ],
    )
    def test_no_recommendations_logs_message(self, _mock_list, caplog):
        with caplog.at_level(logging.INFO, logger="scripts.ci.backfill_issue_priorities"):
            result = mod._run(self._make_args(), MagicMock(), MagicMock())
        assert result == 0
        assert "No issues need priority labels" in caplog.text


# ---------------------------------------------------------------------------
# main (runner-injectable entry point)
# ---------------------------------------------------------------------------


class TestMain:
    @patch("scripts.ci.backfill_issue_priorities.list_issues", return_value=[])
    def test_main_returns_zero(self, _mock_list, monkeypatch):
        monkeypatch.setattr("sys.argv", ["backfill_issue_priorities", "--repo", "owner/repo"])
        runner = MagicMock()
        result = mod.main(runner_factory=lambda: runner)
        assert result == 0
