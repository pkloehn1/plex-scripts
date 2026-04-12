#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
compose_file="${COMPOSE_FILE:-${repo_root}/docker-compose-edge.yml}"
secrets_dir="${SECRETS_DIR:-${repo_root}/secrets}"

if [[ ! -f "${compose_file}" ]]; then
  printf 'ERROR: compose file not found: %s\n' "${compose_file}" >&2
  exit 2
fi

mapfile -t required_files < <(
  grep -E '^[[:space:]]*file:[[:space:]]*\$\{SECRETS_DIR\}/' "${compose_file}" |
    sed -E 's/^[[:space:]]*file:[[:space:]]*\$\{SECRETS_DIR\}\///' |
    sed -E 's/[[:space:]]*$//' |
    sort -u
)

if [[ "${#required_files[@]}" -eq 0 ]]; then
  printf "ERROR: no secrets discovered in %s (expected file: \${SECRETS_DIR}/...)\n" "${compose_file}" >&2
  exit 2
fi

mkdir -p "${secrets_dir}"
chmod 700 "${secrets_dir}"

created=0
for filename in "${required_files[@]}"; do
  path="${secrets_dir}/${filename}"
  if [[ -e "${path}" ]]; then
    continue
  fi

  umask 077
  : >"${path}"
  chmod 600 "${path}"
  created=$((created + 1))
  printf 'created: %s\n' "${path}"
done

printf '\nSecrets directory: %s\n' "${secrets_dir}"
printf 'Compose file (discovery source): %s\n' "${compose_file}"
printf 'Required secret files:\n'
for filename in "${required_files[@]}"; do
  printf '  - %s/%s\n' "${secrets_dir}" "${filename}"
done

empty=()
for filename in "${required_files[@]}"; do
  path="${secrets_dir}/${filename}"
  if [[ ! -s "${path}" ]]; then
    empty+=("${path}")
  fi
done

if [[ "${created}" -eq 0 ]]; then
  printf '\nNo changes (all required secret files already exist).\n'
else
  printf '\nCreated %d missing secret file(s). Populate them with real values on the node (never commit).\n' "${created}"
fi

if [[ "${#empty[@]}" -gt 0 ]]; then
  printf '\nWARNING: One or more secret files are empty. Populate before deployment:\n' >&2
  for path in "${empty[@]}"; do
    printf '  - %s\n' "${path}" >&2
  done
fi
