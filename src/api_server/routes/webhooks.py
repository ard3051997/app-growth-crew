import asyncio
import json
import sqlite3

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from api_server.auth import revenuecat_verification_required
from api_server.webhook_store import (
    claim_next_webhook_event,
    claim_webhook_event,
    finish_webhook_event,
    finish_webhook_receipt,
)
from app_manager.credential_store import get_app_credentials
from fcm_push_mcp.client import FCMClient
from funnel_engine.db import DEFAULT_DB_PATH, log_db_action
from mcp_gc_shared.write_guard import assert_writes_allowed, is_read_only

logger = structlog.get_logger("api_webhooks")

router = APIRouter()


class RevenueCatEvent(BaseModel):
    id: str | None = Field(default=None, description="RevenueCat provider event ID")
    type: str = Field(..., description="RevenueCat event type, e.g. CANCELLATION or BILLING_ERROR")
    app_id: str = Field(..., description="The app's package name / bundle ID")
    app_user_id: str = Field(..., description="The subscriber's user ID")
    product_id: str | None = None
    entitlement_id: str | None = None


class RevenueCatWebhookPayload(BaseModel):
    event: RevenueCatEvent


def _redacted_action_arguments(event: RevenueCatEvent) -> str:
    return json.dumps(
        {
            "user_id": "[REDACTED]",
            "event_type": event.type,
            "product_id": event.product_id,
        }
    )


# Deterministic, non-LLM copy for each RevenueCat event type this pipeline reacts to.
# (Interactive/AI-composed copy now happens in the user's coding-agent CLI session, not here.)
_REENGAGEMENT_TEMPLATES: dict[str, tuple[str, str]] = {
    "CANCELLATION": (
        "We miss you already!",
        "Your subscription was cancelled — come back anytime and pick up right where you left off.",
    ),
    "BILLING_ERROR": (
        "There's an issue with your payment",
        "We couldn't process your last payment. Update your payment method to keep your "
        "subscription active.",
    ),
}
_DEFAULT_REENGAGEMENT_TEMPLATE = (
    "We'd love to have you back",
    "Come back and see what's new.",
)


def _reengagement_notification(event: RevenueCatEvent) -> tuple[str, str]:
    """Pick a deterministic re-engagement notification title/body for the event type."""
    return _REENGAGEMENT_TEMPLATES.get(event.type, _DEFAULT_REENGAGEMENT_TEMPLATE)


async def run_fcm_reengagement(event: RevenueCatEvent) -> None:
    """Send a templated FCM re-engagement push notification for a RevenueCat event."""
    assert_writes_allowed("FCM re-engagement")
    logger.info("Starting FCM re-engagement logic", event_type=event.type, app=event.app_id)
    try:
        # Resolve app-specific credentials from the credential store
        creds = get_app_credentials(event.app_id)
        title, body = _reengagement_notification(event)
        client = FCMClient(credentials_path=creds.google_credentials_path)

        logger.info("Sending FCM re-engagement push", event_type=event.type, app=event.app_id)
        result = await asyncio.to_thread(
            client.send_push_to_token,
            event.app_user_id,
            title,
            body,
            {"revenuecat_event_type": event.type},
        )
        if result.get("status") != "success":
            raise RuntimeError(f"FCM send failed: {result.get('error_message', 'unknown error')}")
        logger.info("FCM re-engagement push sent", event_type=event.type, app=event.app_id)

        # Log successful action to DB
        log_db_action(
            db_path=DEFAULT_DB_PATH,
            action_type="push_reengagement",
            app_package=event.app_id,
            tool_name="fcm_push/send_push_to_token",
            arguments=_redacted_action_arguments(event),
            result="success",
            reasoning=f"RevenueCat {event.type} event triggered FCM push.",
        )
    except Exception:
        # Specialist exceptions may include the prompt and subscriber token.
        logger.error(  # noqa: TRY400
            "FCM re-engagement pipeline execution failed",
            event_type=event.type,
            app=event.app_id,
        )
        # Log exception failure to DB
        try:
            log_db_action(
                db_path=DEFAULT_DB_PATH,
                action_type="push_reengagement",
                app_package=event.app_id,
                tool_name="fcm_push/send_push_to_token",
                arguments=_redacted_action_arguments(event),
                result="failed",
                reasoning="Exception during FCM re-engagement pipeline.",
            )
        except Exception:
            logger.error("Failed to log re-engagement failure to DB")  # noqa: TRY400
        raise


