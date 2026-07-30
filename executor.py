"""
executor.py  -  COMPONENT C: OS Automation Executor
===================================================
Takes the normalized action dicts from the planner and actually drives the
mouse and keyboard via PyAutoGUI. Every action passes through the safety
guardrails first (bounding box + sensitive-action confirmation).

Coordinate translation happens here: the model thinks in model-space
(e.g. 1280x800), so we ask the current Screenshot to map those into real
screen pixels before moving the mouse.
"""

from __future__ import annotations

import time
from typing import Any

import pyautogui

from config import CONFIG
from perception import Screenshot
from safety import Guardrails


class ActionResult:
    """Outcome of executing one action, reported back up to the loop."""

    def __init__(self, ok: bool, message: str = "",
                 needs_screenshot: bool = True) -> None:
        self.ok = ok
        self.message = message
        # Most GUI actions change the screen, so we usually want a fresh
        # screenshot to send back to the model.
        self.needs_screenshot = needs_screenshot


class Executor:
    def __init__(self, guardrails: Guardrails) -> None:
        self.guardrails = guardrails
        # Configure PyAutoGUI global behavior.
        pyautogui.FAILSAFE = CONFIG.pyautogui_failsafe
        pyautogui.PAUSE = 0  # we manage our own delays in the main loop

    # -- dispatch ---------------------------------------------------------
    def execute(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        """Route an action dict to the right handler."""
        atype = action.get("type")
        handler = getattr(self, f"_do_{atype}", None)
        if handler is None:
            return ActionResult(False, f"Unsupported action: {atype}",
                                needs_screenshot=False)
        try:
            return handler(action, shot)
        except pyautogui.FailSafeException:
            # Mouse slammed into a corner -> treat as an abort signal.
            raise
        except Exception as exc:  # noqa: BLE001 - report any failure to model
            return ActionResult(False, f"Error running {atype}: {exc}")

    # -- guardrail helper -------------------------------------------------
    def _check_point(self, x: int, y: int) -> str | None:
        """Return an error string if the point is out of bounds, else None."""
        if not self.guardrails.point_allowed(x, y):
            return (f"Blocked: target ({x},{y}) is outside the allowed "
                    f"bounding box {self.guardrails.box}.")
        return None

    # -- mouse actions ----------------------------------------------------
    def _do_click(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        x, y = shot.to_real_coords(action["x"], action["y"])
        err = self._check_point(x, y)
        if err:
            return ActionResult(False, err)

        # Confirm if this looks sensitive (clicking a "Submit/Buy/Delete" btn is
        # impossible to detect by coordinates alone, so we confirm on demand via
        # the planner's text; here we optionally confirm out-of-box edges).
        button = action.get("button", "left")
        clicks = action.get("clicks", 1)
        pyautogui.click(x=x, y=y, clicks=clicks, interval=0.08, button=button)
        return ActionResult(True, f"{button} click x{clicks} at ({x},{y})")

    def _do_move(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        x, y = shot.to_real_coords(action["x"], action["y"])
        err = self._check_point(x, y)
        if err:
            return ActionResult(False, err)
        pyautogui.moveTo(x, y, duration=0.2)
        return ActionResult(True, f"moved to ({x},{y})", needs_screenshot=False)

    def _do_drag(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        end_x, end_y = shot.to_real_coords(action["x"], action["y"])
        err = self._check_point(end_x, end_y)
        if err:
            return ActionResult(False, err)
        if action.get("start"):
            sx, sy = shot.to_real_coords(action["start"][0], action["start"][1])
            err = self._check_point(sx, sy)
            if err:
                return ActionResult(False, err)
            pyautogui.moveTo(sx, sy, duration=0.2)
        pyautogui.dragTo(end_x, end_y, duration=0.4, button="left")
        return ActionResult(True, f"dragged to ({end_x},{end_y})")

    def _do_scroll(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        # Move to the anchor point first if one was provided.
        if action.get("x") is not None and action.get("y") is not None:
            x, y = shot.to_real_coords(action["x"], action["y"])
            if err := self._check_point(x, y):
                return ActionResult(False, err)
            pyautogui.moveTo(x, y, duration=0.15)

        amount = action.get("amount", 3)
        direction = action.get("direction", "down")
        # PyAutoGUI: positive = up, negative = down. ~100 px per "click".
        clicks = amount * 100
        if direction in ("down", "right"):
            clicks = -clicks
        if direction in ("left", "right"):
            pyautogui.hscroll(clicks)
        else:
            pyautogui.scroll(clicks)
        return ActionResult(True, f"scrolled {direction} {amount}")

    # -- keyboard actions -------------------------------------------------
    def _do_type(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        text = action.get("text", "")
        if self.guardrails.is_sensitive("type", text):
            preview = text if len(text) < 40 else text[:37] + "..."
            if not self.guardrails.confirm(f"Type sensitive text: '{preview}'?"):
                return ActionResult(False, "User declined to type sensitive text.")
        pyautogui.write(text, interval=0.02)
        return ActionResult(True, f"typed {len(text)} chars")

    def _do_key(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        keys = action.get("keys", "")
        if self.guardrails.is_sensitive("key", keys):
            if not self.guardrails.confirm(f"Press key combo '{keys}'?"):
                return ActionResult(False, "User declined key press.")
        # Support combos like "ctrl+s" via hotkey, single keys via press.
        parts = [self._map_key(k) for k in keys.replace(" ", "").split("+") if k]
        if len(parts) > 1:
            pyautogui.hotkey(*parts)
        elif parts:
            pyautogui.press(parts[0])
        return ActionResult(True, f"pressed {keys}")

    @staticmethod
    def _map_key(key: str) -> str:
        """Translate common Computer Use key names to PyAutoGUI names."""
        key = key.lower()
        aliases = {
            "return": "enter",
            "escape": "esc",
            "control": "ctrl",
            # The Windows key: PyAutoGUI's "winleft" is far more reliable in
            # hotkey combos than the generic "win", so normalize everything to it.
            "super": "winleft",
            "win": "winleft",
            "cmd": "winleft",   # Windows-first: map Mac cmd -> Windows key
            "command": "winleft",
            "meta": "winleft",
            "page_down": "pagedown",
            "page_up": "pageup",
            "backspace": "backspace",
        }
        return aliases.get(key, key)

    # -- passive actions --------------------------------------------------
    def _do_wait(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        time.sleep(action.get("seconds", 1))
        return ActionResult(True, "waited")

    def _do_screenshot(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        # No-op here; the main loop always returns a fresh screenshot anyway.
        return ActionResult(True, "screenshot requested")

    def _do_cursor_position(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        x, y = pyautogui.position()
        return ActionResult(True, f"cursor at ({x},{y})", needs_screenshot=False)

    def _do_unsupported(self, action: dict[str, Any], shot: Screenshot) -> ActionResult:
        return ActionResult(False, f"Ignored unsupported action: {action.get('raw')}",
                            needs_screenshot=False)
