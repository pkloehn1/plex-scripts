from __future__ import annotations

import scripts.testing.hooks.check_repo_layout as mod
from scripts.testing.hooks.conftest import (
    assert_read_file_error,
    assert_staged_paths_error,
    fake_file_reader,
    fake_staged_paths,
)


def test_compose_outside_allowed_path(monkeypatch, capsys):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["misc/app.yml"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader({"misc/app.yml": "name: bad\nservices:\n  web:\n    image: busybox\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Compose files must live" in err
    assert "must start with '---' and end with '...'" in err


def test_env_files_blocked(monkeypatch, capsys):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["app.env"]))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Tracked env files are blocked" in err


def test_env_template_swarm_allowed(monkeypatch):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths([".env.template.swarm"]))

    assert mod.main() == 0


def test_secrets_blocked(monkeypatch, capsys):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["secrets/token.txt"]))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Tracked secrets are blocked" in err


def test_stack_name_forbidden(monkeypatch, capsys):
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader(
            {
                "stacks/edge/docker-compose.yml": "---\nname: stack\nservices:\n  web:\n    image: busybox\n...",
            }
        ),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "must NOT include name" in err


def test_compose_requires_services(monkeypatch, capsys):
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader({"stacks/edge/docker-compose.yml": "---\nservices: {}\n...\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "must define services" in err


def test_compose_requires_markers(monkeypatch, capsys):
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader({"stacks/edge/docker-compose.yml": "services:\n  web:\n    image: busybox\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "must start with '---' and end with '...'" in err


def test_compose_missing_end_marker(monkeypatch, capsys):
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader({"stacks/edge/docker-compose.yml": "---\nservices:\n  web:\n    image: busybox\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "must start with '---' and end with '...'" in err


def test_compose_single_document(monkeypatch, capsys):
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader(
            {
                "stacks/edge/docker-compose.yml": (
                    "---\nservices:\n  web:\n    image: busybox\n...\n---\nservices:\n  api:\n    image: busybox\n...\n"
                )
            }
        ),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "exactly one document" in err


def test_non_compose_yaml_without_markers_allows(monkeypatch):
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths([".github/labeler.yml"]))
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader({".github/labeler.yml": "labels:\n  - name: ci\n    patterns:\n      - .github/**\n"}),
    )

    assert mod.main() == 0


def test_invalid_yaml_reports_parse_error(monkeypatch, capsys):
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader(
            {"stacks/edge/docker-compose.yml": "---\nservices:\n  web:\n    image: busybox\n  - invalid\n...\n"}
        ),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "YAML parse error" in err


def test_include_only_stack_allowed(monkeypatch):
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader({"stacks/edge/docker-compose.yml": "---\ninclude:\n  - base.yml\n...\n"}),
    )

    assert mod.main() == 0


def test_include_only_with_bad_services(monkeypatch, capsys):
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader({"stacks/edge/docker-compose.yml": "---\ninclude:\n  - base.yml\nservices: bad\n...\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "services must be a mapping" in err


def test_multi_document_with_scalar(monkeypatch, capsys):
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader(
            {"stacks/edge/docker-compose.yml": "---\nservices:\n  web:\n    image: busybox\n...\n--- scalar\n"}
        ),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "exactly one document" in err


def test_nested_stacks_path_rejected(monkeypatch, capsys):
    """stacks/edge/traefik/docker-compose.yml (4 parts) is not allowed."""
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/traefik/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader(
            {"stacks/edge/traefik/docker-compose.yml": "---\nservices:\n  web:\n    image: busybox\n...\n"}
        ),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Compose files must live" in err


def test_get_staged_paths_git_error(monkeypatch, capsys):
    """_get_staged_paths() returns error when git diff fails."""
    assert_staged_paths_error(mod, monkeypatch, capsys)


def test_read_staged_file_git_error(monkeypatch, capsys):
    """_read_staged_file() returns error when git show fails."""
    assert_read_file_error(mod, monkeypatch, capsys, "_get_staged_paths", ["stacks/edge/docker-compose.yml"])


def test_read_staged_file_returns_none_content(monkeypatch, capsys):
    """main() handles None content from _read_staged_file."""
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]))

    def fake_reader_none(path):
        return None, None

    monkeypatch.setattr(mod, "_read_staged_file", fake_reader_none)
    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Unable to read staged file content" in err


def test_env_file_dotenv_blocked(monkeypatch, capsys):
    """.env file is blocked."""
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths([".env"]))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Tracked env files are blocked" in err


def test_env_file_dotenv_prefixed_blocked(monkeypatch, capsys):
    """.env.local file is blocked."""
    monkeypatch.setattr(mod, "_get_staged_paths", lambda: fake_staged_paths([".env.local"]))

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "Tracked env files are blocked" in err


def test_is_secret_violation_empty_path():
    """_is_secret_violation returns False for empty path."""
    from pathlib import Path

    assert mod._is_secret_violation(Path()) is False


def test_is_allowed_compose_path_empty_path():
    """_is_allowed_compose_path returns False for empty path."""
    from pathlib import Path

    assert mod._is_allowed_compose_path(Path()) is False


def test_truenas_config_allowed(monkeypatch):
    """TrueNAS compose-like configs bypass Swarm validation."""
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["app-config/truenas/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader(
            {"app-config/truenas/docker-compose.yml": "---\nservices:\n  app:\n    image: busybox\n...\n"}
        ),
    )
    assert mod.main() == 0


def test_has_doc_markers_empty_string():
    """_has_doc_markers returns False for empty/whitespace-only content."""
    assert mod._has_doc_markers("") is False
    assert mod._has_doc_markers("   \n  \n") is False


def test_include_doc_with_name_forbidden(monkeypatch, capsys):
    """Include-only doc with name: is blocked."""
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader({"stacks/edge/docker-compose.yml": "---\nname: stack\ninclude:\n  - base.yml\n...\n"}),
    )

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "must NOT include name" in err


def test_empty_file_no_markers(monkeypatch):
    """Empty compose file passes (not compose)."""
    monkeypatch.setattr(
        mod,
        "_get_staged_paths",
        lambda: fake_staged_paths(["stacks/edge/docker-compose.yml"]),
    )
    monkeypatch.setattr(
        mod,
        "_read_staged_file",
        fake_file_reader({"stacks/edge/docker-compose.yml": "   \n\n"}),
    )

    # Empty file is not detected as compose, so no violation
    assert mod.main() == 0
