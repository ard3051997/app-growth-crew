"""Database management layer for storing derived store performance metrics in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "store_performance.db"
SCHEMA_VERSION = 4
SQLITE_BUSY_TIMEOUT_MS = 5_000


def get_db_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Get a connection to the SQLite database, creating parent directories if needed."""
    resolved_path = Path(db_path).resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(resolved_path), timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    # Return rows as dictionaries for easier manipulation
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")
    return conn


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Initialize the SQLite database schema if tables do not exist."""
    logger.info("Initializing storefront database", db_path=str(db_path))
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # Country performance table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS listing_performance_by_country (
                    date TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    country TEXT NOT NULL,
                    visitors INTEGER NOT NULL,
                    installs INTEGER NOT NULL,
                    conversion_rate REAL NOT NULL,
                    PRIMARY KEY (date, package_name, country)
                );
                """
            )
            # Real per-day impressions, kept separate from listing_performance_by_country
            # rather than as a nullable column on it: only App Store Connect analytics
            # ingestion populates this today (Play Console CSVs carry visitors/installs
            # but not impressions), and keeping it additive leaves existing Play Store
            # behavior byte-for-byte unchanged.
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS listing_impressions_by_country (
                    date TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    country TEXT NOT NULL,
                    impressions INTEGER NOT NULL,
                    PRIMARY KEY (date, package_name, country)
                );
                """
            )
            # Traffic source performance table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS listing_performance_by_traffic_source (
                    date TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    traffic_source TEXT NOT NULL,
                    visitors INTEGER NOT NULL,
                    installs INTEGER NOT NULL,
                    conversion_rate REAL NOT NULL,
                    PRIMARY KEY (date, package_name, traffic_source)
                );
                """
            )
            # Search term performance table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS listing_performance_by_search_term (
                    date TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    search_term TEXT NOT NULL,
                    visitors INTEGER NOT NULL,
                    installs INTEGER NOT NULL,
                    conversion_rate REAL NOT NULL,
                    PRIMARY KEY (date, package_name, search_term)
                );
                """
            )
            # Core experiment tracking table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    app_package TEXT NOT NULL,
                    experiment_type TEXT NOT NULL,
                    hypothesis TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    success_metric TEXT NOT NULL,
                    baseline_value REAL,
                    target_value REAL,
                    min_observation_days INTEGER NOT NULL DEFAULT 7,
                    max_observation_days INTEGER NOT NULL DEFAULT 28,
                    rollback_threshold REAL,
                    snapshot_before TEXT,
                    snapshot_after TEXT,
                    result_value REAL,
                    result_verdict TEXT,
                    confidence REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    concluded_at TIMESTAMP,
                    created_by TEXT DEFAULT 'autonomous',
                    approved_via TEXT
                    ,target_tool TEXT
                    ,target_args TEXT
                    ,target_improvement_pct REAL
                    ,rollback_degradation_pct REAL
                    ,evidence_json TEXT
                    ,validation_json TEXT
                    ,execution_mode TEXT NOT NULL DEFAULT 'manual'
                    ,approval_actor TEXT
                    ,approval_reason TEXT
                    ,approved_at TIMESTAMP
                    ,rejection_actor TEXT
                    ,rejection_reason TEXT
                    ,rejected_at TIMESTAMP
                    ,validated_at TIMESTAMP
                    ,executed_at TIMESTAMP
                    ,retained_at TIMESTAMP
                    ,rolled_back_at TIMESTAMP
                    ,execution_result_json TEXT
                    ,evaluation_json TEXT
                    ,approval_validation_json TEXT
                    ,min_observation_visitors INTEGER NOT NULL DEFAULT 1000
                );
                """
            )
            # Daily metric snapshots table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL REFERENCES experiments(id),
                    observed_at DATE NOT NULL,
                    metric_value REAL NOT NULL,
                    raw_data TEXT,
                    visitors INTEGER,
                    installs INTEGER,
                    phase TEXT NOT NULL DEFAULT 'treatment',
                    locale TEXT,
                    period_start DATE,
                    period_end DATE,
                    source TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(experiment_id, observed_at)
                );
                """
            )
            # Existing installations predate the explicit execution fields. SQLite
            # has no ADD COLUMN IF NOT EXISTS, so migrate based on table metadata.
            experiment_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(experiments);").fetchall()
            }
            migrations = {
                "target_tool": "TEXT",
                "target_args": "TEXT",
                "target_improvement_pct": "REAL",
                "rollback_degradation_pct": "REAL",
                "evidence_json": "TEXT",
                "validation_json": "TEXT",
                "execution_mode": "TEXT NOT NULL DEFAULT 'manual'",
                "approval_actor": "TEXT",
                "approval_reason": "TEXT",
                "approved_at": "TIMESTAMP",
                "rejection_actor": "TEXT",
                "rejection_reason": "TEXT",
                "rejected_at": "TIMESTAMP",
                "validated_at": "TIMESTAMP",
                "executed_at": "TIMESTAMP",
                "retained_at": "TIMESTAMP",
                "rolled_back_at": "TIMESTAMP",
                "execution_result_json": "TEXT",
                "evaluation_json": "TEXT",
                "approval_validation_json": "TEXT",
                "min_observation_visitors": "INTEGER NOT NULL DEFAULT 1000",
            }
            for column, column_type in migrations.items():
                if column not in experiment_columns:
                    conn.execute(f"ALTER TABLE experiments ADD COLUMN {column} {column_type};")
            observation_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(experiment_observations);").fetchall()
            }
            observation_migrations = {
                "visitors": "INTEGER",
                "installs": "INTEGER",
                "phase": "TEXT NOT NULL DEFAULT 'treatment'",
                "locale": "TEXT",
                "period_start": "DATE",
                "period_end": "DATE",
                "source": "TEXT",
                "created_at": "TIMESTAMP",
            }
            for column, column_type in observation_migrations.items():
                if column not in observation_columns:
                    conn.execute(
                        f"ALTER TABLE experiment_observations ADD COLUMN {column} {column_type};"
                    )
            # Audit log table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS action_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    app_package TEXT,
                    action_type TEXT NOT NULL,
                    tool_name TEXT,
                    arguments TEXT,
                    result TEXT,
                    reasoning TEXT,
                    experiment_id TEXT REFERENCES experiments(id)
                );
                """
            )
            # System trust tracking table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_confidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    experiments_proposed INTEGER DEFAULT 0,
                    experiments_succeeded INTEGER DEFAULT 0,
                    experiments_failed INTEGER DEFAULT 0,
                    experiments_rolled_back INTEGER DEFAULT 0,
                    prediction_accuracy REAL,
                    current_trust_tier TEXT DEFAULT 'conservative'
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS emergency_brakes (
                    app_package TEXT PRIMARY KEY,
                    active INTEGER NOT NULL DEFAULT 1,
                    reason TEXT NOT NULL,
                    triggered_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    cleared_at TIMESTAMP
                );
                """
            )
            # App metrics snapshots — pre-computed by the PRAO loop, read by the API server
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_metrics_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_name TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL,

                    -- Funnel metrics
                    funnel_health_score REAL,
                    top_leak_name TEXT,
                    top_leak_value REAL,
                    top_leak_benchmark REAL,

                    -- Revenue metrics
                    mrr REAL DEFAULT 0,
                    mrr_change_pct REAL DEFAULT 0,
                    ad_revenue_30d REAL DEFAULT 0,
                    rc_revenue_30d REAL DEFAULT 0,
                    total_revenue_30d REAL DEFAULT 0,

                    -- Engagement metrics
                    installs_7d TEXT,
                    active_users_30d INTEGER DEFAULT 0,
                    d1_retention REAL DEFAULT 0,
                    d7_retention REAL DEFAULT 0,

                    -- Full raw snapshots (JSON)
                    raw_funnel_json TEXT,
                    raw_revenue_json TEXT,
                    source_status_json TEXT,
                    data_as_of TIMESTAMP,
                    is_partial INTEGER NOT NULL DEFAULT 0,

                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(package_name, snapshot_date)
                );
                """
            )
            snapshot_columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(app_metrics_snapshots);").fetchall()
            }
            snapshot_migrations = {
                "source_status_json": "TEXT",
                "data_as_of": "TIMESTAMP",
                "is_partial": "INTEGER NOT NULL DEFAULT 0",
            }
            for column, column_type in snapshot_migrations.items():
                if column not in snapshot_columns:
                    conn.execute(
                        f"ALTER TABLE app_metrics_snapshots ADD COLUMN {column} {column_type};"
                    )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    package_name TEXT,
                    status TEXT NOT NULL CHECK(status IN ('running', 'success', 'partial', 'failure')),
                    started_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    period_start TEXT,
                    period_end TEXT,
                    record_count INTEGER NOT NULL DEFAULT 0,
                    error_safe TEXT,
                    metadata_json TEXT
                );
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_sync_runs_source_package_started
                ON sync_runs(source, package_name, started_at DESC);
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_watermarks (
                    source TEXT NOT NULL,
                    package_name TEXT NOT NULL DEFAULT '',
                    last_run_id INTEGER REFERENCES sync_runs(id),
                    last_started_at TIMESTAMP NOT NULL,
                    last_completed_at TIMESTAMP,
                    last_success_at TIMESTAMP,
                    last_status TEXT NOT NULL,
                    period_start TEXT,
                    period_end TEXT,
                    record_count INTEGER NOT NULL DEFAULT 0,
                    error_safe TEXT,
                    PRIMARY KEY(source, package_name)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_heartbeat (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    process_started_at TIMESTAMP,
                    heartbeat_at TIMESTAMP NOT NULL,
                    last_cycle_started_at TIMESTAMP,
                    last_cycle_completed_at TIMESTAMP,
                    last_cycle_status TEXT,
                    last_error_safe TEXT
                );
                """
            )
            conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (1);")
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?);",
                (SCHEMA_VERSION,),
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")
            # Durable experiment command storage is an additive migration.  Keep
            # this call at the end so legacy databases are fully usable even when
            # they predate the command model.
            from funnel_engine.durable_experiments import migrate_durable_schema

            migrate_durable_schema(conn)
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?);",
                (SCHEMA_VERSION,),
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.exception("Failed to initialize database", error=str(e))
        raise
    finally:
        conn.close()


def save_country_performance(
    db_path: str | Path,
    date: str,
    package_name: str,
    country: str,
    visitors: int,
    installs: int,
    conversion_rate: float,
) -> None:
    """Idempotently save country storefront metrics (upsert/replace)."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO listing_performance_by_country
                (date, package_name, country, visitors, installs, conversion_rate)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (date, package_name, country, visitors, installs, conversion_rate),
            )
    finally:
        conn.close()


