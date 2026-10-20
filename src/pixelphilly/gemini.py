"""One Gemini 3 Pro Image redraw call, shared by 07_redraw.py and
13_build_trainset.py so frames and training targets are made identically.

Cost: $0.134 per 1K output image at standard pricing (Gemini API pricing
page, checked Oct. 20, 2026).

Terms note: the Gemini API terms bar using the service "to develop models
that compete with the Services". Training a Philadelphia-only style LoRA on
these outputs was approved by Stephen for internal use on Oct. 20, 2026, with
legal review required before anything is published (see README).
"""

from __future__ import annotations

import io
import os

from PIL import Image

MODEL = "gemini-3-pro-image"
PRICE_PER_IMAGE = 0.134


def make_client():
    from dotenv import load_dotenv
    from google import genai

    from .projection import REPO_ROOT

    load_dotenv(REPO_ROOT / ".env")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
    return genai.Client(api_key=key)


def redraw(client, png_bytes: bytes, prompt: str, size: int) -> tuple[Image.Image, list[int] | None]:
    """Send one render with the prompt; return the redraw at size x size and
    the size Gemini actually returned (None if it already matched)."""
    from google.genai import types

    resp = client.models.generate_content(
        model=MODEL,
        contents=[types.Part.from_bytes(data=png_bytes, mime_type="image/png"), prompt],
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="1:1", image_size="1K"),
        ),
    )
    parts = resp.candidates[0].content.parts if resp.candidates else []
    img_part = next((p for p in parts if p.inline_data and p.inline_data.data), None)
    if img_part is None:
        raise RuntimeError(f"no image in response: {getattr(resp, 'text', resp)}")
    img = Image.open(io.BytesIO(img_part.inline_data.data)).convert("RGB")
    returned = None
    if img.size != (size, size):
        # Gemini returns ~1K; resample onto the frame grid so it lines up with the render
        returned = list(img.size)
        img = img.resize((size, size), Image.LANCZOS)
    return img, returned


def is_quota_error(exc: Exception) -> bool:
    # A quota error fails every later call too, so callers stop instead of
    # burning through their list.
    return "RESOURCE_EXHAUSTED" in str(exc)
