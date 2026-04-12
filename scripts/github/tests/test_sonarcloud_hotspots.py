"""Tests for security hotspots support in sonarcloud_issues."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts.github.sonarcloud_issues import (
    _VALID_HOTSPOT_RESOLUTIONS,
    _VALID_HOTSPOT_STATUSES,
    SecurityHotspot,
    _hotspot_from_raw,
    _validate_csv,
    fetch_hotspots,
    format_hotspots_json,
    format_hotspots_summary,
    main,
)

# --- SecurityHotspot dataclass ------------------------------------------------


class TestSecurityHotspot:
    def test_frozen(self) -> None:
        hotspot = SecurityHotspot(
            key="HS1",
            rule_key="python:S5146",
            message="Use secure URL.",
            component="proj:scripts/foo.py",
            security_category="others",
            vulnerability_probability="LOW",
            status="TO_REVIEW",
            line=42,
        )
        with pytest.raises(AttributeError):
            hotspot.key = "changed"  # type: ignore[misc]

    def test_fields(self) -> None:
        hotspot = SecurityHotspot(
            key="HS1",
            rule_key="python:S5146",
            message="Use secure URL.",
            component="proj:scripts/foo.py",
            security_category="others",
            vulnerability_probability="LOW",
            status="TO_REVIEW",
            line=42,
        )
        assert hotspot.key == "HS1"
        assert hotspot.rule_key == "python:S5146"
        assert hotspot.security_category == "others"
        assert hotspot.vulnerability_probability == "LOW"
        assert hotspot.status == "TO_REVIEW"
        assert hotspot.line == 42


# --- _hotspot_from_raw --------------------------------------------------------


class TestHotspotFromRaw:
    def test_full_payload(self) -> None:
        raw = {
            "key": "HS1",
            "ruleKey": "python:S5146",
            "message": "Fix this.",
            "component": "proj:scripts/foo.py",
            "securityCategory": "others",
            "vulnerabilityProbability": "LOW",
            "status": "TO_REVIEW",
            "line": 42,
        }
        hotspot = _hotspot_from_raw(raw)
        assert hotspot.key == "HS1"
        assert hotspot.rule_key == "python:S5146"
        assert hotspot.message == "Fix this."
        assert hotspot.component == "proj:scripts/foo.py"
        assert hotspot.security_category == "others"
        assert hotspot.vulnerability_probability == "LOW"
        assert hotspot.status == "TO_REVIEW"
        assert hotspot.line == 42

    def test_missing_optional_fields(self) -> None:
        hotspot = _hotspot_from_raw({})
        assert hotspot.key == ""
        assert hotspot.rule_key == ""
        assert hotspot.line is None


# --- _validate_csv for hotspot constants -------------------------------------


class TestHotspotValidation:
    def test_valid_hotspot_statuses(self) -> None:
        assert _validate_csv("TO_REVIEW", _VALID_HOTSPOT_STATUSES, "hotspot status") == "TO_REVIEW"
        assert _validate_csv("REVIEWED", _VALID_HOTSPOT_STATUSES, "hotspot status") == "REVIEWED"

    def test_invalid_hotspot_status(self) -> None:
        with pytest.raises(ValueError, match="Invalid hotspot status"):
            _validate_csv("INVALID", _VALID_HOTSPOT_STATUSES, "hotspot status")

    def test_valid_hotspot_resolutions(self) -> None:
        assert _validate_csv("FIXED", _VALID_HOTSPOT_RESOLUTIONS, "hotspot resolution") == "FIXED"
        assert _validate_csv("SAFE", _VALID_HOTSPOT_RESOLUTIONS, "hotspot resolution") == "SAFE"
        assert _validate_csv("ACKNOWLEDGED", _VALID_HOTSPOT_RESOLUTIONS, "hotspot resolution") == "ACKNOWLEDGED"

    def test_invalid_hotspot_resolution(self) -> None:
        with pytest.raises(ValueError, match="Invalid hotspot resolution"):
            _validate_csv("WONTFIX", _VALID_HOTSPOT_RESOLUTIONS, "hotspot resolution")


# --- fetch_hotspots -----------------------------------------------------------


class TestFetchHotspots:
    def test_basic_fetch(self) -> None:
        api_response = {
            "hotspots": [
                {
                    "key": "HS1",
                    "ruleKey": "python:S5146",
                    "message": "Fix.",
                    "component": "proj:foo.py",
                    "securityCategory": "others",
                    "vulnerabilityProbability": "LOW",
                    "status": "TO_REVIEW",
                    "line": 10,
                }
            ],
            "paging": {"pageIndex": 1, "pageSize": 100, "total": 1},
        }
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value=api_response,
        ) as mock_get:
            result = fetch_hotspots(project_key="proj", token="tok")
        assert len(result) == 1
        assert result[0].key == "HS1"
        url = mock_get.call_args[0][0]
        assert "projectKey=proj" in url
        assert "/api/hotspots/search" in url

    def test_with_pull_request(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"hotspots": [], "paging": {"total": 0}},
        ) as mock_get:
            fetch_hotspots(project_key="proj", token="tok", pull_request="42")
        url = mock_get.call_args[0][0]
        assert "pullRequest=42" in url

    def test_with_branch(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"hotspots": [], "paging": {"total": 0}},
        ) as mock_get:
            fetch_hotspots(project_key="proj", token="tok", branch="main")
        url = mock_get.call_args[0][0]
        assert "branch=main" in url

    def test_with_statuses(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"hotspots": [], "paging": {"total": 0}},
        ) as mock_get:
            fetch_hotspots(project_key="proj", token="tok", statuses="TO_REVIEW")
        url = mock_get.call_args[0][0]
        assert "status=TO_REVIEW" in url

    def test_with_resolution(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"hotspots": [], "paging": {"total": 0}},
        ) as mock_get:
            fetch_hotspots(project_key="proj", token="tok", resolution="SAFE")
        url = mock_get.call_args[0][0]
        assert "resolution=SAFE" in url

    def test_invalid_project_key_raises(self) -> None:
        with pytest.raises(ValueError, match="unsafe characters"):
            fetch_hotspots(project_key="p&evil=1", token="t")

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid hotspot status"):
            fetch_hotspots(project_key="proj", token="t", statuses="INVALID")

    def test_invalid_resolution_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid hotspot resolution"):
            fetch_hotspots(project_key="proj", token="t", resolution="INVALID")

    def test_page_size(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"hotspots": [], "paging": {"total": 0}},
        ) as mock_get:
            fetch_hotspots(project_key="proj", token="tok", page_size=50)
        url = mock_get.call_args[0][0]
        assert "ps=50" in url


# --- format_hotspots_json -----------------------------------------------------


class TestFormatHotspotsJson:
    def test_empty(self) -> None:
        result = json.loads(format_hotspots_json([]))
        assert result["count"] == 0
        assert result["hotspots"] == []

    def test_serializes_fields(self) -> None:
        hotspot = SecurityHotspot(
            key="HS1",
            rule_key="python:S5146",
            message="Fix.",
            component="proj:scripts/foo.py",
            security_category="others",
            vulnerability_probability="LOW",
            status="TO_REVIEW",
            line=10,
        )
        result = json.loads(format_hotspots_json([hotspot]))
        assert result["count"] == 1
        entry = result["hotspots"][0]
        assert entry["key"] == "HS1"
        assert entry["rule_key"] == "python:S5146"
        assert entry["security_category"] == "others"
        assert entry["vulnerability_probability"] == "LOW"
        assert entry["line"] == 10


# --- format_hotspots_summary --------------------------------------------------


class TestFormatHotspotsSummary:
    def test_no_hotspots(self) -> None:
        assert format_hotspots_summary([]) == "No SonarCloud security hotspots found."

    def test_table_format(self) -> None:
        hotspot = SecurityHotspot(
            key="HS1",
            rule_key="python:S5146",
            message="Fix.",
            component="proj:scripts/foo.py",
            security_category="others",
            vulnerability_probability="LOW",
            status="TO_REVIEW",
            line=10,
        )
        summary = format_hotspots_summary([hotspot])
        assert "Security Hotspots (1)" in summary
        assert "| LOW |" in summary
        assert "`scripts/foo.py`" in summary
        assert "| 10 |" in summary
        assert "| TO_REVIEW |" in summary

    def test_no_line(self) -> None:
        hotspot = SecurityHotspot(
            key="HS2",
            rule_key="python:S5146",
            message="Fix.",
            component="proj:scripts/foo.py",
            security_category="others",
            vulnerability_probability="HIGH",
            status="REVIEWED",
            line=None,
        )
        summary = format_hotspots_summary([hotspot])
        assert "| \u2014 |" in summary

    def test_no_colon_in_component(self) -> None:
        hotspot = SecurityHotspot(
            key="HS3",
            rule_key="r",
            message="m",
            component="simple_path.py",
            security_category="others",
            vulnerability_probability="LOW",
            status="TO_REVIEW",
            line=1,
        )
        summary = format_hotspots_summary([hotspot])
        assert "`simple_path.py`" in summary

    def test_pipe_in_message_escaped(self) -> None:
        hotspot = SecurityHotspot(
            key="HS4-pipe",
            rule_key="python:S5146",
            message="Use a | b",
            component="proj:scripts/foo.py",
            security_category="others",
            vulnerability_probability="LOW",
            status="TO_REVIEW",
            line=10,
        )
        summary = format_hotspots_summary([hotspot])
        assert r"Use a \| b" in summary


# --- main() hotspots mode -----------------------------------------------------


class TestMainHotspots:
    def test_hotspots_json(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--hotspots"])
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_hotspots",
            lambda **_: [],
        )
        assert main() == 0
        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 0

    def test_hotspots_summary(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--project-key", "proj", "--hotspots", "--format", "summary"],
        )
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_hotspots",
            lambda **_: [],
        )
        assert main() == 0
        assert "No SonarCloud security hotspots found" in capsys.readouterr().out

    def test_hotspots_rejects_issue_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--hotspots", "--types", "BUG"])
        with pytest.raises(SystemExit, match="2"):
            main()

    def test_hotspots_rejects_duplications(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--hotspots", "--duplications"])
        with pytest.raises(SystemExit, match="2"):
            main()

    def test_hotspot_statuses_filter(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--project-key", "proj", "--hotspots", "--hotspot-statuses", "TO_REVIEW"],
        )
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        captured_kwargs: dict[str, object] = {}

        def _capture(**kwargs: object) -> list[object]:
            captured_kwargs.update(kwargs)
            return []

        monkeypatch.setattr("scripts.github.sonarcloud_issues.fetch_hotspots", _capture)
        assert main() == 0
        assert captured_kwargs.get("statuses") == "TO_REVIEW"

    def test_hotspot_resolution_filter(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--project-key", "proj", "--hotspots", "--hotspot-resolution", "SAFE"],
        )
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        captured_kwargs: dict[str, object] = {}

        def _capture(**kwargs: object) -> list[object]:
            captured_kwargs.update(kwargs)
            return []

        monkeypatch.setattr("scripts.github.sonarcloud_issues.fetch_hotspots", _capture)
        assert main() == 0
        assert captured_kwargs.get("resolution") == "SAFE"

    def test_hotspot_flags_without_hotspots_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--project-key", "proj", "--hotspot-statuses", "TO_REVIEW"],
        )
        with pytest.raises(SystemExit, match="2"):
            main()

    def test_hotspots_allows_branch(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--project-key", "proj", "--hotspots", "--branch", "main"],
        )
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        captured_kwargs: dict[str, object] = {}

        def _capture(**kwargs: object) -> list[object]:
            captured_kwargs.update(kwargs)
            return []

        monkeypatch.setattr("scripts.github.sonarcloud_issues.fetch_hotspots", _capture)
        assert main() == 0
        assert captured_kwargs.get("branch") == "main"

    def test_hotspots_allows_pull_request(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--project-key", "proj", "--hotspots", "--pull-request", "99"],
        )
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        captured_kwargs: dict[str, object] = {}

        def _capture(**kwargs: object) -> list[object]:
            captured_kwargs.update(kwargs)
            return []

        monkeypatch.setattr("scripts.github.sonarcloud_issues.fetch_hotspots", _capture)
        assert main() == 0
        assert captured_kwargs.get("pull_request") == "99"

    def test_hotspots_api_error(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--hotspots"])
        monkeypatch.setenv("SONAR_TOKEN", "tok")

        def _raise(**_: object) -> None:
            raise RuntimeError("API down")

        monkeypatch.setattr("scripts.github.sonarcloud_issues.fetch_hotspots", _raise)
        assert main() == 2
        assert "API down" in capsys.readouterr().err
