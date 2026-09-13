"""GCS Client wrapper."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from google.cloud import storage
from google.oauth2 import service_account


class GCSClientError(Exception):
    """Base exception for GCSClient errors."""


class GCSClient:
    """A client for Google Cloud Storage."""

    def __init__(self, credentials_json: dict[str, Any] | None = None) -> None:
        """Initialize GCS client.

        Args:
            credentials_json: Optional dict containing service account credentials.
                            If not provided, falls back to environment variables.
        """
        self._credentials_json = credentials_json
        self._client: storage.Client | None = None

    def _get_client(self) -> storage.Client:
        """Get or initialize the Google Cloud Storage client.

        Returns:
            Configured storage.Client

        Raises:
            GCSClientError: If initialization fails
        """
        if self._client is not None:
            return self._client

        try:
            if self._credentials_json:
                credentials = service_account.Credentials.from_service_account_info(
                    self._credentials_json
                )
                self._client = storage.Client(
                    credentials=credentials, project=credentials.project_id
                )
            else:
                # Try getting credentials from GOOGLE_PLAY_STORE_CREDENTIALS env var (since it might be the same SA)
                # or fallback to standard ADC.
                env_creds = os.environ.get("GOOGLE_PLAY_STORE_CREDENTIALS")
                if env_creds:
                    try:
                        creds_dict = json.loads(env_creds)
                        credentials = service_account.Credentials.from_service_account_info(
                            creds_dict
                        )
                        self._client = storage.Client(
                            credentials=credentials, project=credentials.project_id
                        )
                    except json.JSONDecodeError:
                        # Maybe it's a file path
                        credentials = service_account.Credentials.from_service_account_file(
                            env_creds
                        )
                        self._client = storage.Client(
                            credentials=credentials, project=credentials.project_id
                        )
                else:
                    self._client = storage.Client()
        except Exception as e:
            raise GCSClientError(f"Failed to initialize GCS client: {e}") from e

        return self._client

    def list_buckets(self) -> list[dict[str, Any]]:
        """List all buckets in the project.

        Returns:
            List of dictionaries containing bucket details.
        """
        try:
            client = self._get_client()
            buckets = client.list_buckets()
            return [
                {
                    "name": bucket.name,
                    "created": bucket.time_created.isoformat() if bucket.time_created else None,
                }
                for bucket in buckets
            ]
        except Exception as e:
            raise GCSClientError(f"Failed to list buckets: {e}") from e

    def list_blobs(self, bucket_name: str, prefix: str = "") -> list[dict[str, Any]]:
        """List blobs in a specific bucket.

        Args:
            bucket_name: Name of the GCS bucket.
            prefix: Optional prefix to filter blobs.

        Returns:
            List of dictionaries containing blob details.
        """
        try:
            client = self._get_client()
            bucket = client.bucket(bucket_name)
            blobs = bucket.list_blobs(prefix=prefix)
            return [
                {
                    "name": blob.name,
                    "size": blob.size,
                    "updated": blob.updated.isoformat() if blob.updated else None,
                    "content_type": blob.content_type,
                }
                for blob in blobs
            ]
        except Exception as e:
            raise GCSClientError(f"Failed to list blobs in {bucket_name}: {e}") from e

    def read_blob_content(self, bucket_name: str, blob_name: str) -> str:
        """Read the content of a blob into memory.

        Args:
            bucket_name: Name of the GCS bucket.
            blob_name: Name of the blob to read.

        Returns:
            String content of the blob.
        """
        try:
            client = self._get_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)
            content = cast("bytes", blob.download_as_bytes())
            for encoding in ["utf-8", "utf-16", "utf-16-le", "utf-16-be"]:
                try:
                    return content.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return content.decode("utf-8")
        except Exception as e:
            raise GCSClientError(f"Failed to read blob {blob_name} in {bucket_name}: {e}") from e

    def download_blob(
        self, bucket_name: str, blob_name: str, destination_path: str
    ) -> dict[str, Any]:
        """Download a blob to a local file.

        Args:
            bucket_name: Name of the GCS bucket.
            blob_name: Name of the blob to download.
            destination_path: Local path to save the file.

        Returns:
            Dictionary with success status and path.
        """
        try:
            client = self._get_client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(blob_name)

            dest_file = Path(destination_path)
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            blob.download_to_filename(str(dest_file))
            return {"success": True, "destination_path": str(dest_file)}
        except Exception as e:
            raise GCSClientError(
                f"Failed to download blob {blob_name} in {bucket_name}: {e}"
            ) from e
