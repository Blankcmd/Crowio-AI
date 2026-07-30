"""
config.py
=========
Central configuration for Crowio AI.

Everything that you might reasonably want to tune lives here so you never have
to hunt through the logic modules. Values are documented inline so a newcomer
can understand the trade-offs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Tuple

from dotenv import load_dotenv

# Load variables from a local .env file (if present) into os.environ.
load_dotenv()


@dataclass
class CrowioConfig:
    # ---------------------------------------------------------------------
    # Model / API
    # ---------------------------------------------------------------------
    # The Anthropic API key. Never hard-code this; read it from the env.
    api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))

    # Base URL for the API endpoint. Leave empty to use Anthropic directly.
    # Set this to your AgentRouter (or any Anthropic-compatible proxy) URL when
    # using a third-party router key. Read from ANTHROPIC_BASE_URL in .env.
    base_url: str = field(default_factory=lambda: os.getenv("ANTHROPIC_BASE_URL", ""))

    # Claude model that supports the Computer Use tool.
    # Set to the exact model name your provider (AgentRouter) offers.
    # Update this string if you switch providers or Anthropic ships a newer snapshot.
    model: str = "claude-opus-4-8"

    # Beta header required to enable the computer-use tool family.
    beta_flag: str = "computer-use-2025-01-24"

    # Max tokens the model may use per planning turn.
    max_tokens: int = 1500

    # ---------------------------------------------------------------------
    # Screen / coordinate handling
    # ---------------------------------------------------------------------
    # Anthropic recommends sending screenshots at <= 1280x800 (WXGA) for the
    # best accuracy and lowest latency. We capture at native resolution, then
    # downscale to this target before sending. The executor scales the model's
    # returned coordinates back up to the real screen. Keep the aspect ratio
    # close to your monitor's to avoid distortion.
    target_width: int = 1280
    target_height: int = 800

    # Which monitor to control (1 = primary). mss uses 1-based indexing.
    monitor_index: int = 1

    # ---------------------------------------------------------------------
    # Safety guardrails
    # ---------------------------------------------------------------------
    # Global emergency kill-switch. Pressing this combo aborts everything.
    kill_switch_hotkey: Tuple[str, ...] = ("ctrl", "alt", "k")

    # Restrict all mouse activity to a bounding box (left, top, right, bottom)
    # in REAL screen pixels. None = full screen allowed. Use this to fence the
    # agent into, say, a single browser window while you build confidence.
    bounding_box: Tuple[int, int, int, int] | None = None

    # Require a human "y/N" confirmation before running risky actions
    # (anything that submits, purchases, deletes, or leaves the box).
    require_confirmation: bool = True

    # Keywords that, if present in the typed text or target, force a
    # confirmation prompt even when require_confirmation is otherwise relaxed.
    sensitive_keywords: tuple[str, ...] = (
        "password", "delete", "buy", "purchase", "pay", "transfer",
        "confirm", "submit", "send", "format", "shutdown", "sudo",
    )

    # ---------------------------------------------------------------------
    # Loop behavior
    # ---------------------------------------------------------------------
    # Hard cap on planning iterations so a confused agent can't loop forever.
    max_steps: int = 40

    # Seconds to pause after each executed action so the UI can settle before
    # the next screenshot. Too low = stale screenshots; too high = sluggish.
    action_delay: float = 1.0

    # PyAutoGUI's built-in failsafe: slamming the mouse to a screen corner
    # raises an exception. Keep this True as a second kill-switch.
    pyautogui_failsafe: bool = True

    def validate(self) -> None:
        """Fail fast with a friendly message if something essential is missing."""
        if not self.api_key:
            raise SystemExit(
                "ANTHROPIC_API_KEY is not set.\n"
                "Create a .env file (copy .env.example) or set the environment "
                "variable, then try again."
            )


# A single shared instance most modules can import directly.
CONFIG = CrowioConfig()
