from __future__ import annotations

from pathlib import Path

from scripts.linting.check_bash_test_syntax import (
    _is_bash_script,
    _iter_paths_from_argv,
    find_disallowed_test_syntax,
    main,
)


def test_allows_double_bracket_conditionals(tmp_path: Path) -> None:
    script = tmp_path / "ok.sh"
    script.write_text(
        '#!/usr/bin/env bash\n\nif [[ -n "${FOO:-}" ]]; then\n  echo ok\nfi\n',
        encoding="utf-8",
    )

    assert find_disallowed_test_syntax(script) == []


def test_flags_single_bracket_in_command_substitution(tmp_path: Path) -> None:
    script = tmp_path / "bad.sh"
    script.write_text(
        '#!/usr/bin/env bash\n\nvalue=$([ -n "${FOO:-}" ] && echo true || echo false)\n',
        encoding="utf-8",
    )

    findings = find_disallowed_test_syntax(script)
    assert len(findings) == 1
    assert findings[0].line == 3


def test_does_not_enforce_for_posix_sh(tmp_path: Path) -> None:
    script = tmp_path / "posix.sh"
    script.write_text(
        '#!/bin/sh\n\nif [ -n "${FOO:-}" ]; then\n  echo ok\nfi\n',
        encoding="utf-8",
    )

    assert find_disallowed_test_syntax(script) == []


def test_is_bash_script_non_sh_file(tmp_path: Path) -> None:
    py_file = tmp_path / "script.py"
    py_file.write_text("print('hi')\n", encoding="utf-8")
    assert _is_bash_script(py_file) is False


def test_is_bash_script_empty_file(tmp_path: Path) -> None:
    script = tmp_path / "empty.sh"
    script.write_text("", encoding="utf-8")
    assert _is_bash_script(script) is True


def test_is_bash_script_no_shebang(tmp_path: Path) -> None:
    script = tmp_path / "no_shebang.sh"
    script.write_text("echo hello\n", encoding="utf-8")
    assert _is_bash_script(script) is True


def test_iter_paths_from_argv_with_args() -> None:
    result = _iter_paths_from_argv(["prog", "a.sh", "b.sh"])
    assert len(result) == 2


def test_main_with_findings(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    script = tmp_path / "bad.sh"
    script.write_text('#!/usr/bin/env bash\nif [ -n "$FOO" ]; then\n  echo ok\nfi\n', encoding="utf-8")
    code = main(["prog", str(script)])
    assert code == 1


def test_main_no_findings(tmp_path: Path) -> None:
    script = tmp_path / "ok.sh"
    script.write_text('#!/usr/bin/env bash\nif [[ -n "$FOO" ]]; then\n  echo ok\nfi\n', encoding="utf-8")
    code = main(["prog", str(script)])
    assert code == 0


def test_main_missing_file() -> None:
    code = main(["prog", "/nonexistent/file.sh"])
    assert code == 0


def test_main_no_args_globs_cwd(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.chdir(tmp_path)  # type: ignore[attr-defined]
    code = main(["prog"])
    assert code == 0
