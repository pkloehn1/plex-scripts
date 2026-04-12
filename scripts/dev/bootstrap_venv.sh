#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[FAIL] python3 not found on PATH." >&2
  exit 1
fi

cd "${repo_root}"
python3 -m scripts.dev.bootstrap_venv "$@"
