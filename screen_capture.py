"""
Jarvis V2 — Screen Capture
Takes screenshots and describes them via Gemini Vision.
"""

import io
from PIL import ImageGrab
from google.genai import types


def capture_screen() -> bytes:
    """Capture the entire screen, return PNG bytes."""
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def describe_screen(client, model: str) -> str:
    """Capture screen and describe it using Gemini Vision."""
    png_bytes = capture_screen()

    response = await client.aio.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
            "Briefly describe in English what is on this screen. 2-3 sentences at most. Name the main open programs and content.",
        ],
        config=types.GenerateContentConfig(
            max_output_tokens=300,
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
            http_options=types.HttpOptions(timeout=45_000, retry_options=types.HttpRetryOptions(attempts=2)),
        ),
    )
    return response.text or ""
