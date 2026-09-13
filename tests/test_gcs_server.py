"""Tests for gcs_mcp/server.py."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from gcs_mcp.client import GCSClient, GCSClientError
from gcs_mcp.server import (
    download_blob,
    list_blobs,
    list_buckets,
    mcp,
    read_blob_content,
)


def _mock_context(client: MagicMock) -> MagicMock:
    """Create a mock MCP context with the given client."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"client": client}
    return ctx


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock GCSClient."""
    return MagicMock(spec=GCSClient)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock) -> Any:
    """Patch mcp.get_context to return our mock client."""
    ctx = _mock_context(mock_client)
    with patch.object(mcp, "get_context", return_value=ctx):
        yield


class TestLifespan:
    """Test GCS server lifespan."""

    @pytest.mark.asyncio
    async def test_lifespan_success(self) -> None:
        """Test successful lifespan initialization."""
        from gcs_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch("gcs_mcp.server.GCSClient") as MockClient,
            patch("gcs_mcp.server.GCSClientError", GCSClientError),
        ):
            instance = MockClient.return_value
            async with lifespan(mock_server) as ctx:
                assert ctx["client"] is instance

    @pytest.mark.asyncio
    async def test_lifespan_failure(self) -> None:
        """Test lifespan initialization failure."""
        from gcs_mcp.server import lifespan

        mock_server = MagicMock()

        with (
            patch(
                "gcs_mcp.server.GCSClient",
                side_effect=GCSClientError("Failed to initialize"),
            ),
            patch("gcs_mcp.server.GCSClientError", GCSClientError),
        ):
            async with lifespan(mock_server) as ctx:
                assert ctx["client"] is None


class TestGCSTools:
    """Test GCS server tools."""

    def test_list_buckets(self, mock_client: MagicMock) -> None:
        mock_client.list_buckets.return_value = [
            {"name": "my-bucket", "created": "2026-06-07T12:00:00Z"}
        ]

        result = list_buckets()
        mock_client.list_buckets.assert_called_once()
        assert len(result) == 1
        assert result[0]["name"] == "my-bucket"

    def test_list_blobs(self, mock_client: MagicMock) -> None:
        mock_client.list_blobs.return_value = [
            {"name": "stats/file.csv", "size": 1234, "content_type": "text/csv"}
        ]

        result = list_blobs(bucket_name="my-bucket", prefix="stats/")
        mock_client.list_blobs.assert_called_once_with("my-bucket", "stats/")
        assert len(result) == 1
        assert result[0]["name"] == "stats/file.csv"

    def test_read_blob_content(self, mock_client: MagicMock) -> None:
        mock_client.read_blob_content.return_value = "header1,header2\nval1,val2"

        result = read_blob_content(bucket_name="my-bucket", blob_name="stats/file.csv")
        mock_client.read_blob_content.assert_called_once_with("my-bucket", "stats/file.csv")
        assert result == "header1,header2\nval1,val2"

    def test_download_blob(self, mock_client: MagicMock, tmp_path: Any) -> None:
        destination_path = str(tmp_path / "file.csv")
        mock_client.download_blob.return_value = {
            "success": True,
            "destination_path": destination_path,
        }

        result = download_blob(
            bucket_name="my-bucket",
            blob_name="stats/file.csv",
            destination_path=destination_path,
        )
        mock_client.download_blob.assert_called_once_with(
            "my-bucket", "stats/file.csv", destination_path
        )
        assert result["success"] is True
        assert result["destination_path"] == destination_path


class TestGCSToolsErrorPaths:
    """Test that tool functions surface GCSClientError correctly."""

    def test_list_buckets_raises_on_client_error(self, mock_client: MagicMock) -> None:
        mock_client.list_buckets.side_effect = GCSClientError("permission denied")

        with pytest.raises(GCSClientError, match="permission denied"):
            list_buckets()

    def test_list_blobs_raises_on_client_error(self, mock_client: MagicMock) -> None:
        mock_client.list_blobs.side_effect = GCSClientError("bucket not found")

        with pytest.raises(GCSClientError, match="bucket not found"):
            list_blobs(bucket_name="missing-bucket")

    def test_read_blob_content_raises_on_client_error(self, mock_client: MagicMock) -> None:
        mock_client.read_blob_content.side_effect = GCSClientError("blob not found")

        with pytest.raises(GCSClientError, match="blob not found"):
            read_blob_content(bucket_name="b", blob_name="missing.csv")

    def test_download_blob_raises_on_client_error(
        self, mock_client: MagicMock, tmp_path: Any
    ) -> None:
        mock_client.download_blob.side_effect = GCSClientError("download failed")

        with pytest.raises(GCSClientError, match="download failed"):
            download_blob(
                bucket_name="b",
                blob_name="f.csv",
                destination_path=str(tmp_path / "f.csv"),
            )

    def test_list_blobs_without_prefix(self, mock_client: MagicMock) -> None:
        mock_client.list_blobs.return_value = []

        result = list_blobs(bucket_name="my-bucket")
        mock_client.list_blobs.assert_called_once_with("my-bucket", "")
        assert result == []

    def test_list_buckets_with_null_client(self) -> None:
        """Lifespan failure leaves client as None; get_client_from_context raises GCSClientError."""
        ctx = MagicMock()
        ctx.request_context.lifespan_context = {"client": None}
        with patch.object(mcp, "get_context", return_value=ctx):
            with pytest.raises(GCSClientError):
                list_buckets()


class TestServerMain:
    """Test server main entry point."""

    def test_main_calls_mcp_run(self) -> None:
        from gcs_mcp import main

        with patch.object(mcp, "run") as mock_run:
            main()
            mock_run.assert_called_once()
