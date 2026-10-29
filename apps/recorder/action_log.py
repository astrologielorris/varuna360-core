# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The AI action log of a take (SPEC-REC-001 D-23, Lorris 2026-10-24): what
was clicked, pointed at and shown in the app, second by second, so an AI
watching the video later knows what each moment was about.

One JSON object per line, ``<video stem>.actions.jsonl`` beside the video.
``t`` is the position in the FINISHED video in seconds (pauses removed:
``ScreenRecorderManager.video_time``). Mouse positions are given in screen
pixels (``x``, ``y``) and as fractions of the recorded area (``fx``, ``fy``,
0..1, null outside it), so they map onto the video at any output size.

What is logged (the first line of every file describes it for the AI):
``click`` / ``double_click`` / ``wheel`` (with the target under the
pointer), ``hover`` (the pointer rested on a new target), ``tooltip`` (text
that appeared), ``menu`` (a menu item chosen), ``key`` (shortcuts and
navigation keys; typed TEXT is never logged, only ``typing`` in a field),
``window`` (a dialog opened or closed), ``view`` (the open tabs and the
chart title changed), ``mouse`` (pointer position, at most twice a second
while it moves), ``pause`` / ``resume`` / ``end``.

The filter only reads events; it never consumes or changes one. Nothing is
written while the take is paused.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QAbstractSpinBox,
                               QApplication, QComboBox, QDialog, QDockWidget, QGraphicsView,
                               QGroupBox, QLabel, QLineEdit, QMenu, QPlainTextEdit, QTabBar,
                               QTabWidget, QTextEdit, QToolTip, QWidget)

FORMAT = "varuna360-recording-actions/1"
POLL_MS = 250                # pointer, hover, tooltip
HOVER_REST_S = 0.4           # a target counts as hovered after this rest
MOUSE_EVERY_S = 0.5
VIEW_EVERY_S = 1.0
FLUSH_EVERY_MS = 1000
TEXT_MAX = 160
_TAGS = re.compile(r"<[^>]+>")
_NAV_KEYS = {
    Qt.Key.Key_Left: "Left", Qt.Key.Key_Right: "Right", Qt.Key.Key_Up: "Up",
    Qt.Key.Key_Down: "Down", Qt.Key.Key_PageUp: "PageUp", Qt.Key.Key_PageDown: "PageDown",
    Qt.Key.Key_Home: "Home", Qt.Key.Key_End: "End", Qt.Key.Key_Escape: "Escape",
    Qt.Key.Key_Return: "Enter", Qt.Key.Key_Enter: "Enter", Qt.Key.Key_Tab: "Tab",
    Qt.Key.Key_Space: "Space", Qt.Key.Key_Delete: "Delete",
}
_NAV = {k.value: n for k, n in _NAV_KEYS.items()}
_TEXT_INPUTS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)
_EVENTS = {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.Wheel,
           QEvent.Type.KeyPress, QEvent.Type.Show, QEvent.Type.Hide}

HEADER_FIELDS = {
    "t": "seconds into the video (pauses removed)",
    "type": "click, double_click, wheel, hover, tooltip, menu, key, typing, window, view, "
            "mouse, pause, resume, end",
    "x,y": "pointer in screen pixels",
    "fx,fy": "pointer as a fraction of the recorded area (0..1), null outside it",
    "target": "what is under the pointer: widget kind, its text, tooltip, the "
              "chart item (planet_Sun, sector_3...), the table cell with its headers",
    "where": "the tabs and group boxes around the target, outermost first",
    "view": "the open tab of every visible tab bar, outermost first, and the chart title",
}


def _clean(text, limit: int = TEXT_MAX) -> str:
    text = _TAGS.sub(" ", str(text or "")).replace("&nbsp;", " ")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tab_label(tabs: QTabWidget, widget: QWidget) -> Optional[str]:
    i = tabs.indexOf(widget)
    if i < 0:
        return None
    return _clean(tabs.tabText(i).replace("&", "")) or _clean(tabs.tabToolTip(i)) or None


