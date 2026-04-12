#!/usr/bin/env python3

"""Compatibility wrapper.

This repository now enforces a broader naming rule (short identifiers) rather than
a special-case rule for argparse.ArgumentParser variables.

Kept as a thin forwarder to avoid breaking older tooling references.
"""

from __future__ import annotations

from scripts.linting.check_short_identifier_names import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
