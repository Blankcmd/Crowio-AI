"""
planner.py  -  COMPONENT B: Vision / Planning LLM Connector
===========================================================
This is Crowio AI's "brain". It talks to Anthropic's Claude using the native
**Computer Use** tool. The flow is:

  1. We describe a virtual "computer" (screen size) to the model as a tool.
  2. We send the user's GOAL plus the latest SCREENSHOT.
  3. Claude replies with (a) its reasoning text and (b) one or more `tool_use`
     blocks requesting concrete actions -> click here, type this, scroll, etc.
  4. We normalize those into plain Python dicts for the executor.
  5. After executing, we send the *result* (usually a fresh screenshot) back so
     Claude can decide the next step. The conversation is stateful.

Why Computer Use instead of "return me some JSON"?  Because the model is
specifically post-trained to emit grounded GUI actions with pixel coordinates,
which is dramatically more reliable than free-form prompting.

The normalized action schema this module emits:
    {"type": "click",   "button": "left", "x": 100, "y": 200}
    {"type": "type",    "text": "hello world"}
    {"type": "key",     "keys": "ctrl+s"}
    {"type": "scroll",  "x": 100, "y": 200, "direction": "down", "amount": 3}
    {"type": "screenshot"}
    {"type": "wait",    "seconds": 1}
    {"type": "done",    "text": "why we're finished"}   # synthesized, see below
"""

from __future__ import annotations

from typing import Any

from anthropic import Anthropic

from config import CONFIG
from perception import Screenshot

# System prompt: sets the agent's identity and its operating rules.
SYSTEM_PROMPT = """You are Crowio AI, an autonomous desktop and browser assistant \
running on a WINDOWS computer (Windows 10/11). You control the mouse and keyboard \
to accomplish the user's goal.

CRITICAL - This is WINDOWS, not macOS:
- There is NO "cmd" or "command" key. NEVER emit cmd+anything.
- To open the Run dialog use the key action "super+r" (the Windows key + r).
- Common Windows shortcuts: "super" opens the Start menu; "super+r" = Run; \
"super+e" = File Explorer; "ctrl+c/ctrl+v" = copy/paste; "alt+tab" = switch \
windows; "alt+F4" = close window.
- To open an app, the most reliable path is: press "super", then TYPE the app \
name (e.g. "notepad"), then press "enter".

Rules:
- Work in small, verifiable steps. Take a screenshot when you are unsure of the \
current state.
- Prefer precise clicks and Windows-correct keyboard shortcuts over guessing.
- Never fabricate that a task is done. Only stop when the goal is genuinely \
complete or truly blocked.
- When the goal is complete, reply with a short plain-text summary and DO NOT \
request any further tool actions.
"""


