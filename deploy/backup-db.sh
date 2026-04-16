#!/usr/bin/env bash
# Daily SQLite backup — install as helix cron: 0 2 * * * /opt/helix/deploy/backup-db.sh
# Keeps 14 days of backups
BACKUP_DIR="/opt/helix/backups"
DB_PATH="/opt/helix/agent/data/pbx_assistant.db"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/pbx_assistant-$TIMESTAMP.db"

mkdir -p "$BACKUP_DIR"

# Use SQLite online backup (safe while agent is running)
sqlite3 "$DB_PATH" ".backup '$DEST'"

# Compress
gzip "$DEST"

# Prune older than 14 days
find "$BACKUP_DIR" -name "pbx_assistant-*.db.gz" -mtime +14 -delete

echo "Backup: $DEST.gz"
