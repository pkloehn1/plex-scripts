"""Tests for scripts.github.sonarcloud_issues."""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from scripts.github.sonarcloud_issues import (
    _VALID_TYPES,
    DuplicationBlockRef,
    DuplicationGroup,
    DuplicationMetrics,
    FileDuplication,
    SonarIssue,
    _escape_md_table,
    _fetch_all_blocks,
    _format_block_details,
    _http_get,
    _issue_from_raw,
    _measures_to_dict,
    _validate_csv,
    _validate_param,
    fetch_duplication_blocks,
    fetch_duplications,
    fetch_file_duplications,
    fetch_issues,
    format_duplications_json,
    format_duplications_summary,
    format_json,
    format_summary,
    main,
)

# --- _validate_csv -----------------------------------------------------------


class TestValidateCsv:
    def test_valid_single(self) -> None:
        assert _validate_csv("BUG", _VALID_TYPES, "type") == "BUG"

    def test_valid_multiple(self) -> None:
        assert _validate_csv("BUG,VULNERABILITY", _VALID_TYPES, "type") == "BUG,VULNERABILITY"

    def test_normalizes_spaces(self) -> None:
        assert _validate_csv("BUG, VULNERABILITY", _VALID_TYPES, "type") == "BUG,VULNERABILITY"

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid type"):
            _validate_csv("NOPE", _VALID_TYPES, "type")


# --- _escape_md_table --------------------------------------------------------


class TestEscapeMdTable:
    def test_plain_text(self) -> None:
        assert _escape_md_table("hello world") == "hello world"

    def test_pipe_escaped(self) -> None:
        assert _escape_md_table("a | b") == r"a \| b"

    def test_newline_replaced(self) -> None:
        assert _escape_md_table("line1\nline2") == "line1 line2"

    def test_combined(self) -> None:
        assert _escape_md_table("a | b\nc") == r"a \| b c"


# --- _validate_param ---------------------------------------------------------


class TestValidateParam:
    def test_valid_project_key(self) -> None:
        assert _validate_param("org_my-project", "project_key") == "org_my-project"

    def test_valid_branch(self) -> None:
        assert _validate_param("feat/foo-bar", "branch") == "feat/foo-bar"

    def test_valid_pull_request(self) -> None:
        assert _validate_param("42", "pull_request") == "42"

    def test_rejects_ampersand(self) -> None:
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_param("foo&bar=baz", "project_key")

    def test_rejects_newline(self) -> None:
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_param("foo\nbar", "branch")

    def test_rejects_space(self) -> None:
        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_param("foo bar", "pull_request")


# --- _issue_from_raw ---------------------------------------------------------


class TestIssueFromRaw:
    def test_full_payload(self) -> None:
        raw = {
            "key": "AX1",
            "rule": "python:S1234",
            "severity": "MAJOR",
            "type": "BUG",
            "message": "Fix this.",
            "component": "proj:scripts/foo.py",
            "line": 42,
            "status": "OPEN",
            "effort": "5min",
        }
        issue = _issue_from_raw(raw)
        assert issue.key == "AX1"
        assert issue.rule == "python:S1234"
        assert issue.severity == "MAJOR"
        assert issue.issue_type == "BUG"
        assert issue.message == "Fix this."
        assert issue.component == "proj:scripts/foo.py"
        assert issue.line == 42
        assert issue.status == "OPEN"
        assert issue.effort == "5min"

    def test_missing_optional_fields(self) -> None:
        issue = _issue_from_raw({})
        assert issue.key == ""
        assert issue.line is None
        assert issue.effort == ""


# --- _http_get ----------------------------------------------------------------