def save_impressions_performance(
    db_path: str | Path,
    date: str,
    package_name: str,
    country: str,
    impressions: int,
) -> None:
    """Idempotently save real per-day storefront impressions (upsert/replace)."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO listing_impressions_by_country
                (date, package_name, country, impressions)
                VALUES (?, ?, ?, ?);
                """,
                (date, package_name, country, impressions),
            )
    finally:
        conn.close()


def get_total_impressions(
    db_path: str | Path,
    package_name: str,
    days: int = 30,
) -> int | None:
    """Retrieve total real storefront impressions for a package within the last N days."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(date) FROM listing_impressions_by_country WHERE package_name = ?;",
            (package_name,),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return None
        latest_date_str = row[0]

        cursor.execute(
            """
            SELECT SUM(impressions)
            FROM listing_impressions_by_country
            WHERE package_name = ? AND date >= date(?, ?);
            """,
            (package_name, latest_date_str, f"-{days} days"),
        )
        res = cursor.fetchone()
        if res and res[0] is not None:
            return int(res[0])
        return None
    except Exception as e:
        logger.exception("Failed to query total impressions", error=str(e))
        return None
    finally:
        conn.close()


def save_traffic_performance(
    db_path: str | Path,
    date: str,
    package_name: str,
    traffic_source: str,
    visitors: int,
    installs: int,
    conversion_rate: float,
) -> None:
    """Idempotently save traffic source storefront metrics (upsert/replace)."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO listing_performance_by_traffic_source
                (date, package_name, traffic_source, visitors, installs, conversion_rate)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (date, package_name, traffic_source, visitors, installs, conversion_rate),
            )
    finally:
        conn.close()


