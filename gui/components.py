"""Reusable GUI widgets – Hyperliquid-style dark trading terminal."""
from __future__ import annotations
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from gui.theme import *


# ── Helper: draw a rounded rectangle on a Canvas ────────────────
def _round_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Draw a rounded rectangle using smooth polygon."""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(pts, smooth=True, **kw)


# ── Card (subtle dark panel – no hard border) ───────────────────
class Card(tk.Frame):
    """Dark card container with optional title. Relies on bg contrast
    between BG_CARD and BG_DARK instead of a hard border."""

    def __init__(self, parent, title: str = "", **kw):
        super().__init__(parent, bg=BG_CARD, bd=0,
                         highlightthickness=0, **kw)
        if title:
            lbl = tk.Label(self, text=title, font=FONT_HEADING,
                           bg=BG_CARD, fg=TEXT, anchor="w")
            lbl.pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 4))
            tk.Frame(self, bg=BORDER, height=1).pack(
                fill="x", padx=CARD_PAD)


# ── Stat box (label + large value) ──────────────────────────────
class StatBox(tk.Frame):
    """Single KPI stat: small label on top, large value below."""

    def __init__(self, parent, label: str, initial: str = "--",
                 value_color: str = TEXT, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        self._lbl = tk.Label(self, text=label.upper(), font=FONT_TINY,
                             bg=BG_CARD, fg=TEXT_DIM)
        self._lbl.pack(anchor="w")
        self._val = tk.Label(self, text=initial, font=FONT_MONO_MD,
                             bg=BG_CARD, fg=value_color)
        self._val.pack(anchor="w")

    def set(self, text: str, color: str | None = None):
        self._val.config(text=text)
        if color:
            self._val.config(fg=color)


# ── StatusDot (green / red circle next to text) ─────────────────
class StatusDot(tk.Frame):
    """Coloured dot + label for connection / bot status."""

    def __init__(self, parent, text: str = "Disconnected",
                 color: str = RED, **kw):
        super().__init__(parent, bg=BG_DARK, **kw)
        self._canvas = tk.Canvas(self, width=12, height=12,
                                 bg=BG_DARK, highlightthickness=0)
        self._dot = self._canvas.create_oval(2, 2, 10, 10, fill=color,
                                             outline=color)
        self._canvas.pack(side="left", padx=(0, 6))
        self._label = tk.Label(self, text=text, font=FONT_SMALL,
                               bg=BG_DARK, fg=TEXT_DIM)
        self._label.pack(side="left")

    def set(self, text: str, color: str):
        self._canvas.itemconfig(self._dot, fill=color, outline=color)
        self._label.config(text=text)


# ── LabelledEntry (label above a rounded text entry) ────────────
class LabelledEntry(tk.Frame):
    """Label + Entry with rounded border, returns a StringVar."""

    def __init__(self, parent, label: str, default: str = "",
                 width: int = 18, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        tk.Label(self, text=label, font=FONT_SMALL, bg=BG_CARD,
                 fg=TEXT_DIM).pack(anchor="w")

        # Fixed pixel width derived from character width (~8px per char + padding)
        px_width = width * 8 + 16

        # Rounded border wrapper
        self._border = tk.Canvas(self, bg=BG_CARD, highlightthickness=0,
                                 height=28, width=px_width)
        self._border.pack(pady=(2, 0))
        self._border.pack_propagate(False)

        self.var = tk.StringVar(value=default)
        self._entry = tk.Entry(self._border, textvariable=self.var,
                               width=width, font=FONT_MONO_SM,
                               bg=BG_INPUT, fg=TEXT,
                               insertbackground=TEXT, relief="flat",
                               bd=0, highlightthickness=0)
        self._entry.place(x=6, y=4, relwidth=1.0, width=-12, height=20)
        self._border.bind("<Configure>", self._draw_border)

    def _draw_border(self, _e=None):
        self._border.delete("border")
        w = self._border.winfo_width()
        h = self._border.winfo_height()
        if w > 1:
            _round_rect(self._border, 1, 1, w - 1, h - 1, 5,
                        fill=BG_INPUT, outline=BORDER, width=1, tags="border")
            self._border.tag_lower("border")

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str):
        self.var.set(value)

    def disable(self):
        self._entry.config(state="disabled")

    def enable(self):
        self._entry.config(state="normal")


# ── LabelledCombo (label above a combobox) ───────────────────────
class LabelledCombo(tk.Frame):
    """Label + Combobox dropdown."""

    def __init__(self, parent, label: str, values: list[str],
                 default: str = "", width: int = 16, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        tk.Label(self, text=label, font=FONT_SMALL, bg=BG_CARD,
                 fg=TEXT_DIM).pack(anchor="w")
        self.var = tk.StringVar(value=default or (values[0] if values else ""))
        self._combo = ttk.Combobox(self, textvariable=self.var,
                                   values=values, width=width,
                                   state="readonly", font=FONT_MONO_SM)
        self._combo.pack(fill="x", pady=(2, 0))

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str):
        self.var.set(value)

    def set_values(self, values: list[str]):
        self._combo["values"] = values


# ── ActionButton (rounded Canvas button) ─────────────────────────
class ActionButton(tk.Canvas):
    """Rounded button with hover effect – Hyperliquid palette."""

    def __init__(self, parent, text: str, color: str = ACCENT,
                 command=None, **kw):
        self._color = color
        self._fg = "#0b0e11" if color in (GREEN, ACCENT, YELLOW) else WHITE
        self._command = command
        self._text_str = text
        self._disabled = False

        # Measure text to size the canvas
        font_obj = tkfont.Font(font=FONT_BODY)
        tw = int(font_obj.measure(text))
        th = int(font_obj.metrics("linespace"))
        px, py = 20, 8
        self._btn_w = tw + px * 2
        self._btn_h = th + py * 2

        try:
            parent_bg = parent.cget("bg")
        except Exception:
            parent_bg = BG_DARK

        super().__init__(parent, width=self._btn_w, height=self._btn_h,
                         bg=parent_bg, highlightthickness=0, **kw)

        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _draw(self):
        self.delete("all")
        fill = BG_INPUT if self._disabled else self._color
        fg = TEXT_DIM if self._disabled else self._fg
        _round_rect(self, 1, 1, self._btn_w - 1, self._btn_h - 1, CORNER,
                    fill=fill, outline="")
        self.create_text(self._btn_w // 2, self._btn_h // 2,
                         text=self._text_str, fill=fg, font=FONT_BODY)

    def _on_enter(self, _e):
        if not self._disabled:
            self.configure(cursor="hand2")

    def _on_leave(self, _e):
        self.configure(cursor="")

    def _on_click(self, _e):
        if not self._disabled and self._command:
            self._command()

    def config(self, **kw):
        if "state" in kw:
            state = kw.pop("state")
            self._disabled = (state == "disabled")
            self._draw()
        if "command" in kw:
            self._command = kw.pop("command")
        if kw:
            super().config(**kw)

    configure = config


# ── ScrollableLog (text area for trade log) ──────────────────────
class ScrollableLog(tk.Frame):
    """Scrollable text log with timestamp colouring."""

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG_CARD, **kw)
        self._text = tk.Text(self, bg=BG_CARD, fg=TEXT, font=FONT_MONO_SM,
                             relief="flat", wrap="word", state="disabled",
                             insertbackground=TEXT, selectbackground=ACCENT,
                             highlightthickness=0, padx=8, pady=8)
        sb = tk.Scrollbar(self, command=self._text.yview,
                          bg=BG_CARD, troughcolor=BG_DARK)
        self._text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._text.pack(side="left", fill="both", expand=True)

        # Tag colours
        self._text.tag_config("time", foreground=TEXT_DIM)
        self._text.tag_config("info", foreground=ACCENT)
        self._text.tag_config("long", foreground=GREEN)
        self._text.tag_config("short", foreground=RED)
        self._text.tag_config("warn", foreground=YELLOW)
        self._text.tag_config("error", foreground=RED)
        self._text.tag_config("profit", foreground=GREEN)
        self._text.tag_config("loss", foreground=RED)

    def append(self, timestamp: str, message: str, tag: str = "info"):
        self._text.config(state="normal")
        self._text.insert("end", f"[{timestamp}] ", "time")
        self._text.insert("end", f"{message}\n", tag)
        self._text.see("end")
        self._text.config(state="disabled")

    def clear(self):
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.config(state="disabled")
