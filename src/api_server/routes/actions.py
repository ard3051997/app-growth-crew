from typing import Any

from fastapi import APIRouter, HTTPException

from funnel_engine.db import DEFAULT_DB_PATH, get_db_actions

router = APIRouter()


@router.get("/")
def list_actions(
    app: str | None = None,
    type: str | None = None,
    experiment_id: str | None = None,
    limit: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    """Action log entries from SQLite database."""
    try:
        actions = get_db_actions(
            DEFAULT_DB_PATH,
            app_package=app,
            action_type=type,
            experiment_id=experiment_id,
            limit=limit,
        )
        return {"actions": actions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
