"""Firebase Cloud Messaging (FCM) v1 Client."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import google.auth.transport.requests
import structlog
from google.oauth2 import service_account

logger = structlog.get_logger(__name__)

FCM_SCOPE = ["https://www.googleapis.com/auth/firebase.messaging"]


class FCMClientError(Exception):
    """Base exception for FCM client errors."""


class FCMClient:
    """Client for Firebase Cloud Messaging v1 API."""

    def __init__(
        self,
        credentials_path: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Initialize the FCM client.

        Args:
            credentials_path: Path to service account JSON.
                             Defaults to GOOGLE_APPLICATION_CREDENTIALS env var.
            project_id: Firebase project ID. Defaults to extracting from service account JSON.
        """
        self._credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        self._project_id = project_id
        self._logger = logger.bind(component="FCMClient")
        self._is_mock = False

        if not self._credentials_path or not Path(self._credentials_path).exists():
            self._logger.warning("FCM client credentials not found. Running in MOCK mode.")
            self._is_mock = True
            return

        # Attempt to parse project ID from credentials if not explicitly passed
        if not self._project_id:
            try:
                with Path(self._credentials_path).open(encoding="utf-8") as f:
                    creds_info = json.load(f)
                    self._project_id = creds_info.get("project_id")
            except Exception as e:
                self._logger.warning("Failed to parse project_id from credentials", error=str(e))

        if not self._project_id:
            self._logger.warning("No Firebase project ID found. Running in MOCK mode.")
            self._is_mock = True

    def _get_authorized_session(self) -> google.auth.transport.requests.AuthorizedSession | None:
        """Get an authorized session with firebase messaging scope."""
        if self._is_mock:
            return None
        try:
            creds = service_account.Credentials.from_service_account_file(
                self._credentials_path, scopes=FCM_SCOPE
            )
            return google.auth.transport.requests.AuthorizedSession(creds)
        except Exception:
            self._logger.exception("Failed to create authorized session")
            self._is_mock = True
            return None

    def send_push_notification(
        self,
        topic: str,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send a push notification to a topic.

        Args:
            topic: FCM topic to send to.
            title: Notification title.
            body: Notification body.
            data: Key-value custom metadata payload.
        """
        message = {
            "topic": topic,
            "notification": {"title": title, "body": body},
        }
        if data:
            message["data"] = data

        return self._send(message)

    def send_push_to_token(
        self,
        token: str,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send a push notification to a single registration token.

        Args:
            token: Recipient device registration token.
            title: Notification title.
            body: Notification body.
            data: Key-value custom metadata payload.
        """
        message = {
            "token": token,
            "notification": {"title": title, "body": body},
        }
        if data:
            message["data"] = data

        return self._send(message)

    def send_push_to_condition(
        self,
        condition: str,
        title: str,
        body: str,
        data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send a push notification to a condition (logical expression of topics).

        Args:
            condition: Logical expression (e.g. "'trial_expired' in topics && 'us' in topics").
            title: Notification title.
            body: Notification body.
            data: Key-value custom metadata payload.
        """
        message = {
            "condition": condition,
            "notification": {"title": title, "body": body},
        }
        if data:
            message["data"] = data

        return self._send(message)

    def _send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send the message payload via FCM REST API."""
        if self._is_mock:
            self._logger.info("Mock FCM send trigger", payload=message)
            return {
                "status": "success",
                "mode": "mocked",
                "message_id": f"mock-msg-{os.urandom(8).hex()}",
            }

        session = self._get_authorized_session()
        if not session:
            self._logger.warning("FCM credentials authorization failed. Defaulting to mock.")
            self._is_mock = True
            return self._send(message)

        url = f"https://fcm.googleapis.com/v1/projects/{self._project_id}/messages:send"
        payload = {"message": message}

        try:
            self._logger.info("Sending FCM notification", target=next(iter(message)))
            resp = session.post(url, json=payload)
            if resp.status_code == 200:
                result = resp.json()
                self._logger.info(
                    "FCM notification sent successfully", message_id=result.get("name")
                )
                return {
                    "status": "success",
                    "mode": "live",
                    "message_id": result.get("name"),
                }
            else:
                self._logger.error(
                    "FCM API error response", status=resp.status_code, text=resp.text
                )
                return {
                    "status": "error",
                    "mode": "live",
                    "error_code": resp.status_code,
                    "error_message": resp.text,
                }
        except Exception as e:
            self._logger.exception("Exception during FCM request", error=str(e))
            return {
                "status": "error",
                "mode": "live",
                "error_message": str(e),
            }
