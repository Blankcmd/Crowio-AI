"""
crowio_ui.py  -  Crowio AI control panel (crow-themed GUI)
==========================================================
A professional, dark, crow-themed desktop UI for driving the agent without
touching a terminal. Built on Tkinter (ships with Python -> zero new deps).

Layout
------
    +--------------------------------------------------------------+
    |  (crow logo)  CROWIO AI          [admin] [model] [killswitch]|
    +--------------------------------------------------------------+
    |  Goal: [__________________________________]  [ Start ][Stop]|
    +--------------------------------------------------------------+
    |  live, color-coded log console (thinks / acts / ok / fail)   |
    |                                                              |
    +--------------------------------------------------------------+
    |  status bar: kill-switch hint + current state                |
    +--------------------------------------------------------------+

Threading model
---------------
The agent's Perception-Plan-Act loop is blocking and must NOT run on Tkinter's
main thread or the window would freeze. So:

  * A worker thread runs `crowio_agent.run(...)`.
  * The agent's `emit(kind, message)` callback is thread-safe: it just drops an
    event onto a `queue.Queue`.
  * The main thread polls that queue ~20x/sec via `root.after()` and paints the
    log console. All Tk widget access stays on the main thread.
  * "Stop" sets a `threading.Event` the loop checks at each safe checkpoint.
  * Sensitive-action confirmations are marshalled back to the main thread: the
    worker blocks on an `Event` while the main thread shows a modal Yes/No.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox

import crowio_agent
from chat import ChatCompanion
from config import CONFIG
from safety import is_admin

# ---------------------------------------------------------------------------
# Crow theme palette
# ---------------------------------------------------------------------------
BG          = "#0e0f13"   # near-black feather
PANEL       = "#161821"   # raised panel
PANEL_EDGE  = "#242835"   # subtle border
INK         = "#e8eaf0"   # primary text (near-white)
MUTED       = "#8b909e"   # secondary text
ACCENT      = "#c8a24a"   # crow's-eye gold (primary accent)
ACCENT_DIM  = "#7d6a37"
DANGER      = "#e0533d"   # stop / fail
OK          = "#5bd08a"   # success green
THINK       = "#7aa2f7"   # reasoning blue
ACT         = "#c8a24a"   # action gold
WARN        = "#e6b450"   # warning amber
INFO        = "#8b909e"   # info grey


class CrowLogo(tk.Canvas):
    """A small, hand-drawn crow silhouette + gold eye, painted on a canvas."""

    def __init__(self, parent: tk.Widget, size: int = 46) -> None:
        super().__init__(parent, width=size, height=size,
                         bg=BG, highlightthickness=0, bd=0)
        s = size
        # Body: a rounded blob using overlapping ovals.
        self.create_oval(s*0.18, s*0.30, s*0.86, s*0.86,
                         fill="#05060a", outline="")
        # Head.
        self.create_oval(s*0.50, s*0.14, s*0.92, s*0.56,
                         fill="#05060a", outline="")
        # Beak: a gold wedge.
        self.create_polygon(
            s*0.90, s*0.30, s*1.02, s*0.36, s*0.90, s*0.42,
            fill=ACCENT, outline="",
        )
        # Wing accent: a swept feather line.
        self.create_arc(s*0.16, s*0.24, s*0.82, s*0.94,
                        start=200, extent=110, style="arc",
                        outline=PANEL_EDGE, width=2)
        # The eye: the crow's knowing gold dot.
        self.create_oval(s*0.70, s*0.28, s*0.78, s*0.36,
                         fill=ACCENT, outline="")


class StatusChip(tk.Frame):
    """A small pill showing a labeled status with a colored dot."""

    def __init__(self, parent: tk.Widget, label: str) -> None:
        super().__init__(parent, bg=PANEL, highlightbackground=PANEL_EDGE,
                         highlightthickness=1)
        self._dot = tk.Canvas(self, width=10, height=10, bg=PANEL,
                              highlightthickness=0)
        self._oval = self._dot.create_oval(2, 2, 9, 9, fill=MUTED, outline="")
        self._dot.pack(side="left", padx=(8, 4), pady=4)
        self._text = tk.Label(self, text=label, bg=PANEL, fg=INK,
                             font=("Segoe UI", 9))
        self._text.pack(side="left", padx=(0, 10), pady=4)

    def set(self, text: str, color: str) -> None:
        self._text.config(text=text)
        self._dot.itemconfig(self._oval, fill=color)


class CrowioUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.events: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None

        # Two brains: "agent" drives the computer, "chat" just banters.
        self.mode: str = "agent"
        self.companion: ChatCompanion | None = None  # lazy-built on first chat

        # Confirmation marshalling (worker <-> main thread).
        self._confirm_answer: bool = False
        self._confirm_done = threading.Event()

        self._build_window()
        self._build_header()
        self._build_controls()
        self._build_console()
        self._build_statusbar()
        self._refresh_chips()

        # Start the event-drain pump.
        self.root.after(50, self._drain_events)

    # -- window scaffolding ----------------------------------------------
    def _build_window(self) -> None:
        self.root.title("Crowio AI")
        self.root.configure(bg=BG)
        self.root.geometry("880x620")
        self.root.minsize(720, 520)
        # Fonts.
        self.mono = tkfont.Font(family="Consolas", size=10)
        self.h1 = tkfont.Font(family="Segoe UI Semibold", size=18)
        self.small = tkfont.Font(family="Segoe UI", size=9)

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=18, pady=(16, 8))

        CrowLogo(header, size=46).pack(side="left", padx=(0, 12))

        title_box = tk.Frame(header, bg=BG)
        title_box.pack(side="left", anchor="w")
        tk.Label(title_box, text="CROWIO AI", bg=BG, fg=INK,
                 font=self.h1).pack(anchor="w")
        tk.Label(title_box, text="autonomous desktop agent", bg=BG, fg=MUTED,
                 font=self.small).pack(anchor="w")

        chips = tk.Frame(header, bg=BG)
        chips.pack(side="right")
        self.chip_admin = StatusChip(chips, "admin")
        self.chip_model = StatusChip(chips, "model")
        self.chip_kill = StatusChip(chips, "kill-switch")
        for c in (self.chip_admin, self.chip_model, self.chip_kill):
            c.pack(side="left", padx=4)

    def _build_controls(self) -> None:
        bar = tk.Frame(self.root, bg=PANEL, highlightbackground=PANEL_EDGE,
                       highlightthickness=1)
        bar.pack(fill="x", padx=18, pady=8)

        # Mode toggle: flip between "Agent" (drive the PC) and "Chat" (banter).
        self.mode_btn = tk.Button(
            bar, text="Agent", command=self._toggle_mode,
            bg=BG, fg=ACCENT, activebackground=PANEL_EDGE,
            activeforeground=ACCENT, relief="flat", font=("Segoe UI Semibold", 10),
            padx=14, pady=6, cursor="hand2", width=6,
            highlightbackground=PANEL_EDGE, highlightthickness=1,
        )
        self.mode_btn.pack(side="left", padx=(12, 8), pady=10)

        self.input_label = tk.Label(bar, text="Goal", bg=PANEL, fg=MUTED,
                                    font=self.small)
        self.input_label.pack(side="left", padx=(0, 8), pady=12)

        self.goal_var = tk.StringVar()
        self.goal_entry = tk.Entry(
            bar, textvariable=self.goal_var, font=("Segoe UI", 11),
            bg=BG, fg=INK, insertbackground=ACCENT, relief="flat",
            highlightbackground=PANEL_EDGE, highlightcolor=ACCENT,
            highlightthickness=1,
        )
        self.goal_entry.pack(side="left", fill="x", expand=True, ipady=6,
                             padx=(0, 10), pady=10)
        self.goal_entry.bind("<Return>", lambda _e: self._on_start())
        self.goal_entry.focus_set()

        self.start_btn = tk.Button(
            bar, text="Start", command=self._on_start,
            bg=ACCENT, fg="#1a1400", activebackground=ACCENT_DIM,
            activeforeground="#1a1400", relief="flat", font=("Segoe UI Semibold", 10),
            padx=18, pady=6, cursor="hand2",
        )
        self.start_btn.pack(side="left", padx=(0, 6), pady=10)

        self.stop_btn = tk.Button(
            bar, text="Stop", command=self._on_stop,
            bg=PANEL, fg=DANGER, activebackground="#2a1512",
            activeforeground=DANGER, relief="flat", font=("Segoe UI Semibold", 10),
            padx=18, pady=6, cursor="hand2", state="disabled",
            highlightbackground=PANEL_EDGE, highlightthickness=1,
        )
        self.stop_btn.pack(side="left", padx=(0, 12), pady=10)

    def _build_console(self) -> None:
        wrap = tk.Frame(self.root, bg=PANEL, highlightbackground=PANEL_EDGE,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True, padx=18, pady=8)

        self.console = tk.Text(
            wrap, bg="#0b0c10", fg=INK, font=self.mono, relief="flat",
            wrap="word", padx=14, pady=12, state="disabled",
            insertbackground=ACCENT, spacing1=1, spacing3=2,
        )
        scroll = tk.Scrollbar(wrap, command=self.console.yview)
        self.console.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.console.pack(side="left", fill="both", expand=True)

        # Color tags per event kind.
        self.console.tag_config("info", foreground=INFO)
        self.console.tag_config("warn", foreground=WARN)
        self.console.tag_config("think", foreground=THINK)
        self.console.tag_config("act", foreground=ACT)
        self.console.tag_config("ok", foreground=OK)
        self.console.tag_config("fail", foreground=DANGER)
        self.console.tag_config("done", foreground=OK,
                                font=("Consolas", 10, "bold"))
        self.console.tag_config("error", foreground=DANGER,
                                font=("Consolas", 10, "bold"))
        self.console.tag_config("step", foreground=ACCENT,
                                font=("Consolas", 10, "bold"))
        self.console.tag_config("meta", foreground=MUTED)
        self.console.tag_config("you", foreground=INK,
                                font=("Consolas", 10, "bold"))
        self.console.tag_config("crow", foreground=ACCENT)

        self._log("meta", "Crowio AI ready. Enter a goal and press Start.")
        self._log("meta", "Tip: click the mode button to flip between Agent "
                          "(drive your PC) and Chat (just banter).")
        self._log("meta", f"Emergency stop: press "
                          f"{'+'.join(k.upper() for k in CONFIG.kill_switch_hotkey)} "
                          f"anytime, or slam the mouse into a screen corner.")

    def _build_statusbar(self) -> None:
        self.status = tk.Label(
            self.root, text="Idle.", bg=BG, fg=MUTED, font=self.small,
            anchor="w",
        )
        self.status.pack(fill="x", padx=20, pady=(0, 10))

    # -- status chips -----------------------------------------------------
    def _refresh_chips(self) -> None:
        if is_admin():
            self.chip_admin.set("Administrator", OK)
        else:
            self.chip_admin.set("Not elevated", WARN)
        self.chip_model.set(CONFIG.model, ACCENT)
        self.chip_kill.set("armed on run", MUTED)

    # -- console helpers --------------------------------------------------
    def _log(self, kind: str, message: str) -> None:
        label = {
            "think": "think  ", "act": "act    ", "ok": "ok     ",
            "fail": "fail   ", "info": "info   ", "warn": "warn   ",
            "done": "done   ", "error": "error  ", "step": "",
            "meta": "       ", "you": "you    ", "crow": "crowio ",
        }.get(kind, "       ")
        self.console.config(state="normal")
        if kind == "step":
            self.console.insert("end", f"\n{message}\n", kind)
        else:
            self.console.insert("end", f"{label}  {message}\n", kind)
        self.console.see("end")
        self.console.config(state="disabled")

    # -- event pump (main thread) ----------------------------------------
    def _drain_events(self) -> None:
        try:
            while True:
                kind, message = self.events.get_nowait()
                if kind == "__finished__":
                    self._on_finished()
                    continue
                self._log(kind, message)
                if kind == "step":
                    self.status.config(text=message)
                elif kind in ("done", "error"):
                    self.status.config(text=message)
        except queue.Empty:
            pass
        self.root.after(50, self._drain_events)

    # -- confirmation dialog (marshalled to main thread) -----------------
    def _confirm_from_worker(self, prompt: str) -> bool:
        """Called ON THE WORKER THREAD. Blocks until the user answers."""
        self._confirm_done.clear()
        self.root.after(0, lambda: self._show_confirm(prompt))
        self._confirm_done.wait()
        return self._confirm_answer

    def _show_confirm(self, prompt: str) -> None:
        answer = messagebox.askyesno("Crowio AI — confirm sensitive action",
                                     prompt, icon="warning")
        self._confirm_answer = bool(answer)
        self._confirm_done.set()

    # -- mode toggle ------------------------------------------------------
    def _toggle_mode(self) -> None:
        """Flip between Agent (drive the PC) and Chat (just banter)."""
        # Don't switch modes mid-run; it would orphan the worker.
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(
                "Crowio AI",
                "Finish or stop the current run before switching modes.",
            )
            return

        if self.mode == "agent":
            self.mode = "chat"
            self.mode_btn.config(text="Chat")
            self.input_label.config(text="Chat")
            self.start_btn.config(text="Send")
            self.goal_entry.delete(0, "end")
            self._log("meta", "Switched to Chat mode. I'm off duty - just here "
                              "to talk. (Won't touch your PC in this mode.)")
            self._log("crow", "Hey. Rough day, good day, or just here to "
                             "procrastinate? Either way, I'm listening. (caw)")
        else:
            self.mode = "agent"
            self.mode_btn.config(text="Agent")
            self.input_label.config(text="Goal")
            self.start_btn.config(text="Start")
            self.goal_entry.delete(0, "end")
            self._log("meta", "Switched to Agent mode. Give me a goal and I'll "
                              "drive your PC to get it done.")
        self.goal_entry.focus_set()

    # -- start / stop -----------------------------------------------------
    def _on_start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        text = self.goal_var.get().strip()
        if not text:
            hint = ("Say something first." if self.mode == "chat"
                    else "Please enter a goal first.")
            messagebox.showinfo("Crowio AI", hint)
            return

        if self.mode == "chat":
            self._start_chat(text)
        else:
            self._start_agent(text)

    def _start_agent(self, goal: str) -> None:
        self.stop_event.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.chip_kill.set("ARMED", OK)
        self.console.config(state="normal")
        self.console.insert("end", "\n")
        self.console.config(state="disabled")
        self.status.config(text="Running...")

        self.worker = threading.Thread(
            target=self._run_agent, args=(goal,), daemon=True,
        )
        self.worker.start()

    def _start_chat(self, message: str) -> None:
        # Echo the user's line, clear the box, then let the companion reply
        # off the main thread so the window never freezes.
        self._log("you", message)
        self.goal_entry.delete(0, "end")
        self.start_btn.config(state="disabled")
        self.status.config(text="Crowio is thinking...")

        self.worker = threading.Thread(
            target=self._run_chat, args=(message,), daemon=True,
        )
        self.worker.start()

    def _run_chat(self, message: str) -> None:
        """Worker thread: get one witty reply from the companion."""
        try:
            if self.companion is None:
                self.companion = ChatCompanion()
            reply = self.companion.reply(message)
            self.events.put(("crow", reply))
        except Exception as exc:  # noqa: BLE001 - surface any crash in the UI
            self.events.put(("error", f"Chat hiccup: {exc}"))
        finally:
            self.events.put(("__finished__", ""))

    def _on_stop(self) -> None:
        self.stop_event.set()
        self.status.config(text="Stopping...")
        self.stop_btn.config(state="disabled")

    def _run_agent(self, goal: str) -> None:
        """Worker thread entry point."""
        def emit(kind: str, message: str) -> None:
            self.events.put((kind, message))

        try:
            crowio_agent.run(
                goal,
                emit=emit,
                stop_event=self.stop_event,
                confirm_fn=self._confirm_from_worker,
                startup_delay=3.0,
            )
        except Exception as exc:  # noqa: BLE001 - surface any crash in the UI
            self.events.put(("error", f"Agent crashed: {exc}"))
        finally:
            self.events.put(("__finished__", ""))

    def _on_finished(self) -> None:
        self.start_btn.config(state="normal")
        if self.mode == "chat":
            # Chat has no stop/kill-switch semantics; just re-arm the box.
            self.start_btn.config(text="Send")
            self.status.config(text="Idle.")
            self.goal_entry.focus_set()
            return
        self.stop_btn.config(state="disabled")
        self.chip_kill.set("armed on run", MUTED)
        if not self.status.cget("text").startswith(("DONE", "ERROR", "Reached")):
            self.status.config(text="Idle.")


def main() -> None:
    root = tk.Tk()
    CrowioUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
