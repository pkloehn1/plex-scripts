from __future__ import annotations

from pathlib import Path

from scripts.linting.check_mermaid_diagrams import (
    _as_path,
    _iter_square_bracket_labels,
    _parse_args,
    find_mermaid_render_findings,
    main,
)


def test_mermaid_linter_flags_curly_braces_in_node_labels(tmp_path: Path) -> None:
    markdown_file = tmp_path / "doc.md"
    markdown_file.write_text(
        """# Title

```mermaid
flowchart TD
    restList[REST: GET /repos/{owner}/{repo}/issues]
```
""",
        encoding="utf-8",
    )

    findings = find_mermaid_render_findings(path=markdown_file)
    assert any(finding.code == "MERMAID001" for finding in findings)


def test_mermaid_linter_flags_parentheses_and_slashes_like_github_errors(
    tmp_path: Path,
) -> None:
    markdown_file = tmp_path / "doc.md"
    markdown_file.write_text(
        """# Title

```mermaid
flowchart TD
    gqlResolve[GraphQL: mutation resolveReviewThread(threadId)]
    restList[REST: GET /repos/OWNER/REPO/pulls/PR_NUMBER/comments]
    restUser[REST: GET /user (default author filter)]
```
""",
        encoding="utf-8",
    )

    findings = find_mermaid_render_findings(path=markdown_file)
    codes = {finding.code for finding in findings}

    # Matches the common GitHub renderer failures seen in PR screenshots.
    assert "MERMAID002" in codes  # parentheses in label
    assert "MERMAID003" in codes  # slashes in label


def test_mermaid_linter_allows_simplified_labels(tmp_path: Path) -> None:
    markdown_file = tmp_path / "doc.md"
    markdown_file.write_text(
        """# Title

```mermaid
flowchart TD
    start([Start])
    stepA[REST: list PR review comments]
    stepB[GraphQL: resolve review thread]
    start --> stepA --> stepB
```
""",
        encoding="utf-8",
    )

    findings = find_mermaid_render_findings(path=markdown_file)
    assert findings == []


def test_as_path() -> None:
    result = _as_path("foo/bar.md")
    assert isinstance(result, Path)
    assert result.name == "bar.md"


def test_iter_square_bracket_labels_unclosed() -> None:
    result = list(_iter_square_bracket_labels("node[unclosed label"))
    assert result == []


def test_iter_square_bracket_labels_no_open() -> None:
    result = list(_iter_square_bracket_labels("no brackets here"))
    assert result == []


def test_find_mermaid_render_findings_unreadable(tmp_path: Path) -> None:
    missing = tmp_path / "missing.md"
    findings = find_mermaid_render_findings(path=missing)
    assert len(findings) == 1
    assert findings[0].code == "MERMAID000"


def test_parse_args() -> None:
    args = _parse_args(["file1.md", "file2.md"])
    assert len(args.paths) == 2


def test_main_no_findings(tmp_path: Path) -> None:
    md_file = tmp_path / "clean.md"
    md_file.write_text("# Title\n\nNo mermaid here.\n", encoding="utf-8")
    code = main([str(md_file)])
    assert code == 0


def test_main_with_findings(tmp_path: Path) -> None:
    md_file = tmp_path / "bad.md"
    md_file.write_text(
        "# Title\n\n```mermaid\nflowchart TD\n    node[{bad}]\n```\n",
        encoding="utf-8",
    )
    code = main([str(md_file)])
    assert code == 2


def test_main_with_directory(tmp_path: Path) -> None:
    md_file = tmp_path / "doc.md"
    md_file.write_text("# Title\n\nNo mermaid.\n", encoding="utf-8")
    code = main([str(tmp_path)])
    assert code == 0
