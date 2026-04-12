#!/usr/bin/env bash
set -Eeuo pipefail

# Run Super-Linter locally using Docker
# https://github.com/super-linter/super-linter
#
# Usage:
#   ./scripts/linting/run_super_linter.sh

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${REPO_ROOT}/.github/super-linter.env"
ENV_ARGS=()

if [[ -f "${ENV_FILE}" ]]; then
  printf "Loading configuration from %s...\n" "${ENV_FILE}"
  while IFS='=' read -r key value; do
    if [[ "${key}" =~ ^[^#]*$ ]] && [[ -n "${key}" ]]; then
      ENV_ARGS+=(-e "${key}=${value}")
    fi
  done <"${ENV_FILE}"
fi

printf "Running Super-Linter on: %s\n" "${REPO_ROOT}"

docker run \
  --rm \
  -e RUN_LOCAL=true \
  -e DEFAULT_BRANCH=main \
  -v "${REPO_ROOT}:/tmp/lint" \
  "${ENV_ARGS[@]}" \
  ghcr.io/super-linter/super-linter:v8
