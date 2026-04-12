"""Tests for the keyword-based auto-labeler."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import keyword_labeler as kwl
from scripts.github.gh_cli import GhCliError, GhResult


class _StubRunner:
    """Minimal GhRunner stub for unit tests."""

    def __init__(
        self,
        responses: list[Any] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._error = error
        self.calls: list[tuple[list[str], str | None]] = []

    def run(self, argv: list[str], *, input_text: str | None = None) -> GhResult:
        self.calls.append((argv, input_text))
        if self._error:
            raise self._error
        if not self._responses:
            return GhResult(stdout="null", stderr="")
        response = self._responses.pop(0)
        return GhResult(stdout=json.dumps(response), stderr="")


# ---------------------------------------------------------------------------
# conventional_type_from_title
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("feat: add new feature", "feat"),
        ("fix(core): resolve bug", "fix"),
        ("chore: update deps", "chore"),
        ("docs: update README", "docs"),
        ("refactor(ci): restructure", "refactor"),
        ("security: patch vuln", "security"),
        ("test(linting): add coverage", "test"),
        ("perf: optimize query", "perf"),
        ("enh(ui): improve layout", "enh"),
        ("bug(api): fix crash", "bug"),
        ("FEAT: uppercase prefix", "feat"),
        ("Fix(scope): mixed case", "fix"),
        ("no prefix here", None),
        ("feat - not conventional", None),
        ("feat:missing space", None),
        ("", None),
    ],
)
def test_conventional_type_from_title(title: str, expected: str | None) -> None:
    assert kwl.conventional_type_from_title(title) == expected


# ---------------------------------------------------------------------------
# contains_keyword
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("haystack", "keyword", "expected"),
    [
        # Single word: word-boundary matching
        ("the overlay network is configured", "overlay", True),
        ("overlay", "overlay", True),
        ("no overlaying here", "overlay", False),
        # Multi-word phrase: substring matching
        ("uses routing mesh for ingress", "routing mesh", True),
        ("no routing here", "routing mesh", False),
        # Dotted keys: substring matching
        ("set deploy.placement.constraints", "deploy.placement.constraints", True),
        ("deployment constraints", "deploy.placement.constraints", False),
        # Slash-containing: substring matching
        ("/run/secrets/my-secret", "/run/secrets", True),
        ("/opt/services/data/volume", "/opt/services/data", True),
        # Colon-containing: substring matching
        ("mode: global service", "mode: global", True),
        # Hyphen-containing: substring matching
        ("order: start-first is default", "order: start-first", True),
        # Empty keyword
        ("anything", "", False),
        # Case insensitivity for single words
        ("NFS is mounted", "nfs", True),
        # Case insensitivity for phrases (substring path)
        ("Routing Mesh is configured", "routing mesh", True),
        # Edge: keyword not present
        ("nothing relevant here", "overlay", False),
    ],
)
def test_contains_keyword(haystack: str, keyword: str, expected: bool) -> None:
    assert kwl.contains_keyword(haystack, keyword) is expected


# ---------------------------------------------------------------------------
# compute_labels
# ---------------------------------------------------------------------------


def _defaults(**overrides: Any) -> dict[str, Any]:
    """Build default kwargs for compute_labels with overrides."""
    base: dict[str, Any] = {
        "title": "",
        "body": "",
        "author": "some-user",
        "changed_files": [],
        "compose_contents": {},
        "image_service_map": {},
    }
    base.update(overrides)
    return base


class TestTypeLabels:
    """type/* labels from conventional commit prefix and keyword fallback."""

    @pytest.mark.parametrize(
        ("title", "expected_label"),
        [
            ("feat: add feature", "type/feat"),
            ("fix(api): resolve bug", "type/fix"),
            ("chore: update deps", "type/chore"),
            ("docs: update README", "type/docs"),
            ("refactor: restructure", "type/refactor"),
            ("security: patch CVE", "type/security"),
            ("test: add coverage", "type/test"),
            ("perf: optimize", "type/perf"),
            ("enh: improve UX", "type/enh"),
            ("bug: crash fix", "type/bug"),
        ],
    )
    def test_from_conventional_commit(self, title: str, expected_label: str) -> None:
        labels = kwl.compute_labels(**_defaults(title=title))
        assert expected_label in labels

    def test_security_fallback_from_keyword(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                title="update security patches",
                body="fixes a vulnerability",
            )
        )
        assert "type/security" in labels

    def test_security_fallback_cve(self) -> None:
        labels = kwl.compute_labels(**_defaults(title="patch cve-2024-1234"))
        assert "type/security" in labels

    def test_no_type_label_for_unrecognized_prefix(self) -> None:
        labels = kwl.compute_labels(**_defaults(title="wip: in progress"))
        assert not any(lbl.startswith("type/") for lbl in labels)

    def test_conventional_commit_suppresses_security_fallback(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                title="feat: add security scanning",
                body="this involves security",
            )
        )
        assert "type/feat" in labels
        assert "type/security" not in labels


class TestDependencyLabels:
    """dependency labels from PR author."""

    @pytest.mark.parametrize("author", ["dependabot[bot]", "github-actions[bot]"])
    def test_bot_authors(self, author: str) -> None:
        labels = kwl.compute_labels(**_defaults(author=author))
        assert "dependencies" in labels

    def test_human_author(self) -> None:
        labels = kwl.compute_labels(**_defaults(author="human-user"))
        assert "dependencies" not in labels


class TestFilePathLabels:
    """Labels derived from changed file paths."""

    def test_github_actions_from_workflows(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=[".github/workflows/ci.yml"],
            )
        )
        assert "github-actions" in labels

    def test_github_actions_from_actions_dir(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=[".github/actions/setup/action.yml"],
            )
        )
        assert "github-actions" in labels

    def test_docker_from_stacks(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["stacks/edge/docker-compose.yml"],
            )
        )
        assert "docker" in labels

    def test_docker_from_dockerfile(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["services/app/Dockerfile"],
            )
        )
        assert "docker" in labels

    def test_terraform_and_infrastructure(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["infrastructure/main.tf"],
            )
        )
        assert "terraform" in labels
        assert "infrastructure" in labels

    def test_terraform_from_tfvars(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["variables.tfvars"],
            )
        )
        assert "terraform" in labels

    def test_security_from_coraza_path(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["app-config/coraza/rules.conf"],
            )
        )
        assert "security" in labels

    def test_security_from_fail2ban_path(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["app-config/fail2ban/jail.conf"],
            )
        )
        assert "security" in labels

    def test_security_from_security_directory(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["infrastructure/security/firewall.tf"],
            )
        )
        assert "security" in labels

    def test_security_from_keyword_in_text(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                title="feat: add feature",
                body="address a vulnerability in auth",
            )
        )
        assert "security" in labels


class TestSwarmLabels:
    """swarm/* labels from keyword matches."""

    @pytest.mark.parametrize(
        ("keyword", "expected_label"),
        [
            ("overlay", "swarm/networking"),
            ("routing mesh", "swarm/networking"),
            ("placement constraints", "swarm/scheduling"),
            ("deploy.placement.constraints", "swarm/scheduling"),
            ("/run/secrets", "swarm/secrets-configs"),
            ("volume driver", "swarm/storage"),
            ("nfs", "swarm/storage"),
            ("update_config", "swarm/updates-health"),
            ("rollback_config", "swarm/updates-health"),
        ],
    )
    def test_keyword_triggers_label(self, keyword: str, expected_label: str) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                body=f"We configure {keyword} for the service",
            )
        )
        assert expected_label in labels

    def test_no_swarm_label_without_keywords(self) -> None:
        labels = kwl.compute_labels(**_defaults(body="A simple update to the README"))
        swarm_labels = {lbl for lbl in labels if lbl.startswith("swarm/")}
        assert swarm_labels == set()


class TestServiceLabels:
    """service/* labels from compose image names."""

    def test_from_compose_image(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["stacks/edge/docker-compose.yml"],
                compose_contents={
                    "stacks/edge/docker-compose.yml": "services:\n  proxy:\n    image: traefik:v3.6\n",
                },
                image_service_map={"traefik": "service/traefik"},
            )
        )
        assert "service/traefik" in labels
        assert "docker" in labels

    def test_with_registry_prefix(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["stacks/security/docker-compose.yml"],
                compose_contents={
                    "stacks/security/docker-compose.yml": (
                        "services:\n  crowdsec:\n    image: ghcr.io/crowdsecurity/crowdsec:v1.7\n"
                    ),
                },
                image_service_map={"crowdsecurity/crowdsec": "service/crowdsec"},
            )
        )
        assert "service/crowdsec" in labels

    def test_unmapped_image_produces_no_label(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                changed_files=["stacks/db/docker-compose.yml"],
                compose_contents={
                    "stacks/db/docker-compose.yml": "services:\n  db:\n    image: postgres:16\n",
                },
                image_service_map={"traefik": "service/traefik"},
            )
        )
        service_labels = {lbl for lbl in labels if lbl.startswith("service/")}
        assert service_labels == set()


class TestSanitizeLogValue:
    """Unit tests for _sanitize_log_value allowlist-based sanitization."""

    def test_replaces_newline(self) -> None:
        assert kwl._sanitize_log_value("hello\nworld") == "hello?world"

    def test_replaces_carriage_return(self) -> None:
        assert kwl._sanitize_log_value("hello\rworld") == "hello?world"

    def test_replaces_crlf(self) -> None:
        assert kwl._sanitize_log_value("hello\r\nworld") == "hello??world"

    def test_no_change_for_clean_value(self) -> None:
        assert kwl._sanitize_log_value("traefik") == "traefik"

    def test_preserves_image_ref_chars(self) -> None:
        assert kwl._sanitize_log_value("ghcr.io/org/img:v1.2-rc") == "ghcr.io/org/img:v1.2-rc"

    def test_preserves_at_sign_for_digest_refs(self) -> None:
        assert kwl._sanitize_log_value("img@sha256:abc123") == "img@sha256:abc123"

    def test_replaces_shell_metacharacters(self) -> None:
        assert kwl._sanitize_log_value("img;rm -rf /") == "img?rm?-rf?/"

    def test_empty_string(self) -> None:
        assert kwl._sanitize_log_value("") == ""


class TestServiceLabelsLogInjection:
    """Verify _service_labels sanitizes log output against injection payloads."""

    def test_newline_in_image_name_is_sanitized(self, caplog: pytest.LogCaptureFixture) -> None:
        compose = {"c.yml": "services:\n  app:\n    image: evil\ninjected:v1\n"}
        image_map = {"evil": "service/evil"}
        with caplog.at_level("INFO"):
            kwl._service_labels(compose, image_map)
        for record in caplog.records:
            assert "\n" not in record.getMessage()

    def test_newline_in_map_value_is_sanitized(self, caplog: pytest.LogCaptureFixture) -> None:
        compose = {"c.yml": "services:\n  app:\n    image: traefik:v3\n"}
        image_map = {"traefik": "service/traefik\nINJECTED"}
        with caplog.at_level("INFO"):
            kwl._service_labels(compose, image_map)
        for record in caplog.records:
            assert "\n" not in record.getMessage()


class TestMajorBumpLabels:
    """major-version-bump label for major version bumps in bot PRs."""

    _LABEL = "major-version-bump"

    def test_major_bump_from_prose(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                author="dependabot[bot]",
                title="ci(deps): bump foo from 1.2.3 to 2.0.0",
            )
        )
        assert self._LABEL in labels

    def test_major_bump_from_table(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                author="dependabot[bot]",
                body="| pkg | `1.9.0` | `2.0.0` |",
            )
        )
        assert self._LABEL in labels

    def test_minor_bump_no_label(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                author="dependabot[bot]",
                title="ci(deps): bump foo from 2.33.7 to 2.38.1",
            )
        )
        assert self._LABEL not in labels

    def test_calendar_version_major_bump(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                author="dependabot[bot]",
                title="ci(deps): bump bar from 2025.12.3 to 2026.2",
            )
        )
        assert self._LABEL in labels

    def test_human_author_no_label(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                author="human-user",
                title="ci(deps): bump foo from 1.0.0 to 2.0.0",
            )
        )
        assert self._LABEL not in labels

    def test_no_versions_no_label(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                author="dependabot[bot]",
                title="ci(deps): bump the dependency-updates group",
            )
        )
        assert self._LABEL not in labels

    def test_v_prefixed_major_bump(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                author="dependabot[bot]",
                title="ci(deps): bump traefik from v3.6.1 to v4.0.0",
            )
        )
        assert self._LABEL in labels

    def test_single_segment_major_bump(self) -> None:
        labels = kwl.compute_labels(
            **_defaults(
                author="dependabot[bot]",
                title="ci(deps): bump uptime-kuma from 1 to 2",
            )
        )
        assert self._LABEL in labels


class TestComputeLabelsEdgeCases:
    """Edge cases for compute_labels."""

    def test_no_labels_returns_empty_set(self) -> None:
        labels = kwl.compute_labels(**_defaults())
        assert labels == set()


# ---------------------------------------------------------------------------
# I/O functions
# ---------------------------------------------------------------------------


class TestListChangedFiles:
    """Tests for list_changed_files using stub runner."""

    def test_single_page(self) -> None:
        runner = _StubRunner(responses=[[{"filename": "README.md"}, {"filename": "stacks/edge/docker-compose.yml"}]])
        result = kwl.list_changed_files(runner=runner, repo="owner/repo", pr_number=42)
        assert result == ["README.md", "stacks/edge/docker-compose.yml"]

    def test_pagination(self) -> None:
        runner = _StubRunner(
            responses=[
                [{"filename": f"file{idx}.txt"} for idx in range(100)],
                [{"filename": "last.txt"}],
            ]
        )
        result = kwl.list_changed_files(runner=runner, repo="owner/repo", pr_number=42)
        assert len(result) == 101
        assert result[-1] == "last.txt"

    def test_empty_response(self) -> None:
        runner = _StubRunner(responses=[[]])
        result = kwl.list_changed_files(runner=runner, repo="owner/repo", pr_number=42)
        assert result == []

    def test_returns_empty_on_api_failure(self) -> None:
        runner = _StubRunner(error=GhCliError("fail", argv=["gh"], returncode=1, stdout="", stderr=""))
        result = kwl.list_changed_files(runner=runner, repo="owner/repo", pr_number=42)
        assert result == []

    def test_returns_empty_on_os_error(self) -> None:
        runner = _StubRunner(error=OSError("gh not found"))
        result = kwl.list_changed_files(runner=runner, repo="owner/repo", pr_number=42)
        assert result == []

    def test_returns_empty_on_json_decode_error(self) -> None:
        runner = _StubRunner(error=json.JSONDecodeError("fail", "", 0))
        result = kwl.list_changed_files(runner=runner, repo="owner/repo", pr_number=42)
        assert result == []


class TestGetFileContent:
    """Tests for get_file_content using stub runner."""

    def test_decodes_base64_content(self) -> None:
        import base64

        encoded = base64.b64encode(b"image: traefik:v3\n").decode()
        runner = _StubRunner(responses=[{"content": encoded}])
        result = kwl.get_file_content(runner=runner, repo="o/r", path="compose.yml", ref="abc123")
        assert result == "image: traefik:v3\n"

    def test_returns_none_on_api_failure(self) -> None:
        runner = _StubRunner(error=GhCliError("fail", argv=["gh"], returncode=1, stdout="", stderr=""))
        result = kwl.get_file_content(runner=runner, repo="o/r", path="compose.yml", ref="abc123")
        assert result is None

    def test_returns_none_when_no_content_field(self) -> None:
        runner = _StubRunner(responses=[{"sha": "abc"}])
        result = kwl.get_file_content(runner=runner, repo="o/r", path="compose.yml", ref="abc123")
        assert result is None

    def test_returns_none_on_os_error(self) -> None:
        runner = _StubRunner(error=OSError("gh not found"))
        result = kwl.get_file_content(runner=runner, repo="o/r", path="compose.yml", ref="abc123")
        assert result is None

    def test_returns_none_on_invalid_base64(self) -> None:
        runner = _StubRunner(responses=[{"content": "not-valid-base64!!!"}])
        result = kwl.get_file_content(runner=runner, repo="o/r", path="compose.yml", ref="abc123")
        assert result is None

    def test_returns_none_when_response_is_not_dict(self) -> None:
        runner = _StubRunner(responses=[[{"path": "compose.yml"}]])
        result = kwl.get_file_content(runner=runner, repo="o/r", path="compose.yml", ref="abc123")
        assert result is None

    def test_returns_none_on_unicode_decode_error(self) -> None:
        import base64 as _b64

        # Raw bytes that are valid base64 but not valid UTF-8.
        raw_bytes = b"\xff\xfe"
        encoded = _b64.b64encode(raw_bytes).decode()
        runner = _StubRunner(responses=[{"content": encoded}])
        result = kwl.get_file_content(runner=runner, repo="o/r", path="compose.yml", ref="abc123")
        assert result is None


class TestFetchComposeContents:
    """Tests for fetch_compose_contents."""

    def test_skips_files_where_get_file_content_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runner = _StubRunner()
        monkeypatch.setattr(kwl, "get_file_content", lambda **kwargs: None)
        result = kwl.fetch_compose_contents(
            runner=runner,
            repo="o/r",
            ref="abc123",
            changed_files=["stacks/edge/docker-compose.yml"],
        )
        assert result == {}

    def test_includes_files_where_get_file_content_returns_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        runner = _StubRunner()
        monkeypatch.setattr(kwl, "get_file_content", lambda **kwargs: "services:\n  web:\n")
        result = kwl.fetch_compose_contents(
            runner=runner,
            repo="o/r",
            ref="abc123",
            changed_files=["stacks/edge/docker-compose.yml"],
        )
        assert result == {"stacks/edge/docker-compose.yml": "services:\n  web:\n"}


class TestAddLabels:
    """Tests for add_labels using stub runner."""

    def test_calls_runner_with_json_body(self) -> None:
        runner = _StubRunner(responses=[{}])
        kwl.add_labels(runner=runner, repo="o/r", pr_number=42, labels={"type/feat", "docker"})

        assert len(runner.calls) == 1
        argv, input_text = runner.calls[0]
        assert "/repos/o/r/issues/42/labels" in argv
        assert input_text is not None
        parsed = json.loads(input_text)
        assert sorted(parsed["labels"]) == ["docker", "type/feat"]

    def test_warns_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        runner = _StubRunner(error=GhCliError("fail", argv=["gh"], returncode=1, stdout="", stderr=""))
        with caplog.at_level("WARNING"):
            kwl.add_labels(runner=runner, repo="o/r", pr_number=42, labels={"type/feat"})
        assert "Failed to add labels" in caplog.text

    def test_warns_on_os_error(self, caplog: pytest.LogCaptureFixture) -> None:
        runner = _StubRunner(error=OSError("gh not found"))
        with caplog.at_level("WARNING"):
            kwl.add_labels(runner=runner, repo="o/r", pr_number=42, labels={"type/feat"})
        assert "Failed to add labels" in caplog.text


# ---------------------------------------------------------------------------
# _read_event_payload
# ---------------------------------------------------------------------------


class TestReadEventPayload:
    """Tests for the event payload reader."""

    def test_reads_valid_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {"pull_request": {"number": 42, "title": "test"}}
        event_file = tmp_path / "event.json"
        event_file.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        assert kwl._read_event_payload() == payload

    def test_returns_empty_dict_when_env_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
        assert kwl._read_event_payload() == {}

    def test_returns_empty_dict_on_invalid_json(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event_file = tmp_path / "event.json"
        event_file.write_text("not-json", encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        assert kwl._read_event_payload() == {}

    def test_returns_empty_dict_on_missing_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_EVENT_PATH", "/nonexistent/path.json")
        assert kwl._read_event_payload() == {}


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    """Integration-level tests for the main entry point."""

    def test_exits_with_error_when_no_repo(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event_file = tmp_path / "event.json"
        event_file.write_text(
            json.dumps(
                {
                    "pull_request": {
                        "number": 1,
                        "title": "test",
                        "user": {"login": "user"},
                        "head": {"sha": "abc"},
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        assert kwl.main() == 1

    def test_full_flow_no_labels(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event_file = tmp_path / "event.json"
        event_file.write_text(
            json.dumps(
                {
                    "pull_request": {
                        "number": 1,
                        "title": "update readme",
                        "body": "",
                        "user": {"login": "human"},
                        "head": {"sha": "abc"},
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setattr(kwl, "list_changed_files", lambda **kwargs: ["README.md"])
        monkeypatch.setattr(kwl, "load_map", lambda: {})
        assert kwl.main() == 0

    def test_continues_when_load_map_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify main() falls back to empty map when load_map() raises."""
        event_file = tmp_path / "event.json"
        event_file.write_text(
            json.dumps(
                {
                    "pull_request": {
                        "number": 1,
                        "title": "feat: add feature",
                        "body": "",
                        "user": {"login": "human"},
                        "head": {"sha": "abc"},
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setattr(kwl, "list_changed_files", lambda **kwargs: [])

        def failing_load_map() -> dict[str, str]:
            raise OSError("map file missing")

        monkeypatch.setattr(kwl, "load_map", failing_load_map)

        added_labels: list[set[str]] = []
        monkeypatch.setattr(
            kwl,
            "add_labels",
            lambda **kwargs: added_labels.append(kwargs["labels"]),
        )

        assert kwl.main() == 0
        # type/feat should still be applied despite load_map failure
        assert len(added_labels) == 1
        assert "type/feat" in added_labels[0]

    def test_exits_cleanly_when_no_pr_or_issue(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event_file = tmp_path / "event.json"
        event_file.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        assert kwl.main() == 0

    def test_issue_payload_applies_type_label(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event_file = tmp_path / "event.json"
        event_file.write_text(
            json.dumps(
                {
                    "issue": {
                        "number": 10,
                        "title": "feat: add new widget",
                        "body": "",
                        "user": {"login": "human"},
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

        added_labels: list[set[str]] = []
        monkeypatch.setattr(
            kwl,
            "add_labels",
            lambda **kwargs: added_labels.append(kwargs["labels"]),
        )

        assert kwl.main() == 0
        assert len(added_labels) == 1
        assert "type/feat" in added_labels[0]

    def test_issue_payload_no_changed_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify issue context does not fetch changed files or compose contents."""
        event_file = tmp_path / "event.json"
        event_file.write_text(
            json.dumps(
                {
                    "issue": {
                        "number": 10,
                        "title": "docs: update README",
                        "body": "",
                        "user": {"login": "human"},
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

        file_calls: list[int] = []

        def _track_file_call(**kwargs: Any) -> list[str]:
            file_calls.append(1)
            return []

        monkeypatch.setattr(
            kwl,
            "list_changed_files",
            _track_file_call,
        )
        monkeypatch.setattr(
            kwl,
            "add_labels",
            lambda **kwargs: None,
        )

        kwl.main()
        assert len(file_calls) == 0, "list_changed_files should not be called for issues"

    def test_issue_payload_exits_with_error_when_no_repo(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event_file = tmp_path / "event.json"
        event_file.write_text(
            json.dumps(
                {
                    "issue": {
                        "number": 10,
                        "title": "feat: test",
                        "user": {"login": "user"},
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        assert kwl.main() == 1

    def test_uses_fork_repo_for_file_content(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Verify get_file_content is called with the head repo, not the base repo."""
        event_file = tmp_path / "event.json"
        event_file.write_text(
            json.dumps(
                {
                    "pull_request": {
                        "number": 1,
                        "title": "feat: update compose",
                        "body": "",
                        "user": {"login": "contributor"},
                        "head": {
                            "sha": "abc123",
                            "repo": {"full_name": "contributor/fork-repo"},
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

        content_repos: list[str] = []

        def fake_list_changed_files(**kwargs: Any) -> list[str]:
            return ["stacks/edge/docker-compose.yml"]

        def fake_fetch_compose_contents(**kwargs: Any) -> dict[str, str]:
            content_repos.append(kwargs["repo"])
            return {}

        monkeypatch.setattr(kwl, "list_changed_files", fake_list_changed_files)
        monkeypatch.setattr(kwl, "fetch_compose_contents", fake_fetch_compose_contents)
        monkeypatch.setattr(kwl, "load_map", lambda: {})
        monkeypatch.setattr(kwl, "add_labels", lambda **kwargs: None)
        kwl.main()

        assert content_repos == ["contributor/fork-repo"]