async def _process_revenuecat_event(event: RevenueCatEvent, claim_token: str) -> None:
    """Process one claimed event and durably publish its terminal state."""
    try:
        await run_fcm_reengagement(event)
    except Exception as exc:
        finish_webhook_event(
            "revenuecat",
            event.id or "",
            claim_token,
            succeeded=False,
            error_safe=f"FCM re-engagement failed ({type(exc).__name__})",
            db_path=DEFAULT_DB_PATH,
        )
        return
    finish_webhook_event(
        "revenuecat",
        event.id or "",
        claim_token,
        succeeded=True,
        db_path=DEFAULT_DB_PATH,
    )


async def run_revenuecat_outbox_worker() -> None:
    """Recover failed or expired RevenueCat outbox work in the background."""
    while True:
        await asyncio.sleep(30)
        if is_read_only():
            continue
        try:
            claim = claim_next_webhook_event("revenuecat", DEFAULT_DB_PATH)
            if claim is None:
                continue
            try:
                payload = RevenueCatWebhookPayload.model_validate_json(claim["payload_json"])
            except Exception as exc:
                finish_webhook_receipt(
                    "revenuecat",
                    claim["event_id_hash"],
                    claim["claim_token"],
                    succeeded=False,
                    error_safe=f"Invalid stored webhook payload ({type(exc).__name__})",
                    db_path=DEFAULT_DB_PATH,
                )
                continue
            if payload.event.type in ("CANCELLATION", "BILLING_ERROR"):
                await _process_revenuecat_event(payload.event, claim["claim_token"])
            else:
                finish_webhook_receipt(
                    "revenuecat",
                    claim["event_id_hash"],
                    claim["claim_token"],
                    succeeded=True,
                    db_path=DEFAULT_DB_PATH,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("RevenueCat outbox recovery iteration failed")


@router.post("/revenuecat")
async def receive_revenuecat_webhook(
    payload: RevenueCatWebhookPayload,
    background_tasks: BackgroundTasks,
    request: Request,
) -> dict[str, str]:
    """Receive webhook events from RevenueCat and trigger FCM re-engagement campaigns."""
    if is_read_only():
        raise HTTPException(
            status_code=403,
            detail="API is in read-only mode; webhook processing is disabled",
        )
    event = payload.event
    verified = getattr(request.state, "revenuecat_webhook_verified", False)
    if revenuecat_verification_required() and not verified:
        raise HTTPException(status_code=401, detail="Invalid RevenueCat webhook secret")
    if not event.id:
        raise HTTPException(status_code=400, detail="RevenueCat event ID is required")

    try:
        state, claim_token = claim_webhook_event(
            "revenuecat",
            event.id,
            payload.model_dump_json(),
            DEFAULT_DB_PATH,
        )
    except (sqlite3.Error, RuntimeError):
        logger.exception("Unable to persist RevenueCat webhook receipt")
        raise HTTPException(status_code=503, detail="Webhook receipt store unavailable")
    if claim_token is None:
        logger.info(
            "Ignored replayed RevenueCat webhook",
            type=event.type,
            app=event.app_id,
            receipt_state=state,
        )
        return {"status": "duplicate", "message": f"Event is already {state}"}

    logger.info("Received RevenueCat webhook event", type=event.type, app=event.app_id)

    if event.type in ("CANCELLATION", "BILLING_ERROR"):
        background_tasks.add_task(_process_revenuecat_event, event, claim_token)
        return {"status": "processing", "message": f"Triggered FCM push for {event.type}"}

    if not finish_webhook_event(
        "revenuecat",
        event.id,
        claim_token,
        succeeded=True,
        db_path=DEFAULT_DB_PATH,
    ):
        raise HTTPException(status_code=503, detail="Webhook receipt finalization failed")
    return {"status": "ignored", "message": f"Event type {event.type} does not require action"}
