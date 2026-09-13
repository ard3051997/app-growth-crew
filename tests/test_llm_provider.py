"""Tests for the provider-agnostic LLM completion helper.

No real network calls -- httpx.AsyncClient is mocked throughout.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app_manager.llm_provider import complete_json


def _mock_httpx_post_client(response: MagicMock) -> MagicMock:
    """Build a mock httpx.AsyncClient usable as `async with httpx.AsyncClient() as client`."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _ok_response(json_body: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = json_body
    response.raise_for_status = MagicMock()  # no-op: 2xx
    return response


def _error_response(status_code: int = 500) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "error", request=MagicMock(), response=MagicMock(status_code=status_code)
        )
    )
    return response


class TestAnthropicProvider:
    @pytest.mark.asyncio
    async def test_returns_extracted_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
        response = _ok_response({"content": [{"type": "text", "text": "hello from anthropic"}]})
        mock_client = _mock_httpx_post_client(response)

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            result = await complete_json("system", "prompt", provider="anthropic")

        assert result == "hello from anthropic"
        call_kwargs = mock_client.__aenter__.return_value.post.call_args
        assert call_kwargs.args[0] == "https://api.anthropic.com/v1/messages"
        assert call_kwargs.kwargs["headers"]["x-api-key"] == "test-anthropic-key"
        assert call_kwargs.kwargs["headers"]["anthropic-version"] == "2023-06-01"
        assert call_kwargs.kwargs["json"]["system"] == "system"
        assert call_kwargs.kwargs["json"]["messages"] == [{"role": "user", "content": "prompt"}]

    @pytest.mark.asyncio
    async def test_non_2xx_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
        mock_client = _mock_httpx_post_client(_error_response(500))

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError):
                await complete_json("system", "prompt", provider="anthropic")


class TestGeminiProvider:
    @pytest.mark.asyncio
    async def test_returns_extracted_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        response = _ok_response(
            {"candidates": [{"content": {"parts": [{"text": "hello from gemini"}]}}]}
        )
        mock_client = _mock_httpx_post_client(response)

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            result = await complete_json("system", "prompt", provider="gemini")

        assert result == "hello from gemini"
        call_args = mock_client.__aenter__.return_value.post.call_args
        assert call_args.args[0].startswith(
            "https://generativelanguage.googleapis.com/v1beta/models/"
        )
        assert "key=test-gemini-key" in call_args.args[0]
        assert call_args.kwargs["json"]["systemInstruction"]["parts"] == [{"text": "system"}]
        assert call_args.kwargs["json"]["contents"] == [{"parts": [{"text": "prompt"}]}]

    @pytest.mark.asyncio
    async def test_non_2xx_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        mock_client = _mock_httpx_post_client(_error_response(503))

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError):
                await complete_json("system", "prompt", provider="gemini")

    @pytest.mark.asyncio
    async def test_is_default_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No explicit provider and no HYPOTHESIS_LLM_PROVIDER env var -> gemini."""
        monkeypatch.delenv("HYPOTHESIS_LLM_PROVIDER", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        response = _ok_response(
            {"candidates": [{"content": {"parts": [{"text": "default provider text"}]}}]}
        )
        mock_client = _mock_httpx_post_client(response)

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            result = await complete_json("system", "prompt")

        assert result == "default provider text"


class TestOpenAIProvider:
    @pytest.mark.asyncio
    async def test_returns_extracted_text(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        response = _ok_response(
            {"choices": [{"message": {"role": "assistant", "content": "hello from openai"}}]}
        )
        mock_client = _mock_httpx_post_client(response)

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            result = await complete_json("system", "prompt", provider="openai")

        assert result == "hello from openai"
        call_kwargs = mock_client.__aenter__.return_value.post.call_args
        assert call_kwargs.args[0] == "https://api.openai.com/v1/chat/completions"
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer test-openai-key"
        assert call_kwargs.kwargs["json"]["messages"] == [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "prompt"},
        ]

    @pytest.mark.asyncio
    async def test_non_2xx_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        mock_client = _mock_httpx_post_client(_error_response(401))

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError):
                await complete_json("system", "prompt", provider="openai")


class TestProviderSelection:
    @pytest.mark.asyncio
    async def test_env_var_selects_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HYPOTHESIS_LLM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        response = _ok_response(
            {"choices": [{"message": {"role": "assistant", "content": "via env var"}}]}
        )
        mock_client = _mock_httpx_post_client(response)

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            # No explicit provider= -- must be resolved from HYPOTHESIS_LLM_PROVIDER.
            result = await complete_json("system", "prompt")

        assert result == "via env var"
        call_kwargs = mock_client.__aenter__.return_value.post.call_args
        assert call_kwargs.args[0] == "https://api.openai.com/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_explicit_provider_overrides_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYPOTHESIS_LLM_PROVIDER", "openai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
        response = _ok_response({"content": [{"type": "text", "text": "via explicit arg"}]})
        mock_client = _mock_httpx_post_client(response)

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            result = await complete_json("system", "prompt", provider="anthropic")

        assert result == "via explicit arg"
        call_kwargs = mock_client.__aenter__.return_value.post.call_args
        assert call_kwargs.args[0] == "https://api.anthropic.com/v1/messages"

    @pytest.mark.asyncio
    async def test_explicit_api_key_overrides_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-should-not-be-used")
        response = _ok_response({"content": [{"type": "text", "text": "ok"}]})
        mock_client = _mock_httpx_post_client(response)

        with patch("app_manager.llm_provider.httpx.AsyncClient", return_value=mock_client):
            await complete_json("system", "prompt", provider="anthropic", api_key="explicit-key")

        call_kwargs = mock_client.__aenter__.return_value.post.call_args
        assert call_kwargs.kwargs["headers"]["x-api-key"] == "explicit-key"