def save_search_performance(
    db_path: str | Path,
    date: str,
    package_name: str,
    search_term: str,
    visitors: int,
    installs: int,
    conversion_rate: float,
) -> None:
    """Idempotently save search term storefront metrics (upsert/replace)."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO listing_performance_by_search_term
                (date, package_name, search_term, visitors, installs, conversion_rate)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (date, package_name, search_term, visitors, installs, conversion_rate),
            )
    finally:
        conn.close()


def get_country_performance(
    db_path: str | Path,
    package_name: str,
) -> list[dict[str, Any]]:
    """Retrieve country performance metrics, ordered by installs descending."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date, country, visitors, installs, conversion_rate
            FROM listing_performance_by_country
            WHERE package_name = ?
            ORDER BY date DESC, installs DESC;
            """,
            (package_name,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_traffic_performance(
    db_path: str | Path,
    package_name: str,
) -> list[dict[str, Any]]:
    """Retrieve traffic source performance metrics."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date, traffic_source, visitors, installs, conversion_rate
            FROM listing_performance_by_traffic_source
            WHERE package_name = ?
            ORDER BY date DESC, installs DESC;
            """,
            (package_name,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_search_performance(
    db_path: str | Path,
    package_name: str,
) -> list[dict[str, Any]]:
    """Retrieve search term performance metrics."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT date, search_term, visitors, installs, conversion_rate
            FROM listing_performance_by_search_term
            WHERE package_name = ?
            ORDER BY date DESC, installs DESC;
            """,
            (package_name,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_total_storefront_metrics(
    db_path: str | Path,
    package_name: str,
    days: int = 30,
) -> dict[str, int] | None:
    """Retrieve total storefront visitors and installs for a package name within the last N days from SQLite."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        # Find the latest date in the database to calculate relative range
        cursor.execute(
            "SELECT MAX(date) FROM listing_performance_by_country WHERE package_name = ?;",
            (package_name,),
        )
        row = cursor.fetchone()
        if not row or not row[0]:
            return None
        latest_date_str = row[0]

        # Query total visitors and installs from country performance table
        cursor.execute(
            """
            SELECT SUM(visitors), SUM(installs)
            FROM listing_performance_by_country
            WHERE package_name = ? AND date >= date(?, ?);
            """,
            (package_name, latest_date_str, f"-{days} days"),
        )
        res = cursor.fetchone()
        if res and res[0] is not None:
            return {
                "visitors": int(res[0]),
                "installs": int(res[1]),
            }
        return None
    except Exception as e:
        logger.exception("Failed to query total storefront metrics", error=str(e))
        return None
    finally:
        conn.close()


