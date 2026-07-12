#!/bin/bash
# Sauvegarde quotidienne Kinder School International (base MySQL + medias)
# Usage : ~/kanderschoolinternational/scripts/backup_kinder.sh
# Prerequis : le mot de passe MySQL doit etre dans ~/.my.cnf (chmod 600), jamais ici.
set -euo pipefail

BACKUP_DIR="$HOME/backups"
PROJECT_DIR="$HOME/kanderschoolinternational"
DB_NAME='myschoolgn$kinderdb'
DB_USER='myschoolgn'
DB_HOST='myschoolgn.mysql.pythonanywhere-services.com'
KEEP_DAYS=7
STAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# 1. Base de donnees (--no-tablespaces requis sur PythonAnywhere)
mysqldump -u "$DB_USER" -h "$DB_HOST" --no-tablespaces "$DB_NAME" \
    | gzip > "$BACKUP_DIR/kinderdb_${STAMP}.sql.gz"

# 2. Medias (photos eleves, logos, documents uploades)
if [ -d "$PROJECT_DIR/media" ]; then
    tar czf "$BACKUP_DIR/media_${STAMP}.tar.gz" -C "$PROJECT_DIR" media
fi

# 3. Rotation : supprimer les sauvegardes de plus de KEEP_DAYS jours
find "$BACKUP_DIR" -name 'kinderdb_*.sql.gz' -mtime +"$KEEP_DAYS" -delete
find "$BACKUP_DIR" -name 'media_*.tar.gz' -mtime +"$KEEP_DAYS" -delete

echo "Sauvegarde terminee : $STAMP"
ls -lh "$BACKUP_DIR" | tail -6
