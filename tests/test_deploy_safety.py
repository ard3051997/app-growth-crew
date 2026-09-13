"""Behavioral tests for deployment entrypoint safety controls."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOAD_SECRETS = PROJECT_ROOT / "deploy" / "load-secrets.sh"
COMPOSE_FILE = PROJECT_ROOT / "compose.yaml"


def _run_entrypoint(secret_file: Path, environment: dict[str, str]) -> dict[str, str]:
    result = subprocess.run(  # noqa: S603 - fixed repository script and command
        ["/bin/sh", str(LOAD_SECRETS), "/usr/bin/env"],
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "MCP_GC_SECRET_FILE": str(secret_file),
            **environment,
        },
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def test_secret_file_cannot_override_managed_controls(tmp_path: Path) -> None:
    secret_file = tmp_path / "backend.env"
    secret_file.write_text(
        "\n".join(
            (
                "MCP_GC_MANAGED=0",
                "MCP_GC_READ_ONLY=1",
                "MCP_GC_API_AUTH_REQUIRED=0",
                "MCP_GC_CONFIG_WRITES_ENABLED=1",
                "MCP_GC_ENV=local",
                "MCP_GC_INSECURE_DEV_WEBHOOKS=1",
                "UNPROTECTED_SETTING=loaded",
            )
        ),
        encoding="utf-8",
    )

    environment = _run_entrypoint(
        secret_file,
        {
            "MCP_GC_MANAGED": "1",
            "MCP_GC_READ_ONLY": "0",
            "MCP_GC_API_AUTH_REQUIRED": "1",
            "MCP_GC_CONFIG_WRITES_ENABLED": "0",
            "MCP_GC_ENV": "managed",
            "MCP_GC_INSECURE_DEV_WEBHOOKS": "0",
        },
    )

    assert environment["MCP_GC_MANAGED"] == "1"
    assert environment["MCP_GC_READ_ONLY"] == "0"
    assert environment["MCP_GC_API_AUTH_REQUIRED"] == "1"
    assert environment["MCP_GC_CONFIG_WRITES_ENABLED"] == "0"
    assert environment["MCP_GC_ENV"] == "managed"
    assert environment["MCP_GC_INSECURE_DEV_WEBHOOKS"] == "0"
    assert environment["UNPROTECTED_SETTING"] == "loaded"


def test_scheduler_force_read_only_is_reasserted_after_secret_load(tmp_path: Path) -> None:
    secret_file = tmp_path / "scheduler.env"
    secret_file.write_text(
        "MCP_GC_READ_ONLY=0\nMCP_GC_FORCE_READ_ONLY=0\nMCP_GC_MANAGED=0\n",
        encoding="utf-8",
    )

    environment = _run_entrypoint(
        secret_file,
        {
            "MCP_GC_MANAGED": "1",
            "MCP_GC_READ_ONLY": "0",
            "MCP_GC_FORCE_READ_ONLY": "1",
        },
    )

    assert environment["MCP_GC_MANAGED"] == "1"
    assert environment["MCP_GC_READ_ONLY"] == "1"


def test_container_hardening_contracts_remain_deployable() -> None:
    load_secrets = LOAD_SECRETS.read_text(encoding="utf-8")
    assert load_secrets.index('chmod 400 "$destination"') < load_secrets.index(
        'chown "$run_as" "$destination"'
    )

    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    proxy_capabilities = compose["services"]["proxy"]["cap_add"]
    assert "NET_BIND_SERVICE" in proxy_capabilities
    assert "NET_BIND_SERVICE" not in compose["services"]["api"]["cap_add"]
    assert compose["services"]["scheduler"]["environment"]["MCP_GC_FORCE_READ_ONLY"] == "1"
    assert "MCP_GC_DATA_VOLUME" in compose["volumes"]["mcp_gc_data"]["name"]
    assert "MCP_GC_BACKUP_VOLUME" in compose["volumes"]["mcp_gc_backups"]["name"]

    backend_dockerfile = (PROJECT_ROOT / "deploy" / "backend.Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "--all-extras" not in backend_dockerfile
    assert "--extra orchestration" in backend_dockerfile

    frontend_dockerfile = (PROJECT_ROOT / "deploy" / "frontend.Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "RUN npm run build" in frontend_dockerfile

    db_tools = (PROJECT_ROOT / "deploy" / "db-tools.sh").read_text(encoding="utf-8")
    assert 'backup_name="store-performance-${timestamp}.db"' in db_tools
    assert "restore_name=${2:-}" in db_tools
