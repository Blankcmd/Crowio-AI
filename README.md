<div align="center">

# 🐦‍⬛ Crowio AI

**An autonomous Windows desktop assistant with a crow-themed control panel.**

Crowio watches your screen, plans steps with a vision-capable Claude model, and
drives your real mouse and keyboard to finish tasks — behind a hard emergency
kill-switch and layered safety guardrails. When you'd rather just talk, flip it
to **Chat mode** for a witty off-duty companion.

</div>

---

## ✨ Features

- **Agent mode** — give Crowio a goal ("open Notepad and write my grocery list")
  and it runs a Perception → Plan → Act loop until the task is done.
- **Chat mode** — a warm, mischievous crow you can banter with for a quick
  breather. No screen access, just conversation.
- **Crow-themed control panel** — a dark, hand-drawn Tkinter UI (zero extra
  dependencies) with live status chips, a color-coded console, and a
  one-click mode toggle.
- **One-click launcher** — `Run Crowio.bat` self-elevates to Administrator,
  sets up the virtual environment on first run, and starts the UI.
- **Safety first** — global `CTRL + ALT + K` kill-switch, corner failsafe,
  optional bounding box, and human confirmation on sensitive actions.
- **Bring-your-own endpoint** — talk to Anthropic directly, or route through any
  Anthropic-compatible proxy via a single `ANTHROPIC_BASE_URL` setting.

---

## 🚀 Quick start (Windows)

```text
1. Download or clone this repo.
2. Copy .env.example to .env and paste your API key.
3. Double-click "Run Crowio.bat".
```

That's it. On first launch the batch file requests Administrator rights, creates
a `.venv`, installs dependencies, and opens the Crowio control panel. Every run
after that just opens the panel.

> **Prefer the terminal?** See [Manual setup](#-manual-setup) below.

---

## 🖥️ Using the control panel

The window opens in **Agent** mode. Use the toggle in the top controls to switch
between the two brains:

| Mode | What it does | Screen access |
|------|--------------|:-------------:|
| **Agent** | Type a goal, hit Start, and Crowio executes it step by step. Watch progress in the console; abort any time with Stop or the kill-switch. | ✅ Yes |
| **Chat**  | Type a message and chat with Crowio the crow — casual, humorous, good for a quick mental breather. | ❌ No |

Status chips show the current mode, whether the agent is running, and admin
state. The console is color-coded: thinking, actions, warnings, and errors each
get their own tone.

---

## 🧠 How Agent mode works

Crowio runs a closed feedback loop. Each cycle it looks at the screen, decides
one small step, does it, then looks again to see what changed — repeating until
the goal is met, it gets stuck, it hits the step cap, or you abort it.

```
   +--------------+     screenshot      +-------------+     actions      +--------------+
   |   PERCEIVE   | ------------------> |    PLAN     | ---------------> |     ACT      |
   | ScreenCapture|                     |   Planner   |                  |   Executor   |
   |  (mss + PIL) |                     | (Claude API)|                  | (PyAutoGUI)  |
   +--------------+ <---- results ----- +-------------+ <--- results --- +--------------+
         ^                                                                      |
         |                   loop until: done / max_steps / kill-switch / error |
         +----------------------------------------------------------------------+
                                    ^
                                    |  every action first passes through
                              +-----+------+
                              | GUARDRAILS |  kill-switch • bounding box • confirm
                              +------------+
```

Observing after every action lets the model self-correct when reality diverges
from the plan — a dialog pops up, a page loads slowly, a click misses — which is
exactly what Computer Use models are trained for.

### Component map

| Component | File | Responsibility |
|-----------|------|----------------|
| **Perception** | `perception.py` | Capture the screen, downscale to the model's resolution, and record scale factors so click coordinates map back to real pixels. |
| **Planning** | `planner.py` | Send the goal + screenshot to Claude's Computer Use tool; parse `tool_use` blocks into a flat action schema; feed results back to stay stateful. |
| **Execution** | `executor.py` | Translate model-space coordinates to screen pixels and drive mouse/keyboard via PyAutoGUI. |
| **Safety** | `safety.py` | Global kill-switch, admin detection, bounding-box fencing, and confirmation for sensitive actions. |
| **Chat brain** | `chat.py` | The off-duty conversational companion (plain, tool-less Claude call). |
| **Control panel** | `crowio_ui.py` | Crow-themed Tkinter UI wiring both modes together. |
| **Runner** | `crowio_agent.py` | Wires perception/plan/act into the loop above. |
| **Config** | `config.py` | Every tunable knob in one place. |

---

## 🛡️ Safety — read before running

Agent mode moves your real mouse and types on your real keyboard. Four
independent layers protect you:

1. **Emergency kill-switch** — press **`CTRL + ALT + K`** any time to abort
   immediately. A background listener catches it even while the agent is busy.
2. **Corner failsafe** — slam the mouse into any screen corner to raise an abort.
3. **Bounding box** — set `CONFIG.bounding_box = (left, top, right, bottom)` in
   `config.py` to fence all mouse activity into one region. Clicks outside are
   rejected.
4. **Human confirmation** — with `require_confirmation = True`, Crowio pauses for
   your approval before actions matching sensitive keywords (`password`, `buy`,
   `delete`, `submit`, …).

**First run:** test on a throwaway app (Notepad, a scratch browser tab), keep the
kill-switch hand ready, and don't point it at banking or anything irreversible
until you trust its behavior.

---

## ⚙️ Manual setup

**Prerequisites:** Python 3.10–3.12 and an API key.

```bash
# 1. create a virtual environment
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate         # macOS / Linux

# 2. install dependencies
pip install -r requirements.txt

# 3. add your key
copy .env.example .env             # Windows  (cp on macOS/Linux)
#    then edit .env

# 4. launch the UI
python crowio_ui.py

# ...or run headless with a goal
python crowio_agent.py "Open Notepad and type 'Hello from Crowio AI'"
```

### Configuration (`.env`)

| Variable | Required | Notes |
|----------|:--------:|-------|
| `ANTHROPIC_API_KEY` | ✅ | Direct Anthropic keys start with `sk-ant-`. Using a proxy? Paste that provider's key. |
| `ANTHROPIC_BASE_URL` | ❌ | Leave blank for Anthropic direct. For an Anthropic-compatible proxy, use the **bare domain** — the SDK appends `/v1/messages` itself, so no `/v1` suffix. |

Everything else (model, resolution, step cap, sensitive keywords, kill-switch
hotkey) lives in `config.py`.

---

## 🔐 Security

Never commit your `.env` — it holds a live key. This repo's `.gitignore` already
excludes it. If a key is ever exposed, **rotate it immediately** in your provider
dashboard and drop the new one into `.env`.

---

## 📄 License

Released under the [MIT License](LICENSE).