class TestHttpGet:
    def test_success(self) -> None:
        payload = {"result": "ok"}
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        with patch("urllib.request.urlopen", return_value=resp) as mock_urlopen:
            result = _http_get("https://example.com/api", "tok123")
        assert result == payload
        _, kwargs = mock_urlopen.call_args
        assert kwargs["timeout"] == 30

    def test_http_error_raises(self) -> None:
        exc = urllib.error.HTTPError(
            url="https://example.com/api",
            code=401,
            msg="Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
        exc.read = lambda: b"bad credentials"  # type: ignore[assignment, misc]
        with (
            patch("urllib.request.urlopen", side_effect=exc),
            pytest.raises(RuntimeError, match=r"HTTP 401.*bad credentials"),
        ):
            _http_get("https://example.com/api", "tok123")

    def test_url_error_raises(self) -> None:
        exc = urllib.error.URLError("connection refused")
        with patch("urllib.request.urlopen", side_effect=exc), pytest.raises(RuntimeError, match="connection refused"):
            _http_get("https://example.com/api", "tok123")


# --- _measures_to_dict -------------------------------------------------------


class TestMeasuresToDict:
    def test_converts_measures(self) -> None:
        measures = [
            {"metric": "duplicated_lines", "value": "42"},
            {"metric": "duplicated_blocks", "value": "5"},
        ]
        result = _measures_to_dict(measures)
        assert result == {"duplicated_lines": "42", "duplicated_blocks": "5"}

    def test_missing_value_defaults(self) -> None:
        measures = [{"metric": "m1"}]
        assert _measures_to_dict(measures) == {"m1": "0"}


# --- format_json --------------------------------------------------------------


class TestFormatJson:
    def test_empty(self) -> None:
        result = json.loads(format_json([]))
        assert result["count"] == 0
        assert result["issues"] == []

    def test_serializes_fields(self) -> None:
        issue = SonarIssue(
            key="K1",
            rule="python:S100",
            severity="MINOR",
            issue_type="CODE_SMELL",
            message="Rename.",
            component="proj:scripts/bar.py",
            line=10,
            status="OPEN",
            effort="2min",
        )
        result = json.loads(format_json([issue]))
        assert result["count"] == 1
        assert result["issues"][0]["rule"] == "python:S100"
        assert result["issues"][0]["line"] == 10


# --- format_summary ----------------------------------------------------------


class TestFormatSummary:
    def test_no_issues(self) -> None:
        assert format_summary([]) == "No SonarCloud issues found."

    def test_table_format(self) -> None:
        issue = SonarIssue(
            key="K1",
            rule="python:S100",
            severity="MAJOR",
            issue_type="BUG",
            message="Fix it.",
            component="proj:scripts/bar.py",
            line=5,
            status="OPEN",
            effort="3min",
        )
        summary = format_summary([issue])
        assert "SonarCloud Issues (1)" in summary
        assert "| MAJOR |" in summary
        assert "`scripts/bar.py`" in summary
        assert "| 5 |" in summary

    def test_no_line(self) -> None:
        issue = SonarIssue(
            key="K2",
            rule="python:S200",
            severity="INFO",
            issue_type="CODE_SMELL",
            message="Consider this.",
            component="proj:scripts/baz.py",
            line=None,
            status="OPEN",
            effort="",
        )
        summary = format_summary([issue])
        assert "| — |" in summary

    def test_no_colon_in_component(self) -> None:
        issue = SonarIssue(
            key="K3",
            rule="r",
            severity="INFO",
            issue_type="BUG",
            message="m",
            component="simple_path.py",
            line=1,
            status="OPEN",
            effort="",
        )
        summary = format_summary([issue])
        assert "`simple_path.py`" in summary

    def test_pipe_in_message_escaped(self) -> None:
        issue = SonarIssue(
            key="K4-pipe",
            rule="python:S100",
            severity="INFO",
            issue_type="BUG",
            message="Use a | b",
            component="proj:foo.py",
            line=1,
            status="OPEN",
            effort="",
        )
        summary = format_summary([issue])
        assert r"Use a \| b" in summary


# --- fetch_issues -------------------------------------------------------------


class TestFetchIssues:
    def test_basic_fetch(self) -> None:
        api_response = {
            "issues": [
                {
                    "key": "AX1",
                    "rule": "python:S1234",
                    "severity": "MAJOR",
                    "type": "BUG",
                    "message": "Fix.",
                    "component": "proj:foo.py",
                    "line": 1,
                    "status": "OPEN",
                    "effort": "5min",
                }
            ]
        }
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value=api_response,
        ) as mock_get:
            result = fetch_issues(project_key="proj", token="tok")
        assert len(result) == 1
        assert result[0].key == "AX1"
        url = mock_get.call_args[0][0]
        assert "componentKeys=proj" in url
        assert "ps=100" in url

    def test_all_filters(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"issues": []},
        ) as mock_get:
            fetch_issues(
                project_key="p",
                token="t",
                types="BUG",
                severities="MAJOR",
                statuses="OPEN",
                branch="main",
                pull_request="42",
            )
        url = mock_get.call_args[0][0]
        assert "types=BUG" in url
        assert "severities=MAJOR" in url
        assert "statuses=OPEN" in url
        assert "branch=main" in url
        assert "pullRequest=42" in url

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid type"):
            fetch_issues(project_key="p", token="t", types="INVALID")

    def test_invalid_project_key_raises(self) -> None:
        with pytest.raises(ValueError, match="unsafe characters"):
            fetch_issues(project_key="p&evil=1", token="t")

    def test_invalid_branch_raises(self) -> None:
        with pytest.raises(ValueError, match="unsafe characters"):
            fetch_issues(project_key="p", token="t", branch="b&evil=1")

    def test_invalid_pull_request_raises(self) -> None:
        with pytest.raises(ValueError, match="unsafe characters"):
            fetch_issues(project_key="p", token="t", pull_request="1&evil=1")


