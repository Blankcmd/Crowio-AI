"""
crowio_agent.py  -  Crowio AI main runner
==========================================
Wires together the four components into a Perception -> Plan -> Act loop:

    +-----------+     screenshot      +---------+     actions      +----------+
    | PERCEIVE  | ------------------> |  PLAN   | ---------------> |   ACT    |
    | (capture) |                     | (Claude)|                  |(PyAutoGUI)|
    +-----------+ <------ results --- +---------+ <-- results ---- +----------+
          ^                                                             |
          |                        loop until done / max steps / abort  |
          +-------------------------------------------------------------+

Usage:
    python crowio_agent.py "Open Notepad and type 'Hello from Crowio AI'"
    python crowio_agent.py            # then type the goal at the prompt

Press CTRL+ALT+K at ANY time to abort. Slamming the mouse into a screen corner
also triggers PyAutoGUI's failsafe.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable

from config import CONFIG
from executor import Executor
from perception import ScreenCapture
from planner import Planner
from safety import Guardrails, KillSwitch, is_admin

# Type of the structured-event sink. The UI passes a callback that pushes
# events onto a thread-safe queue; the CLI uses a printer that writes to stdout.
#   emit(kind, message)  ->  kind is one of: "info", "think", "act", "ok",
#   "fail", "step", "done", "error", "warn"
EmitFn = Callable[[str, str], None]


def _cli_emit(kind: str, message: str) -> None:
    """Default event sink: pretty-print structured events to the console."""
    prefix = {
        "info": "[CROWIO]",
        "warn": "[CROWIO] !",
        "think": "[CROWIO thinks]",
        "act": "[CROWIO acts]",
        "ok": "        ->",
        "fail": "        ->",
        "step": "-----",
        "done": "[CROWIO] DONE",
        "error": "[CROWIO] ERROR",
    }.get(kind, "[CROWIO]")
    if kind == "step":
        print(f"\n----- {message} -----")
    else:
        print(f"{prefix} {message}")


def get_goal() -> str:
    """Read the task goal from argv or interactively."""
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:])
    return input("What should Crowio AI do?\n> ").strip()


def run(
    goal: str,
    *,
    emit: EmitFn | None = None,
    stop_event: threading.Event | None = None,
    confirm_fn: Callable[[str], bool] | None = None,
    startup_delay: float = 3.0,
) -> None:
    """
    Run one Perception-Plan-Act session.

    Parameters
    ----------
    goal : str
        The natural-language task for the agent.
    emit : callable(kind, message), optional
        Structured-event sink. Defaults to console printing. A UI can pass a
        callback that forwards events to its log console.
    stop_event : threading.Event, optional
        When set from another thread (e.g. a UI "Stop" button), the loop aborts
        at the next safe checkpoint. Works alongside the global kill-switch.
    confirm_fn : callable(prompt) -> bool, optional
        How to ask the human to approve a sensitive action. Defaults to the
        terminal y/N prompt; a UI injects a modal dialog instead.
    startup_delay : float
        Seconds to wait before the first screenshot so the user can switch to
        their target window.
    """
    emit = emit or _cli_emit

    def stopped() -> bool:
        return kill.is_triggered() or (stop_event is not None and stop_event.is_set())

    # --- wiring ----------------------------------------------------------
    CONFIG.validate()

    # Elevation self-check: on Windows a non-elevated process cannot send input
    # to elevated windows, which silently breaks control. Warn loudly.
    if not is_admin():
        emit(
            "warn",
            "Not running as Administrator. Windows will BLOCK input to elevated "
            "windows (UAC, Task Manager, admin apps), so the agent may appear to "
            "do nothing. For full control, relaunch as Administrator.",
        )

    camera = ScreenCapture()
    planner = Planner()
    guardrails = Guardrails(confirm_fn=confirm_fn)
    executor = Executor(guardrails)
    kill = KillSwitch()

    kill.start()  # arm the emergency hotkey before doing anything

    try:
        emit("info", f"Goal: {goal}")
        emit("info", f"Starting in {startup_delay:.0f}s. Switch to your target window...")

        # Interruptible countdown so Stop works even during the delay.
        waited = 0.0
        while waited < startup_delay:
            if stopped():
                emit("info", "Aborted before start.")
                return
            time.sleep(0.1)
            waited += 0.1

        # --- seed the conversation with the first screenshot -------------
        shot = camera.capture()
        planner.start_task(goal, shot)

        # --- the Perception-Plan-Act loop --------------------------------
        for step in range(1, CONFIG.max_steps + 1):
            if stopped():
                emit("info", "Aborted by kill-switch/Stop.")
                break

            emit("step", f"Step {step}/{CONFIG.max_steps}")

            # PLAN: ask Claude what to do next.
            try:
                actions, tool_uses, text = planner.next_actions()
            except Exception as exc:  # network/API/quota errors, etc.
                emit("error", f"Planning failed: {exc}")
                break

            if text.strip():
                emit("think", text.strip())

            # No tool actions requested => Claude considers the task finished.
            if not tool_uses:
                emit("done", text.strip() or "(done)")
                break

            # ACT: execute each requested action.
            tool_results = []
            aborted = False
            for tool_use, action in zip(tool_uses, actions):
                if stopped():
                    aborted = True
                    break

                emit("act", str(action))
                try:
                    result = executor.execute(action, shot)
                except Exception as exc:  # includes PyAutoGUI failsafe
                    emit("fail", f"Failsafe/abort triggered: {exc}")
                    aborted = True
                    break

                emit("ok" if result.ok else "fail",
                     f"{'OK' if result.ok else 'FAIL'}: {result.message}")

                # PERCEIVE (again): capture fresh state for the model.
                time.sleep(CONFIG.action_delay)
                new_shot = camera.capture() if result.needs_screenshot else shot
                shot = new_shot

                tool_results.append({
                    "tool_use_id": tool_use["id"],
                    "screenshot": new_shot if result.needs_screenshot else None,
                    "text": result.message if not result.ok else None,
                    "is_error": not result.ok,
                })

            if aborted:
                emit("info", "Stopping loop.")
                break

            # Hand the results back so Claude can plan the next step.
            planner.send_results(tool_results)
        else:
            emit("info", f"Reached max_steps ({CONFIG.max_steps}). Stopping.")
    finally:
        kill.stop()
        emit("info", "Session ended.")


def main() -> None:
    goal = get_goal()
    if not goal:
        print("No goal provided. Exiting.")
        return
    try:
        run(goal)
    except KeyboardInterrupt:
        print("\n[CROWIO] Interrupted by user (Ctrl+C).")


if __name__ == "__main__":
    main()
