"""Provider-agnostic single-turn LLM completion helper.

This is intentionally minimal: it exists to back one call site
(``HypothesisGenerator.generate`` in ``experiment_engine.py``) that needs a
single JSON-producing completion from whichever LLM provider is configured.
It does not attempt to be a general-purpose SDK wrapper — no streaming, no
tool use, no retries beyond what ``httpx`` gives us for free.

Callers are responsible for their own JSON-fence-stripping / ``json.loads``ing
of the returned text; this module only resolves the provider and returns the
raw completion text.
"""

from __future__ import annotations

import os

import httpx

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
_GEMINI_MODEL = "gemini-2.0-flash"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_OPENAI_MODEL = "gpt-4o"

_REQUEST_TIMEOUT = 60.0


async def complete_json(
    system_instructions: str,
    prompt: str,
    *,
    provider: str | None = None,
    api_key: str | None = None,
) -> str:
    """Get a single completion from the configured LLM provider.

    Args:
        system_instructions: System/instruction text for the model.
        prompt: The user prompt.
        provider: One of "anthropic", "gemini", "openai". Falls back to the
            ``HYPOTHESIS_LLM_PROVIDER`` env var, then "gemini" (preserving
            behavior for existing deployments with no config changes).
        api_key: Explicit API key. Falls back to the provider-appropriate
            env var (``ANTHROPIC_API_KEY`` / ``GEMINI_API_KEY`` / ``OPENAI_API_KEY``).

    Returns:
        The raw completion text from the model. Callers handle their own
        markdown-fence stripping and JSON parsing.
    """
    resolved_provider = (provider or os.environ.get("HYPOTHESIS_LLM_PROVIDER") or "gemini").lower()

    if resolved_provider == "anthropic":
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        return await _complete_anthropic(system_instructions, prompt, key)
    if resolved_provider == "openai":
        key = api_key or os.environ.get("OPENAI_API_KEY")
        return await _complete_openai(system_instructions, prompt, key)

    # Default / "gemini" / anything unrecognized falls back to Gemini.
    key = api_key or os.environ.get("GEMINI_API_KEY")
    return await _complete_gemini(system_instructions, prompt, key)


async def _complete_anthropic(system_instructions: str, prompt: str, api_key: str | None) -> str:
    """POST to the Anthropic Messages API and return the completion text."""
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": _ANTHROPIC_MODEL,
        "max_tokens": 4096,
        "system": system_instructions,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.post(_ANTHROPIC_URL, headers=headers, json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Anthropic API request failed: {exc}") from exc

        return str(response.json()["content"][0]["text"])


async def _complete_gemini(system_instructions: str, prompt: str, api_key: str | None) -> str:
    """POST to the Gemini generateContent API and return the completion text."""
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{_GEMINI_MODEL}:generateContent?key={api_key}"
    )
    body = {
        "systemInstruction": {"parts": [{"text": system_instructions}]},
        "contents": [{"parts": [{"text": prompt}]}],
    }

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.post(url, json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc

        return str(response.json()["candidates"][0]["content"]["parts"][0]["text"])


async def _complete_openai(system_instructions: str, prompt: str, api_key: str | None) -> str:
    """POST to the OpenAI chat completions API and return the completion text."""
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set")

    headers = {"Authorization": f"Bearer {api_key}"}
    body = {
        "model": _OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_instructions},
            {"role": "user", "content": prompt},
        ],
    }

    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.post(_OPENAI_URL, headers=headers, json=body)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"OpenAI API request failed: {exc}") from exc

        return str(response.json()["choices"][0]["message"]["content"])
