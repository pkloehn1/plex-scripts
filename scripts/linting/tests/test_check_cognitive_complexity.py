from __future__ import annotations

from pathlib import Path

from scripts.linting.check_cognitive_complexity import (
    _CognitiveComplexity,
    analyze_python_file,
    find_violations,
    main,
)


def test_find_violations_returns_empty_for_simple_function(tmp_path: Path) -> None:
    src = tmp_path / "simple.py"
    src.write_text(
        """
def f():
    return 1
""".lstrip(),
        encoding="utf-8",
    )

    assert find_violations([src], max_complexity=1) == []


def test_find_violations_flags_nested_branching(tmp_path: Path) -> None:
    src = tmp_path / "complex.py"
    src.write_text(
        """
def f(x):
    if x:
        if x > 1:
            return 1
        return 0
    return -1
""".lstrip(),
        encoding="utf-8",
    )

    offenders = find_violations([src], max_complexity=2)
    assert len(offenders) == 1
    assert offenders[0].qualified_name == "f"
    assert offenders[0].path.name == "complex.py"
    assert offenders[0].complexity > 2


def test_find_violations_counts_boolean_ops(tmp_path: Path) -> None:
    src = tmp_path / "bools.py"
    src.write_text(
        """
def f(a, b, c):
    if a and b and c:
        return True
    return False
""".lstrip(),
        encoding="utf-8",
    )

    # Per SonarSource spec: if(+1) + one bool sequence(+1) = 2
    offenders = find_violations([src], max_complexity=1)
    assert len(offenders) == 1
    assert offenders[0].qualified_name == "f"
    assert offenders[0].complexity == 2


def test_main_reports_pass_summary(capsys: object, tmp_path: Path) -> None:
    src = tmp_path / "ok.py"
    src.write_text(
        """
def f():
    return 1
""".lstrip(),
        encoding="utf-8",
    )

    ret = main(["--max", "15", str(src)])
    captured = capsys.readouterr()  # type: ignore[attr-defined]

    assert ret == 0
    assert "PASS:" in captured.out
    assert "threshold=15" in captured.out
    assert "findings=0" in captured.out


