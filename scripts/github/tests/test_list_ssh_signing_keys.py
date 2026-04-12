"""Tests for list_ssh_signing_keys module."""

from __future__ import annotations

import argparse
import json

import pytest

from scripts.github.conftest import ExpectedCall, QueueRunner
from scripts.github.gh_cli import GhCliError, GhResult
from scripts.github.list_ssh_signing_keys import (
    _build_parser,
    _parse_args,
    _redact_key,
    list_ssh_signing_keys,
    main,
)

_KEYS_ARGV = ["gh", "api", "--paginate", "/user/ssh_signing_keys"]


def _sample_payload() -> list[dict]:
    return [
        {"id": 101, "title": "work", "key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG", "created_at": "2025-01-01"},
        {"id": 102, "title": "home", "key": "ssh-rsa AAAAB3NzaC1yc2EAAAA", "created_at": "2025-06-01"},
    ]


# -- list_ssh_signing_keys ----------------------------------------------------


def test_returns_filtered_fields() -> None:
    runner = QueueRunner([ExpectedCall(argv=_KEYS_ARGV, stdout=json.dumps(_sample_payload()))])
    result = list_ssh_signing_keys(runner=runner)
    assert len(result) == 2
    assert set(result[0].keys()) == {"id", "title", "key", "created_at"}
    runner.assert_exhausted()


def test_skips_non_dict_items() -> None:
    payload = [{"id": 1, "title": "k", "key": "x", "created_at": "2025-01-01"}, "bad", 42]
    runner = QueueRunner([ExpectedCall(argv=_KEYS_ARGV, stdout=json.dumps(payload))])
    assert len(list_ssh_signing_keys(runner=runner)) == 1


def test_empty_list() -> None:
    runner = QueueRunner([ExpectedCall(argv=_KEYS_ARGV, stdout="[]")])
    assert list_ssh_signing_keys(runner=runner) == []


def test_raises_on_non_list() -> None:
    runner = QueueRunner([ExpectedCall(argv=_KEYS_ARGV, stdout='{"x": 1}')])
    with pytest.raises(ValueError, match="Unexpected ssh_signing_keys payload"):
        list_ssh_signing_keys(runner=runner)


# -- _build_parser / _parse_args -----------------------------------------------


def test_build_parser() -> None:
    parser = _build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    assert parser.parse_args([]).redact is False
    assert parser.parse_args(["--redact"]).redact is True


def test_parse_args(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["prog"])
    assert _parse_args().redact is False


# -- _redact_key ---------------------------------------------------------------


def test_redact_short_key() -> None:
    assert _redact_key("short") == "***"


def test_redact_boundary_key() -> None:
    assert _redact_key("a" * 20) == "***"


def test_redact_long_key() -> None:
    key_val = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG"
    result = _redact_key(key_val)
    assert result.startswith(key_val[:8])
    assert result.endswith(key_val[-8:])
    assert "..." in result


# -- main ----------------------------------------------------------------------


def test_main_success(monkeypatch, capsys) -> None:
    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout=json.dumps(_sample_payload()), stderr="")

    monkeypatch.setattr("scripts.github.list_ssh_signing_keys.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog"])
    assert main() == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["count"] == 2


def test_main_with_redact(monkeypatch, capsys) -> None:
    payload = [{"id": 1, "title": "k", "key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG", "created_at": "2025-01-01"}]

    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("scripts.github.list_ssh_signing_keys.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--redact"])
    assert main() == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "..." in parsed["keys"][0]["key"]


def test_main_redact_skips_non_string_key(monkeypatch, capsys) -> None:
    payload = [{"id": 1, "title": "k", "key": None, "created_at": "2025-01-01"}]

    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("scripts.github.list_ssh_signing_keys.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--redact"])
    assert main() == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["keys"][0]["key"] is None


def test_main_redact_skips_empty_key(monkeypatch, capsys) -> None:
    payload = [{"id": 1, "title": "k", "key": "", "created_at": "2025-01-01"}]

    class _FakeRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("scripts.github.list_ssh_signing_keys.SubprocessGhRunner", _FakeRunner)
    monkeypatch.setattr("sys.argv", ["prog", "--redact"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["keys"][0]["key"] == ""


def test_main_gh_cli_error(monkeypatch) -> None:
    class _ErrorRunner:
        def run(self, argv, *, input_text=None):
            raise GhCliError("fail", argv=argv, returncode=1, stdout="", stderr="oops")

    monkeypatch.setattr("scripts.github.list_ssh_signing_keys.SubprocessGhRunner", _ErrorRunner)
    monkeypatch.setattr("sys.argv", ["prog"])
    assert main() == 2


def test_main_value_error(monkeypatch) -> None:
    class _BadRunner:
        def run(self, argv, *, input_text=None):
            return GhResult(stdout='{"not": "a list"}', stderr="")

    monkeypatch.setattr("scripts.github.list_ssh_signing_keys.SubprocessGhRunner", _BadRunner)
    monkeypatch.setattr("sys.argv", ["prog"])
    assert main() == 2
