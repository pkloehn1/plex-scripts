"""Tests for GitHub ruleset export synchronization.

Covers parsing existing JSONC export, normalizing remote ruleset payloads,
idempotent file updates, and declarative required-contexts management.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.ci import sync_github_ruleset_export as sgr


def test_normalize_ruleset_removes_volatile_fields() -> None:
    raw = {
        "id": 123,
        "name": "main",
        "target": "branch",
        "source_type": "Repository",
        "source": "o/r",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [{"type": "deletion"}],
        "bypass_actors": [],
        "node_id": "abc",
        "created_at": "yesterday",
        "updated_at": "today",
        "current_user_can_bypass": "never",
        "_links": {"self": {"href": "https://example"}},
    }

    normalized = sgr.normalize_ruleset(raw)

    assert normalized["id"] == 123
    assert "node_id" not in normalized
    assert "created_at" not in normalized
    assert "updated_at" not in normalized
    assert "_links" not in normalized
    assert "current_user_can_bypass" not in normalized


def test_extract_json_from_jsonc_ignores_leading_comments() -> None:
    text = """// header\n// more\n\n{\n  \"id\": 1,\n  \"name\": \"main\"\n}\n"""
    assert sgr.extract_json_object(text) == {"id": 1, "name": "main"}


def test_write_jsonc_export_idempotent(tmp_path: Path) -> None:
    out_path = tmp_path / "main-ruleset.jsonc"

    data = {
        "id": 1,
        "name": "main",
        "target": "branch",
        "source_type": "Repository",
        "source": "o/r",
        "enforcement": "active",
        "conditions": {"ref_name": {"exclude": [], "include": ["~DEFAULT_BRANCH"]}},
        "rules": [],
        "bypass_actors": [],
    }

    changed_1 = sgr.write_ruleset_jsonc_if_changed(
        path=out_path,
        repo="o/r",
        ruleset_name="main",
        normalized_ruleset=data,
    )
    assert changed_1 is True

    changed_2 = sgr.write_ruleset_jsonc_if_changed(
        path=out_path,
        repo="o/r",
        ruleset_name="main",
        normalized_ruleset=data,
    )
    assert changed_2 is False


def test_diff_summary_reports_required_context_changes() -> None:
    before = {
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "A"}, {"context": "B"}],
                },
            }
        ]
    }
    after = {
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "B"}, {"context": "C"}],
                },
            }
        ]
    }

    summary = sgr.diff_summary(before, after)
    assert summary.added_required_contexts == {"C"}
    assert summary.removed_required_contexts == {"A"}


def test_fetch_ruleset_uses_gh_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str]) -> str:
        calls.append(cmd)
        return '{"id": 1, "name": "main"}'

    monkeypatch.setattr(sgr, "_run", fake_run)

    out = sgr.fetch_ruleset_json(repo="o/r", ruleset_id=1)
    assert out == {"id": 1, "name": "main"}
    assert calls == [["gh", "api", "/repos/o/r/rulesets/1"]]


# ---------------------------------------------------------------------------
# extract_json_object error paths
# ---------------------------------------------------------------------------


def test_extract_json_object_raises_when_no_opening_brace() -> None:
    with pytest.raises(ValueError, match="No JSON object found"):
        sgr.extract_json_object("// just a comment\n")


def test_extract_json_object_raises_on_invalid_json() -> None:
    with pytest.raises(ValueError, match="Failed to parse JSON object"):
        sgr.extract_json_object("{ not valid json }")


# ---------------------------------------------------------------------------
# _find_required_status_checks branch coverage
# ---------------------------------------------------------------------------


def test_find_required_status_checks_returns_empty_when_rules_not_list() -> None:
    ruleset: dict = {"rules": "not-a-list"}
    assert sgr._find_required_status_checks(ruleset) == []


def test_find_required_status_checks_skips_non_dict_rule() -> None:
    ruleset: dict = {"rules": ["not-a-dict"]}
    assert sgr._find_required_status_checks(ruleset) == []


