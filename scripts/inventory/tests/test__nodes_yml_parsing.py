from __future__ import annotations

import pytest

from scripts.inventory._nodes_yml_parsing import (
    optional_int,
    optional_str,
    parse_node_base_fields,
    parse_str_list,
    require_str_field,
    validate_network_interfaces,
)


def test_optional_str_raises_on_non_string() -> None:
    with pytest.raises(ValueError, match="Expected string or null"):
        optional_str(42)


def test_optional_int_raises_on_bool() -> None:
    with pytest.raises(ValueError, match="Expected int or null"):
        optional_int(True)


def test_optional_int_raises_on_float() -> None:
    with pytest.raises(ValueError, match="Expected int or null"):
        optional_int(3.14)


def test_parse_str_list_raises_on_non_list() -> None:
    with pytest.raises(ValueError, match="must be a list of strings"):
        parse_str_list({"roles": "not-a-list"}, "myhost", "roles")


def test_parse_str_list_raises_on_non_string_items() -> None:
    with pytest.raises(ValueError, match="must be a list of strings"):
        parse_str_list({"roles": [1, 2]}, "myhost", "roles")


def test_require_str_field_raises_on_missing() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        require_str_field({}, "hostname")


def test_require_str_field_raises_on_empty_string() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        require_str_field({"hostname": "   "}, "hostname")


def test_validate_network_interfaces_raises_on_non_dict_network() -> None:
    with pytest.raises(ValueError, match="network must be a mapping"):
        validate_network_interfaces("myhost", {"network": "bad"})


def test_validate_network_interfaces_raises_on_non_list_interfaces() -> None:
    with pytest.raises(ValueError, match=r"network\.interfaces must be a list"):
        validate_network_interfaces("myhost", {"network": {"interfaces": "bad"}})


def test_validate_network_interfaces_raises_on_non_dict_entry() -> None:
    with pytest.raises(ValueError, match="entries must be mappings"):
        validate_network_interfaces("myhost", {"network": {"interfaces": ["not-a-dict"]}})


def test_validate_network_interfaces_raises_on_empty_name() -> None:
    with pytest.raises(ValueError, match="name must be a non-empty string"):
        validate_network_interfaces(
            "myhost",
            {"network": {"interfaces": [{"name": "", "addresses": ["192.0.2.1/24"]}]}},
        )


def test_validate_network_interfaces_raises_on_non_list_addresses() -> None:
    with pytest.raises(ValueError, match="addresses must be a list of strings"):
        validate_network_interfaces(
            "myhost",
            {"network": {"interfaces": [{"name": "eth0", "addresses": "bad"}]}},
        )


def test_parse_node_base_fields_raises_on_non_dict() -> None:
    with pytest.raises(ValueError, match="Each node entry must be a mapping"):
        parse_node_base_fields("not-a-dict")


def test_parse_node_base_fields_raises_on_cpu_non_dict() -> None:
    with pytest.raises(ValueError, match="cpu must be a mapping"):
        parse_node_base_fields({"hostname": "myhost", "cpu": "bad"})


def test_parse_node_base_fields_raises_on_software_non_dict() -> None:
    with pytest.raises(ValueError, match="software must be a mapping"):
        parse_node_base_fields({"hostname": "myhost", "software": "bad"})
