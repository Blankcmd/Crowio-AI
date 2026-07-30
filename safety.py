"""
safety.py  -  COMPONENT D: Safety Guardrails
============================================
Nothing in an autonomous mouse/keyboard agent matters more than the ability to
STOP it instantly and to keep it from doing something destructive. This module
provides three layers of protection:

  1. Emergency kill-switch  -> a global hotkey (default CTRL+ALT+K) that works
     even while the agent is dragging the mouse around.
  2. Bounding-box fencing   -> reject any click outside an allowed rectangle.
  3. Human confirmation     -> pause and ask before sensitive actions
     (submit, purchase, delete, typing passwords, leaving the box, etc.).

PyAutoGUI's corner failsafe is a fourth, independent layer configured in main.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

from pynput import keyboard

from config import CONFIG


def is_admin() -> bool:
    """
    Return True if the current process has Administrator/root privileges.

    On Windows this matters a lot: a NON-elevated process cannot send
    synthetic keyboard/mouse input to elevated windows (UAC prompts, Task
    Manager, elevated apps). Windows silently swallows the input, which is a
    common reason the agent "does nothing". Run as Administrator to fix it.

    We degrade gracefully on non-Windows and if the check itself fails.
    """
    if os.name == "nt":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    # POSIX: treat uid 0 as elevated.
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return True


class KillSwitch:
    """
    Listens globally for the kill-switch hotkey on a background thread.

    Once triggered, `is_triggered()` returns True forever (until reset). The
    main loop checks this flag before every action and aborts if set.
    """

    def __init__(self) -> None:
        self._triggered = threading.Event()
        self._combo = {k.lower() for k in CONFIG.kill_switch_hotkey}
        self._pressed: set[str] = set()
        self._listener: keyboard.Listener | None = None

    # -- normalization helpers -------------------------------------------
    @staticmethod
    def _key_name(key) -> str | None:
        """Turn a pynput key event into a lowercase name like 'ctrl' or 'k'."""
        if isinstance(key, keyboard.KeyCode) and key.char:
            return key.char.lower()
        if isinstance(key, keyboard.Key):
            # e.g. Key.ctrl_l -> "ctrl", Key.alt_r -> "alt"
            name = key.name.lower()
            for base in ("ctrl", "alt", "shift", "cmd"):
                if name.startswith(base):
                    return base
            return name
        return None

    def _on_press(self, key) -> None:
        name = self._key_name(key)
        if name:
            self._pressed.add(name)
            if self._combo.issubset(self._pressed):
                print("\n[SAFETY] Kill-switch activated! Aborting Crowio AI.")
                self._triggered.set()

    def _on_release(self, key) -> None:
        name = self._key_name(key)
        if name and name in self._pressed:
            self._pressed.discard(name)

    # -- public API -------------------------------------------------------
    def start(self) -> None:
        """Begin listening for the hotkey in the background."""
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()
        combo = "+".join(k.upper() for k in CONFIG.kill_switch_hotkey)
        print(f"[SAFETY] Kill-switch armed. Press {combo} at any time to abort.")

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()

    def is_triggered(self) -> bool:
        return self._triggered.is_set()


class Guardrails:
    """Stateless-ish policy checks for the executor."""

    def __init__(self, confirm_fn: Callable[[str], bool] | None = None) -> None:
        self.box = CONFIG.bounding_box  # (left, top, right, bottom) or None
        # How to ask the human for sign-off on a sensitive action. Defaults to
        # a blocking terminal y/N prompt, but a UI can inject its own dialog
        # callback (e.g. a Tkinter modal) so confirmations work without a
        # console.
        self._confirm_fn: Callable[[str], bool] = confirm_fn or self._terminal_confirm

    def point_allowed(self, x: int, y: int) -> bool:
        """True if a click at real pixel (x, y) is inside the bounding box."""
        if self.box is None:
            return True
        left, top, right, bottom = self.box
        return left <= x <= right and top <= y <= bottom

    def is_sensitive(self, action_type: str, text: str = "") -> bool:
        """
        Decide whether an action needs explicit human sign-off.

        We treat anything typing sensitive keywords, or key presses like
        'enter'/'return' on a form, as sensitive when configured to do so.
        """
        if not CONFIG.require_confirmation:
            return False

        haystack = f"{action_type} {text}".lower()
        return any(word in haystack for word in CONFIG.sensitive_keywords)

    def set_confirm_fn(self, confirm_fn: Callable[[str], bool]) -> None:
        """Swap in a different confirmation strategy (e.g. a UI dialog)."""
        self._confirm_fn = confirm_fn

    def confirm(self, prompt: str) -> bool:
        """
        Ask the human to sign off on a sensitive action.

        Delegates to whatever confirmation strategy was injected (terminal
        prompt by default, or a UI dialog when running under the GUI).
        Returns True only on an explicit approval.
        """
        return self._confirm_fn(prompt)

    @staticmethod
    def _terminal_confirm(prompt: str) -> bool:
        """
        Block for a y/N answer in the terminal.

        Returns True only on an explicit 'y'/'yes'. Anything else = skip.
        """
        try:
            answer = input(f"[CONFIRM] {prompt} [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return False
        return answer in ("y", "yes")
