# Managed self-hosted beta runbook

This bundle runs one private, single-tenant MCP-GC installation:

- `proxy`: the only published service; Caddy serves the built React application, requires HTTP Basic authentication for operator routes, and authenticates proxied API traffic with internal-only headers.
- `api`: FastAPI on an internal-only network.
- `scheduler`: the existing autonomous scheduler, sharing the SQLite volume with the API.
- `backup`: an on-demand SQLite online-backup/restore utility in the `tools` profile.
- `mcp-gc-beta-data`: persistent SQLite data.
- `mcp-gc-beta-backups`: persistent, checksummed backups.

The default host bind is `127.0.0.1:8080`. Keep it loopback-only and reach it with an SSH tunnel or private ingress. Basic authentication over public plain HTTP is not safe; terminate TLS at a private ingress before changing `MCP_GC_BIND_ADDRESS` to a non-loopback address.

## Source packaging constraint

The repository's existing `Dockerfile` intentionally builds the published `play-store-mcp` wheel and starts its console script. The Hatch wheel package list in `pyproject.toml` does **not** include `src/api_server/` or `src/run_autonomous_loop.py`, so that image cannot run this bundle.

`deploy/backend.Dockerfile` therefore uses the repository root as its context, installs locked Python dependencies from the root `pyproject.toml`/`uv.lock`, copies `src/`, and sets `PYTHONPATH=/app/src`. This is a source-tree beta image, not proof that the API or scheduler is wheel-installable. The frontend is independently built from `frontend/package-lock.json` with `npm ci`; the root npm package is not used. Dockerfile-specific ignore files prevent local config, credentials, data, and unrelated root files from entering either build context.

The current frontend source also fails its package-level `npm run build` because `ExperimentCenter.tsx` contains an unused `ArrowDownRight` import. The deployment build does not edit source: it runs TypeScript checks with only `noUnusedLocals` relaxed, then runs Vite. Remove that exception after the frontend package's standard build is clean.

## 1. Prerequisites

- Docker Engine with Compose v2 (`docker compose version`).
- A private host or private ingress with enough space for images, SQLite, and backups.
- One app configuration and least-privilege integration credentials.

Run all commands from the repository root, where `compose.yaml` and `pyproject.toml` live.

## 2. Prepare configuration and secrets

Create operator-owned files from the tracked templates:

```sh
cp deploy/config/apps.json.example deploy/config/apps.json
cp deploy/secrets/backend.env.example deploy/secrets/backend.env
cp deploy/secrets/scheduler.env.example deploy/secrets/scheduler.env
cp deploy/secrets/proxy.env.example deploy/secrets/proxy.env
chmod 600 deploy/secrets/backend.env deploy/secrets/scheduler.env deploy/secrets/proxy.env
chmod 600 deploy/secrets/google-service-account.json deploy/secrets/google-service-account-read-only.json
```

Edit `deploy/config/apps.json` for exactly one tenant/app. Keep secret fields `null`; never put host machine paths or credentials in this file. Put credential files in `deploy/secrets/`, for example:

```text
deploy/secrets/google-service-account.json
deploy/secrets/google-service-account-read-only.json
```

Compose mounts only each service's declared secrets. A root-only launcher uses narrowly scoped startup capabilities to copy those files to the container's `/tmp` tmpfs with service-user ownership, then `gosu`/`su-exec` starts the application as UID 10001 with those capabilities cleared. This keeps host files at mode `0600` compatible with fixed container UIDs. Credential paths in the environment templates therefore use `/tmp/mcp-gc-secrets/`, not `/run/secrets/`. The `.env` secret files are parsed as literal `KEY=VALUE` lines: no `export`, interpolation, or shell quoting. The proxy receives only `proxy.env`.

Additional file-based integrations, such as Google Ads or App Store Connect, require an operator-owned Compose override declaring and mounting another secret into the applicable service. Do not mount the whole host secrets directory into every service.

Generate a password hash interactively, then put the output in `PROXY_PASSWORD_HASH` without quotes. Generate independent random values for the proxy token, any direct API keys, and the RevenueCat webhook secret; do not reuse the Basic authentication password:

```sh
docker run --rm -it caddy:2.10-alpine caddy hash-password
openssl rand -hex 32
```

Copy the same generated proxy token into `MCP_GC_PROXY_SHARED_TOKEN` in both `backend.env` and `proxy.env`. Caddy removes/replaces the internal proxy headers before forwarding, so browser JavaScript receives neither this token nor a direct API key. Keep `MCP_GC_PROXY_ROLE=viewer` for read-only deployments; use `admin` only when API mutations are deliberately enabled. Configure RevenueCat to send the exact `MCP_GC_REVENUECAT_WEBHOOK_SECRET` value in `MCP_GC_REVENUECAT_WEBHOOK_HEADER` (default example: `Authorization`).

`MCP_GC_API_AUTH_REQUIRED=1` is mandatory for this managed deployment. Authentication remains optional when running locally without that variable. Optional direct clients use `Authorization: Bearer <MCP_GC_ADMIN_API_KEY>` or the viewer key.

Use separate scheduler credentials restricted to viewer/read-only roles. In particular, do not give the scheduler Play Console release/listing write access, RevenueCat write credentials, FCM send permission, or mutable cloud roles.

## 3. Validate and start

Resolve and validate Compose configuration before building:

```sh
docker compose config --quiet
docker compose build api proxy
docker compose up -d
docker compose ps
```

Open `http://127.0.0.1:8080` and authenticate. For a remote host, tunnel instead of publishing plain HTTP:

```sh
ssh -L 8080:127.0.0.1:8080 operator@private-host
```

Optional deployment variables can be placed in an operator-controlled shell environment or untracked root `.env`:

