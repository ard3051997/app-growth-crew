#!/bin/sh
set -eu

secret_file="${MCP_GC_SECRET_FILE:-/run/secrets/runtime.env}"
run_as=${MCP_GC_RUN_AS:-}

if [ ! -r "$secret_file" ]; then
    printf 'Required secret file is not readable: %s\n' "$secret_file" >&2
    exit 1
fi

while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
        ''|'#'*) continue ;;
    esac

    key=${line%%=*}
    value=${line#*=}
    if [ "$key" = "$line" ]; then
        printf 'Invalid secret line (expected KEY=VALUE): %s\n' "$key" >&2
        exit 1
    fi
    case "$key" in
        ''|[0-9]*|*[!A-Za-z0-9_]*)
            printf 'Invalid environment key in secret file: %s\n' "$key" >&2
            exit 1
            ;;
        *) ;;
    esac
    case "$key" in
        MCP_GC_MANAGED|MCP_GC_READ_ONLY|MCP_GC_FORCE_READ_ONLY|MCP_GC_API_AUTH_REQUIRED|MCP_GC_CONFIG_WRITES_ENABLED|MCP_GC_ENV|MCP_GC_INSECURE_DEV_WEBHOOKS)
            printf 'Ignoring protected managed control in secret file: %s\n' "$key" >&2
            continue
            ;;
    esac
    export "$key=$value"
done < "$secret_file"

if [ "${MCP_GC_MANAGED:-0}" = "1" ]; then
    export MCP_GC_API_AUTH_REQUIRED=1
    export MCP_GC_CONFIG_WRITES_ENABLED=0
    export MCP_GC_ENV=managed
    export MCP_GC_INSECURE_DEV_WEBHOOKS=0
fi

if [ "${MCP_GC_FORCE_READ_ONLY:-0}" = "1" ]; then
    export MCP_GC_READ_ONLY=1
fi

if [ "$(id -u)" = "0" ] && [ -n "$run_as" ]; then
    runtime_secret_dir=${MCP_GC_RUNTIME_SECRET_DIR:-/tmp/mcp-gc-secrets}
    mkdir -p "$runtime_secret_dir"
    chmod 700 "$runtime_secret_dir"
    for mounted_secret in /run/secrets/*; do
        [ -f "$mounted_secret" ] || continue
        destination="$runtime_secret_dir/$(basename "$mounted_secret")"
        cp "$mounted_secret" "$destination"
        chmod 400 "$destination"
        chown "$run_as" "$destination"
    done
    chown "$run_as" "$runtime_secret_dir"

    if command -v gosu >/dev/null 2>&1; then
        exec gosu "$run_as" "$@"
    fi
    if command -v su-exec >/dev/null 2>&1; then
        exec su-exec "$run_as" "$@"
    fi
    printf 'Cannot drop privileges: neither gosu nor su-exec is installed.\n' >&2
    exit 1
fi

exec "$@"
