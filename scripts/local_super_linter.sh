#!/usr/bin/env bash
set -Eeuo pipefail

# Run Super-Linter locally using Docker
# Usage: ./scripts/local-super-linter.sh

REPO_ROOT="$(git rev-parse --show-toplevel)"
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

printf "Running Super-Linter...\n"
docker run --rm \
  -e RUN_LOCAL=true \
  -v "${REPO_ROOT}:/tmp/lint" \
  "${ENV_ARGS[@]}" \
  ghcr.io/super-linter/super-linter:v8
