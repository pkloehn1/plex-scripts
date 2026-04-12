#!/usr/bin/env bash
# Setup TrueNAS container directories and permissions.
#
# Run on TrueNAS before deploying containers.
# See: docs/infrastructure/truenas-container-deployment.md
#
# Prerequisites:
#   - apps-pool ZFS pool must exist
#   - Run as root or with sudo
#
# Usage:
#   scp scripts/truenas/setup_container_dirs.sh truenas:/tmp/
#   ssh truenas sudo /tmp/setup_container_dirs.sh

set -Eeuo pipefail

POOL_PATH="/mnt/apps-pool"
STORAGE_PATH="/mnt/zfs-storage-prod-01"

# Guard against running when the storage dataset is not mounted.
if [[ ! -d "$STORAGE_PATH" ]]; then
  printf 'ERROR: Expected storage path "%s" does not exist. Is the zfs-storage-prod-01 dataset created?\n' "$STORAGE_PATH" >&2
  exit 1
fi

if ! mountpoint -q "$STORAGE_PATH"; then
  printf 'ERROR: Storage path "%s" is not a mountpoint. Refusing to create directories on the boot pool.\n' "$STORAGE_PATH" >&2
  printf '       Ensure the zfs-storage-prod-01 dataset is mounted on "%s" and re-run this script.\n' "$STORAGE_PATH" >&2
  exit 1
fi

printf 'Setting up TrueNAS container directories...\n'

# Create directories
printf 'Creating directories...\n'
mkdir -p "$POOL_PATH/postgres/authentik"
mkdir -p "$POOL_PATH/postgres/servarr"
mkdir -p "$POOL_PATH/pgadmin"
mkdir -p "$POOL_PATH/secrets"
mkdir -p "$POOL_PATH/backups"
mkdir -p "$POOL_PATH/sabnzbd"
mkdir -p "$STORAGE_PATH/downloads/usenet"

# Set ownership - PostgreSQL containers run as UID 70
printf 'Setting PostgreSQL directory ownership (UID 70)...\n'
chown -R 70:70 "$POOL_PATH/postgres"
chmod 700 "$POOL_PATH/postgres/authentik"
chmod 700 "$POOL_PATH/postgres/servarr"

# Set ownership - pgAdmin runs as UID 5050
printf 'Setting pgAdmin directory ownership (UID 5050)...\n'
chown -R 5050:5050 "$POOL_PATH/pgadmin"
chmod 700 "$POOL_PATH/pgadmin"

# Set ownership - SABnzbd config (docker-svc 2000:2000)
printf 'Setting SABnzbd config directory ownership (UID 2000)...\n'
chown -R 2000:2000 "$POOL_PATH/sabnzbd"
chmod 700 "$POOL_PATH/sabnzbd"

# Set ownership - SABnzbd downloads (docker-svc 2000:2000)
# Non-recursive: SABnzbd owns files it creates; avoid traversing terabytes on re-runs.
printf 'Setting SABnzbd downloads directory ownership (UID 2000)...\n'
chown 2000:2000 "$STORAGE_PATH/downloads/usenet"

# Verify aclmode=passthrough before chmod (restricted mode rejects POSIX chmod).
ACLMODE=$(zfs get -H -o value aclmode zfs-storage-prod-01/downloads 2>/dev/null || true)
if [[ "$ACLMODE" != "passthrough" ]]; then
  printf 'ERROR: ZFS aclmode on zfs-storage-prod-01/downloads is "%s" (expected "passthrough").\n' "$ACLMODE" >&2
  printf '       Run: zfs set aclmode=passthrough zfs-storage-prod-01/downloads\n' >&2
  exit 1
fi
chmod 775 "$STORAGE_PATH/downloads/usenet"

# Secrets directory - restricted access
printf 'Setting secrets directory permissions...\n'
chmod 700 "$POOL_PATH/secrets"

printf '\nDirectory setup complete. Next steps:\n'
printf '  1. Run setup_secrets.sh to create password files\n'
printf '  2. Copy init script: scp scripts/truenas/init_servarr_databases.sh truenas:%s/postgres/\n' "$POOL_PATH"
printf '  3. Deploy containers via TrueNAS Apps > Custom App\n'
printf '\nSee docs/infrastructure/truenas-container-deployment.md for details.\n'
