#!/usr/bin/env bash
# Daily PostgreSQL backup with rotation. Run from cron, e.g.:
#   15 2 * * * /opt/horeca/deploy/backup.sh >> /var/log/horeca-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/horeca}"
KEEP_DAYS="${KEEP_DAYS:-14}"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env)

mkdir -p "$BACKUP_DIR"
FILE="$BACKUP_DIR/horeca-$(date +%Y%m%d-%H%M%S).dump"

"${COMPOSE[@]}" exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$FILE.partial"
mv "$FILE.partial" "$FILE"
# A backup that cannot be listed is not a backup.
"${COMPOSE[@]}" exec -T postgres pg_restore --list < "$FILE" > /dev/null

find "$BACKUP_DIR" -name 'horeca-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "backup ok: $FILE ($(du -h "$FILE" | cut -f1))"
