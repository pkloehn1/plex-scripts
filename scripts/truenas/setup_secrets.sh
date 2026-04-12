#!/usr/bin/env bash
# Setup TrueNAS container secrets.
#
# Run on TrueNAS to generate password files for containers.
# See: docs/infrastructure/truenas-container-deployment.md
#
# Prerequisites:
#   - Run setup_container_dirs.sh first
#   - Run as root or with sudo
#
# Usage:
#   scp scripts/truenas/setup_secrets.sh truenas:/tmp/
#   ssh truenas sudo /tmp/setup_secrets.sh

set -Eeuo pipefail

SECRETS_PATH="/mnt/apps-pool/secrets"

printf 'Setting up TrueNAS container secrets...\n'

# Check if secrets directory exists
if [[ ! -d "$SECRETS_PATH" ]]; then
  printf 'ERROR: Secrets directory does not exist: %s\n' "$SECRETS_PATH" >&2
  printf 'Run setup_container_dirs.sh first.\n' >&2
  exit 1
fi

# Function to create a secret file if it doesn't exist
create_secret() {
  local name="$1"
  local owner="$2"
  local path="$SECRETS_PATH/$name"

  if [[ -f "$path" ]]; then
    printf '  %s: already exists (skipping)\n' "$name"
  else
    openssl rand -base64 32 >"$path"
    chmod 600 "$path"
    chown "$owner" "$path"
    printf '  %s: created\n' "$name"
  fi
  return 0
}

printf 'Creating password files...\n'

# PostgreSQL passwords (UID 70)
create_secret "servarr_pg_pass" "70:70"
create_secret "authentik_pg_pass" "70:70"

# pgAdmin password (UID 5050)
create_secret "pgadmin_password" "5050:5050"

printf '\nSecrets setup complete.\n'
printf '\nIMPORTANT: Save these passwords for application configuration:\n\n'

printf 'servarr_pg_pass:\n'
cat "$SECRETS_PATH/servarr_pg_pass"
printf '\n\n'

printf 'authentik_pg_pass:\n'
cat "$SECRETS_PATH/authentik_pg_pass"
printf '\n\n'

printf 'pgadmin_password:\n'
cat "$SECRETS_PATH/pgadmin_password"
printf '\n'
