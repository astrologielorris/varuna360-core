# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""A status-bar message that cannot be talked over (SPEC-PERSIST-001 INV-6).

Lorris's ruling on a failed chart write: red, bottom left, held at least
thirty seconds. Neither half of that is what a status bar does by default.

WHY `showMessage(text, 30000)` IS NOT THE ANSWER
------------------------------------------------
`showMessage` is a single slot. There are 78 `showMessage` calls in
core_gui_qt.py alone, and creating a chart fires several of them right after
the write — so the failure notice would be replaced within milliseconds by
"Chart loaded". The timeout controls how long the message survives SILENCE,
not how long it survives the next message.

WHY A PLAIN `addWidget` LABEL IS NOT THE ANSWER EITHER
-------------------------------------------------------
Qt hides every normal (left-side) status-bar widget for the duration of any
temporary message. `addPermanentWidget` is immune, but permanent widgets sit
on the RIGHT, and the ruling says bottom left.

WHAT THIS DOES
--------------
A left-side label plus a priority window: while the sticky is up, temporary
messages are dropped as they arrive (`messageChanged` -> `clearMessage`).
After the hold expires the status bar goes back to behaving exactly as
before, with nothing left behind.

Suppressing other messages for thirty seconds is the deliberate cost. It
only happens when a chart could not be saved, which outranks "Chart loaded".
The standing condition is reported separately and permanently in Settings
(`managers.persist_health`) — this channel is only about the chart in front
of the user right now.
"""

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QLabel

# Semantic red. Rule 20 requires theme colours from get_theme_colors() and
# exempts semantic red/green; this is that exemption, and it matches
# ui/session_health_banner.py rather than inventing a second red.
ERROR_RED = "#D9534F"

DEFAULT_HOLD_MS = 30_000


class StickyStatus(QObject):
    """One per main window. Use `sticky_status_for(window)`, not this."""

    def __init__(self, status_bar, hold_ms: int = DEFAULT_HOLD_MS, parent=None):
        super().__init__(parent)
        self._bar = status_bar
        self._hold_ms = int(hold_ms)
        self._active = False
        self._label = QLabel("")
        self._label.setStyleSheet(
            f"QLabel {{ color: {ERROR_RED}; font-weight: bold; "
            f"padding-left: 4px; }}")
        self._label.setVisible(False)
        # stretch=1 so a long message gets the width instead of eliding.
        self._bar.addWidget(self._label, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear)
        self._bar.messageChanged.connect(self._on_message)

    # -- the one thing this class is for ---------------------------------

    def show_error(self, text: str, hold_ms: int = None) -> None:
        """Show `text` in red, bottom left, and hold the floor."""
        self._label.setText(text)
        self._label.setVisible(True)
        self._active = True
        # Clear whatever is showing now, or the label stays hidden behind it
        # until that message times out on its own.
        self._bar.clearMessage()
        self._timer.start(int(hold_ms) if hold_ms else self._hold_ms)

    def clear(self) -> None:
        self._timer.stop()
        self._active = False
        self._label.setVisible(False)
        self._label.setText("")

    @property
    def active(self) -> bool:
        return self._active

    # -- the priority window ---------------------------------------------

    def _on_message(self, text: str) -> None:
        """Drop temporary messages while the sticky holds the floor.

        Re-entrancy is bounded: clearMessage() emits messageChanged("") once,
        and the empty string fails the `if text` guard, so this returns
        immediately on the second pass.
        """
        if self._active and text:
            self._bar.clearMessage()


def sticky_status_for(widget):
    """The main window's StickyStatus, created on first use, or None.

    Walks up from any widget, so a dialog or a sub-tab can report without
    knowing how it is parented. Returns None headless (no window, no status
    bar) — callers must treat this channel as best-effort and keep the
    persisted record (managers.persist_health) as the one that must not fail.
    """
    try:
        window = widget.window() if hasattr(widget, "window") else None
        if window is None or not hasattr(window, "statusBar"):
            return None
        existing = getattr(window, "_sticky_status", None)
        if existing is not None:
            return existing
        sticky = StickyStatus(window.statusBar(), parent=window)
        window._sticky_status = sticky
        return sticky
    except Exception:
        return None


def report_write_failure(widget, message: str, chart_name: str = "") -> bool:
    """Say, in the status bar, that a chart was created but not saved.

    Returns True when it reached a status bar. The persisted half is written
    by the pipeline itself, so a headless or detached caller still leaves a
    trace the user finds in Settings.
    """
    sticky = sticky_status_for(widget)
    if sticky is None:
        return False
    who = f"{chart_name} was created" if chart_name else "The chart was created"
    sticky.show_error(f"{who} but NOT saved to a file — {message}")
    return True
