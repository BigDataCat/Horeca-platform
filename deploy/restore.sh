#!/usr/bin/env bash
# Restore a backup into the running stack. DESTRUCTIVE: replaces the current database contents.
#   ./restore.sh /var/backups/horeca/horeca-20261003-021500.dump
# Test it regularly on a staging stack: an untested backup is a hope, not a backup.
set -euo pipefail

[ $# -eq 1 ] && [ -f "$1" ] || { echo "usage: $0 <backup.dump>" >&2; exit 1; }
cd "$(dirname "$0")"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env)

read -r -p "This REPLACES the current database with $1. Type 'restore' to continue: " answer
[ "$answer" = "restore" ] || { echo "aborted"; exit 1; }

"${COMPOSE[@]}" stop backend worker
"${COMPOSE[@]}" exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$1"
"${COMPOSE[@]}" run --rm migrate          # bring an older dump up to the current schema
"${COMPOSE[@]}" up -d backend worker
echo "restore finished"
