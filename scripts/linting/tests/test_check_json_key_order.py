from __future__ import annotations

import json
from pathlib import Path

from scripts.linting.check_json_key_order import check_file, main


def test_sorted_file_passes(tmp_path: Path) -> None:
    file = tmp_path / "sorted.json"
    file.write_text(
        json.dumps({"alpha": 1, "beta": 2, "gamma": 3}, indent=2) + "\n",
        encoding="utf-8",
    )

    assert check_file(file) == []


def test_unsorted_top_level_fails(tmp_path: Path) -> None:
    file = tmp_path / "unsorted.json"
    content = '{\n  "beta": 1,\n  "alpha": 2\n}\n'
    file.write_text(content, encoding="utf-8")

    findings = check_file(file)
    assert len(findings) == 1
    assert "alpha" in findings[0].message
    assert findings[0].path == file


def test_unsorted_nested_keys_fails(tmp_path: Path) -> None:
    file = tmp_path / "nested.json"
    data = {"outer": {"zebra": 1, "apple": 2}}
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    findings = check_file(file)
    assert len(findings) == 1
    assert "apple" in findings[0].message
    assert "$.outer" in findings[0].message


def test_array_ordering_not_enforced(tmp_path: Path) -> None:
    file = tmp_path / "arrays.json"
    data = {"items": ["cherry", "apple", "banana"]}
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert check_file(file) == []


def test_case_insensitive_sorting(tmp_path: Path) -> None:
    file = tmp_path / "case.json"
    data = {"Alpha": 1, "beta": 2, "Gamma": 3}
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert check_file(file) == []


def test_empty_object_passes(tmp_path: Path) -> None:
    file = tmp_path / "empty.json"
    file.write_text("{}\n", encoding="utf-8")

    assert check_file(file) == []


def test_non_object_root_passes(tmp_path: Path) -> None:
    file = tmp_path / "array_root.json"
    file.write_text("[1, 2, 3]\n", encoding="utf-8")

    assert check_file(file) == []


def test_invalid_json_returns_finding(tmp_path: Path) -> None:
    file = tmp_path / "bad.json"
    file.write_text("{not valid json", encoding="utf-8")

    findings = check_file(file)
    assert len(findings) == 1
    assert "Invalid JSON" in findings[0].message


def test_main_returns_zero_on_pass(tmp_path: Path) -> None:
    file = tmp_path / "ok.json"
    file.write_text('{"a": 1, "b": 2}\n', encoding="utf-8")

    assert main([str(file)]) == 0


def test_main_returns_one_on_failure(tmp_path: Path) -> None:
    file = tmp_path / "bad.json"
    file.write_text('{"b": 1, "a": 2}\n', encoding="utf-8")

    assert main([str(file)]) == 1


def test_bracket_sections_sort_before_plain_keys(tmp_path: Path) -> None:
    """Bracket-prefixed keys like [python] sort before plain keys."""
    file = tmp_path / "settings.json"
    data = {"[python]": {"a": 1}, "zulu": 2}
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert check_file(file) == []


def test_unreadable_file_returns_finding(tmp_path: Path) -> None:
    file = tmp_path / "missing.json"

    findings = check_file(file)
    assert len(findings) == 1
    assert "Cannot read file" in findings[0].message


def test_main_returns_zero_on_no_args() -> None:
    assert main([]) == 0


def test_array_with_nested_objects_checked(tmp_path: Path) -> None:
    file = tmp_path / "arr_obj.json"
    data = {"items": [{"z": 1, "a": 2}]}
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    findings = check_file(file)
    assert len(findings) == 1
    assert "$[0]" in findings[0].message or "$.items[0]" in findings[0].message


def test_first_key_out_of_order_uses_should_be_first_message(tmp_path: Path) -> None:
    file = tmp_path / "first.json"
    content = '{\n  "zebra": 1,\n  "alpha": 2\n}\n'
    file.write_text(content, encoding="utf-8")

    findings = check_file(file)
    assert len(findings) == 1
    assert "should be first" in findings[0].message
    assert "should come after" not in findings[0].message


def test_root_array_with_unsorted_nested_objects(tmp_path: Path) -> None:
    file = tmp_path / "root_arr.json"
    data = [{"z": 1, "a": 2}]
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    findings = check_file(file)
    assert len(findings) == 1
    assert "$[0]" in findings[0].message


def test_non_first_key_out_of_order_uses_should_come_after_message(
    tmp_path: Path,
) -> None:
    file = tmp_path / "mid.json"
    content = '{\n  "alpha": 1,\n  "gamma": 2,\n  "beta": 3\n}\n'
    file.write_text(content, encoding="utf-8")

    findings = check_file(file)
    assert len(findings) == 1
    assert "should come after" in findings[0].message
    assert "should be first" not in findings[0].message


def test_primitive_root_passes(tmp_path: Path) -> None:
    file = tmp_path / "string.json"
    file.write_text('"just a string"\n', encoding="utf-8")

    assert check_file(file) == []


def test_root_array_with_sorted_nested_objects(tmp_path: Path) -> None:
    file = tmp_path / "root_arr_ok.json"
    data = [{"a": 1, "z": 2}]
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert check_file(file) == []


def test_deeply_nested_violation(tmp_path: Path) -> None:
    file = tmp_path / "deep.json"
    data = {"level1": {"level2": {"zoo": 1, "ant": 2}}}
    file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    findings = check_file(file)
    assert len(findings) == 1
    assert "$.level1.level2" in findings[0].message
