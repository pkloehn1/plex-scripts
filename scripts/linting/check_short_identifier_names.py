#!/usr/bin/env python3

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_MIN_LENGTH = 3

# Domain-standard abbreviations that are universally understood in this
# codebase and would lose clarity if expanded (e.g. "pr" → "pull_request"
# makes dataclass fields and JSON keys needlessly verbose).
# "_" is Python convention (PEP 8) for intentionally unused variables.
_APPROVED_SHORT_NAMES: frozenset[str] = frozenset(
    {
        "_",
        "f",  # file handle (Python convention: `with open(...) as f`)
        "i",  # loop index (Python convention: `for i, x in enumerate(...)`)
        "pr",
        "q1",  # first quartile (statistics)
        "q3",  # third quartile (statistics)
    }
)

_SKIP_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    name: str
    kind: str


def _as_path(value: str) -> Path:
    return Path(value)


def _is_in_skipped_dir(path: Path) -> bool:
    return any(part in _SKIP_DIR_NAMES for part in path.parts)


def _iter_python_files_in_dir(root: Path) -> Iterable[Path]:
    for py_file in root.rglob("*.py"):
        if not _is_in_skipped_dir(py_file):
            yield py_file


def _iter_python_files(paths: list[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            if not _is_in_skipped_dir(path):
                yield path
        elif path.is_dir():
            yield from _iter_python_files_in_dir(path)


def _is_too_short(name: str, *, min_length: int) -> bool:
    if name in _APPROVED_SHORT_NAMES:
        return False
    stripped = name.lstrip("_")
    if not stripped:
        return False
    return len(stripped) < min_length


def _iter_name_targets(target: ast.AST) -> Iterable[tuple[str, int]]:
    if isinstance(target, ast.Name):
        yield target.id, target.lineno
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _iter_name_targets(elt)


def _iter_function_param_names(node: ast.arguments) -> Iterable[tuple[str, int]]:
    for arg in list(node.posonlyargs) + list(node.args) + list(node.kwonlyargs):
        yield arg.arg, arg.lineno

    if node.vararg is not None:
        yield node.vararg.arg, node.vararg.lineno

    if node.kwarg is not None:
        yield node.kwarg.arg, node.kwarg.lineno


def _iter_match_capture_names(pattern: ast.AST) -> Iterable[tuple[str, int]]:
    for node in ast.walk(pattern):
        if (isinstance(node, ast.MatchAs) and node.name is not None) or (
            isinstance(node, ast.MatchStar) and node.name is not None
        ):
            yield node.name, node.lineno
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            yield node.rest, node.lineno


class _ShortIdentifierVisitor(ast.NodeVisitor):
    def __init__(self, *, path: Path, min_length: int) -> None:
        self._path = path
        self._min_length = min_length
        self.findings: list[Finding] = []

    def _record(self, *, lineno: int, name: str, kind: str) -> None:
        if _is_too_short(name, min_length=self._min_length):
            self.findings.append(Finding(path=self._path, line=lineno, name=name, kind=kind))

    def _record_targets(self, *, target: ast.AST, kind: str) -> None:
        for name, lineno in _iter_name_targets(target):
            self._record(lineno=lineno, name=name, kind=kind)

    def _record_params(self, args: ast.arguments) -> None:
        for name, lineno in _iter_function_param_names(args):
            self._record(lineno=lineno, name=name, kind="param")

    def _visit_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda) -> None:
        self._record_params(node.args)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_callable(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._record_targets(target=target, kind="assign")
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._record_targets(target=node.target, kind="annassign")
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._record_targets(target=node.target, kind="augassign")
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self._record_targets(target=node.target, kind="for")
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._record_targets(target=node.target, kind="asyncfor")
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._record_targets(target=item.optional_vars, kind="with")
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._record_targets(target=item.optional_vars, kind="asyncwith")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self._record(lineno=node.lineno, name=node.name, kind="except")
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self._record_targets(target=node.target, kind="comprehension")
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self._record_targets(target=node.target, kind="namedexpr")
        self.generic_visit(node)

    def visit_match_case(self, node: ast.match_case) -> None:
        for name, lineno in _iter_match_capture_names(node.pattern):
            self._record(lineno=lineno, name=name, kind="match")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.asname is not None:
                self._record(lineno=node.lineno, name=alias.asname, kind="import-as")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.asname is not None:
                self._record(lineno=node.lineno, name=alias.asname, kind="from-import-as")
        self.generic_visit(node)


def _find_violations_in_tree(*, tree: ast.AST, path: Path, min_length: int) -> list[Finding]:
    visitor = _ShortIdentifierVisitor(
        path=path,
        min_length=min_length,
    )
    visitor.visit(tree)
    return visitor.findings


def find_violations(paths: list[Path], *, min_length: int) -> list[Finding]:
    findings: list[Finding] = []

    for py_file in _iter_python_files(paths):
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError:
            continue

        findings.extend(
            _find_violations_in_tree(
                tree=tree,
                path=py_file,
                min_length=min_length,
            )
        )

    return sorted(
        findings,
        key=lambda finding: (
            str(finding.path),
            finding.line,
            finding.name,
            finding.kind,
        ),
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail on short identifier names (< min length).",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=_DEFAULT_MIN_LENGTH,
        help=f"Minimum identifier length (default: {_DEFAULT_MIN_LENGTH}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output.",
    )
    parser.add_argument("paths", nargs="*", type=_as_path, default=[Path(".")])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv_list = sys.argv[1:] if argv is None else argv
    args = _parse_args(argv_list)

    findings = find_violations(
        list(args.paths),
        min_length=int(args.min_length),
    )

    if args.json:
        payload = {
            "min_length": int(args.min_length),
            "total_findings": len(findings),
            "findings": [
                {
                    "file": str(finding.path),
                    "line": int(finding.line),
                    "kind": finding.kind,
                    "name": finding.name,
                }
                for finding in findings
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not findings else 1

    if not findings:
        print(f"PASS: short identifier names min_length={args.min_length} total_findings=0")
        return 0

    print("Findings (all):")
    for finding in findings:
        print(f"- file={finding.path} line={finding.line} kind={finding.kind} name={finding.name}")

    print(f"FAIL: short identifier names min_length={args.min_length} findings={len(findings)}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
