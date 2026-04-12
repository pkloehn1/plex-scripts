"""Tests for scripts.linting.check_filename_conventions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.linting.check_filename_conventions import (
    _iter_tree,
    collect_candidate_paths,
    find_dash_underscore_collisions,
    find_directory_name_violations,
    find_json_filename_violations,
    find_markdown_filename_violations,
    find_path_space_violations,
    find_powershell_filename_violations,
    find_python_filename_violations,
    find_shell_filename_violations,
    find_yaml_filename_violations,
    is_valid_python_filename,
    main,
)


def test_is_valid_python_filename() -> None:
    assert is_valid_python_filename("run_super_linter.py")
    assert is_valid_python_filename("a1_b2.py")

    assert not is_valid_python_filename("run-super-linter.py")
    assert not is_valid_python_filename("Run_super_linter.py")
    assert not is_valid_python_filename("run super linter.py")


def test_find_python_filename_violations_flags_dashes(tmp_path: Path) -> None:
    good_file = tmp_path / "good_name.py"
    bad_file = tmp_path / "bad-name.py"
    good_file.write_text("print('ok')\n")
    bad_file.write_text("print('no')\n")

    findings = find_python_filename_violations([good_file, bad_file])
    assert [finding.path.name for finding in findings] == ["bad-name.py"]


def test_find_dash_underscore_collisions(tmp_path: Path) -> None:
    dash_name = tmp_path / "foo-bar.py"
    underscore_name = tmp_path / "foo_bar.py"
    dash_name.write_text("print('a')\n")
    underscore_name.write_text("print('b')\n")

    findings = find_dash_underscore_collisions([dash_name, underscore_name])
    assert len(findings) == 1
    assert "foo_bar" in findings[0].message


def test_find_dash_underscore_collisions_allows_cross_platform_scripts(
    tmp_path: Path,
) -> None:
    powershell_script = tmp_path / "Set-Config.ps1"
    shell_script = tmp_path / "set_config.sh"
    python_script = tmp_path / "set_config.py"
    powershell_script.write_text("Write-Output 'ok'\n")
    shell_script.write_text("#!/usr/bin/env bash\n")
    python_script.write_text("print('ok')\n")

    findings = find_dash_underscore_collisions([powershell_script, shell_script, python_script])
    assert findings == []


def test_find_shell_filename_violations(tmp_path: Path) -> None:
    ok_script = tmp_path / "run_super_linter.sh"
    bad_script = tmp_path / "run-super-linter.sh"
    ok_script.write_text("#!/usr/bin/env bash\n")
    bad_script.write_text("#!/usr/bin/env bash\n")

    findings = find_shell_filename_violations([ok_script, bad_script])
    assert [finding.path.name for finding in findings] == ["run-super-linter.sh"]


def test_find_powershell_filename_violations(tmp_path: Path) -> None:
    ok_script = tmp_path / "Invoke-Something.ps1"
    bad_script = tmp_path / "run-super-linter.ps1"
    ok_script.write_text("Write-Output 'ok'\n")
    bad_script.write_text("Write-Output 'bad'\n")

    findings = find_powershell_filename_violations([ok_script, bad_script])
    assert [finding.path.name for finding in findings] == ["run-super-linter.ps1"]


def test_find_yaml_filename_violations(tmp_path: Path) -> None:
    ok_file = tmp_path / "edge-stack.yml"
    bad_file = tmp_path / "edge_stack.yml"
    ok_file.write_text("---\n")
    bad_file.write_text("---\n")

    findings = find_yaml_filename_violations([ok_file, bad_file])
    assert [finding.path.name for finding in findings] == ["edge_stack.yml"]


def test_find_markdown_filename_violations_allows_readme(tmp_path: Path) -> None:
    ok_file = tmp_path / "README.md"
    bad_file = tmp_path / "My Doc.md"
    ok_file.write_text("# Title\n")
    bad_file.write_text("# Title\n")

    findings = find_markdown_filename_violations([ok_file, bad_file])
    assert [finding.path.name for finding in findings] == ["My Doc.md"]


def test_find_markdown_filename_violations_allows_dot_segments(tmp_path: Path) -> None:
    ip_file = tmp_path / "ip-inventory-10.10.40.120.md"
    cis_file = tmp_path / "5.2-ssh-server-configuration.md"
    ip_file.write_text("# Title\n")
    cis_file.write_text("# Title\n")

    findings = find_markdown_filename_violations([ip_file, cis_file])
    assert findings == []


def test_find_markdown_filename_violations_rejects_bad_dot_patterns(
    tmp_path: Path,
) -> None:
    trailing_dot = tmp_path / "bad-.md"
    consecutive = tmp_path / "bad..md"
    underscore = tmp_path / "has_underscore.md"
    for bad_file in (trailing_dot, consecutive, underscore):
        bad_file.write_text("# Title\n")

    findings = find_markdown_filename_violations([trailing_dot, consecutive, underscore])
    assert len(findings) == 3


def test_find_json_filename_violations_allows_dot_separators(tmp_path: Path) -> None:
    ok_file = tmp_path / "nodes.report.jsonc"
    bad_file = tmp_path / "Nodes.Report.jsonc"
    ok_file.write_text("{}\n")
    bad_file.write_text("{}\n")

    findings = find_json_filename_violations([ok_file, bad_file])
    assert [finding.path.name for finding in findings] == ["Nodes.Report.jsonc"]


def test_find_directory_name_violations_flags_spaces(tmp_path: Path) -> None:
    repo_root = tmp_path
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir()

    bad_dir = scripts_dir / "Bad Dir"
    bad_dir.mkdir()

    paths = [scripts_dir, bad_dir]
    findings = find_directory_name_violations(paths, repo_root=repo_root)
    assert len(findings) == 1
    assert "spaces" in findings[0].message


def test_find_directory_name_violations_allows_fail2ban_dot_d(tmp_path: Path) -> None:
    repo_root = tmp_path
    app_config = repo_root / "app-config"
    fail2ban = app_config / "fail2ban"
    filter_d = fail2ban / "filter.d"
    jail_d = fail2ban / "jail.d"

    filter_d.mkdir(parents=True)
    jail_d.mkdir(parents=True)

    paths = [app_config, fail2ban, filter_d, jail_d]
    findings = find_directory_name_violations(paths, repo_root=repo_root)
    assert findings == []


def test_find_python_violations_skips_non_py(tmp_path: Path) -> None:
    txt = tmp_path / "data.txt"
    txt.write_text("text", encoding="utf-8")
    assert find_python_filename_violations([txt]) == []


def test_find_shell_violations_skips_non_sh(tmp_path: Path) -> None:
    txt = tmp_path / "data.txt"
    txt.write_text("text", encoding="utf-8")
    assert find_shell_filename_violations([txt]) == []


def test_find_yaml_violations_skips_non_yaml(tmp_path: Path) -> None:
    txt = tmp_path / "data.txt"
    txt.write_text("text", encoding="utf-8")
    assert find_yaml_filename_violations([txt]) == []


def test_find_markdown_violations_skips_non_md(tmp_path: Path) -> None:
    txt = tmp_path / "data.txt"
    txt.write_text("text", encoding="utf-8")
    assert find_markdown_filename_violations([txt]) == []


def test_find_json_violations_skips_non_json(tmp_path: Path) -> None:
    txt = tmp_path / "data.txt"
    txt.write_text("text", encoding="utf-8")
    assert find_json_filename_violations([txt]) == []


def test_find_powershell_violations_skips_non_ps1(tmp_path: Path) -> None:
    txt = tmp_path / "data.txt"
    txt.write_text("text", encoding="utf-8")
    assert find_powershell_filename_violations([txt]) == []


def test_find_dash_underscore_collisions_skips_single(tmp_path: Path) -> None:
    single = tmp_path / "foo_bar.py"
    single.write_text("x = 1\n", encoding="utf-8")
    assert find_dash_underscore_collisions([single]) == []


def test_find_dash_underscore_collisions_skips_same_names(tmp_path: Path) -> None:
    file_one = tmp_path / "foo_bar.py"
    file_one.write_text("x = 1\n", encoding="utf-8")
    # Same file passed twice = same distinct name, len(names) < 2
    assert find_dash_underscore_collisions([file_one, file_one]) == []


def test_find_dash_underscore_collisions_skips_non_collision_candidate(tmp_path: Path) -> None:
    txt = tmp_path / "foo_bar.txt"
    txt.write_text("text", encoding="utf-8")
    assert find_dash_underscore_collisions([txt]) == []


def test_find_directory_name_violations_skips_files(tmp_path: Path) -> None:
    f = tmp_path / "scripts" / "test.py"
    f.parent.mkdir(parents=True)
    f.write_text("x = 1\n", encoding="utf-8")
    findings = find_directory_name_violations([f], repo_root=tmp_path)
    assert findings == []


def test_find_directory_name_violations_skips_unscoped_dir(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    findings = find_directory_name_violations([other], repo_root=tmp_path)
    assert findings == []


def test_find_directory_name_violations_flags_bad_scripts_dir(tmp_path: Path) -> None:
    bad = tmp_path / "scripts" / "Bad-Name"
    bad.mkdir(parents=True)
    findings = find_directory_name_violations([bad], repo_root=tmp_path)
    assert len(findings) == 1
    assert "scripts/" in findings[0].message


def test_find_directory_name_violations_flags_bad_docs_dir(tmp_path: Path) -> None:
    bad = tmp_path / "docs" / "Bad_Name"
    bad.mkdir(parents=True)
    findings = find_directory_name_violations([bad], repo_root=tmp_path)
    assert len(findings) == 1
    assert "kebab-case" in findings[0].message


def test_find_path_space_violations(tmp_path: Path) -> None:
    space_file = tmp_path / "bad file.py"
    space_file.write_text("x = 1\n", encoding="utf-8")
    findings = find_path_space_violations([space_file])
    assert len(findings) == 1
    assert "spaces" in findings[0].message


def test_find_path_space_violations_no_spaces(tmp_path: Path) -> None:
    good = tmp_path / "good_file.py"
    good.write_text("x = 1\n", encoding="utf-8")
    assert find_path_space_violations([good]) == []


def test_iter_tree_missing_root(tmp_path: Path) -> None:
    assert _iter_tree(tmp_path / "nonexistent") == []


def test_iter_tree_with_files(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    result = _iter_tree(tmp_path)
    assert len(result) >= 1


def test_collect_candidate_paths(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    py_file = scripts_dir / "mod.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    readme = tmp_path / "README.md"
    readme.write_text("# Readme\n", encoding="utf-8")
    paths = collect_candidate_paths(tmp_path)
    assert any(path.name == "mod.py" for path in paths)
    assert any(path.name == "README.md" for path in paths)


def test_collect_candidate_paths_no_optional_files(tmp_path: Path) -> None:
    # No scripts/docs/stacks/app-config dirs, no README/docker-compose
    paths = collect_candidate_paths(tmp_path)
    assert paths == []


def test_main_no_findings(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    pkg = scripts_dir / "mypkg"
    pkg.mkdir(parents=True)
    py_file = pkg / "good_name.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    with patch("scripts.common.paths.repo_root", return_value=tmp_path):
        code = main()
    assert code == 0


def test_main_with_findings(tmp_path: Path) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    bad = scripts_dir / "Bad-Name.py"
    bad.write_text("x = 1\n", encoding="utf-8")
    with patch("scripts.common.paths.repo_root", return_value=tmp_path):
        code = main()
    assert code == 1


def test_main_finding_relative_path_fallback(tmp_path: Path) -> None:
    from scripts.linting.check_filename_conventions import Finding

    outside_path = Path("/outside/Bad-Name.py")
    fake_findings = [Finding(path=outside_path, message="bad")]

    def fake_collect(_repo_root: Path) -> list[Path]:
        return []

    with (
        patch("scripts.common.paths.repo_root", return_value=tmp_path),
        patch(
            "scripts.linting.check_filename_conventions.collect_candidate_paths",
            side_effect=fake_collect,
        ),
        patch(
            "scripts.linting.check_filename_conventions.find_path_space_violations",
            return_value=fake_findings,
        ),
    ):
        code = main()
    assert code == 1
