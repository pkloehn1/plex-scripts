from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from scripts.github.gh_cli import GhResult

# ---------------------------------------------------------------------------
# Shared queue-based GhRunner stub (used across multiple test modules)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedCall:
    """A single expected ``gh`` CLI invocation with optional input validation."""

    argv: list[str]
    stdout: str
    expected_input: str | None = None


class QueueRunner:
    """Mock GhRunner that pops expected calls from a queue.

    Validates ``argv`` for every call.  When ``expected_input`` is set on an
    :class:`ExpectedCall`, the ``input_text`` argument is also compared as
    parsed JSON (order-insensitive).
    """

    def __init__(self, calls: list[ExpectedCall]) -> None:
        self._calls = list(calls)

    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
        if not self._calls:
            raise AssertionError(f"Unexpected gh call (no calls left): {argv!r}")
        expected = self._calls.pop(0)
        assert argv == expected.argv
        if expected.expected_input is not None:
            assert input_text is not None, "Expected input_text but got None"
            assert json.loads(input_text) == json.loads(expected.expected_input)
        return GhResult(stdout=expected.stdout, stderr="")

    def assert_exhausted(self) -> None:
        assert not self._calls, f"Unused expected calls: {self._calls!r}"


def as_stdout(payload: Any) -> str:
    """Normalize payloads to JSON strings unless already a string."""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload)


def make_call(argv: list[str], stdout: Any = "") -> ExpectedCall:
    """Build an :class:`ExpectedCall` with automatic JSON serialization."""
    return ExpectedCall(argv=argv, stdout=as_stdout(stdout))


def make_runner(*calls: ExpectedCall) -> QueueRunner:
    """Build a :class:`QueueRunner` from positional expected calls."""
    return QueueRunner(list(calls))


# ---------------------------------------------------------------------------
# Smart stub runner (auto-responds based on endpoint pattern)
# ---------------------------------------------------------------------------


class _StubGhRunner:
    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
        _ = input_text
        endpoint = _extract_endpoint(argv)
        payload = _payload_for(endpoint, argv)
        return GhResult(stdout=json.dumps(payload), stderr="")


def _extract_endpoint(argv: list[str]) -> str:
    if "--method" in argv:
        method_index = argv.index("--method")
        endpoint_index = method_index + 2
        if endpoint_index < len(argv):
            return argv[endpoint_index]
        return ""
    if len(argv) > 2:
        return argv[2]
    return ""


def _payload_for(endpoint: str, argv: list[str]) -> object:
    if endpoint == "/user":
        return {"login": "testuser"}
    if "/pulls/comments/" in endpoint:
        return {
            "node_id": "NODE123",
            "pull_request_url": "https://api.github.com/repos/octo/widgets/pulls/45",
        }
    if "/pulls/" in endpoint and "/comments" in endpoint:
        if "--method" in argv:
            return {"id": 333, "node_id": "NODE333"}
        return []
    return {}


@pytest.fixture
def runner() -> _StubGhRunner:
    return _StubGhRunner()


@pytest.fixture
def repo() -> str:
    return "octo/widgets"


@pytest.fixture
def pr_number() -> int:
    return 45


@pytest.fixture
def comment_id() -> int:
    return 999


@pytest.fixture
def test_body() -> str:
    return "Test reply"