def where(widget: Optional[QWidget]) -> List[str]:
    """The tabs, group boxes, docks and dialog around ``widget``, outermost first."""
    chain: List[QWidget] = []
    w = widget
    while w is not None:
        chain.append(w)
        w = w.parentWidget()
    out: List[str] = []
    for i, w in enumerate(chain):
        if isinstance(w, QTabWidget) and i >= 2:      # chain[i-1] is its page stack
            label = _tab_label(w, chain[i - 2])
            if label:
                out.append("tab: " + label)
        elif isinstance(w, QGroupBox) and w.title():
            out.append("group: " + _clean(w.title()))
        elif isinstance(w, QDockWidget) and w.windowTitle():
            out.append("dock: " + _clean(w.windowTitle()))
        elif w.isWindow() and isinstance(w, QDialog) and w.windowTitle():
            out.append("dialog: " + _clean(w.windowTitle()))
    return list(reversed(out))


def describe(widget: Optional[QWidget], global_pos: QPoint) -> dict:
    """What the pointer is on: a short, AI-readable description."""
    if widget is None:
        return {"kind": "outside the app"}
    d: dict = {"kind": type(widget).__name__}
    if widget.objectName() and not widget.objectName().startswith("qt_"):
        d["name"] = widget.objectName()
    local = widget.mapFromGlobal(global_pos)
    text = ""
    if isinstance(widget, QAbstractButton):
        text = widget.text().replace("&", "")
        if widget.isCheckable():
            d["checked"] = widget.isChecked()
    elif isinstance(widget, QLabel):
        text = widget.text()
    elif isinstance(widget, QComboBox) and not widget.isEditable():
        text = widget.currentText()             # an editable one holds typed text
    elif isinstance(widget, QTabBar):
        i = widget.tabAt(local)
        if i >= 0:
            d["tab"] = _clean(widget.tabText(i).replace("&", "")) or _clean(widget.tabToolTip(i))
    elif isinstance(widget, QMenu):
        act = widget.actionAt(local)
        if act is not None:
            d["item"] = _clean(act.text().replace("&", ""))
        if widget.title():
            d["menu"] = _clean(widget.title().replace("&", ""))
    if text:
        d["text"] = _clean(text)
    view = _owning(widget, QAbstractItemView)
    if view is not None:
        d.update(_cell(view, global_pos))
    gview = _owning(widget, QGraphicsView)
    if gview is not None:
        items = _graphics_items(gview, global_pos)
        if items:
            d["items"] = items
    tip = widget.toolTip()
    if tip:
        d["tooltip"] = _clean(tip)
    if widget.accessibleName():
        d["label"] = _clean(widget.accessibleName())
    return d


def _owning(widget, cls):
    """``widget`` itself or the view whose viewport it is."""
    if isinstance(widget, cls):
        return widget
    parent = widget.parentWidget()
    return parent if isinstance(parent, cls) and getattr(parent, "viewport", lambda: None)() is widget else None