def get_latest_storefront_counts(
    db_path: str | Path,
    package_name: str,
) -> dict[str, Any] | None:
    """Return aggregate visitor/install counts for the latest exact storefront date."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute(
            """
            SELECT date, SUM(visitors) AS visitors, SUM(installs) AS installs
            FROM listing_performance_by_country
            WHERE package_name = ?
              AND date = (
                  SELECT MAX(date) FROM listing_performance_by_country WHERE package_name = ?
              )
            GROUP BY date;
            """,
            (package_name, package_name),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_db_experiment(
    db_path: str | Path,
    exp_id: str,
    app_package: str,
    experiment_type: str,
    hypothesis: str,
    success_metric: str,
    baseline_value: float | None = None,
    target_value: float | None = None,
    min_observation_days: int = 7,
    max_observation_days: int = 28,
    rollback_threshold: float | None = None,
    snapshot_before: str | None = None,
    created_by: str = "autonomous",
    target_tool: str | None = None,
    target_args: str | None = None,
    target_improvement_pct: float | None = None,
    rollback_degradation_pct: float | None = None,
    evidence_json: str | None = None,
    execution_mode: str = "manual",
    min_observation_visitors: int = 1000,
) -> None:
    """Create a proposed experiment record in SQLite."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO experiments (
                    id, app_package, experiment_type, hypothesis, success_metric,
                    baseline_value, target_value, min_observation_days, max_observation_days,
                    rollback_threshold, snapshot_before, status, created_by,
                    target_tool, target_args, target_improvement_pct,
                    rollback_degradation_pct, evidence_json, execution_mode,
                    min_observation_visitors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    exp_id,
                    app_package,
                    experiment_type,
                    hypothesis,
                    success_metric,
                    baseline_value,
                    target_value,
                    min_observation_days,
                    max_observation_days,
                    rollback_threshold,
                    snapshot_before,
                    created_by,
                    target_tool,
                    target_args,
                    target_improvement_pct,
                    rollback_degradation_pct,
                    evidence_json,
                    execution_mode,
                    min_observation_visitors,
                ),
            )
    finally:
        conn.close()