class Planner:
    """Wraps the Anthropic client and maintains the running conversation."""

    def __init__(self) -> None:
        # Build client kwargs; only pass base_url if the user configured one
        # (e.g. an AgentRouter proxy). Empty string means "use Anthropic direct".
        client_kwargs: dict[str, Any] = {"api_key": CONFIG.api_key}
        if CONFIG.base_url:
            client_kwargs["base_url"] = CONFIG.base_url
        self.client = Anthropic(**client_kwargs)
        self.messages: list[dict[str, Any]] = []

    # -- tool definition --------------------------------------------------
    def _computer_tool(self) -> dict[str, Any]:
        """The Computer Use tool spec, sized to the image we send."""
        return {
            "type": "computer_20250124",
            "name": "computer",
            "display_width_px": CONFIG.target_width,
            "display_height_px": CONFIG.target_height,
            "display_number": 1,
        }

    # -- kicking off a task ----------------------------------------------
    def start_task(self, goal: str, screenshot: Screenshot) -> None:
        """Seed the conversation with the goal and the first screenshot."""
        self.messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Goal: {goal}"},
                    self._image_block(screenshot),
                ],
            }
        ]

    # -- one planning turn ------------------------------------------------
    def next_actions(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        """
        Ask Claude for the next step.

        Returns a tuple of:
          - actions:      normalized action dicts for the executor
          - tool_use_ids: the raw tool_use blocks (so we can reply with results)
          - assistant_text: any reasoning/summary text Claude produced
        """
        response = self.client.beta.messages.create(
            model=CONFIG.model,
            max_tokens=CONFIG.max_tokens,
            system=SYSTEM_PROMPT,
            tools=[self._computer_tool()],
            messages=self.messages,
            betas=[CONFIG.beta_flag],
        )

        # Persist the assistant turn verbatim so history stays valid.
        self.messages.append({"role": "assistant", "content": response.content})

        actions: list[dict[str, Any]] = []
        tool_uses: list[dict[str, Any]] = []
        assistant_text = ""

        for block in response.content:
            if block.type == "text":
                assistant_text += block.text
            elif block.type == "tool_use":
                tool_uses.append({"id": block.id, "input": block.input})
                normalized = self._normalize(block.input)
                if normalized:
                    actions.append(normalized)

        return actions, tool_uses, assistant_text

    # -- feed results back ------------------------------------------------
    def send_results(
        self, tool_results: list[dict[str, Any]]
    ) -> None:
        """
        Append a user turn containing tool_result blocks (screenshots or text)
        so Claude can plan the following step.

        Each item in tool_results is:
            {"tool_use_id": "...", "screenshot": Screenshot | None,
             "text": str | None, "is_error": bool}
        """
        content: list[dict[str, Any]] = []
        for r in tool_results:
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": r["tool_use_id"],
                "is_error": r.get("is_error", False),
                "content": [],
            }
            if r.get("text"):
                block["content"].append({"type": "text", "text": r["text"]})
            if r.get("screenshot") is not None:
                block["content"].append(self._image_block(r["screenshot"]))
            content.append(block)

        self.messages.append({"role": "user", "content": content})

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _image_block(screenshot: Screenshot) -> dict[str, Any]:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": screenshot.media_type,
                "data": screenshot.image_b64,
            },
        }

    @staticmethod
    def _normalize(tool_input: dict[str, Any]) -> dict[str, Any] | None:
        """
        Convert a Computer Use `action` into Crowio's flat action schema.

        The Computer Use tool packs everything under an "action" field, e.g.
        {"action": "left_click", "coordinate": [x, y]}.
        """
        action = tool_input.get("action")
        coord = tool_input.get("coordinate")

        # --- clicks -------------------------------------------------------
        click_map = {
            "left_click": "left",
            "right_click": "right",
            "middle_click": "middle",
        }
        if action in click_map and coord:
            return {"type": "click", "button": click_map[action],
                    "x": coord[0], "y": coord[1], "clicks": 1}

        if action == "double_click" and coord:
            return {"type": "click", "button": "left",
                    "x": coord[0], "y": coord[1], "clicks": 2}

        if action == "triple_click" and coord:
            return {"type": "click", "button": "left",
                    "x": coord[0], "y": coord[1], "clicks": 3}

        # --- movement / drag ---------------------------------------------
        if action == "mouse_move" and coord:
            return {"type": "move", "x": coord[0], "y": coord[1]}

        if action == "left_click_drag" and coord:
            start = tool_input.get("start_coordinate")
            return {"type": "drag", "start": start,
                    "x": coord[0], "y": coord[1]}

        # --- keyboard -----------------------------------------------------
        if action == "type":
            return {"type": "type", "text": tool_input.get("text", "")}

        if action == "key":
            # e.g. "ctrl+s", "Return", "cmd+space"
            return {"type": "key", "keys": tool_input.get("text", "")}

        # --- scroll -------------------------------------------------------
        if action == "scroll":
            return {
                "type": "scroll",
                "x": coord[0] if coord else None,
                "y": coord[1] if coord else None,
                "direction": tool_input.get("scroll_direction", "down"),
                "amount": int(tool_input.get("scroll_amount", 3)),
            }

        # --- passive actions ---------------------------------------------
        if action == "screenshot":
            return {"type": "screenshot"}

        if action == "wait":
            return {"type": "wait", "seconds": float(tool_input.get("duration", 1))}

        if action == "cursor_position":
            return {"type": "cursor_position"}

        # Unknown / unsupported action -> ignore but log upstream.
        return {"type": "unsupported", "raw": tool_input}