def _cell(view: QAbstractItemView, global_pos: QPoint) -> dict:
    idx = view.indexAt(view.viewport().mapFromGlobal(global_pos))
    if not idx.isValid():
        return {}
    model = idx.model()
    out = {"cell": _clean(idx.data(Qt.ItemDataRole.DisplayRole)),
           "row": idx.row(), "column": idx.column()}
    col = model.headerData(idx.column(), Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
    row = model.headerData(idx.row(), Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole)
    if col not in (None, "") and str(col) != str(idx.column() + 1):
        out["column_header"] = _clean(col)
    if row not in (None, "") and str(row) != str(idx.row() + 1):
        out["row_header"] = _clean(row)
    if idx.column() > 0:
        first = model.index(idx.row(), 0, idx.parent()).data(Qt.ItemDataRole.DisplayRole)
        if first not in (None, ""):
            out["row_first_cell"] = _clean(first)
    tip = idx.data(Qt.ItemDataRole.ToolTipRole)
    if tip:
        out["cell_tooltip"] = _clean(tip)
    return out


def _graphics_items(view: QGraphicsView, global_pos: QPoint, limit: int = 4) -> List[str]:
    """The chart items under the pointer, topmost first (their UserRole id,
    e.g. ``planet_Sun``, ``sector_3``; else their tooltip or text)."""
    out: List[str] = []
    try:
        found = view.items(view.viewport().mapFromGlobal(global_pos))
    except RuntimeError:
        return out
    for item in found:
        label = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(label, str) or label in ("background", "ruler_tick", "sector_line"):
            label = None
        label = label or _clean(item.toolTip()) or (
            _clean(item.toPlainText()) if hasattr(item, "toPlainText") else "")
        if label and label not in out:
            out.append(label)
        if len(out) >= limit:
            break
    return out


class ActionLog(QObject):
    """Installed on the application for the length of a take."""

    def __init__(self, clock: Callable[[], float], paused: Callable[[], bool],
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._clock = clock
        self._paused = paused
        self.path: Optional[str] = None
        self._file = None
        self._buf: List[str] = []
        self._area = QRect()
        self._root: Optional[QWidget] = None
        self._title: Callable[[], Optional[QWidget]] = lambda: None
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self._sample)
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(FLUSH_EVERY_MS)
        self._flush_timer.timeout.connect(self.flush)
        self._reset_state()

    def _reset_state(self) -> None:
        self._last_pos = None
        self._last_mouse_t = -1e9
        self._hover_key = None
        self._hover_since = 0.0
        self._hover_logged = None
        self._tip = ""
        self._view = None
        self._last_view_t = -1e9
        self._typing_in = None
        self._last_key = None
        self._last_press = None
        self._wheel = None

    @property
    def active(self) -> bool:
        return self._file is not None

    # ------------------------------------------------------------ life

    def start(self, path: str, area: QRect, root: QWidget, title=None, meta=None) -> bool:
        """Chart names are logged even when the video blurs them: the log is
        for the AI, which needs to know the chart (Lorris 2026-10-24)."""
        self.stop()
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._file = open(path, "w", encoding="utf-8")
        except OSError:
            self._file = None
            return False
        self.path, self._area, self._root = path, QRect(area), root
        self._title = title or (lambda: None)
        self._reset_state()
        head = {"t": 0.0, "type": "session", "format": FORMAT,
                "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "recorded_area": [area.x(), area.y(), area.width(), area.height()],
                "fields": HEADER_FIELDS}
        head.update(meta or {})
        self._write(head, force=True)
        QApplication.instance().installEventFilter(self)
        self._poll.start()
        self._flush_timer.start()
        return True

    def set_area(self, area: QRect) -> None:
        self._area = QRect(area)

    def mark(self, kind: str, **extra) -> None:
        if self.active:
            self._write({"t": self._t(), "type": kind, **extra}, force=True)

    def stop(self) -> Optional[str]:
        """Remove the filter, write the end line, close; the file path."""
        if self._file is None:
            return None
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._poll.stop()
        self._flush_timer.stop()
        self._flush_wheel()
        self._write({"t": self._t(), "type": "end"}, force=True)
        self.flush()
        try:
            self._file.close()
        except OSError:
            pass
        self._file = None
        return self.path

    def flush(self) -> None:
        if self._file is None or not self._buf:
            return
        try:
            self._file.write("".join(self._buf))
            self._file.flush()
        except OSError:
            pass
        self._buf = []

    # ------------------------------------------------------------ writing

    def _t(self) -> float:
        try:
            return round(float(self._clock()), 2)
        except Exception:
            return 0.0

    def _write(self, entry: dict, force: bool = False) -> None:
        if self._file is None or (not force and self._paused()):
            return
        self._buf.append(json.dumps(entry, ensure_ascii=False) + "\n")

    def _pos(self, gp: QPoint) -> dict:
        a = self._area
        inside = a.width() > 0 and a.contains(gp)
        return {"x": gp.x(), "y": gp.y(),
                "fx": round((gp.x() - a.x()) / a.width(), 4) if inside else None,
                "fy": round((gp.y() - a.y()) / a.height(), 4) if inside else None}

    def _entry(self, kind: str, widget, gp: QPoint, **extra) -> dict:
        e = {"t": self._t(), "type": kind, **self._pos(gp)}
        e.update(extra)
        e["target"] = describe(widget, gp)
        place = where(widget)
        if place:
            e["where"] = place
        return e

    # ------------------------------------------------------------ events

    def eventFilter(self, obj, event):                       # noqa: N802 (Qt API)
        try:
            et = event.type()
            if et in _EVENTS and isinstance(obj, QWidget):
                self._on_event(obj, event, et)
        except Exception:                                    # a log never breaks the app
            pass
        return False

    def _on_event(self, obj: QWidget, event, et) -> None:
        if self._paused():
            return
        if et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            gp = event.globalPosition().toPoint()
            stamp = (et, event.timestamp(), int(event.button().value), gp.x(), gp.y())
            if stamp == self._last_press:
                return                                       # the same click seen by a parent
            self._last_press = stamp
            self._flush_wheel()
            button = {Qt.MouseButton.LeftButton: "left", Qt.MouseButton.RightButton: "right",
                      Qt.MouseButton.MiddleButton: "middle"}.get(event.button(), "other")
            if isinstance(obj, QMenu):
                act = obj.actionAt(event.position().toPoint())
                if act is not None and not act.menu():
                    self._write({"t": self._t(), "type": "menu", **self._pos(gp),
                                 "item": _clean(act.text().replace("&", "")),
                                 "menu": _clean(obj.title().replace("&", "")) or None})
                    return
            kind = "double_click" if et == QEvent.Type.MouseButtonDblClick else "click"
            self._write(self._entry(kind, obj, gp, button=button))
        elif et == QEvent.Type.Wheel:
            gp = event.globalPosition().toPoint()
            stamp = (et, event.timestamp(), gp.x(), gp.y())
            if stamp == self._last_press:
                return
            self._last_press = stamp
            dy = event.angleDelta().y() // 120 or (1 if event.angleDelta().y() > 0 else -1)
            now = time.monotonic()
            if self._wheel and self._wheel["widget"] is obj and now - self._wheel["last"] < 0.6:
                self._wheel["steps"] += dy
                self._wheel["last"] = now
            else:
                self._flush_wheel()
                self._wheel = {"widget": obj, "entry": self._entry("wheel", obj, gp),
                               "steps": dy, "last": now}
        elif et == QEvent.Type.KeyPress:
            stamp = (event.timestamp(), event.key(), int(event.modifiers().value))
            if stamp == self._last_key:
                return                                       # the same key seen by a parent
            self._last_key = stamp
            self._on_key(obj, event)
        elif et in (QEvent.Type.Show, QEvent.Type.Hide):
            if obj.isWindow() and isinstance(obj, QDialog) and obj.windowTitle():
                self._write({"t": self._t(), "type": "window",
                             "state": "opened" if et == QEvent.Type.Show else "closed",
                             "title": _clean(obj.windowTitle()), "kind": type(obj).__name__})

    def _on_key(self, obj: QWidget, event) -> None:
        mods = event.modifiers()
        names = [n for flag, n in ((Qt.KeyboardModifier.ControlModifier, "Ctrl"),
                                   (Qt.KeyboardModifier.AltModifier, "Alt"),
                                   (Qt.KeyboardModifier.MetaModifier, "Meta"),
                                   (Qt.KeyboardModifier.ShiftModifier, "Shift")) if mods & flag]
        key = event.key()
        nav = _NAV.get(key)
        if nav is None and Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F35.value:
            nav = f"F{key - Qt.Key.Key_F1.value + 1}"
        typing = isinstance(obj, _TEXT_INPUTS) or (isinstance(obj, QComboBox) and obj.isEditable())
        # AltGr arrives as Ctrl+Alt with a character: that is typing, never a chord
        chord = any(n in ("Ctrl", "Alt", "Meta") for n in names) and not (
            typing and event.text() and event.text().isprintable())
        if chord:
            from PySide6.QtGui import QKeySequence
            text = QKeySequence(key).toString() or nav or ""
            self._write({"t": self._t(), "type": "key",
                         "keys": "+".join(names + ([text] if text else [])),
                         "focus": describe(obj, QCursor.pos()).get("name") or type(obj).__name__})
        elif nav is not None and not (typing and nav in ("Left", "Right", "Home", "End",
                                                          "Space", "Delete")):
            self._write({"t": self._t(), "type": "key", "keys": "+".join(names + [nav]),
                         "focus": describe(obj, QCursor.pos()).get("name") or type(obj).__name__})
        elif typing and event.text():
            if self._typing_in is not obj:                   # once per field, never the text
                self._typing_in = obj
                gp = obj.mapToGlobal(obj.rect().center())
                e = self._entry("typing", obj, gp)
                for k in ("text", "label"):
                    e["target"].pop(k, None)
                self._write(e)

    def _flush_wheel(self) -> None:
        w, self._wheel = self._wheel, None
        if w is not None:
            w["entry"]["steps"] = w["steps"]
            self._write(w["entry"])

    # ------------------------------------------------------------ polling

    def _sample(self) -> None:
        try:
            self._sample_inner()
        except Exception:
            pass

    def _sample_inner(self) -> None:
        if self._paused():
            return
        now = time.monotonic()
        if self._wheel and now - self._wheel["last"] >= 0.6:
            self._flush_wheel()
        gp = QCursor.pos()
        if gp != self._last_pos and now - self._last_mouse_t >= MOUSE_EVERY_S:
            self._write({"t": self._t(), "type": "mouse", **self._pos(gp)})
            self._last_pos, self._last_mouse_t = QPoint(gp), now
        widget = QApplication.widgetAt(gp)
        target = describe(widget, gp)
        key = json.dumps(target, sort_keys=True)
        if key != self._hover_key:
            self._hover_key, self._hover_since = key, now
        elif key != self._hover_logged and now - self._hover_since >= HOVER_REST_S:
            self._hover_logged = key
            if widget is not None:
                self._write(self._entry("hover", widget, gp))
        tip = _clean(QToolTip.text()) if QToolTip.isVisible() else ""
        if tip != self._tip:
            self._tip = tip
            if tip:
                self._write({"t": self._t(), "type": "tooltip", **self._pos(gp), "text": tip})
        if now - self._last_view_t >= VIEW_EVERY_S:
            self._last_view_t = now
            view = self._view_state()
            if view != self._view:
                self._view = view
                self._write({"t": self._t(), "type": "view", **view})

    def _view_state(self) -> dict:
        tabs: List[str] = []
        root = self._root
        if root is not None:
            for tw in root.findChildren(QTabWidget):
                if tw.isVisible() and tw.currentIndex() >= 0:
                    label = _clean(tw.tabText(tw.currentIndex()).replace("&", "")) \
                        or _clean(tw.tabToolTip(tw.currentIndex()))
                    if label:
                        tabs.append(label)
        out = {"tabs": tabs}
        title = self._title()
        if title is not None and hasattr(title, "text"):
            text = _clean(title.text())
            if text:
                out["chart"] = text
        active = QApplication.activeWindow()
        if active is not None and active is not root and active.windowTitle():
            out["window"] = _clean(active.windowTitle())
        return out


def finish(path: Optional[str], video_path: Optional[str]) -> Optional[str]:
    """Rename the log to the stem of the published video (the MP4 may have
    taken ``_2``, or stayed MKV); the final log path."""
    from core.recorder import output
    if not path or not os.path.exists(path):
        return None
    if not video_path:
        return path
    target = output.action_log_path(video_path)
    if target == path:
        return path
    try:
        if os.path.exists(target):
            return path
        os.replace(path, target)
        return target
    except OSError:
        return path