def test_recursion_counted_once(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def rec(n):
    if n <= 0:
        return 0
    return rec(n - 1)
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert len(funcs) == 1
    # if => +1, recursion => +1
    assert funcs[0].complexity == 2


def test_context_manager_not_counted(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def read_first(path):
    with open(path) as fh:
        return fh.readline()
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert funcs[0].complexity == 0


def test_loop_and_branch_without_break_penalty(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def find_positive(items):
    for value in items:
        if value > 0:
            break
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert funcs[0].complexity == 3  # loop (+1) + nested if (+2)


def test_try_not_counted_catch_increments(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f():
    try:
        pass
    except ValueError:
        pass
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    # Per SonarSource spec: try adds nothing, catch(except) adds +1
    assert funcs[0].complexity == 1


def test_try_does_not_increase_nesting(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f(x):
    try:
        if x:
            pass
    except ValueError:
        pass
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    # if inside try: if(+1, nesting=0) = 1; catch: +1 = total 2
    # try does NOT add nesting, so if is at nesting level 0
    assert funcs[0].complexity == 2


def test_bool_sequence_counts_once(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f(a, b, c, d):
    if a and b and c and d:
        pass
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    # Per SonarSource spec: if(+1) + one bool sequence(+1) = 2
    # NOT +3 for three 'and' operators
    assert funcs[0].complexity == 2


def test_mixed_bool_operators_add_extra(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f(a, b, c):
    if a and (b or c):
        pass
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    # if(+1) + outer 'and' sequence(+1) + inner 'or' sequence(+1)
    # + mixed operator penalty(+1) = 4
    assert funcs[0].complexity == 4


def test_nested_function_not_counted_in_parent(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def outer():
    def inner():
        if True:
            pass
    return inner
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert len(funcs) == 2
    outer = next(func for func in funcs if func.qualified_name == "outer")
    inner = next(func for func in funcs if func.qualified_name == "outer.inner")
    assert outer.complexity == 0
    assert inner.complexity == 1


def test_nested_async_function_not_counted_in_parent(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def outer():
    async def inner():
        pass
    return inner
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert len(funcs) == 2
    outer = next(func for func in funcs if func.qualified_name == "outer")
    assert outer.complexity == 0


def test_lambda_not_counted_in_parent(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def outer():
    fn = lambda x: x + 1
    return fn
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert len(funcs) == 1
    assert funcs[0].complexity == 0


def test_elif_counts_as_peer_branch(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    else:
        return 0
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    # if(+1) + elif(+1) + else(+1) = 3
    assert funcs[0].complexity == 3


def test_async_for_counted_as_loop(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
async def f(items):
    async for item in items:
        pass
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert funcs[0].complexity == 1


def test_while_loop_counted(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f():
    while True:
        break
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert funcs[0].complexity == 1


def test_match_statement_counted(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f(cmd):
    match cmd:
        case "start":
            pass
        case "stop":
            pass
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    # match(+1) + 2 case bodies at nesting+1 (no extra increment per case)
    assert funcs[0].complexity == 1


def test_ternary_expression_counted(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f(x):
    return 1 if x else 0
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert funcs[0].complexity == 1


def test_recursion_via_attribute_counted(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def traverse(node):
    if node.left:
        self.traverse(node.left)
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    # if(+1) + recursion(+1) = 2
    assert funcs[0].complexity == 2


def test_continue_not_counted(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f(items):
    for item in items:
        continue
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert funcs[0].complexity == 1


def test_class_method_qualified_name(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
class MyClass:
    def method(self):
        if True:
            pass
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    assert len(funcs) == 1
    assert funcs[0].qualified_name == "MyClass.method"
    assert funcs[0].complexity == 1


def test_is_recursive_call_without_function_name() -> None:
    import ast as _ast

    visitor = _CognitiveComplexity(function_name=None)
    call_node = _ast.Call(func=_ast.Name(id="foo", ctx=_ast.Load()), args=[], keywords=[])
    assert visitor._is_recursive_call(call_node) is False


def test_call_without_function_name_context(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def outer():
    def inner():
        print("hi")
    inner()
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    outer = next(func for func in funcs if func.qualified_name == "outer")
    # inner() is not recursion of outer, no increment
    assert outer.complexity == 0


def test_subscript_call_not_counted_as_recursion(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text(
        """
def f(handlers):
    handlers[0]()
""".lstrip(),
        encoding="utf-8",
    )
    funcs = analyze_python_file(src)
    # handlers[0]() is a Subscript call, not Name or Attribute — no recursion
    assert funcs[0].complexity == 0


def test_find_violations_skips_non_python(tmp_path: Path) -> None:
    src = tmp_path / "data.txt"
    src.write_text("not python", encoding="utf-8")
    assert find_violations([src], max_complexity=1) == []


def test_find_violations_handles_syntax_error(tmp_path: Path) -> None:
    src = tmp_path / "broken.py"
    src.write_text("def f(\n", encoding="utf-8")
    offenders = find_violations([src], max_complexity=5)
    assert len(offenders) == 1
    assert offenders[0].qualified_name == "<parse-error>"
    assert offenders[0].complexity == 6


def test_main_rejects_zero_max(capsys: object) -> None:
    ret = main(["--max", "0"])
    assert ret == 2
    assert "--max must be" in capsys.readouterr().err  # type: ignore[attr-defined]


def test_main_returns_ok_for_no_files() -> None:
    ret = main(["--max", "15"])
    assert ret == 0


def test_main_reports_fail_summary_and_findings(capsys: object, tmp_path: Path) -> None:
    src = tmp_path / "bad.py"
    src.write_text(
        """
def f(x):
    if x:
        if x > 1:
            return 1
        return 0
    return -1
""".lstrip(),
        encoding="utf-8",
    )

    ret = main(["--max", "2", str(src)])
    captured = capsys.readouterr()  # type: ignore[attr-defined]

    assert ret == 1
    assert "FAIL:" in captured.err
    assert "threshold=2" in captured.err
    assert "Findings:" in captured.out
    assert "file=" in captured.out
    assert str(src) in captured.out
    assert "function=f" in captured.out
