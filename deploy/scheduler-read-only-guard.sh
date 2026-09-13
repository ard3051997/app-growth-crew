#!/bin/sh
set -eu

db_path=${MCP_GC_DB_PATH:-/app/data/store_performance.db}

if [ "${MCP_GC_READ_ONLY:-1}" = "1" ]; then
    if [ ! -r "$db_path" ]; then
        printf 'Read-only guard cannot inspect SQLite database: %s\n' "$db_path" >&2
        exit 1
    fi

    approved=$(sqlite3 -readonly "$db_path" "SELECT count(*) FROM experiments WHERE status = 'approved';")
    if [ "$approved" -ne 0 ]; then
        printf 'Read-only guard refused scheduler startup: %s approved experiment(s) can execute writes.\n' "$approved" >&2
        exit 1
    fi
fi

exec "$@"
