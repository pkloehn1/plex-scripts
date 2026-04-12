"""Tests for scripts.linting.check_argparse_parser_names."""

from __future__ import annotations


def test_import_re_exports_main() -> None:
    from scripts.linting.check_argparse_parser_names import main
    from scripts.linting.check_short_identifier_names import main as original_main

    assert main is original_main