# --- fetch_duplications -------------------------------------------------------


class TestFetchDuplications:
    def test_basic(self) -> None:
        api_response = {
            "component": {
                "measures": [
                    {"metric": "duplicated_lines", "value": "100"},
                    {"metric": "duplicated_blocks", "value": "5"},
                    {"metric": "duplicated_files", "value": "3"},
                    {"metric": "duplicated_lines_density", "value": "4.2"},
                    {"metric": "new_duplicated_lines", "value": "10"},
                    {"metric": "new_duplicated_blocks", "value": "2"},
                    {"metric": "new_duplicated_lines_density", "value": "1.5"},
                ]
            }
        }
        with patch("scripts.github.sonarcloud_issues._http_get", return_value=api_response):
            result = fetch_duplications(project_key="proj", token="tok")
        assert result.duplicated_lines == 100
        assert result.duplicated_blocks == 5
        assert result.duplicated_files == 3
        assert result.duplicated_lines_density == pytest.approx(4.2)
        assert result.new_duplicated_lines == 10
        assert result.new_duplicated_blocks == 2
        assert result.new_duplicated_lines_density == pytest.approx(1.5)

    def test_with_pull_request(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"component": {"measures": []}},
        ) as mock_get:
            fetch_duplications(project_key="proj", token="tok", pull_request="99")
        url = mock_get.call_args[0][0]
        assert "pullRequest=99" in url

    def test_empty_measures(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"component": {"measures": []}},
        ):
            result = fetch_duplications(project_key="proj", token="tok")
        assert result.duplicated_lines == 0
        assert result.duplicated_lines_density == pytest.approx(0.0)


# --- fetch_file_duplications --------------------------------------------------