def test_find_required_status_checks_skips_non_matching_type() -> None:
    ruleset: dict = {"rules": [{"type": "deletion"}]}
    assert sgr._find_required_status_checks(ruleset) == []


def test_find_required_status_checks_skips_when_params_not_dict() -> None:
    ruleset: dict = {
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": "not-a-dict",
            }
        ]
    }
    assert sgr._find_required_status_checks(ruleset) == []


# ---------------------------------------------------------------------------
# load_required_contexts
# ---------------------------------------------------------------------------


def _write_contexts_yaml(path: Path, contexts: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as yml:
        yaml.safe_dump(contexts, yml, default_flow_style=False, sort_keys=False)


def test_load_required_contexts_valid(tmp_path: Path) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(ctx_file, [{"context": "Lint Code Base", "integration_id": 15368}])

    result = sgr.load_required_contexts(ctx_file)
    assert result == [{"context": "Lint Code Base", "integration_id": 15368}]


def test_load_required_contexts_empty_file(tmp_path: Path) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    ctx_file.write_text("---\n...\n", encoding="utf-8")

    result = sgr.load_required_contexts(ctx_file)
    assert result == []


def test_load_required_contexts_rejects_missing_context(tmp_path: Path) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(ctx_file, [{"integration_id": 15368}])

    with pytest.raises(ValueError, match="missing required key 'context'"):
        sgr.load_required_contexts(ctx_file)


def test_load_required_contexts_rejects_missing_integration_id(tmp_path: Path) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(ctx_file, [{"context": "Lint Code Base"}])

    with pytest.raises(ValueError, match="missing required key 'integration_id'"):
        sgr.load_required_contexts(ctx_file)


def test_load_required_contexts_rejects_non_list(tmp_path: Path) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    ctx_file.write_text("not_a_list: true\n", encoding="utf-8")

    with pytest.raises(ValueError, match="must be a YAML list"):
        sgr.load_required_contexts(ctx_file)


def test_load_required_contexts_rejects_non_dict_entry(tmp_path: Path) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    ctx_file.write_text("- just a string\n", encoding="utf-8")

    with pytest.raises(ValueError, match="entry must be a mapping"):
        sgr.load_required_contexts(ctx_file)


def test_load_required_contexts_rejects_non_string_context(tmp_path: Path) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(ctx_file, [{"context": 123, "integration_id": 15368}])

    with pytest.raises(ValueError, match="'context' must be a string"):
        sgr.load_required_contexts(ctx_file)


def test_load_required_contexts_rejects_non_int_integration_id(tmp_path: Path) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(ctx_file, [{"context": "Lint Code Base", "integration_id": "not-an-int"}])

    with pytest.raises(ValueError, match="'integration_id' must be an integer"):
        sgr.load_required_contexts(ctx_file)


# ---------------------------------------------------------------------------
# validate_contexts
# ---------------------------------------------------------------------------


def _make_live_ruleset(checks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": "main",
        "rules": [
            {"type": "deletion"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                    "required_status_checks": checks,
                },
            },
        ],
    }


def test_validate_contexts_match() -> None:
    declared = [{"context": "Lint Code Base", "integration_id": 15368}]
    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])

    diff = sgr.validate_contexts(declared, live)
    assert diff.added_required_contexts == set()
    assert diff.removed_required_contexts == set()


def test_validate_contexts_drift_detected() -> None:
    declared = [
        {"context": "Lint Code Base", "integration_id": 15368},
        {"context": "Run Tests", "integration_id": 99999},
    ]
    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])

    diff = sgr.validate_contexts(declared, live)
    assert diff.added_required_contexts == {"Run Tests"}
    assert diff.removed_required_contexts == set()


def test_validate_contexts_extra_in_live() -> None:
    declared = [{"context": "Lint Code Base", "integration_id": 15368}]
    live = _make_live_ruleset(
        [
            {"context": "Lint Code Base", "integration_id": 15368},
            {"context": "Stale Check", "integration_id": 11111},
        ]
    )

    diff = sgr.validate_contexts(declared, live)
    assert diff.added_required_contexts == set()
    assert diff.removed_required_contexts == {"Stale Check"}


