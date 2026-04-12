from __future__ import annotations

from pathlib import Path

from scripts.linting.check_short_identifier_names import (
    _is_in_skipped_dir,
    _is_too_short,
    _iter_python_files,
    find_violations,
    main,
)


def test_find_violations_flags_short_function_param(tmp_path: Path) -> None:
    py_file = tmp_path / "bad_param.py"
    py_file.write_text(
        """
def example(x):
    return x
""".lstrip(),
        encoding="utf-8",
    )

    offenders = find_violations([py_file], min_length=3)
    assert len(offenders) == 1
    assert {offender.kind for offender in offenders} == {"param"}
    assert {offender.name for offender in offenders} == {"x"}


def test_main_reports_fail_on_short_identifier(tmp_path: Path) -> None:
    py_file = tmp_path / "bad.py"
    py_file.write_text(
        """
def example(x):
    return x
""".lstrip(),
        encoding="utf-8",
    )
    result_code = main([str(py_file)])
    assert result_code == 1


def test_main_reports_pass_when_no_findings(tmp_path: Path) -> None:
    py_file = tmp_path / "good.py"
    py_file.write_text(
        """
def example(value):
    return value
""".lstrip(),
        encoding="utf-8",
    )

    result_code = main([str(py_file)])
    assert result_code == 0


def test_is_too_short_approved_names() -> None:
    assert _is_too_short("_", min_length=3) is False
    assert _is_too_short("f", min_length=3) is False
    assert _is_too_short("i", min_length=3) is False
    assert _is_too_short("pr", min_length=3) is False


def test_is_too_short_strips_leading_underscores() -> None:
    # Leading underscores are convention markers, not semantic content.
    # The check should measure only the non-underscore suffix.
    assert _is_too_short("_key", min_length=3) is False  # "key" = 3 chars
    assert _is_too_short("__key", min_length=3) is False  # "key" = 3 chars
    assert _is_too_short("_k", min_length=3) is True  # "k" = 1 char
    assert _is_too_short("__k", min_length=3) is True  # "k" = 1 char
    assert _is_too_short("__", min_length=3) is False  # all underscores = unused convention


def test_is_in_skipped_dir() -> None:
    assert _is_in_skipped_dir(Path(".venv/lib/foo.py")) is True
    assert _is_in_skipped_dir(Path("scripts/ci/main.py")) is False


def test_iter_python_files_directory(tmp_path: Path) -> None:
    py_file = tmp_path / "module.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    venv_dir = tmp_path / ".venv"
    venv_dir.mkdir()
    venv_file = venv_dir / "skip.py"
    venv_file.write_text("x = 1\n", encoding="utf-8")
    result = list(_iter_python_files([tmp_path]))
    assert len(result) == 1
    assert result[0].name == "module.py"


def test_iter_python_files_non_py(tmp_path: Path) -> None:
    txt_file = tmp_path / "data.txt"
    txt_file.write_text("text", encoding="utf-8")
    result = list(_iter_python_files([txt_file]))
    assert result == []


