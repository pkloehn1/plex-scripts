#!/usr/bin/env python3
"""Validate GitHub Copilot instruction file token limits.

Wrapper script for the context_validator package.
"""

import sys

from scripts.context_validator.main import main

if __name__ == "__main__":
    sys.exit(main())
