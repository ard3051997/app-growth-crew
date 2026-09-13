"""Tests for image_gen_mcp client and server."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from image_gen_mcp.client import ImageGenClient, ImageGenClientError
from image_gen_mcp.server import generate_image, mcp


def _mock_context(client: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = {"client": client}
    return ctx


@pytest.fixture
def mock_client() -> MagicMock:
    return MagicMock(spec=ImageGenClient)


@pytest.fixture(autouse=True)
def _patch_mcp_context(mock_client: MagicMock) -> Any:
    ctx = _mock_context(mock_client)
    with patch.object(mcp, "get_context", return_value=ctx):
        yield


def _fake_part(*, inline_data: MagicMock | None = None, text: str | None = None) -> MagicMock:
    part = MagicMock()
    part.inline_data = inline_data
    part.text = text
    return part


def _fake_response(parts: list[MagicMock]) -> MagicMock:
    response = MagicMock()
    candidate = MagicMock()
    candidate.content.parts = parts
    response.candidates = [candidate]
    return response


class TestImageGenClient:
    def test_requires_api_key(self) -> None:
        with pytest.raises(ImageGenClientError, match="GEMINI_API_KEY"):
            ImageGenClient(api_key="")

    @patch("image_gen_mcp.client.genai.Client")
    def test_generate_image_returns_real_bytes_as_base64(
        self, mock_genai_client: MagicMock
    ) -> None:
        inline_data = MagicMock(data=b"\x89PNG\r\n fake bytes", mime_type="image/png")
        response = _fake_response([_fake_part(inline_data=inline_data)])
        mock_instance = mock_genai_client.return_value
        mock_instance.models.generate_content.return_value = response

        client = ImageGenClient(api_key="fake-key")
        result = client.generate_image("a red circle")

        assert result["mime_type"] == "image/png"
        assert result["model"] == "gemini-2.5-flash-image"
        assert result["saved_to"] is None
        import base64

        assert base64.b64decode(result["image_base64"]) == b"\x89PNG\r\n fake bytes"

    @patch("image_gen_mcp.client.genai.Client")
    def test_generate_image_saves_to_disk_when_requested(
        self, mock_genai_client: MagicMock, tmp_path
    ) -> None:
        inline_data = MagicMock(data=b"fake-png-bytes", mime_type="image/png")
        response = _fake_response([_fake_part(inline_data=inline_data)])
        mock_genai_client.return_value.models.generate_content.return_value = response

        client = ImageGenClient(api_key="fake-key")
        out_path = tmp_path / "icon.png"
        result = client.generate_image("a red circle", save_path=str(out_path))

        assert result["saved_to"] == str(out_path)
        assert out_path.read_bytes() == b"fake-png-bytes"

    @patch("image_gen_mcp.client.genai.Client")
    def test_no_image_in_response_raises_instead_of_faking_success(
        self, mock_genai_client: MagicMock
    ) -> None:
        response = _fake_response([_fake_part(text="I can't generate that image.")])
        mock_genai_client.return_value.models.generate_content.return_value = response

        client = ImageGenClient(api_key="fake-key")
        with pytest.raises(ImageGenClientError, match="did not return an image"):
            client.generate_image("something declined")

    @patch("image_gen_mcp.client.genai.Client")
    def test_empty_candidates_raises(self, mock_genai_client: MagicMock) -> None:
        response = MagicMock()
        response.candidates = []
        mock_genai_client.return_value.models.generate_content.return_value = response

        client = ImageGenClient(api_key="fake-key")
        with pytest.raises(ImageGenClientError, match="no content"):
            client.generate_image("a red circle")

    @patch("image_gen_mcp.client.genai.Client")
    def test_api_exception_is_wrapped_not_swallowed(self, mock_genai_client: MagicMock) -> None:
        mock_genai_client.return_value.models.generate_content.side_effect = RuntimeError(
            "quota exceeded"
        )

        client = ImageGenClient(api_key="fake-key")
        with pytest.raises(ImageGenClientError, match="quota exceeded"):
            client.generate_image("a red circle")


class TestImageGenServerTools:
    def test_generate_image(self, mock_client: MagicMock) -> None:
        mock_client.generate_image.return_value = {
            "image_base64": "abc123",
            "mime_type": "image/png",
            "model": "gemini-2.5-flash-image",
            "note": None,
            "saved_to": None,
        }
        res = generate_image(prompt="a red circle")
        mock_client.generate_image.assert_called_once_with("a red circle", save_path=None)
        assert res["mime_type"] == "image/png"
