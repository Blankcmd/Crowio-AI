"""
chat.py  -  Crowio's casual, humorous chat companion
====================================================
This is Crowio's "off-duty" mode. Instead of driving the mouse and keyboard,
Crowio just... talks. It's a witty, warm crow you can banter with to blow off
steam. No Computer Use tool, no screenshots, no actions - just conversation.

Why a separate module from planner.py?
  * planner.py sends the Computer Use beta tool on every turn. Some proxies
    (e.g. AgentRouter) run a content filter that can reject those requests
    ("content-blocked"). A plain chat call carries no tool and no beta flag, so
    it slips right past that and is also cheaper + faster.
  * Keeping the two brains apart means the automation agent and the companion
    can each have their own personality and history without stepping on each
    other.

Public surface:
    companion = ChatCompanion()
    reply = companion.reply("ugh, today was rough")   # -> str
    companion.reset()                                  # forget the conversation
"""

from __future__ import annotations

from typing import Any

from anthropic import Anthropic

from config import CONFIG

# The companion's personality. Keep it genuinely funny but kind - a stress-relief
# buddy, not a comedian doing a bit at the user's expense.
PERSONA_PROMPT = """You are Crowio, a clever, warm, slightly mischievous crow who \
hangs out with the user as a casual chat companion. Right now you are OFF duty - \
you are NOT controlling their computer, you are just here to talk, listen, and \
lighten the mood.

Your vibe:
- Witty and playful. Land a good joke, a dry aside, or a bit of crow-themed humor \
(you're a crow, lean into it occasionally - shiny things, cawing, bird puns) - but \
never force it and never let a joke get in the way of actually being helpful.
- Warm and genuinely supportive. If the user is stressed or venting, meet them \
where they are first, THEN lighten things up. Read the room. Some moments call for \
a laugh; some call for "yeah, that sounds hard."
- Conversational and concise. Talk like a smart friend texting, not an essay. A \
sentence or three is usually plenty. No bullet-point lectures.
- Curious. Ask the occasional follow-up question so it feels like a real back-and-forth.

Hard rules:
- Never claim you're doing something on their computer in this mode - you can't, \
you're just chatting. If they clearly want a real task done (open an app, click \
something, automate something), tell them to flip you back to Agent mode.
- Keep it clean-ish and kind. Roast gently and only if they're clearly up for it.
- If someone sounds like they're truly struggling (not just a bad day), drop the \
jokes, be real, and gently point them toward talking to someone they trust or a \
professional. Their wellbeing beats the bit, every time.
"""


class ChatCompanion:
    """A lightweight, stateful chat brain - no tools, just banter."""

    def __init__(self) -> None:
        # Same client-construction logic as the planner: only pass base_url when
        # the user configured a proxy (AgentRouter), otherwise hit Anthropic direct.
        client_kwargs: dict[str, Any] = {"api_key": CONFIG.api_key}
        if CONFIG.base_url:
            client_kwargs["base_url"] = CONFIG.base_url
        self.client = Anthropic(**client_kwargs)
        self.messages: list[dict[str, Any]] = []

    def reset(self) -> None:
        """Forget the conversation so far and start fresh."""
        self.messages = []

    def reply(self, user_message: str) -> str:
        """
        Send one user message, get Crowio's witty reply back as plain text.

        The conversation is stateful: prior turns are kept so the banter has
        continuity. Uses a plain (non-beta, tool-less) Messages call, which
        avoids the Computer Use content filter entirely.
        """
        text = (user_message or "").strip()
        if not text:
            return "You went quiet on me. Everything alright? (caw?)"

        self.messages.append({"role": "user", "content": text})

        response = self.client.messages.create(
            model=CONFIG.model,
            max_tokens=CONFIG.max_tokens,
            system=PERSONA_PROMPT,
            messages=self.messages,
        )

        # Flatten the assistant reply to plain text.
        reply_text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                reply_text += block.text
        reply_text = reply_text.strip() or "...I've got nothing. Even crows get \
speechless sometimes."

        # Persist the assistant turn so the next message has context.
        self.messages.append({"role": "assistant", "content": reply_text})
        return reply_text