class TestFetchFileDuplications:
    def test_basic(self) -> None:
        api_response = {
            "components": [
                {
                    "path": "src/foo.py",
                    "measures": [
                        {"metric": "duplicated_lines", "value": "20"},
                        {"metric": "duplicated_lines_density", "value": "8.5"},
                        {"metric": "duplicated_blocks", "value": "2"},
                    ],
                }
            ]
        }
        with patch("scripts.github.sonarcloud_issues._http_get", return_value=api_response):
            result = fetch_file_duplications(project_key="proj", token="tok")
        assert len(result) == 1
        assert result[0].path == "src/foo.py"
        assert result[0].duplicated_lines == 20

    def test_skips_zero_dup_files(self) -> None:
        api_response = {
            "components": [
                {
                    "path": "src/clean.py",
                    "measures": [
                        {"metric": "duplicated_lines", "value": "0"},
                    ],
                }
            ]
        }
        with patch("scripts.github.sonarcloud_issues._http_get", return_value=api_response):
            result = fetch_file_duplications(project_key="proj", token="tok")
        assert result == []

    def test_with_pull_request(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"components": []},
        ) as mock_get:
            fetch_file_duplications(project_key="proj", token="tok", pull_request="55")
        url = mock_get.call_args[0][0]
        assert "pullRequest=55" in url

    def test_falls_back_to_key(self) -> None:
        api_response = {
            "components": [
                {
                    "key": "proj:src/bar.py",
                    "measures": [
                        {"metric": "duplicated_lines", "value": "5"},
                    ],
                }
            ]
        }
        with patch("scripts.github.sonarcloud_issues._http_get", return_value=api_response):
            result = fetch_file_duplications(project_key="proj", token="tok")
        assert result[0].path == "proj:src/bar.py"


# --- fetch_duplication_blocks -------------------------------------------------


class TestFetchDuplicationBlocks:
    def test_basic(self) -> None:
        api_response = {
            "duplications": [
                {
                    "blocks": [
                        {"_ref": "1", "from": 10, "size": 20},
                        {"_ref": "2", "from": 30, "size": 20},
                    ]
                }
            ],
            "files": {
                "1": {"key": "proj:foo.py", "name": "foo.py"},
                "2": {"key": "proj:bar.py", "name": "bar.py"},
            },
        }
        with patch("scripts.github.sonarcloud_issues._http_get", return_value=api_response):
            result = fetch_duplication_blocks(file_key="proj:foo.py", token="tok")
        assert len(result) == 1
        assert len(result[0].blocks) == 2
        assert result[0].blocks[0].file_key == "proj:foo.py"
        assert result[0].blocks[0].from_line == 10
        assert result[0].blocks[0].size == 20
        assert result[0].blocks[1].file_name == "bar.py"

    def test_empty(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"duplications": [], "files": {}},
        ):
            result = fetch_duplication_blocks(file_key="proj:foo.py", token="tok")
        assert result == []

    def test_missing_file_ref(self) -> None:
        api_response = {
            "duplications": [{"blocks": [{"_ref": "99", "from": 1, "size": 5}]}],
            "files": {},
        }
        with patch("scripts.github.sonarcloud_issues._http_get", return_value=api_response):
            result = fetch_duplication_blocks(file_key="proj:foo.py", token="tok")
        assert result[0].blocks[0].file_key == ""
        assert result[0].blocks[0].file_name == ""

    def test_with_pull_request(self) -> None:
        with patch(
            "scripts.github.sonarcloud_issues._http_get",
            return_value={"duplications": [], "files": {}},
        ) as mock_get:
            fetch_duplication_blocks(file_key="proj:foo.py", token="tok", pull_request="99")
        url = mock_get.call_args[0][0]
        assert "pullRequest=99" in url

    def test_invalid_file_key_raises(self) -> None:
        with pytest.raises(ValueError, match="unsafe characters"):
            fetch_duplication_blocks(file_key="proj:foo.py&evil=1", token="tok")


# --- _fetch_all_blocks --------------------------------------------------------