def test_validate_contexts_integration_id_drift() -> None:
    declared = [{"context": "Lint Code Base", "integration_id": 99999}]
    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])

    diff = sgr.validate_contexts(declared, live)
    assert diff.added_required_contexts == set()
    assert diff.removed_required_contexts == set()
    assert diff.mismatched_integration_ids == {
        "Lint Code Base": (99999, 15368),
    }


def test_validate_contexts_no_integration_id_drift() -> None:
    declared = [{"context": "Lint Code Base", "integration_id": 15368}]
    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])

    diff = sgr.validate_contexts(declared, live)
    assert diff.mismatched_integration_ids == {}


# ---------------------------------------------------------------------------
# build_status_checks_patch
# ---------------------------------------------------------------------------


def test_build_status_checks_patch_replaces_checks() -> None:
    declared = [
        {"context": "Lint Code Base", "integration_id": 15368},
        {"context": "Run Tests", "integration_id": 99999},
    ]
    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])

    patch = sgr.build_status_checks_patch(declared, live)

    # Original ruleset is not mutated
    orig_checks = live["rules"][1]["parameters"]["required_status_checks"]
    assert len(orig_checks) == 1

    # Patch has the new checks
    patch_checks = patch["rules"][1]["parameters"]["required_status_checks"]
    assert len(patch_checks) == 2
    assert patch_checks == declared

    # Non-status-check rules are preserved
    assert patch["rules"][0] == {"type": "deletion"}


def test_build_status_checks_patch_no_existing_rule() -> None:
    declared = [{"context": "Lint Code Base", "integration_id": 15368}]
    live: dict[str, Any] = {"name": "main", "rules": [{"type": "deletion"}]}

    with pytest.raises(ValueError, match="No required_status_checks rule"):
        sgr.build_status_checks_patch(declared, live)


def test_build_status_checks_patch_rules_not_list() -> None:
    declared = [{"context": "Lint Code Base", "integration_id": 15368}]
    live: dict[str, Any] = {"name": "main", "rules": "not-a-list"}

    with pytest.raises(ValueError, match="No required_status_checks rule"):
        sgr.build_status_checks_patch(declared, live)


def test_build_status_checks_patch_skips_non_dict_rule() -> None:
    declared = [{"context": "Lint Code Base", "integration_id": 15368}]
    live: dict[str, Any] = {
        "name": "main",
        "rules": [
            "not-a-dict",
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "Old", "integration_id": 1}],
                },
            },
        ],
    }

    patch = sgr.build_status_checks_patch(declared, live)
    patch_checks = patch["rules"][1]["parameters"]["required_status_checks"]
    assert patch_checks == declared


# ---------------------------------------------------------------------------
# apply_contexts
# ---------------------------------------------------------------------------


def test_apply_contexts_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_run_with_input(cmd: list[str], stdin_data: str) -> str:
        calls.append((cmd, stdin_data))
        return ""

    monkeypatch.setattr(sgr, "_run_with_input", fake_run_with_input)

    patch = {"name": "main", "rules": []}
    result = sgr.apply_contexts(repo="o/r", ruleset_id=1, patch=patch, dry_run=True)

    assert calls == []
    assert "dry-run" in result.lower()


def test_apply_contexts_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_run_with_input(cmd: list[str], stdin_data: str) -> str:
        calls.append((cmd, stdin_data))
        return '{"id": 1}'

    monkeypatch.setattr(sgr, "_run_with_input", fake_run_with_input)

    patch = {"name": "main", "rules": []}
    result = sgr.apply_contexts(repo="o/r", ruleset_id=1, patch=patch, dry_run=False)

    assert len(calls) == 1
    url_arg = next(arg for arg in calls[0][0] if arg.startswith("/repos/"))
    assert url_arg == "/repos/o/r/rulesets/1"
    assert "Applied" in result


# ---------------------------------------------------------------------------
# _format_diff
# ---------------------------------------------------------------------------


