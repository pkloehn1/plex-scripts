from __future__ import annotations

import ast
from pathlib import Path


def _build_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


def _is_in_try(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.Try):
            return True
    return False


def _is_in_main(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.FunctionDef) and current.name == "main":
            return True
    return False


def _parse_args_calls_outside_try(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = _build_parent_map(tree)
    failures: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "parse_args"):
            continue
        if not _is_in_main(node, parents):
            continue
        if not _is_in_try(node, parents):
            failures.append((node.lineno, path.name))

    return failures


def test_parse_args_calls_are_guarded() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = repo_root / "scripts" / "github"
    failures: list[tuple[str, int]] = []
    for py_file in scripts_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        for lineno, _filename in _parse_args_calls_outside_try(py_file):
            failures.append((py_file.name, lineno))

    assert not failures, f"parse_args outside try in: {failures}"