```text
MCP_GC_BIND_ADDRESS=127.0.0.1
MCP_GC_PORT=8080
MCP_GC_IMAGE_TAG=release-id
BACKUP_RETENTION_DAYS=14
```

## 4. Health and logs

The unauthenticated `/healthz` endpoint reports only proxy liveness. `/api/health` is also unauthenticated by design and reports only `{"status":"ok"}`. All other API routes require API authorization even if the internal API port is reached directly, except a RevenueCat request that independently passes provider verification.

```sh
curl --fail http://127.0.0.1:8080/healthz
curl --fail http://127.0.0.1:8080/api/health
docker compose ps
docker compose logs --since=15m api scheduler proxy
```

Healthy state is `api`, `scheduler`, and `proxy` running with healthy checks. The API check calls FastAPI's health endpoint, the scheduler check opens SQLite read-only, and the proxy check calls local Caddy liveness.

## 5. Read-only operating mode

Read-only is the default and blocks every mutating API request, including mutations that would only change local SQLite or configuration. Scheduler-owned snapshots, observations, action logs, and proposals remain outside the HTTP request boundary and can still be written.

The deployment enforces this boundary in three layers:

1. FastAPI returns `403` for every non-`GET`/`HEAD`/`OPTIONS` API request when `MCP_GC_READ_ONLY=1`, even for an authenticated admin reaching the internal port directly.
2. The scheduler startup guard exits if SQLite already contains any experiment with status `approved`; a fresh database cannot gain approvals through the read-only proxy.
3. Scheduler credentials must be independently limited to external viewer/read-only permissions.

Verified RevenueCat webhooks are blocked in read-only mode because receipt persistence and FCM re-engagement are mutations. There is no webhook exception to this boundary.

Anyone who can alter SQLite directly, replace deployment configuration, set `MCP_GC_READ_ONLY=0`, or grant write-capable scheduler credentials remains outside the HTTP controls. Do not publish the API container, and inspect restored databases before restarting the scheduler.

## API authorization matrix

| Request | No credential | Viewer bearer/proxy | Admin bearer/proxy | Verified RevenueCat webhook |
| --- | --- | --- | --- | --- |
| `GET`/`HEAD`/`OPTIONS /api/*` | `401` | allowed | allowed | not applicable |
| `POST`/`PUT`/`PATCH`/`DELETE /api/*` | `401` | `403` | allowed unless read-only | only the RevenueCat route |
| `/api/health` | allowed | allowed | allowed | not applicable |
| `/api/webhooks/revenuecat` | `401` | `403` | provider secret still required | allowed unless read-only blocks it |

The matrix applies when `MCP_GC_API_AUTH_REQUIRED=1`. In read-only mode, all mutation cells, including verified RevenueCat webhooks, become `403`. Unsupported safe-method routes may return `404` or `405` after authorization.

RevenueCat event IDs are SHA-256 hashed and atomically inserted into the isolated `webhook_event_receipts` table in the shared SQLite database before work is scheduled. A duplicate receives a successful `duplicate` response and triggers no background action. A receipt-store error fails closed with `503`. Subscriber/token identifiers are excluded from structured logs and replaced with `[REDACTED]` in action arguments.

## 6. Backup

Run an online SQLite backup while the stack is active:

```sh
docker compose run --rm backup backup
docker compose run --rm backup list
```

Each backup is validated with `PRAGMA quick_check` and receives a `.sha256` file. Backups older than `BACKUP_RETENTION_DAYS` are deleted when a new backup completes. Schedule the first command from the host's timer/cron facility; Compose does not include a second scheduler solely for backups.

The backup volume is not off-host protection. Periodically export it to encrypted, access-controlled storage according to the operator's platform procedures.

## 7. Restore

List backups and choose the filename (not the full path):

```sh
docker compose run --rm backup list
docker compose stop scheduler api
docker compose run --rm -e CONFIRM_RESTORE=yes backup restore store-performance-YYYYMMDDTHHMMSSZ.db
docker compose start api
```

Before replacing SQLite, restore creates another online backup of the current database. It verifies a matching checksum when present and runs `PRAGMA quick_check` on the restored copy.

Inspect the restored database for approved experiments before starting the scheduler:

```sh
docker compose run --rm --entrypoint sqlite3 backup -readonly /app/data/store_performance.db \
  "SELECT id, app_package, status FROM experiments WHERE status = 'approved';"
docker compose start scheduler
docker compose ps
```

If rows are returned, the read-only guard intentionally keeps the scheduler stopped. Resolve those records under an explicit change procedure before attempting startup.

## 8. Upgrade

Use an immutable source revision and a unique `MCP_GC_IMAGE_TAG` for every release.

```sh
export MCP_GC_IMAGE_TAG=release-id
docker compose run --rm backup backup
docker compose build --pull api proxy
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8080/api/health
```

The API initializes/migrates SQLite at import time. Always take a verified backup before starting a new backend image. Do not prune the prior tagged images until the upgrade has passed health and operator smoke tests.

## 9. Rollback

Set `MCP_GC_IMAGE_TAG` back to the prior tag and recreate services:

```sh
export MCP_GC_IMAGE_TAG=previous-release-id
docker compose up -d --no-build
docker compose ps
```

If the newer application changed SQLite incompatibly, stop API and scheduler and follow the restore procedure using the pre-upgrade backup, then start API and scheduler in that order. A code rollback does not automatically reverse external actions; read-only credentials are the final control against those actions in this beta bundle.

## 10. Stop and remove

Stop containers without deleting state:

```sh
docker compose down
```

Never add `--volumes` unless both `mcp-gc-beta-data` and `mcp-gc-beta-backups` have been deliberately exported and permanent deletion is approved.
