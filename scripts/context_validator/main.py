"""Main entry point for context validation."""

import sys
from dataclasses import dataclass, field
from pathlib import Path

from scripts.common.paths import repo_root

from .config import LLM_PROVIDERS, load_config, parse_args
from .utils import find_files
from .validator import ValidationResult, validate_file

_STATUS_ICONS = {
    "error": "[ERR]",
    "warning": "[WARN]",
    "info": "[INFO]",
}


@dataclass
class _RunTotals:
    errors: int = 0
    warnings: int = 0
    overall_tokens: int = 0
    overall_files: int = 0
    current_section: str = ""
    section_tokens: int = 0
    section_files: int = 0
    category_totals: dict[str, int] = field(default_factory=dict)

    def close_section(self) -> None:
        """Flush the current section totals before switching to a new one."""
        if not self.current_section:
            return
        prev = self.category_totals.get(self.current_section, 0)
        self.category_totals[self.current_section] = prev + self.section_tokens
        if self.section_files > 1:
            print(f"  --- {self.section_tokens} tokens ({self.section_files} files)")

    def open_section(self, name: str) -> None:
        self.close_section()
        print(f"\n{name}:")
        self.current_section = name
        self.section_tokens = 0
        self.section_files = 0

    def record(self, result: ValidationResult) -> None:
        self.section_tokens += result.token_count
        self.section_files += 1
        self.overall_tokens += result.token_count
        self.overall_files += 1
        if result.status == "error":
            self.errors += 1
        elif result.status == "warning":
            self.warnings += 1


def _print_result(result: ValidationResult, repo_root: Path) -> None:
    icon = _STATUS_ICONS.get(result.status, "[OK]")
    provider_name = LLM_PROVIDERS[result.provider]["display_name"]
    rel_path = Path(result.path).relative_to(repo_root)
    print(
        f"  {icon} {rel_path!s:<50} "
        f"{result.token_count:>5} / {result.token_limit:>5} tokens "
        f"({result.char_count:>6} chars) [{provider_name}]"
    )


_MULTI_AGENT_WORKSPACE = "Multi-Agent Workspace"

# File patterns to check (limits are determined by LLM_PROVIDERS)
_FILE_CHECKS = [
    ("Repository Instructions", ".github/copilot-instructions.md"),
    ("Path-Specific Instructions", ".github/instructions/**/*.instructions.md"),
    ("Prompt Files", ".github/prompts/**/*.prompt.md"),
    ("Custom Agents", ".github/agents/**/*.agent.md"),
    (_MULTI_AGENT_WORKSPACE, "AGENTS.md"),
    (_MULTI_AGENT_WORKSPACE, "CLAUDE.md"),
    (_MULTI_AGENT_WORKSPACE, "GEMINI.md"),
    (_MULTI_AGENT_WORKSPACE, "GPT.md"),
    (_MULTI_AGENT_WORKSPACE, "GROK.md"),
]


def _load_run_config() -> tuple[Path, dict[str, int]]:
    """Load config file and return repo root with parsed settings."""
    root = repo_root()
    config_path = root / "scripts" / "copilot-context-health.conf"
    config = load_config(config_path)
    return root, {
        "info_pct": int(config.get("INFO_THRESHOLD_PERCENT", 50)),
        "warn_pct": int(config.get("WARN_THRESHOLD_PERCENT", 75)),
        "chars_per_token": int(config.get("CHARS_PER_TOKEN", 4)),
    }


def _validate_files(repo_root: Path, cfg: dict[str, int]) -> _RunTotals:
    """Walk file checks and accumulate validation results."""
    totals = _RunTotals()
    for section, pattern in _FILE_CHECKS:
        for file_path in find_files(repo_root, pattern):
            if section != totals.current_section:
                totals.open_section(section)
            result = validate_file(file_path, cfg["chars_per_token"], cfg["info_pct"], cfg["warn_pct"])
            totals.record(result)
            _print_result(result, repo_root)
    totals.close_section()
    return totals


def _print_summary(totals: _RunTotals) -> int:
    """Print final summary and return exit code."""
    print("=" * 70)
    print(f"Total: {totals.overall_tokens} tokens across {totals.overall_files} files")
    if totals.errors > 0:
        print(f"\nFAILED: Found {totals.errors} files exceeding token limits.")
        return 1
    if totals.warnings > 0:
        print(f"\nWARNING: Found {totals.warnings} files approaching token limits.")
    else:
        print("\nSUCCESS: All files within token limits.")
    return 0


def main() -> int:
    """Main entry point."""
    args = parse_args()
    repo_root, cfg = _load_run_config()
    print("Validating GitHub Copilot instruction file token limits...")
    print("Provider limits: 4% of context window (Claude: 8K, Gemini: 42K, GPT: 42K)")
    if args.compare_to:
        print(f"Baseline comparison mode: comparing to {args.compare_to}")
    print("=" * 70)
    totals = _validate_files(repo_root, cfg)
    return _print_summary(totals)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
