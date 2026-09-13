#!/bin/sh
set -eu

db_path=${MCP_GC_DB_PATH:-/app/data/store_performance.db}
backup_dir=${MCP_GC_BACKUP_DIR:-/backups}
retention_days=${BACKUP_RETENTION_DAYS:-14}
command=${1:-backup}

mkdir -p "$backup_dir"

backup_database() {
    if [ ! -r "$db_path" ]; then
        printf 'SQLite database is not readable: %s\n' "$db_path" >&2
        exit 1
    fi

    timestamp=$(date -u +%Y%m%dT%H%M%SZ)
    backup_name="store-performance-${timestamp}.db"
    temporary="$backup_dir/.${backup_name}.tmp"
    destination="$backup_dir/$backup_name"

    sqlite3 "$db_path" ".timeout 10000" ".backup '$temporary'"
    sqlite3 -readonly "$temporary" "PRAGMA quick_check;" | grep -qx ok
    mv "$temporary" "$destination"
    (cd "$backup_dir" && sha256sum "$backup_name" > "$backup_name.sha256")
    find "$backup_dir" -type f -name 'store-performance-*.db*' -mtime "+$retention_days" -delete
    printf '%s\n' "$backup_name"
}

case "$command" in
    backup)
        backup_database
        ;;
    list)
        find "$backup_dir" -maxdepth 1 -type f -name 'store-performance-*.db' -print | sort
        ;;
    restore)
        restore_name=${2:-}
        if [ -z "$restore_name" ] || [ "$restore_name" != "$(basename "$restore_name")" ]; then
            printf 'Usage: db-tools restore <backup-filename>\n' >&2
            exit 2
        fi
        if [ "${CONFIRM_RESTORE:-}" != "yes" ]; then
            printf 'Restore refused; set CONFIRM_RESTORE=yes after stopping API and scheduler.\n' >&2
            exit 2
        fi

        source_file="$backup_dir/$restore_name"
        if [ ! -r "$source_file" ]; then
            printf 'Backup is not readable: %s\n' "$source_file" >&2
            exit 1
        fi
        if [ -r "$source_file.sha256" ]; then
            (cd "$backup_dir" && sha256sum -c "$restore_name.sha256")
        fi

        if [ -e "$db_path" ]; then
            backup_database >/dev/null
        fi
        restore_tmp="${db_path}.restore.tmp"
        rm -f "$restore_tmp"
        sqlite3 "$restore_tmp" ".restore '$source_file'"
        sqlite3 -readonly "$restore_tmp" "PRAGMA quick_check;" | grep -qx ok
        mv "$restore_tmp" "$db_path"
        printf 'Restored %s\n' "$restore_name"
        ;;
    *)
        printf 'Usage: db-tools {backup|list|restore <backup-filename>}\n' >&2
        exit 2
        ;;
esac
