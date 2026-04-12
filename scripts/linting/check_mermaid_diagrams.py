#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    code: str
    message: str


def _as_path(value: str) -> Path:
    return Path(value)


def _iter_mermaid_blocks(lines: list[str]) -> Iterable[tuple[int, list[str]]]:
    """Yield (start_line_number_1_based, block_lines)."""
    in_block = False
    block_start = 0
    block: list[str] = []

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")

        if not in_block:
            if line.strip() == "```mermaid":
                in_block = True
                block_start = idx
                block = []
            continue

        # In a mermaid block.
        if line.strip() == "```":
            in_block = False
            yield block_start, block
            block_start = 0
            block = []
            continue

        block.append(line)


def _iter_square_bracket_labels(line: str) -> Iterable[str]:
    """Return each node label payload found inside [...] on the line.

    Mermaid flowcharts use node labels like: nodeId[Some text].
    This does not attempt to fully parse Mermaid; it only extracts simple
    square-bracket labels to enforce GitHub-render-safe text.
    """
    idx = 0
    while True:
        start = line.find("[", idx)
        if start == -1:
            return
        end = line.find("]", start + 1)
        if end == -1:
            return

        yield line[start + 1 : end]
        idx = end + 1


def _label_findings(*, path: Path, line: int, label_text: str) -> list[Finding]:
    findings: list[Finding] = []

    if "{" in label_text or "}" in label_text:
        findings.append(
            Finding(
                path=path,
                line=line,
                code="MERMAID001",
                message=(
                    "Curly braces inside Mermaid node labels break GitHub rendering. "
                    "Avoid placeholders like {owner}/{repo}; move them into surrounding prose."
                ),
            )
        )

    if "(" in label_text or ")" in label_text:
        findings.append(
            Finding(
                path=path,
                line=line,
                code="MERMAID002",
                message=(
                    "Parentheses inside Mermaid node labels can break GitHub rendering. "
                    "Prefer plain text without ( ... ) in labels."
                ),
            )
        )

    if "/" in label_text:
        findings.append(
            Finding(
                path=path,
                line=line,
                code="MERMAID003",
                message=(
                    "Slash-delimited paths inside Mermaid node labels can break GitHub rendering. "
                    "Prefer short labels (e.g., 'REST: list PR comments') and document endpoints in prose."
                ),
            )
        )

    return findings


def find_mermaid_render_findings(*, path: Path) -> list[Finding]:
    """Lint Mermaid blocks for GitHub renderer pitfalls.

    GitHub's Mermaid renderer is stricter than many local renderers. This linter
    enforces a conservative subset for flowchart node labels (text inside [...]).

    Findings are only emitted for content inside ```mermaid fences.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except OSError as exc:
        return [
            Finding(
                path=path,
                line=1,
                code="MERMAID000",
                message=f"Unable to read file: {exc}",
            )
        ]

    findings: list[Finding] = []

    for block_start, block_lines in _iter_mermaid_blocks(lines):
        for offset, raw in enumerate(block_lines, start=1):
            file_line = block_start + offset
            for label_text in _iter_square_bracket_labels(raw):
                findings.extend(_label_findings(path=path, line=file_line, label_text=label_text))

    return findings


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Lint Mermaid diagrams in Markdown for GitHub-render compatibility "
            "(conservative checks for flowchart node labels)."
        )
    )
    parser.add_argument("paths", nargs="+", type=_as_path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    all_findings: list[Finding] = []
    for path in args.paths:
        if path.is_dir():
            for markdown_file in path.rglob("*.md"):
                all_findings.extend(find_mermaid_render_findings(path=markdown_file))
        else:
            all_findings.extend(find_mermaid_render_findings(path=path))

    if not all_findings:
        return 0

    for finding in all_findings:
        print(f"{finding.path}:{finding.line}: {finding.code} {finding.message}")

    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
