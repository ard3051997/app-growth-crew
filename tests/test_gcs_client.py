"""Tests for gcs_mcp/client.py — covers init, credential paths, and error paths."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from gcs_mcp.client import GCSClient, GCSClientError


class TestGCSClientInit:
    def test_stores_credentials_json(self) -> None:
        creds = {"type": "service_account", "project_id": "proj"}
        client = GCSClient(credentials_json=creds)
        assert client._credentials_json == creds

    def test_no_credentials_by_default(self) -> None:
        client = GCSClient()
        assert client._credentials_json is None
        assert client._client is None


class TestGCSClientGetClient:
    def test_initialises_with_credentials_dict(self) -> None:
        creds = {"type": "service_account"}
        mock_creds = MagicMock()
        mock_creds.project_id = "proj"
        mock_storage = MagicMock()

        with (
            patch(
                "gcs_mcp.client.service_account.Credentials.from_service_account_info",
                return_value=mock_creds,
            ),
            patch("gcs_mcp.client.storage.Client", return_value=mock_storage) as MockClient,
        ):
            client = GCSClient(credentials_json=creds)
            result = client._get_client()

        MockClient.assert_called_once_with(credentials=mock_creds, project="proj")
        assert result is mock_storage

    def test_caches_client_on_second_call(self) -> None:
        mock_storage = MagicMock()
        client = GCSClient()
        client._client = mock_storage
        assert client._get_client() is mock_storage

    def test_falls_back_to_adc_when_no_creds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOOGLE_PLAY_STORE_CREDENTIALS", raising=False)
        mock_storage = MagicMock()

        with patch("gcs_mcp.client.storage.Client", return_value=mock_storage) as MockClient:
            client = GCSClient()
            client._get_client()

        MockClient.assert_called_once_with()

    def test_falls_back_to_env_var_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        creds = {"type": "service_account", "project_id": "env-proj"}
        monkeypatch.setenv("GOOGLE_PLAY_STORE_CREDENTIALS", json.dumps(creds))

        mock_creds = MagicMock()
        mock_creds.project_id = "env-proj"
        mock_storage = MagicMock()

        with (
            patch(
                "gcs_mcp.client.service_account.Credentials.from_service_account_info",
                return_value=mock_creds,
            ),
            patch("gcs_mcp.client.storage.Client", return_value=mock_storage),
        ):
            client = GCSClient()
            client._get_client()

        assert client._client is mock_storage

    def test_raises_gcs_client_error_on_init_failure(self) -> None:
        creds = {"type": "service_account"}

        with patch(
            "gcs_mcp.client.service_account.Credentials.from_service_account_info",
            side_effect=ValueError("bad creds"),
        ):
            client = GCSClient(credentials_json=creds)
            with pytest.raises(GCSClientError, match="Failed to initialize"):
                client._get_client()


class TestGCSClientListBuckets:
    def test_returns_bucket_list(self) -> None:
        mock_bucket = MagicMock()
        mock_bucket.name = "my-bucket"
        mock_bucket.time_created = None

        mock_storage = MagicMock()
        mock_storage.list_buckets.return_value = [mock_bucket]

        client = GCSClient()
        client._client = mock_storage

        result = client.list_buckets()
        assert len(result) == 1
        assert result[0]["name"] == "my-bucket"
        assert result[0]["created"] is None

    def test_raises_on_api_error(self) -> None:
        mock_storage = MagicMock()
        mock_storage.list_buckets.side_effect = Exception("api error")

        client = GCSClient()
        client._client = mock_storage

        with pytest.raises(GCSClientError, match="Failed to list buckets"):
            client.list_buckets()


class TestGCSClientListBlobs:
    def test_returns_blob_list(self) -> None:
        mock_blob = MagicMock()
        mock_blob.name = "reports/file.csv"
        mock_blob.size = 4096
        mock_blob.updated = None
        mock_blob.content_type = "text/csv"

        mock_bucket = MagicMock()
        mock_bucket.list_blobs.return_value = [mock_blob]

        mock_storage = MagicMock()
        mock_storage.bucket.return_value = mock_bucket

        client = GCSClient()
        client._client = mock_storage

        result = client.list_blobs("my-bucket", prefix="reports/")
        assert len(result) == 1
        assert result[0]["name"] == "reports/file.csv"
        assert result[0]["size"] == 4096

    def test_raises_on_api_error(self) -> None:
        mock_storage = MagicMock()
        mock_storage.bucket.side_effect = Exception("bucket not found")

        client = GCSClient()
        client._client = mock_storage

        with pytest.raises(GCSClientError, match="Failed to list blobs"):
            client.list_blobs("missing-bucket")


class TestGCSClientReadBlobContent:
    def test_reads_utf8_content(self) -> None:
        content = b"col1,col2\nval1,val2"

        mock_blob = MagicMock()
        mock_blob.download_as_bytes.return_value = content
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_storage = MagicMock()
        mock_storage.bucket.return_value = mock_bucket

        client = GCSClient()
        client._client = mock_storage

        result = client.read_blob_content("bucket", "file.csv")
        assert result == "col1,col2\nval1,val2"

    def test_raises_on_download_error(self) -> None:
        mock_blob = MagicMock()
        mock_blob.download_as_bytes.side_effect = Exception("not found")
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_storage = MagicMock()
        mock_storage.bucket.return_value = mock_bucket

        client = GCSClient()
        client._client = mock_storage

        with pytest.raises(GCSClientError, match="Failed to read blob"):
            client.read_blob_content("bucket", "missing.csv")


class TestGCSClientDownloadBlob:
    def test_downloads_to_path(self, tmp_path: Any) -> None:
        dest = str(tmp_path / "output.csv")

        mock_blob = MagicMock()
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_storage = MagicMock()
        mock_storage.bucket.return_value = mock_bucket

        client = GCSClient()
        client._client = mock_storage

        result = client.download_blob("bucket", "file.csv", dest)
        mock_blob.download_to_filename.assert_called_once_with(dest)
        assert result["success"] is True
        assert result["destination_path"] == dest

    def test_raises_on_download_error(self, tmp_path: Any) -> None:
        mock_blob = MagicMock()
        mock_blob.download_to_filename.side_effect = Exception("network error")
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_storage = MagicMock()
        mock_storage.bucket.return_value = mock_bucket

        client = GCSClient()
        client._client = mock_storage

        with pytest.raises(GCSClientError, match="Failed to download blob"):
            client.download_blob("bucket", "file.csv", str(tmp_path / "out.csv"))