def test_find_violations_assignment(tmp_path: Path) -> None:
    py_file = tmp_path / "assign.py"
    py_file.write_text("ab = 1\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "assign" for finding in findings)


def test_find_violations_annotated_assignment(tmp_path: Path) -> None:
    py_file = tmp_path / "ann.py"
    py_file.write_text("ab: int = 1\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "annassign" for finding in findings)


def test_find_violations_augmented_assignment(tmp_path: Path) -> None:
    py_file = tmp_path / "aug.py"
    py_file.write_text("ab = 0\nab += 1\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "augassign" for finding in findings)


def test_find_violations_for_loop(tmp_path: Path) -> None:
    py_file = tmp_path / "loop.py"
    py_file.write_text("for ab in [1, 2]:\n    pass\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "for" for finding in findings)


def test_find_violations_async_for(tmp_path: Path) -> None:
    py_file = tmp_path / "aloop.py"
    py_file.write_text("import asyncio\nasync def f():\n    async for ab in []:\n        pass\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "asyncfor" for finding in findings)


def test_find_violations_with_statement(tmp_path: Path) -> None:
    py_file = tmp_path / "ctx.py"
    py_file.write_text("with open('f') as ab:\n    pass\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "with" for finding in findings)


def test_find_violations_async_with(tmp_path: Path) -> None:
    py_file = tmp_path / "actx.py"
    py_file.write_text(
        "import asyncio\nasync def f():\n    async with open('f') as ab:\n        pass\n",
        encoding="utf-8",
    )
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "asyncwith" for finding in findings)


def test_find_violations_except_handler(tmp_path: Path) -> None:
    py_file = tmp_path / "exc.py"
    py_file.write_text("try:\n    pass\nexcept Exception as ab:\n    pass\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "except" for finding in findings)


def test_find_violations_comprehension(tmp_path: Path) -> None:
    py_file = tmp_path / "comp.py"
    py_file.write_text("result = [ab for ab in [1, 2]]\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "comprehension" for finding in findings)


def test_find_violations_named_expr(tmp_path: Path) -> None:
    py_file = tmp_path / "walrus.py"
    py_file.write_text("if (ab := 1) > 0:\n    pass\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "namedexpr" for finding in findings)


def test_find_violations_lambda(tmp_path: Path) -> None:
    py_file = tmp_path / "lam.py"
    py_file.write_text("fn = lambda ab: ab + 1\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "param" for finding in findings)


def test_find_violations_async_function(tmp_path: Path) -> None:
    py_file = tmp_path / "afn.py"
    py_file.write_text("async def example(ab):\n    pass\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "param" for finding in findings)


def test_find_violations_import_as(tmp_path: Path) -> None:
    py_file = tmp_path / "imp.py"
    py_file.write_text("import os as ab\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "import-as" for finding in findings)


def test_find_violations_from_import_as(tmp_path: Path) -> None:
    py_file = tmp_path / "fimp.py"
    py_file.write_text("from os import path as ab\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "from-import-as" for finding in findings)


def test_find_violations_tuple_unpacking(tmp_path: Path) -> None:
    py_file = tmp_path / "unpack.py"
    py_file.write_text("ab, cd = 1, 2\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert len(findings) == 2


def test_find_violations_match_case(tmp_path: Path) -> None:
    py_file = tmp_path / "mtch.py"
    py_file.write_text("match 1:\n    case ab:\n        pass\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "match" for finding in findings)


def test_find_violations_match_mapping_rest(tmp_path: Path) -> None:
    py_file = tmp_path / "mmap.py"
    py_file.write_text(
        "match {'a': 1}:\n    case {'a': 1, **ab}:\n        pass\n",
        encoding="utf-8",
    )
    findings = find_violations([py_file], min_length=3)
    assert any(finding.kind == "match" and finding.name == "ab" for finding in findings)


def test_find_violations_syntax_error(tmp_path: Path) -> None:
    py_file = tmp_path / "broken.py"
    py_file.write_text("def f(\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert findings == []


def test_find_violations_vararg_kwarg(tmp_path: Path) -> None:
    py_file = tmp_path / "varkw.py"
    py_file.write_text("def f(*ab, **cd):\n    pass\n", encoding="utf-8")
    findings = find_violations([py_file], min_length=3)
    assert len(findings) == 2


def test_main_json_output(tmp_path: Path) -> None:
    py_file = tmp_path / "code.py"
    py_file.write_text("ab = 1\n", encoding="utf-8")
    code = main(["--json", str(py_file)])
    assert code == 1


def test_main_json_no_findings(tmp_path: Path) -> None:
    py_file = tmp_path / "code.py"
    py_file.write_text("result = 1\n", encoding="utf-8")
    code = main(["--json", str(py_file)])
    assert code == 0