class TestFetchAllBlocks:
    def test_fetches_for_each_file(self) -> None:
        files = [
            FileDuplication(path="src/foo.py", duplicated_lines=10, duplicated_lines_density=5.0, duplicated_blocks=1),
            FileDuplication(path="src/bar.py", duplicated_lines=5, duplicated_lines_density=2.0, duplicated_blocks=1),
        ]
        group = DuplicationGroup(
            blocks=(DuplicationBlockRef(file_key="proj:src/foo.py", file_name="foo.py", from_line=1, size=10),)
        )
        with patch(
            "scripts.github.sonarcloud_issues.fetch_duplication_blocks",
            side_effect=[[group], []],
        ):
            result = _fetch_all_blocks(files, "proj", "tok")
        assert "src/foo.py" in result
        assert "src/bar.py" not in result

    def test_handles_key_with_colon(self) -> None:
        files = [
            FileDuplication(
                path="proj:src/foo.py", duplicated_lines=10, duplicated_lines_density=5.0, duplicated_blocks=1
            ),
        ]
        with patch(
            "scripts.github.sonarcloud_issues.fetch_duplication_blocks",
            return_value=[],
        ) as mock_fetch:
            _fetch_all_blocks(files, "proj", "tok")
        mock_fetch.assert_called_once_with(file_key="proj:src/foo.py", token="tok", pull_request=None)


# --- _format_block_details ----------------------------------------------------


class TestFormatBlockDetails:
    def test_renders_groups(self) -> None:
        files = [
            FileDuplication(path="src/foo.py", duplicated_lines=10, duplicated_lines_density=5.0, duplicated_blocks=1),
        ]
        blocks = {
            "src/foo.py": [
                DuplicationGroup(
                    blocks=(
                        DuplicationBlockRef(file_key="proj:src/foo.py", file_name="foo.py", from_line=1, size=10),
                        DuplicationBlockRef(file_key="proj:src/bar.py", file_name="bar.py", from_line=20, size=10),
                    )
                )
            ]
        }
        lines = _format_block_details(files, blocks)
        text = "\n".join(lines)
        assert "### Block Details" in text
        assert "**`src/foo.py`**" in text
        assert "Group 1:" in text
        assert "`foo.py` lines 1" in text
        assert "`bar.py` lines 20" in text

    def test_skips_files_without_blocks(self) -> None:
        files = [
            FileDuplication(path="src/clean.py", duplicated_lines=5, duplicated_lines_density=1.0, duplicated_blocks=1),
        ]
        lines = _format_block_details(files, {})
        text = "\n".join(lines)
        assert "### Block Details" in text
        assert "clean.py" not in text


# --- format_duplications_json -------------------------------------------------


class TestFormatDuplicationsJson:
    def test_output(self) -> None:
        metrics = DuplicationMetrics(
            duplicated_lines=100,
            duplicated_blocks=5,
            duplicated_files=3,
            duplicated_lines_density=4.2,
            new_duplicated_lines=10,
            new_duplicated_blocks=2,
            new_duplicated_lines_density=1.5,
        )
        files = [
            FileDuplication(path="src/foo.py", duplicated_lines=20, duplicated_lines_density=8.5, duplicated_blocks=2),
        ]
        result = json.loads(format_duplications_json(metrics, files))
        assert result["metrics"]["duplicated_lines"] == 100
        assert result["metrics"]["new_duplicated_lines_density"] == pytest.approx(1.5)
        assert len(result["files"]) == 1
        assert result["files"][0]["path"] == "src/foo.py"

    def test_empty_files(self) -> None:
        metrics = DuplicationMetrics(0, 0, 0, 0.0, 0, 0, 0.0)
        result = json.loads(format_duplications_json(metrics, []))
        assert result["files"] == []

    def test_with_blocks(self) -> None:
        metrics = DuplicationMetrics(10, 1, 1, 2.0, 0, 0, 0.0)
        files = [
            FileDuplication(path="src/foo.py", duplicated_lines=10, duplicated_lines_density=2.0, duplicated_blocks=1),
        ]
        blocks = {
            "src/foo.py": [
                DuplicationGroup(
                    blocks=(
                        DuplicationBlockRef(file_key="proj:src/foo.py", file_name="foo.py", from_line=1, size=10),
                        DuplicationBlockRef(file_key="proj:src/bar.py", file_name="bar.py", from_line=5, size=10),
                    )
                )
            ]
        }
        result = json.loads(format_duplications_json(metrics, files, blocks))
        assert "block_details" in result["files"][0]
        assert len(result["files"][0]["block_details"]) == 1
        assert result["files"][0]["block_details"][0]["blocks"][0]["from_line"] == 1


