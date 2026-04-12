#!/usr/bin/env bash
# PostgreSQL init script for Servarr applications.
#
# Creates databases for Sonarr, Radarr, and Prowlarr.
# This script runs automatically on first container start.
# See: docs/infrastructure/truenas-container-deployment.md
#
# Deployment:
#   scp scripts/truenas/init_servarr_databases.sh truenas:/mnt/apps-pool/postgres/
#   Mount in servarr-postgres container as:
#     /docker-entrypoint-initdb.d/init_servarr_databases.sh:ro

set -Eeuo pipefail

printf 'Creating Servarr databases...\n'

for db in sonarr sonarr_log radarr radarr_log prowlarr prowlarr_log; do
  printf 'Creating database: %s\n' "$db"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE DATABASE $db;
GRANT ALL PRIVILEGES ON DATABASE $db TO $POSTGRES_USER;
EOSQL
done

printf 'Servarr databases created successfully.\n'
