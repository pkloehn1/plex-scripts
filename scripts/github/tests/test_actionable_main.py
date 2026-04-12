from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.gh_cli import (
    ActionableArgumentParser,
    CliOperationError,
    GhResult,
    GhRunner,
    run_actionable_main,
)


class _DummyRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
        self.calls.append(argv)
        return GhResult(stdout="", stderr="")


def test_run_actionable_main_success(monkeypatch, capsys) -> None:
    def build_parser() -> argparse.ArgumentParser:
        parser = ActionableArgumentParser()
        parser.add_argument("--foo", required=True)
        return parser

    def handler(args: argparse.Namespace, parser: argparse.ArgumentParser, runner: GhRunner) -> int:
        assert args.foo == "bar"
        assert isinstance(runner, _DummyRunner)
        assert isinstance(parser, argparse.ArgumentParser)
        return 0

    monkeypatch.setattr("sys.argv", ["prog", "--foo", "bar"])
    runner = _DummyRunner()
    exit_code = run_actionable_main(build_parser=build_parser, handler=handler, runner_factory=lambda: runner)
    assert exit_code == 0
    assert runner.calls == []
    out, err = capsys.readouterr()
    assert out == ""
    assert err == ""


def test_run_actionable_main_cli_operation_error(monkeypatch, capsys) -> None:
    def build_parser() -> argparse.ArgumentParser:
        parser = ActionableArgumentParser()
        parser.add_argument("--foo", required=True)
        return parser

    def handler(args: argparse.Namespace, _parser: argparse.ArgumentParser, _runner: GhRunner) -> int:
        raise CliOperationError("git log failed")

    monkeypatch.setattr("sys.argv", ["prog", "--foo", "bar"])
    exit_code = run_actionable_main(build_parser=build_parser, handler=handler, runner_factory=_DummyRunner)
    assert exit_code == 2
    out, err = capsys.readouterr()
    assert "git log failed" in out or "git log failed" in err


def test_run_actionable_main_unexpected_runtime_error_propagates(monkeypatch) -> None:
    def build_parser() -> argparse.ArgumentParser:
        parser = ActionableArgumentParser()
        parser.add_argument("--foo", required=True)
        return parser

    def handler(args: argparse.Namespace, _parser: argparse.ArgumentParser, _runner: GhRunner) -> int:
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr("sys.argv", ["prog", "--foo", "bar"])
    with pytest.raises(RuntimeError, match="unexpected bug"):
        run_actionable_main(build_parser=build_parser, handler=handler, runner_factory=_DummyRunner)


def test_run_actionable_main_json_error(monkeypatch, capsys) -> None:
    def build_parser() -> argparse.ArgumentParser:
        parser = ActionableArgumentParser()
        parser.add_argument("--foo", required=True)
        parser.add_argument("--json", action="store_true")
        return parser

    def handler(args: argparse.Namespace, _parser: argparse.ArgumentParser, _runner: GhRunner) -> int:
        raise ValueError("boom")

    monkeypatch.setattr("sys.argv", ["prog", "--foo", "bar", "--json"])
    exit_code = run_actionable_main(build_parser=build_parser, handler=handler, runner_factory=_DummyRunner)
    assert exit_code == 2
    out, err = capsys.readouterr()
    assert json.loads(out) == {"ok": False, "error": "boom"}
    assert err == ""