# --- format_duplications_summary ----------------------------------------------


class TestFormatDuplicationsSummary:
    def test_with_new_code_and_files(self) -> None:
        metrics = DuplicationMetrics(
            duplicated_lines=100,
            duplicated_blocks=5,
            duplicated_files=3,
            duplicated_lines_density=4.2,
            new_duplicated_lines=10,
            new_duplicated_blocks=2,
            new_duplicated_lines_density=1.5,
        )
        files = [
            FileDuplication(path="src/foo.py", duplicated_lines=20, duplicated_lines_density=8.5, duplicated_blocks=2),
        ]
        summary = format_duplications_summary(metrics, files)
        assert "## SonarCloud Duplications" in summary
        assert "100" in summary
        assert "4.2%" in summary
        assert "### New Code" in summary
        assert "### Files with Duplications" in summary
        assert "`src/foo.py`" in summary

    def test_no_new_code(self) -> None:
        metrics = DuplicationMetrics(50, 3, 2, 2.0, 0, 0, 0.0)
        summary = format_duplications_summary(metrics, [])
        assert "### New Code" not in summary
        assert "### Files with Duplications" not in summary

    def test_new_density_only(self) -> None:
        metrics = DuplicationMetrics(50, 3, 2, 2.0, 0, 0, 0.5)
        summary = format_duplications_summary(metrics, [])
        assert "### New Code" in summary

    def test_with_blocks(self) -> None:
        metrics = DuplicationMetrics(10, 1, 1, 2.0, 0, 0, 0.0)
        files = [
            FileDuplication(path="src/foo.py", duplicated_lines=10, duplicated_lines_density=2.0, duplicated_blocks=1),
        ]
        blocks = {
            "src/foo.py": [
                DuplicationGroup(
                    blocks=(DuplicationBlockRef(file_key="proj:src/foo.py", file_name="foo.py", from_line=1, size=10),)
                )
            ]
        }
        summary = format_duplications_summary(metrics, files, blocks)
        assert "### Block Details" in summary
        assert "**`src/foo.py`**" in summary
        assert "Group 1:" in summary


# --- _read_project_key -------------------------------------------------------


