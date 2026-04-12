"""GitHub automation helpers using the GitHub CLI.

All modules in this package are intended to be:
- Safe to run from CI or local dev machines.
- Offline-testable (core logic separated from `gh` subprocess I/O).

"""
