from __future__ import annotations

import pytest

from scripts.inventory.inventory_types import HostRunStatus
from scripts.inventory.reporting import (
    Progress,
    _clip_table_cell,
    print_all_hosts_status_report,
    render_aligned_table,
)


def test_clip_table_cell_width_zero_returns_empty() -> None:
    assert _clip_table_cell("hello", 0) == ""


def test_clip_table_cell_width_negative_returns_empty() -> None:
    assert _clip_table_cell("hello", -5) == ""


def test_clip_table_cell_width_one_returns_first_char() -> None:
    assert _clip_table_cell("hello", 1) == "h"


def test_clip_table_cell_width_one_empty_string() -> None:
    assert _clip_table_cell("", 1) == ""


def test_clip_table_cell_exact_fit() -> None:
    assert _clip_table_cell("hello", 5) == "hello"


def test_clip_table_cell_truncates_with_ellipsis() -> None:
    result = _clip_table_cell("hello world", 8)
    assert result == "hello w\u2026"
    assert len(result) == 8


def test_render_aligned_table_shrinks_last_column_when_too_wide() -> None:
    headers = ["Col1", "Col2", "Message"]
    rows = [["aaa", "bbb", "x" * 200]]
    lines = render_aligned_table(headers, rows, max_total_width=30)
    assert len(lines) >= 2
    for line in lines:
        assert len(line) <= 30 + 5  # allow minor rounding; last col capped


def test_render_aligned_table_basic() -> None:
    headers = ["Name", "Value"]
    rows = [["foo", "bar"]]
    lines = render_aligned_table(headers, rows, max_total_width=120)
    assert lines[0].startswith("Name")
    assert "Value" in lines[0]
    assert "foo" in lines[2]
    assert "bar" in lines[2]


def test_print_all_hosts_status_report_error_code_without_detail(capsys: pytest.CaptureFixture[str]) -> None:
    statuses = [
        HostRunStatus(
            hostname="node-a",
            responded=False,
            all_steps_completed=False,
            error_code="INV-SSH-ALIVE-FAILED",
            error_detail="",
        )
    ]
    print_all_hosts_status_report(statuses, report_completed=False, docs_completed=False)
    output = capsys.readouterr().out
    assert "INV-SSH-ALIVE-FAILED" in output
    assert "Error lookup" in output


def test_print_all_hosts_status_report_error_code_with_detail(capsys: pytest.CaptureFixture[str]) -> None:
    statuses = [
        HostRunStatus(
            hostname="node-b",
            responded=True,
            all_steps_completed=False,
            error_code="INV-SSH-CMD-FAILED",
            error_detail="Connection refused",
        )
    ]
    print_all_hosts_status_report(statuses, report_completed=False, docs_completed=False)
    output = capsys.readouterr().out
    assert "INV-SSH-CMD-FAILED" in output


def test_print_all_hosts_status_report_no_errors(capsys: pytest.CaptureFixture[str]) -> None:
    statuses = [
        HostRunStatus(
            hostname="node-c",
            responded=True,
            all_steps_completed=True,
            error_code=None,
            error_detail=None,
        )
    ]
    print_all_hosts_status_report(statuses, report_completed=True, docs_completed=True)
    output = capsys.readouterr().out
    assert "Overall status report" in output
    assert "Error lookup" not in output


def test_progress_advance_disabled_does_not_write(capsys: pytest.CaptureFixture[str]) -> None:
    prog = Progress(steps=["a", "b"], enabled=False)
    prog.advance("a")
    assert capsys.readouterr().out == ""
