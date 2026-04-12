#!/usr/bin/env python3

"""Cognitive Complexity checker aligned with SonarSource guidance.

See docs/repository-standards/cognitive-complexity-guide.md
for Appendix A (counting rules) and Appendix B (Python specifics).
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

SUMMARY_PREFIX_PASS = "PASS"
SUMMARY_PREFIX_FAIL = "FAIL"


EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_USAGE = 2


@dataclass(frozen=True)
class FunctionComplexity:
    path: Path
    qualified_name: str
    lineno: int
    complexity: int


class _CognitiveComplexity(ast.NodeVisitor):
    def __init__(self, *, function_name: str | None = None) -> None:
        self.score = 0
        self.nesting = 0
        self._function_name = function_name
        self._recursion_recorded = False

    def _skip_nested_callable(self) -> None:
        # Do not count nested callables toward the parent.
        return

    def _add_control_flow(self) -> None:
        self.score += 1 + self.nesting

    def _with_nesting(self, nesting: int, nodes: list[ast.stmt]) -> None:
        old = self.nesting
        self.nesting = nesting
        try:
            for stmt in nodes:
                self.visit(stmt)
        finally:
            self.nesting = old

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._skip_nested_callable()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._skip_nested_callable()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._skip_nested_callable()

    def visit_If(self, node: ast.If) -> None:
        self._add_control_flow()

        # Count boolean operators inside the condition.
        self.visit(node.test)

        self._with_nesting(self.nesting + 1, node.body)

        if not node.orelse:
            return

        # Treat `elif` as a peer branch (no additional nesting).
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            self.visit(node.orelse[0])
        else:
            # Sonar counts `else` as a branch (+1), but not as additional nesting.
            self.score += 1
            self._with_nesting(self.nesting + 1, node.orelse)

    def visit_For(self, node: ast.For) -> None:
        self._visit_loop(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_loop(node)

    def visit_While(self, node: ast.While) -> None:
        self._visit_loop(node)

    def _visit_loop(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        self._add_control_flow()
        if isinstance(node, ast.While):
            self.visit(node.test)
        self._with_nesting(self.nesting + 1, node.body)
        self._with_nesting(self.nesting + 1, node.orelse)

    def visit_Try(self, node: ast.Try) -> None:
        # Per SonarSource spec Appendix B: try is NOT a control flow
        # increment and does NOT increase nesting. Only catch increments.
        self._with_nesting(self.nesting, node.body)

        for handler in node.handlers:
            self._add_control_flow()
            self._with_nesting(self.nesting + 1, handler.body)

        self._with_nesting(self.nesting, node.orelse)
        self._with_nesting(self.nesting, node.finalbody)

    def visit_Match(self, node: ast.Match) -> None:
        self._add_control_flow()
        # Each case body counts as a nested branch.
        for case in node.cases:
            self._with_nesting(self.nesting + 1, case.body)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # Per SonarSource spec: +1 per sequence of like boolean operators.
        # Each BoolOp AST node = one sequence (a and b and c => +1).
        self.score += 1
        # Mixed operators: nested BoolOp with a different operator type adds +1.
        child_boolops = [val for val in node.values if isinstance(val, ast.BoolOp)]
        for child in child_boolops:
            if type(child.op) is not type(node.op):
                self.score += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._add_control_flow()
        self.generic_visit(node)

    def _is_recursive_call(self, node: ast.Call) -> bool:
        if not self._function_name:
            return False
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == self._function_name
        if isinstance(func, ast.Attribute):
            return func.attr == self._function_name
        return False

    def visit_Call(self, node: ast.Call) -> None:
        if not self._recursion_recorded and self._is_recursive_call(node):
            self.score += 1
            self._recursion_recorded = True
        self.generic_visit(node)

    def visit_Break(self, node: ast.Break) -> None:
        return None

    def visit_Continue(self, node: ast.Continue) -> None:
        return None


class _QualifiedFunctionCollector(ast.NodeVisitor):
    def __init__(self, *, path: Path) -> None:
        self._path = path
        self._stack: list[str] = []
        self.functions: list[FunctionComplexity] = []

    def _qualified_name(self, name: str) -> str:
        if not self._stack:
            return name
        return ".".join([*self._stack, name])

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._stack.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_any_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_any_function(node)

    def _visit_any_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._record_function(node)
        self._stack.append(node.name)
        try:
            # Traverse to find nested functions (recorded separately).
            self.generic_visit(node)
        finally:
            self._stack.pop()

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        visitor = _CognitiveComplexity(function_name=node.name)
        visitor._with_nesting(0, node.body)
        self.functions.append(
            FunctionComplexity(
                path=self._path,
                qualified_name=self._qualified_name(node.name),
                lineno=getattr(node, "lineno", 1),
                complexity=visitor.score,
            )
        )


def analyze_python_file(path: Path) -> list[FunctionComplexity]:
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source, filename=str(path))
    collector = _QualifiedFunctionCollector(path=path)
    collector.visit(module)
    return collector.functions


def find_violations(paths: list[Path], *, max_complexity: int) -> list[FunctionComplexity]:
    offenders: list[FunctionComplexity] = []
    for path in paths:
        if path.suffix != ".py":
            continue

        try:
            functions = analyze_python_file(path)
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            offenders.append(
                FunctionComplexity(
                    path=path,
                    qualified_name="<parse-error>",
                    lineno=getattr(exc, "lineno", 1) or 1,
                    complexity=max_complexity + 1,
                )
            )
            continue

        for func in functions:
            if func.complexity > max_complexity:
                offenders.append(func)
    offenders.sort(key=lambda item: (str(item.path), item.lineno, item.qualified_name))
    return offenders


def _format_summary(*, passed: bool, threshold: int, files: int, findings: int) -> str:
    prefix = SUMMARY_PREFIX_PASS if passed else SUMMARY_PREFIX_FAIL
    status = "within" if passed else "exceeded"
    return f"{prefix}: cognitive complexity {status} threshold={threshold}. files={files} findings={findings}"


def _print_findings(*, offenders: list[FunctionComplexity], threshold: int) -> None:
    print("\nFindings:")
    for idx, func in enumerate(offenders, 1):
        over_by = func.complexity - threshold
        print(
            f"{idx}. file={func.path} line={func.lineno} function={func.qualified_name} "
            f"complexity={func.complexity} threshold={threshold} over_by={over_by}"
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail if any Python function exceeds a cognitive complexity threshold."
    )
    parser.add_argument(
        "--max",
        type=int,
        default=15,
        help="Maximum allowed cognitive complexity per function (default: 15)",
    )
    parser.add_argument("paths", nargs="*", help="Python files to analyze")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    max_complexity = args.max
    if max_complexity <= 0:
        print("--max must be a positive integer", file=sys.stderr)
        return EXIT_USAGE

    paths = [Path(arg) for arg in args.paths]
    paths = [path for path in paths if path.is_file()]
    if not paths:
        return EXIT_OK

    offenders = find_violations(paths, max_complexity=max_complexity)
    if not offenders:
        print(
            _format_summary(
                passed=True,
                threshold=max_complexity,
                files=len(paths),
                findings=0,
            )
        )
        return EXIT_OK

    print(
        _format_summary(
            passed=False,
            threshold=max_complexity,
            files=len(paths),
            findings=len(offenders),
        ),
        file=sys.stderr,
    )
    print(
        "Cognitive complexity limit exceeded. Refactor to reduce branching/nesting.",
        file=sys.stderr,
    )
    _print_findings(offenders=offenders, threshold=max_complexity)

    return EXIT_VIOLATION


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
