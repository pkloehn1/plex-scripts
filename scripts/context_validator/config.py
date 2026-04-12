"""Configuration and constants for context validation."""

import argparse
import sys
from pathlib import Path
from typing import Any

# =============================================================================
# LLM Provider Configurations
# =============================================================================
# Context windows are from official provider documentation (December 2025).
# Instruction limits are 4% of context window (middle of 3-5% recommended range).
# Reference: https://docs.github.com/copilot/reference/ai-models/supported-models
#
# File patterns are based on GitHub Copilot agent instructions documentation:
# - CLAUDE.md: Anthropic Claude models
# - GEMINI.md: Google Gemini models
# - AGENTS.md, .github/copilot-instructions.md: Default (any model)
# =============================================================================
LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "display_name": "Anthropic Claude",
        "file_patterns": ["CLAUDE.md"],
        "context_window_tokens": 200_000,  # Claude Sonnet 4/4.5, Opus 4/4.5, Haiku 4.5
        "instruction_limit_pct": 4,  # 4% of context window
    },
    "google": {
        "display_name": "Google Gemini",
        "file_patterns": ["GEMINI.md"],
        "context_window_tokens": 1_048_576,  # Gemini 2.5/3 Pro
        "instruction_limit_pct": 4,  # 4% of context window
    },
    "openai": {
        "display_name": "OpenAI GPT",
        "file_patterns": ["GPT.md", "OPENAI.md"],
        "context_window_tokens": 1_047_576,  # GPT-4.1
        "instruction_limit_pct": 4,  # 4% of context window
    },
    "xai": {
        "display_name": "xAI Grok",
        "file_patterns": ["GROK.md", "XAI.md"],
        "context_window_tokens": 1_000_000,  # Grok Code Fast 1
        "instruction_limit_pct": 4,  # 4% of context window
    },
    "default": {
        "display_name": "Default (Copilot)",
        "file_patterns": [
            "AGENTS.md",
            ".github/copilot-instructions.md",
            ".github/instructions/*.instructions.md",
            ".github/prompts/*.prompt.md",
            ".github/agents/*.agent.md",
        ],
        # Use most conservative limit (Claude's 200K) for generic files
        "context_window_tokens": 200_000,
        "instruction_limit_pct": 4,  # 4% of context window
    },
}


def load_config(config_path: Path) -> dict[str, int | float]:
    """Load configuration from copilot-limits.conf."""
    config = {}
    if not config_path.exists():
        print(f"ERROR: Configuration file not found: {config_path}")
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                value = value.strip()
                # Parse as float if contains decimal point, else int
                if "." in value:
                    config[key.strip()] = float(value)
                else:
                    config[key.strip()] = int(value)
    return config


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate GitHub Copilot instruction file character limits.",
    )
    parser.add_argument(
        "--compare-to",
        metavar="BRANCH",
        help="Compare changed files against baseline from BRANCH (e.g., origin/main)",
    )
    return parser.parse_args()