def get_db_experiments(
    db_path: str | Path,
    app_package: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Retrieve experiments, optionally filtered by app package and status."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM experiments"
        params = []
        conditions = []
        if app_package:
            conditions.append("app_package = ?")
            params.append(app_package)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC;"
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_db_experiment(
    db_path: str | Path,
    exp_id: str,
) -> dict[str, Any] | None:
    """Retrieve one experiment by its stable identifier."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM experiments WHERE id = ?;", (exp_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


EXPERIMENT_MUTABLE_FIELDS = frozenset(
    {
        "status",
        "baseline_value",
        "snapshot_before",
        "snapshot_after",
        "result_value",
        "result_verdict",
        "confidence",
        "approved_via",
        "evidence_json",
        "validation_json",
        "execution_mode",
        "approval_actor",
        "approval_reason",
        "approved_at",
        "rejection_actor",
        "rejection_reason",
        "rejected_at",
        "validated_at",
        "started_at",
        "executed_at",
        "concluded_at",
        "retained_at",
        "rolled_back_at",
        "execution_result_json",
        "evaluation_json",
        "approval_validation_json",
    }
)


def update_db_experiment_fields(
    db_path: str | Path,
    exp_id: str,
    fields: dict[str, Any],
    expected_status: str | None = None,
) -> bool:
    """Update lifecycle-owned fields, optionally using status as a compare-and-set guard."""
    if not fields:
        return False
    unknown = set(fields) - EXPERIMENT_MUTABLE_FIELDS
    if unknown:
        raise ValueError(f"Unsupported experiment fields: {', '.join(sorted(unknown))}")

    assignments = ", ".join(f"{field} = ?" for field in fields)
    params = list(fields.values())
    query = f"UPDATE experiments SET {assignments} WHERE id = ?"  # noqa: S608
    params.append(exp_id)
    if expected_status is not None:
        query += " AND status = ?"
        params.append(expected_status)
    query += ";"

    conn = get_db_connection(db_path)
    try:
        with conn:
            return conn.execute(query, params).rowcount > 0
    finally:
        conn.close()


def update_db_experiment_status(
    db_path: str | Path,
    exp_id: str,
    status: str,
    result_value: float | None = None,
    result_verdict: str | None = None,
    confidence: float | None = None,
    snapshot_before: str | None = None,
    snapshot_after: str | None = None,
    approved_via: str | None = None,
) -> bool:
    """Update experiment status and record execution/conclusion data."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            updates = ["status = ?"]
            params: list[Any] = [status]

            if status in ("active", "measuring"):
                updates.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
            elif status in ("concluded", "rolled_back"):
                updates.append("concluded_at = CURRENT_TIMESTAMP")

            if result_value is not None:
                updates.append("result_value = ?")
                params.append(result_value)
            if result_verdict is not None:
                updates.append("result_verdict = ?")
                params.append(result_verdict)
            if confidence is not None:
                updates.append("confidence = ?")
                params.append(confidence)
            if snapshot_before is not None:
                updates.append("snapshot_before = ?")
                params.append(snapshot_before)
            if snapshot_after is not None:
                updates.append("snapshot_after = ?")
                params.append(snapshot_after)
            if approved_via is not None:
                updates.append("approved_via = ?")
                params.append(approved_via)

            params.append(exp_id)
            # Column fragments are selected only from the fixed list above; values stay parameterized.
            query = f"UPDATE experiments SET {', '.join(updates)} WHERE id = ?;"  # noqa: S608
            cursor = conn.execute(query, params)
            return cursor.rowcount > 0
    finally:
        conn.close()


def persist_db_experiment_snapshot(
    db_path: str | Path,
    exp_id: str,
    snapshot_before: str,
) -> bool:
    """Persist a rollback snapshot without changing experiment lifecycle state."""
    if not snapshot_before.strip():
        return False
    conn = get_db_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE experiments SET snapshot_before = ? WHERE id = ?;",
                (snapshot_before, exp_id),
            )
            return cursor.rowcount > 0
    finally:
        conn.close()


def set_emergency_brake(
    db_path: str | Path,
    app_package: str,
    reason: str,
) -> None:
    """Latch an emergency brake for an app until explicitly cleared."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO emergency_brakes (app_package, active, reason, triggered_at, cleared_at)
                VALUES (?, 1, ?, CURRENT_TIMESTAMP, NULL)
                ON CONFLICT(app_package) DO UPDATE SET
                    active = 1,
                    reason = excluded.reason,
                    triggered_at = CURRENT_TIMESTAMP,
                    cleared_at = NULL;
                """,
                (app_package, reason),
            )
    finally:
        conn.close()


def clear_emergency_brake(db_path: str | Path, app_package: str) -> bool:
    """Explicitly clear an app's emergency brake."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                UPDATE emergency_brakes
                SET active = 0, cleared_at = CURRENT_TIMESTAMP
                WHERE app_package = ? AND active = 1;
                """,
                (app_package,),
            )
            return cursor.rowcount > 0
    finally:
        conn.close()


