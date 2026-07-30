"""
perception.py  -  COMPONENT A: Screen Capture
=============================================
Grabs the current screen (desktop or whatever browser/app is focused), and
prepares it for the vision model.

Key responsibility beyond "take a screenshot": *coordinate scaling*.

The model reasons about a downscaled image (e.g. 1280x800) but the real screen
might be 1920x1080 or a 4K/Retina display. We record the scale factors here so
the executor can translate the model's click coordinates back to real pixels.
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

import mss
from PIL import Image

from config import CONFIG


@dataclass
class Screenshot:
    """A captured frame plus everything needed to map coordinates."""

    image_b64: str          # PNG, base64-encoded, downscaled to model resolution
    media_type: str         # always "image/png" here
    model_width: int        # width of the image the model sees
    model_height: int       # height of the image the model sees
    real_width: int         # actual monitor width in pixels
    real_height: int        # actual monitor height in pixels
    real_left: int          # monitor's left offset (multi-monitor setups)
    real_top: int           # monitor's top offset

    def to_real_coords(self, model_x: int, model_y: int) -> tuple[int, int]:
        """Convert a model-space (x, y) into absolute screen pixels."""
        scale_x = self.real_width / self.model_width
        scale_y = self.real_height / self.model_height
        real_x = self.real_left + int(round(model_x * scale_x))
        real_y = self.real_top + int(round(model_y * scale_y))
        return real_x, real_y


class ScreenCapture:
    """Thin wrapper over mss for fast, multi-monitor capture."""

    def __init__(self) -> None:
        # mss is not thread-safe; keep one instance per thread. We create it
        # lazily inside capture() to stay safe across the agent's loop.
        self._monitor_index = CONFIG.monitor_index

    def capture(self) -> Screenshot:
        """Take a screenshot and return a scaled, encoded Screenshot object."""
        with mss.mss() as sct:
            # monitors[0] is the "all monitors" virtual screen; 1..N are real.
            monitor = sct.monitors[self._monitor_index]
            raw = sct.grab(monitor)

            real_width, real_height = raw.width, raw.height
            real_left, real_top = monitor["left"], monitor["top"]

            # Convert the raw BGRA buffer into a Pillow image.
            img = Image.frombytes("RGB", raw.size, raw.rgb)

        # Downscale to the model's target resolution (preserving nothing fancy;
        # a straight resize keeps coordinate math simple and predictable).
        model_w = CONFIG.target_width
        model_h = CONFIG.target_height
        img_small = img.resize((model_w, model_h), Image.LANCZOS)

        # Encode as PNG in memory, then base64 for the API payload.
        buffer = io.BytesIO()
        img_small.save(buffer, format="PNG")
        image_b64 = base64.b64encode(buffer.getvalue()).decode("ascii")

        return Screenshot(
            image_b64=image_b64,
            media_type="image/png",
            model_width=model_w,
            model_height=model_h,
            real_width=real_width,
            real_height=real_height,
            real_left=real_left,
            real_top=real_top,
        )