class TestReadProjectKey:
    def test_reads_from_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        props = tmp_path / "sonar-project.properties"
        props.write_text("sonar.projectKey=org_my-project\n", encoding="utf-8")
        monkeypatch.setattr("scripts.common.paths.repo_root", lambda: tmp_path)

        from scripts.github.sonarcloud_issues import _read_project_key

        assert _read_project_key() == "org_my-project"

    def test_returns_none_when_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("scripts.common.paths.repo_root", lambda: tmp_path)

        from scripts.github.sonarcloud_issues import _read_project_key

        assert _read_project_key() is None

    def test_returns_none_on_import_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import builtins

        real_import = builtins.__import__

        def _block_paths(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "scripts.common.paths":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _block_paths)

        from scripts.github.sonarcloud_issues import _read_project_key

        assert _read_project_key() is None

    def test_returns_none_when_no_key_line(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        props = tmp_path / "sonar-project.properties"
        props.write_text("sonar.organization=myorg\n", encoding="utf-8")
        monkeypatch.setattr("scripts.common.paths.repo_root", lambda: tmp_path)

        from scripts.github.sonarcloud_issues import _read_project_key

        assert _read_project_key() is None


# --- main ---------------------------------------------------------------------


class TestMain:
    def test_no_project_key(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", ""])
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues._read_project_key",
            lambda: None,
        )
        assert main() == 2
        assert "project-key" in capsys.readouterr().err.lower()

    def test_duplications_rejects_issue_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--duplications", "--types", "BUG"])
        with pytest.raises(SystemExit, match="2"):
            main()

    def test_block_details_requires_duplications(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--block-details"])
        with pytest.raises(SystemExit, match="2"):
            main()

    def test_duplications_rejects_branch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--duplications", "--branch", "main"])
        with pytest.raises(SystemExit, match="2"):
            main()

    def test_no_token(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj"])
        monkeypatch.delenv("SONAR_TOKEN", raising=False)
        assert main() == 2
        assert "SONAR_TOKEN" in capsys.readouterr().err

    def test_issues_json(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj"])
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_issues",
            lambda **_: [],
        )
        assert main() == 0
        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 0

    def test_issues_summary(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--format", "summary"])
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_issues",
            lambda **_: [],
        )
        assert main() == 0
        assert "No SonarCloud issues found" in capsys.readouterr().out

    def test_duplications_json_no_files(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--duplications"])
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        metrics = DuplicationMetrics(10, 2, 1, 1.5, 0, 0, 0.0)
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_duplications",
            lambda **_: metrics,
        )
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_file_duplications",
            lambda **_: [],
        )
        assert main() == 0
        output = json.loads(capsys.readouterr().out)
        assert output["metrics"]["duplicated_lines"] == 10

    def test_duplications_json_with_files(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--duplications", "--block-details"])
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        metrics = DuplicationMetrics(10, 1, 1, 2.0, 0, 0, 0.0)
        files = [
            FileDuplication(path="src/foo.py", duplicated_lines=10, duplicated_lines_density=2.0, duplicated_blocks=1),
        ]
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_duplications",
            lambda **_: metrics,
        )
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_file_duplications",
            lambda **_: files,
        )
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues._fetch_all_blocks",
            lambda *_args, **_kwargs: {},
        )
        assert main() == 0
        output = json.loads(capsys.readouterr().out)
        assert len(output["files"]) == 1

    def test_duplications_no_block_details(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj", "--duplications"])
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        metrics = DuplicationMetrics(10, 1, 1, 2.0, 0, 0, 0.0)
        files = [
            FileDuplication(path="src/foo.py", duplicated_lines=10, duplicated_lines_density=2.0, duplicated_blocks=1),
        ]
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_duplications",
            lambda **_: metrics,
        )
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_file_duplications",
            lambda **_: files,
        )
        assert main() == 0
        output = json.loads(capsys.readouterr().out)
        assert len(output["files"]) == 1
        assert "block_details" not in output["files"][0]

    def test_duplications_summary(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--project-key", "proj", "--duplications", "--format", "summary"],
        )
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        metrics = DuplicationMetrics(10, 2, 1, 1.5, 0, 0, 0.0)
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_duplications",
            lambda **_: metrics,
        )
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_file_duplications",
            lambda **_: [],
        )
        assert main() == 0
        assert "SonarCloud Duplications" in capsys.readouterr().out

    def test_api_error(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr("sys.argv", ["prog", "--project-key", "proj"])
        monkeypatch.setenv("SONAR_TOKEN", "tok")

        def _raise(**_: object) -> None:
            raise RuntimeError("API down")

        monkeypatch.setattr("scripts.github.sonarcloud_issues.fetch_issues", _raise)
        assert main() == 2
        assert "API down" in capsys.readouterr().err

    def test_reads_project_key_from_file(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr("sys.argv", ["prog"])
        monkeypatch.setenv("SONAR_TOKEN", "tok")
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues._read_project_key",
            lambda: "auto-proj",
        )
        monkeypatch.setattr(
            "scripts.github.sonarcloud_issues.fetch_issues",
            lambda **_: [],
        )
        assert main() == 0