def get_emergency_brakes(
    db_path: str | Path,
    app_package: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    """Return persisted emergency-brake states."""
    conn = get_db_connection(db_path)
    try:
        query = "SELECT * FROM emergency_brakes"
        conditions: list[str] = []
        params: list[Any] = []
        if app_package:
            conditions.append("app_package = ?")
            params.append(app_package)
        if active_only:
            conditions.append("active = 1")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY triggered_at DESC;"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def is_emergency_brake_active(db_path: str | Path, app_package: str) -> bool:
    """Check whether writes are blocked for an app."""
    return bool(get_emergency_brakes(db_path, app_package=app_package, active_only=True))


def add_db_observation(
    db_path: str | Path,
    experiment_id: str,
    observed_at: str,
    metric_value: float,
    raw_data: str | None = None,
    visitors: int | None = None,
    installs: int | None = None,
    phase: str = "treatment",
    locale: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    source: str | None = None,
) -> None:
    """Save or replace a daily metric observation for an experiment."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO experiment_observations
                (experiment_id, observed_at, metric_value, raw_data, visitors, installs,
                 phase, locale, period_start, period_end, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    experiment_id,
                    observed_at,
                    metric_value,
                    raw_data,
                    visitors,
                    installs,
                    phase,
                    locale,
                    period_start,
                    period_end,
                    source,
                ),
            )
    finally:
        conn.close()


def insert_db_observation_if_non_overlapping(
    db_path: str | Path,
    experiment_id: str,
    observed_at: str,
    metric_value: float,
    raw_data: str | None,
    *,
    visitors: int | None = None,
    installs: int | None = None,
    locale: str,
    period_start: str,
    period_end: str,
    source: str,
) -> str:
    """Atomically reject duplicate or overlapping treatment observations and insert one row."""
    conn = get_db_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        existing = conn.execute(
            """
            SELECT visitors, installs, metric_value FROM experiment_observations
            WHERE experiment_id = ? AND observed_at = ?;
            """,
            (experiment_id, observed_at),
        ).fetchone()
        if existing is not None:
            conn.rollback()
            if (
                existing["visitors"] == visitors
                and existing["installs"] == installs
                and existing["metric_value"] == metric_value
            ):
                return "duplicate"
            return "conflict"
        overlap = conn.execute(
            """
            SELECT 1 FROM experiment_observations
            WHERE experiment_id = ? AND phase = 'treatment'
              AND COALESCE(period_start, observed_at) <= ?
              AND COALESCE(period_end, observed_at) >= ?
            LIMIT 1;
            """,
            (experiment_id, period_end, period_start),
        ).fetchone()
        if overlap is not None:
            conn.rollback()
            return "overlap"
        conn.execute(
            """
            INSERT INTO experiment_observations
            (experiment_id, observed_at, metric_value, raw_data, visitors, installs,
             phase, locale, period_start, period_end, source)
            VALUES (?, ?, ?, ?, ?, ?, 'treatment', ?, ?, ?, ?);
            """,
            (
                experiment_id,
                observed_at,
                metric_value,
                raw_data,
                visitors,
                installs,
                locale,
                period_start,
                period_end,
                source,
            ),
        )
        conn.commit()
        return "inserted"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_db_observations(
    db_path: str | Path,
    experiment_id: str,
) -> list[dict[str, Any]]:
    """Get all observations for an experiment ordered by observed_at."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT observed_at, metric_value, raw_data, visitors, installs, phase,
                   locale, period_start, period_end, source, created_at
            FROM experiment_observations
            WHERE experiment_id = ?
            ORDER BY observed_at ASC;
            """,
            (experiment_id,),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def log_db_action(
    db_path: str | Path,
    action_type: str,
    app_package: str | None = None,
    tool_name: str | None = None,
    arguments: str | None = None,
    result: str | None = None,
    reasoning: str | None = None,
    experiment_id: str | None = None,
) -> None:
    """Record an autonomous action in the audit log."""
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO action_log (
                    app_package, action_type, tool_name, arguments, result, reasoning, experiment_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (app_package, action_type, tool_name, arguments, result, reasoning, experiment_id),
            )
    finally:
        conn.close()


def get_db_actions(
    db_path: str | Path,
    app_package: str | None = None,
    action_type: str | None = None,
    experiment_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get recent logged actions, ordered by timestamp descending."""
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM action_log"
        params: list[Any] = []
        conditions = []
        if app_package:
            conditions.append("app_package = ?")
            params.append(app_package)
        if action_type:
            conditions.append("action_type = ?")
            params.append(action_type)
        if experiment_id:
            conditions.append("experiment_id = ?")
            params.append(experiment_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC, id DESC LIMIT ?;"
        params.append(limit)
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# =============================================================================
# App Metrics Snapshots — pre-computed by PRAO loop, read by API server
# =============================================================================


def save_app_metrics_snapshot(
    db_path: str | Path,
    package_name: str,
    snapshot_date: str,
    metrics: dict[str, Any],
) -> None:
    """Save or update a daily metrics snapshot for an app.

    Args:
        db_path: Path to the SQLite database.
        package_name: App package name.
        snapshot_date: Date string (YYYY-MM-DD).
        metrics: Dict with keys matching column names (funnel_health_score, mrr, etc.).
    """
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO app_metrics_snapshots (
                    package_name, snapshot_date,
                    funnel_health_score, top_leak_name, top_leak_value, top_leak_benchmark,
                    mrr, mrr_change_pct, ad_revenue_30d, rc_revenue_30d, total_revenue_30d,
                    installs_7d, active_users_30d, d1_retention, d7_retention,
                    raw_funnel_json, raw_revenue_json, source_status_json, data_as_of, is_partial
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(package_name, snapshot_date) DO UPDATE SET
                    funnel_health_score = excluded.funnel_health_score,
                    top_leak_name = excluded.top_leak_name,
                    top_leak_value = excluded.top_leak_value,
                    top_leak_benchmark = excluded.top_leak_benchmark,
                    mrr = excluded.mrr,
                    mrr_change_pct = excluded.mrr_change_pct,
                    ad_revenue_30d = excluded.ad_revenue_30d,
                    rc_revenue_30d = excluded.rc_revenue_30d,
                    total_revenue_30d = excluded.total_revenue_30d,
                    installs_7d = excluded.installs_7d,
                    active_users_30d = excluded.active_users_30d,
                    d1_retention = excluded.d1_retention,
                    d7_retention = excluded.d7_retention,
                    raw_funnel_json = excluded.raw_funnel_json,
                    raw_revenue_json = excluded.raw_revenue_json,
                    source_status_json = excluded.source_status_json,
                    data_as_of = excluded.data_as_of,
                    is_partial = excluded.is_partial,
                    created_at = CURRENT_TIMESTAMP;
                """,
                (
                    package_name,
                    snapshot_date,
                    metrics.get("funnel_health_score"),
                    metrics.get("top_leak_name"),
                    metrics.get("top_leak_value"),
                    metrics.get("top_leak_benchmark"),
                    metrics.get("mrr"),
                    metrics.get("mrr_change_pct"),
                    metrics.get("ad_revenue_30d"),
                    metrics.get("rc_revenue_30d"),
                    metrics.get("total_revenue_30d"),
                    metrics.get("installs_7d"),
                    metrics.get("active_users_30d"),
                    metrics.get("d1_retention"),
                    metrics.get("d7_retention"),
                    metrics.get("raw_funnel_json"),
                    metrics.get("raw_revenue_json"),
                    metrics.get("source_status_json"),
                    metrics.get("data_as_of"),
                    int(bool(metrics.get("is_partial", False))),
                ),
            )
    finally:
        conn.close()


def get_latest_app_snapshot(
    db_path: str | Path,
    package_name: str,
) -> dict[str, Any] | None:
    """Get the most recent metrics snapshot for a single app.

    Args:
        db_path: Path to the SQLite database.
        package_name: App package name.

    Returns:
        Dict of the latest snapshot row, or None if no snapshot exists.
    """
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM app_metrics_snapshots
            WHERE package_name = ?
            ORDER BY snapshot_date DESC
            LIMIT 1;
            """,
            (package_name,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_latest_snapshots(
    db_path: str | Path,
) -> list[dict[str, Any]]:
    """Get the most recent snapshot for every app in the database.

    Uses a window function to pick the latest snapshot_date per package_name.

    Returns:
        List of dicts, one per app.
    """
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM app_metrics_snapshots
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY package_name ORDER BY snapshot_date DESC
                    ) AS rn
                    FROM app_metrics_snapshots
                )
                WHERE rn = 1
            );
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_app_snapshot_history(
    db_path: str | Path,
    package_name: str,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Get snapshot history for an app over the last N days.

    Args:
        db_path: Path to the SQLite database.
        package_name: App package name.
        days: Number of days of history to retrieve.

    Returns:
        List of snapshot dicts ordered by date ascending.
    """
    conn = get_db_connection(db_path)
    try:
        cursor = conn.cursor()
        lookback_days = max(days - 1, 0)
        cursor.execute(
            """
            SELECT * FROM app_metrics_snapshots
            WHERE package_name = ?
              AND snapshot_date >= date(
                  (SELECT MAX(snapshot_date) FROM app_metrics_snapshots WHERE package_name = ?),
                  ?
              )
            ORDER BY snapshot_date ASC;
            """,
            (package_name, package_name, f"-{lookback_days} days"),
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# =============================================================================
# Connector sync state and scheduler liveness
# =============================================================================


def safe_sync_error(error: BaseException | None, fallback: str = "Source unavailable") -> str:
    """Return an operator-safe error label without persisting exception text or credentials."""
    if error is None:
        return fallback
    return f"{fallback} ({type(error).__name__})"


def start_sync_run(
    db_path: str | Path,
    source: str,
    package_name: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    metadata_json: str | None = None,
) -> int:
    """Start a durable connector run and update its source watermark."""
    started_at = datetime.now(UTC).isoformat()
    package_key = package_name or ""
    conn = get_db_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO sync_runs (
                    source, package_name, status, started_at, period_start, period_end, metadata_json
                ) VALUES (?, ?, 'running', ?, ?, ?, ?);
                """,
                (source, package_name, started_at, period_start, period_end, metadata_json),
            )
            assert cursor.lastrowid is not None
            run_id = int(cursor.lastrowid)
            conn.execute(
                """
                INSERT INTO source_watermarks (
                    source, package_name, last_run_id, last_started_at, last_status,
                    period_start, period_end
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                ON CONFLICT(source, package_name) DO UPDATE SET
                    last_run_id = excluded.last_run_id,
                    last_started_at = excluded.last_started_at,
                    last_status = 'running',
                    period_start = excluded.period_start,
                    period_end = excluded.period_end,
                    error_safe = NULL;
                """,
                (source, package_key, run_id, started_at, period_start, period_end),
            )
            return run_id
    finally:
        conn.close()


def finish_sync_run(
    db_path: str | Path,
    run_id: int,
    status: str,
    *,
    record_count: int = 0,
    period_start: str | None = None,
    period_end: str | None = None,
    error_safe: str | None = None,
    metadata_json: str | None = None,
) -> None:
    """Finish a connector run and atomically publish its latest watermark."""
    if status not in {"success", "partial", "failure"}:
        raise ValueError(f"Invalid terminal sync status: {status}")
    completed_at = datetime.now(UTC).isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            run = conn.execute(
                "SELECT source, package_name, status FROM sync_runs WHERE id = ?;", (run_id,)
            ).fetchone()
            if run is None:
                raise ValueError(f"Unknown sync run: {run_id}")
            if run["status"] != "running":
                raise ValueError(f"Sync run {run_id} is already complete")
            conn.execute(
                """
                UPDATE sync_runs SET
                    status = ?, completed_at = ?, period_start = COALESCE(?, period_start),
                    period_end = COALESCE(?, period_end), record_count = ?, error_safe = ?,
                    metadata_json = COALESCE(?, metadata_json)
                WHERE id = ?;
                """,
                (
                    status,
                    completed_at,
                    period_start,
                    period_end,
                    max(0, record_count),
                    error_safe,
                    metadata_json,
                    run_id,
                ),
            )
            package_key = run["package_name"] or ""
            conn.execute(
                """
                UPDATE source_watermarks SET
                    last_completed_at = ?,
                    last_success_at = CASE
                        WHEN ? = 'success' THEN ? ELSE last_success_at END,
                    last_status = ?,
                    period_start = COALESCE(?, period_start),
                    period_end = COALESCE(?, period_end),
                    record_count = ?,
                    error_safe = ?
                WHERE source = ? AND package_name = ? AND last_run_id = ?;
                """,
                (
                    completed_at,
                    status,
                    completed_at,
                    status,
                    period_start,
                    period_end,
                    max(0, record_count),
                    error_safe,
                    run["source"],
                    package_key,
                    run_id,
                ),
            )
    finally:
        conn.close()


def get_source_watermarks(
    db_path: str | Path,
    package_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return latest persisted connector state, optionally for one app."""
    conn = get_db_connection(db_path)
    try:
        if package_name is None:
            rows = conn.execute(
                "SELECT * FROM source_watermarks ORDER BY source, package_name;"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM source_watermarks
                WHERE package_name IN (?, '')
                ORDER BY source, package_name;
                """,
                (package_name,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_latest_sync_runs(
    db_path: str | Path,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent connector runs for operational diagnostics."""
    conn = get_db_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC, id DESC LIMIT ?;",
            (max(1, min(limit, 500)),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_scheduler_heartbeat(
    db_path: str | Path,
    *,
    process_started: bool = False,
    cycle_event: str | None = None,
    error_safe: str | None = None,
) -> None:
    """Publish scheduler liveness and PRAO cycle transitions."""
    now = datetime.now(UTC).isoformat()
    conn = get_db_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO scheduler_heartbeat(id, process_started_at, heartbeat_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    process_started_at = CASE WHEN ? THEN excluded.process_started_at
                                              ELSE scheduler_heartbeat.process_started_at END,
                    heartbeat_at = excluded.heartbeat_at;
                """,
                (now if process_started else None, now, int(process_started)),
            )
            if cycle_event == "started":
                conn.execute(
                    """
                    UPDATE scheduler_heartbeat SET last_cycle_started_at = ?,
                        last_cycle_status = 'running', last_error_safe = NULL WHERE id = 1;
                    """,
                    (now,),
                )
            elif cycle_event in {"success", "partial", "failure"}:
                conn.execute(
                    """
                    UPDATE scheduler_heartbeat SET last_cycle_completed_at = ?,
                        last_cycle_status = ?, last_error_safe = ? WHERE id = 1;
                    """,
                    (now, cycle_event, error_safe),
                )
    finally:
        conn.close()


def get_scheduler_heartbeat(db_path: str | Path) -> dict[str, Any] | None:
    """Return the scheduler's last persisted liveness signal."""
    conn = get_db_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM scheduler_heartbeat WHERE id = 1;").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
