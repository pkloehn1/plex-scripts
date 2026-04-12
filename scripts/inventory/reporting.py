from __future__ import annotations

import re
import shutil
import sys

from scripts.inventory.inventory_types import HostRunStatus


class Progress:
    def __init__(self, steps: list[str], *, enabled: bool = True) -> None:
        self._steps = steps
        self._completed = 0
        self._enabled = enabled

    def banner(self) -> None:
        # Intentionally no-op.
        # The per-step progress lines are the single source of progress output.
        return

    def advance(self, current_step: str) -> None:
        if not self._enabled:
            return
        self._completed += 1
        total = len(self._steps)
        filled = round((self._completed / total) * 20)
        bar = "#" * filled + "-" * (20 - filled)
        percent = round((self._completed / total) * 100)
        sys.stdout.write(f"[{self._completed}/{total}] {current_step} [{bar}] {percent}%\n")
        sys.stdout.flush()


def _clean_table_cell(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clip_table_cell(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    return text[: width - 1] + "…"


def render_aligned_table(
    headers: list[str],
    rows: list[list[str]],
    *,
    max_total_width: int,
    max_col_widths: list[int] | None = None,
) -> list[str]:
    cleaned_headers = [_clean_table_cell(header) for header in headers]
    cleaned_rows = [[_clean_table_cell(col) for col in row] for row in rows]

    widths = [len(header) for header in cleaned_headers]
    for row in cleaned_rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    if max_col_widths is not None:
        widths = [min(widths[idx], max_col_widths[idx]) for idx in range(len(widths))]

    separator = "  "
    min_total = sum(widths) + len(separator) * (len(widths) - 1)

    # If we're too wide, shrink only the last column (usually the long message).
    if min_total > max_total_width and widths:
        other_total = (
            sum(widths[:-1]) + len(separator) * (len(widths) - 1) + 1  # at least one char for last column
        )
        widths[-1] = max(1, max_total_width - other_total)

    def fmt_row(values: list[str]) -> str:
        clipped = [_clip_table_cell(values[idx], widths[idx]) for idx in range(len(values))]
        padded = [clipped[idx].ljust(widths[idx]) for idx in range(len(values))]
        return separator.join(padded).rstrip()

    header_line = fmt_row(cleaned_headers)
    separator_line = separator.join("-" * width for width in widths).rstrip()

    lines = [header_line, separator_line]
    lines.extend(fmt_row(row) for row in cleaned_rows)
    return lines


def print_all_hosts_status_report(
    statuses: list[HostRunStatus], *, report_completed: bool, docs_completed: bool
) -> None:
    print("Overall status report")
    print("")

    # The per-node outcome table is the single source of truth for run results.
    del report_completed, docs_completed

    node_rows: list[list[str]] = []
    codes_seen: set[str] = set()
    for status in statuses:
        error_cell = ""
        if status.error_code is not None:
            codes_seen.add(status.error_code)
            detail = status.error_detail or ""
            if detail:
                error_cell = f"{status.error_code}: {detail}"
            else:
                error_cell = status.error_code
        node_rows.append(
            [
                status.hostname,
                "yes" if status.responded else "no",
                "yes" if status.all_steps_completed else "no",
                error_cell,
            ]
        )

    terminal_width = shutil.get_terminal_size(fallback=(120, 24)).columns
    for line in render_aligned_table(
        ["Hostname", "Responded", "Done", "Error"],
        node_rows,
        max_total_width=max(80, terminal_width),
        max_col_widths=[32, 9, 4, 999],
    ):
        print(line)

    if codes_seen:
        print("")
        print("Error lookup: docs/inventory/collector-error-codes.md")
        print("Codes seen: " + ", ".join(sorted(codes_seen)))
