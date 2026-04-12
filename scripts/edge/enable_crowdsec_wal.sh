#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"

runtime_config_dir="/opt/services/data/crowdsec/etc"
runtime_config_file="${runtime_config_dir}/config.yaml"

template_config_file="${repo_root}/app-config/crowdsec/config.yaml"

if [[ ! -f "${template_config_file}" ]]; then
  printf 'ERROR: Missing template config: %s\n' "${template_config_file}" >&2
  exit 1
fi

mkdir -p "${runtime_config_dir}"

if [[ ! -f "${runtime_config_file}" ]]; then
  # Seed the runtime config if it doesn't exist yet.
  install -m 0644 "${template_config_file}" "${runtime_config_file}"
fi

# Ensure WAL is enabled (idempotent).
# - Replace any existing `use_wal: <value>` line
# - If no line exists, insert it under `db_config:`
if grep -qE '^\s*use_wal:\s*(true|false)\s*$' "${runtime_config_file}"; then
  sed -i -E 's/^([[:space:]]*use_wal:)[[:space:]]*(true|false)[[:space:]]*$/\1 true/' "${runtime_config_file}"
else
  # Insert after the db_config: header with 2-space indentation.
  awk '
    { print }
    /^db_config:$/ {
      print "  use_wal: true"
    }
  ' "${runtime_config_file}" >"${runtime_config_file}.tmp"
  mv "${runtime_config_file}.tmp" "${runtime_config_file}"
fi

if ! grep -qE '^\s*use_wal:\s*true\s*$' "${runtime_config_file}"; then
  printf 'ERROR: Failed to enable WAL in %s\n' "${runtime_config_file}" >&2
  exit 1
fi

printf 'OK: SQLite WAL enabled in %s\n' "${runtime_config_file}"