def test_format_diff_added_and_removed() -> None:
    diff = sgr.DiffSummary(
        added_required_contexts={"Run Tests"},
        removed_required_contexts={"Old Check"},
        mismatched_integration_ids={},
    )
    output = sgr._format_diff(diff)
    assert "+ Run Tests" in output
    assert "- Old Check" in output


def test_format_diff_empty() -> None:
    diff = sgr.DiffSummary(
        added_required_contexts=set(),
        removed_required_contexts=set(),
        mismatched_integration_ids={},
    )
    assert sgr._format_diff(diff) == ""


def test_format_diff_integration_id_mismatch() -> None:
    diff = sgr.DiffSummary(
        added_required_contexts=set(),
        removed_required_contexts=set(),
        mismatched_integration_ids={"Lint Code Base": (99999, 15368)},
    )
    output = sgr._format_diff(diff)
    assert "Lint Code Base" in output
    assert "99999" in output
    assert "15368" in output


# ---------------------------------------------------------------------------
# run_validate_contexts
# ---------------------------------------------------------------------------


def test_run_validate_contexts_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(ctx_file, [{"context": "Lint Code Base", "integration_id": 15368}])

    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])
    monkeypatch.setattr(sgr, "fetch_ruleset_json", lambda **_kwargs: live)

    exit_code = sgr.run_validate_contexts(repo="o/r", ruleset_id=1, contexts_file=ctx_file)
    assert exit_code == 0
    assert "match" in capsys.readouterr().out.lower()


def test_run_validate_contexts_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(
        ctx_file,
        [
            {"context": "Lint Code Base", "integration_id": 15368},
            {"context": "Run Tests", "integration_id": 99999},
        ],
    )

    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])
    monkeypatch.setattr(sgr, "fetch_ruleset_json", lambda **_kwargs: live)

    exit_code = sgr.run_validate_contexts(repo="o/r", ruleset_id=1, contexts_file=ctx_file)
    assert exit_code == 2
    assert "drift" in capsys.readouterr().out.lower()


def test_run_validate_contexts_integration_id_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(ctx_file, [{"context": "Lint Code Base", "integration_id": 99999}])

    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])
    monkeypatch.setattr(sgr, "fetch_ruleset_json", lambda **_kwargs: live)

    exit_code = sgr.run_validate_contexts(repo="o/r", ruleset_id=1, contexts_file=ctx_file)
    assert exit_code == 2
    assert "drift" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# run_apply_contexts
# ---------------------------------------------------------------------------


def test_run_apply_contexts_already_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(ctx_file, [{"context": "Lint Code Base", "integration_id": 15368}])

    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])
    monkeypatch.setattr(sgr, "fetch_ruleset_json", lambda **_kwargs: live)

    sgr.run_apply_contexts(repo="o/r", ruleset_id=1, contexts_file=ctx_file)
    assert "already match" in capsys.readouterr().out.lower()


def test_run_apply_contexts_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(
        ctx_file,
        [
            {"context": "Lint Code Base", "integration_id": 15368},
            {"context": "Run Tests", "integration_id": 99999},
        ],
    )

    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])
    monkeypatch.setattr(sgr, "fetch_ruleset_json", lambda **_kwargs: live)

    sgr.run_apply_contexts(repo="o/r", ruleset_id=1, contexts_file=ctx_file, dry_run=True)
    output = capsys.readouterr().out
    assert "dry-run" in output.lower()
    assert "+ Run Tests" in output


def test_run_apply_contexts_confirm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ctx_file = tmp_path / "required-contexts.yml"
    _write_contexts_yaml(
        ctx_file,
        [
            {"context": "Lint Code Base", "integration_id": 15368},
            {"context": "Run Tests", "integration_id": 99999},
        ],
    )

    live = _make_live_ruleset([{"context": "Lint Code Base", "integration_id": 15368}])
    monkeypatch.setattr(sgr, "fetch_ruleset_json", lambda **_kwargs: live)
    monkeypatch.setattr(sgr, "_run_with_input", lambda *_args, **_kwargs: '{"id": 1}')

    sgr.run_apply_contexts(repo="o/r", ruleset_id=1, contexts_file=ctx_file, dry_run=False)
    assert "Applied" in capsys.readouterr().out
