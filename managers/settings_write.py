# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings writes that must reach the disk, and the startup instance
exclusion (SPEC-SET-003 §4.5b W6b), in every edition.

Moved out of ``managers/app_settings_requests`` (the AI apps' request
service, Pro only, SPEC-EDN-002) so the Lite build keeps them without the
service: ``write_or_restore`` serves the AI Settings page, ``startup_hook``
runs before the app reads its settings file. ``app_settings_requests``
re-exports both."""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Optional

from core.settings_registry import app_requests as ar

_log = logging.getLogger(__name__)
_MISSING = object()


def _get_path(tree: Dict[str, Any], parts) -> Any:
    node: Any = tree
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _set_path(tree: Dict[str, Any], parts, value: Any) -> None:
    node = tree
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def _del_path(tree: Dict[str, Any], parts) -> None:
    node: Any = tree
    for part in parts[:-1]:
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return
    if isinstance(node, dict):
        node.pop(parts[-1], None)


def write_or_restore(sm, key: str, value: Any):
    """Set ``key`` in memory and save at once, as ``SettingsManager.set``
    does, but with the change callbacks held back until the value is durable
    (the caller notifies). On a failed save, the in-memory value is restored
    and this write's pending entry removed, so no later save can flush it
    (an unrelated pending write stays). (True, None) or (False, reason).
    Shared by the request service and the toggle row (W6b fix F4).

    While an AI command runs (``ai_write_hook.ai_writer``) the one AI write
    policy decides first (fix round 3): a refused write raises
    ``AIWriteRefused`` before anything changes."""
    from managers import ai_write_hook
    ai_write_hook.check(sm, key, value)
    parts = tuple(key.split("."))
    with sm._save_lock:
        previous = _get_path(sm._settings, parts)
        previous = previous if previous is _MISSING else copy.deepcopy(previous)
        entry = (parts, copy.deepcopy(value))
        _set_path(sm._settings, parts, copy.deepcopy(value))
        sm._pending_writes.append(entry)
        try:
            ok = bool(sm._save())
        except Exception as exc:                       # _save never raises today
            ok = False
            sm.last_error = f"{type(exc).__name__}: {exc}"
        if ok:
            return True, None
        for i in range(len(sm._pending_writes) - 1, -1, -1):
            if sm._pending_writes[i] is entry:
                del sm._pending_writes[i]
                break
        if previous is _MISSING:
            _del_path(sm._settings, parts)
        else:
            _set_path(sm._settings, parts, previous)
        return False, sm.last_error or "save failed"


# ------------------------------------------------------------------ app startup (W6b fix F3-R1)

last_startup: Optional[ar.StartupResult] = None     # what the last startup established

STARTUP_SIGNAL_KEY = "startup.waiting_for_settings_lock"
STARTUP_SIGNAL_AFTER_S = 5.0          # the in-app signal appears after this long a wait


class StartupWaitSignal:
    """The in-app signal of a long startup wait for the settings-file lock
    (W6b fix round 2, leftover 2). The wait itself stays unlimited
    (orchestrator decision) and its log line is unchanged; after
    ``STARTUP_SIGNAL_AFTER_S`` seconds a small frameless splash window is
    shown, and it closes as soon as the lock is taken.

    Its structured state is ``state`` (``{"code": STARTUP_SIGNAL_KEY,
    "waited": s}`` while shown, None otherwise; ``shown`` stays true once it
    appeared). The words go through the pending-copy gate (``cli_text``):
    while the key is PENDING the window shows only a busy indicator, never
    a marker or a code. Needs a ``QApplication``: without one (a test, a
    tool) nothing is shown and the log line is the only signal."""

    def __init__(self, after_s: Optional[float] = None):
        self.after_s = STARTUP_SIGNAL_AFTER_S if after_s is None else float(after_s)
        self.state: Optional[Dict[str, Any]] = None
        self.shown = False
        self.widget = None
        self.label = None

    def __call__(self, waited: float) -> None:
        if waited < self.after_s:
            return
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None or not isinstance(app, QApplication):
            return
        if self.widget is None:
            self._build()
        self.state = {"code": STARTUP_SIGNAL_KEY, "waited": round(waited, 1)}
        self.shown = True
        app.processEvents()

    def _build(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget
        from core.settings_registry import cli_text
        widget = QWidget(None, Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        widget.setObjectName("startupWaitSignal")
        layout = QVBoxLayout(widget)
        label = QLabel("")
        label.setWordWrap(True)
        if cli_text.is_pending(STARTUP_SIGNAL_KEY):
            label.setVisible(False)
        else:
            label.setText(cli_text.message(STARTUP_SIGNAL_KEY))
        layout.addWidget(label)
        bar = QProgressBar()
        bar.setRange(0, 0)                    # busy: no value, no words
        bar.setTextVisible(False)
        layout.addWidget(bar)
        widget.resize(320, widget.sizeHint().height())
        screen = widget.screen()
        if screen is not None:
            widget.move(screen.availableGeometry().center() - widget.rect().center())
        widget.show()
        self.widget, self.label = widget, label

    def close(self) -> None:
        self.state = None
        widget, self.widget, self.label = self.widget, None, None
        if widget is not None:
            widget.close()
            widget.deleteLater()


def startup_hook(folder=None, signal: Optional[StartupWaitSignal] = None) -> "ar.StartupResult":
    """The app's startup hook (``apps/core_gui_qt.main``, one line, right
    after the ``QApplication``), before anything reads the settings file.
    ``app_requests.startup_wait`` makes the instance known to be alive
    (marker, fallback marker or sentinel) and waits for the settings-file
    lock, or keeps that lock when no marker of any kind could be published;
    this decides on its result: startup goes on ONLY when the read that
    follows is protected by an exclusion (a marker of any kind, the kept
    settings lock, or no user-data folder; an unopenable lock is none, W6b
    fix F3-R2). Anything else (only a bounded test wait produces it) waits
    again; it never goes on unprotected. A wait longer
    than ``STARTUP_SIGNAL_AFTER_S`` shows the ``StartupWaitSignal``."""
    global last_startup
    signal = StartupWaitSignal() if signal is None else signal
    try:
        while True:
            result = ar.startup_wait(folder, on_wait=signal)
            if result and result.exclusion is not None:
                break                         # protected, and by a real exclusion (F3-R2)
            _log.warning("startup: settings read not protected yet (%s); waiting again",
                         dict(result))
    finally:
        signal.close()
    if result.get("errors"):
        _log.warning("startup: instance exclusion %s after marker errors: %s",
                     result.get("exclusion"), "; ".join(result["errors"]))
    last_startup = result
    return result
