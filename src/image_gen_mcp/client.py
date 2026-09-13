"""Gemini image-generation client."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import structlog
from google import genai

logger = structlog.get_logger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash-image"


class ImageGenClientError(Exception):
    """Raised when image generation fails or the API returns no image."""


class ImageGenClient:
    """Client for Gemini's native image-generation models."""

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ImageGenClientError("GEMINI_API_KEY is required")
        self._client = genai.Client(api_key=api_key)
        self._logger = logger.bind(component="ImageGenClient")

    def generate_image(
        self,
        prompt: str,
        *,
        model: str = DEFAULT_MODEL,
        save_path: str | None = None,
    ) -> dict[str, Any]:
        """Generate one image from a text prompt.

        Args:
            prompt: Description of the image to generate.
            model: Gemini image-generation model name.
            save_path: If given, also writes the raw image bytes to this path.

        Returns:
            {image_base64, mime_type, model, note, saved_to}

        Raises:
            ImageGenClientError: on any API failure or if no image is returned
                (e.g. the model declined the prompt) -- never fabricates an image.
        """
        self._logger.info("Generating image", model=model, prompt=prompt[:120])
        try:
            response = self._client.models.generate_content(model=model, contents=prompt)
        except Exception as exc:
            self._logger.exception("Image generation request failed")
            raise ImageGenClientError(f"Image generation failed: {exc}") from exc

        candidates = response.candidates or []
        parts = candidates[0].content.parts if candidates and candidates[0].content else None
        if not parts:
            raise ImageGenClientError("Gemini returned no content for this prompt")

        image_bytes: bytes | None = None
        mime_type: str | None = None
        note: str | None = None
        for part in parts:
            if part.inline_data and part.inline_data.data:
                image_bytes = part.inline_data.data
                mime_type = part.inline_data.mime_type
            elif part.text:
                note = part.text

        if image_bytes is None:
            reason = f" (model said: {note})" if note else ""
            raise ImageGenClientError(f"Gemini did not return an image for this prompt{reason}")

        saved_to = None
        if save_path:
            Path(save_path).write_bytes(image_bytes)
            saved_to = save_path

        return {
            "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            "mime_type": mime_type,
            "model": model,
            "note": note,
            "saved_to": saved_to,
        }
