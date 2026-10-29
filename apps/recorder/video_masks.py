# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Video-only privacy (SPEC-REC-001 INV-7, v0.4): chart names are blurred IN
THE RECORDING, never on the screen.

- Each hidden area is one ffmpeg box (``core.recorder.ffmpeg_command``
  MASK_SLOTS): the memory panel's chart buttons (``buttons_container``; Load
  Folder, the pager, Search, Sort, Clear and Select stay sharp), the chart
  title button, and the window's title bar (the WM draws the chart name
  there; no marker can be painted on it).
- The boxes follow the window and the panel: geometry events move them at
  once, a 100 ms timer is the backstop. Moves grow first (manager.set_mask)
  and reach ffmpeg's zmq filter within a frame. A hidden widget keeps its
  box where it was last seen.
- On screen, a dashed red frame marks each hidden area so the person
  recording sees what the video hides. It is mouse-transparent.
- Popup windows that list chart names (the memory panel's Search Charts
  window, Lorris 2026-10-24) open DURING a take: ``watch_popups`` sees their
  Show at application level and moves the box at once, before the window is
  mapped and painted, so no frame shows the names.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from core.recorder.ffmpeg_command import MASK_SLOTS
from core.recorder.region import Rect, intersect, native_union

PAD_PX = 6                    # logical pixels around each area
BACKSTOP_MS = 100
MARKER_RED = QColor(229, 57, 53)     # semantic "recording" red (Rule 20 exception)
_WATCHED = (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.Hide,
            QEvent.Type.WindowStateChange, QEvent.Type.LayoutRequest)


class MaskMarker(QWidget):
    """The on-screen sign of a hidden area: a dashed frame over its widget."""

    def __init__(self, target: QWidget):
        super().__init__(target)
        self.setObjectName("recorder_mask_marker")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(target.rect())
        self.show()
        self.raise_()

    def paintEvent(self, _event):                       # noqa: N802 (Qt API)
        p = QPainter(self)
        pen = QPen(MARKER_RED, 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(self.rect().adjusted(1, 1, -2, -2))


def _screens():
    out = []
    for s in QGuiApplication.screens():
        g = s.geometry()
        out.append((Rect(g.x(), g.y(), g.width(), g.height()), s.devicePixelRatio()))
    return out


class VideoMasks(QObject):
    """``start(manager, capture, areas)``: ``areas`` maps a MASK_SLOTS name to
    a callable giving the area's logical global QRect (None = not shown)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manager = None
        self._capture: Optional[Rect] = None
        self._areas: Dict[str, Callable[[], Optional[QRect]]] = {}
        self._watched: List[QObject] = []
        self._markers: List[MaskMarker] = []
        self._popup_types: tuple = ()
        self._popup_markers: List[MaskMarker] = []
        self._timer = QTimer(self)
        self._timer.setInterval(BACKSTOP_MS)
        self._timer.timeout.connect(self.update)
        self._queued = False

    @property
    def active(self) -> bool:
        return self._manager is not None

    # ---------------------------------------------------------- geometry

    def native_rect(self, logical: Optional[QRect]) -> Optional[Rect]:
        """Capture-relative X pixels of a logical global rectangle, padded and
        clipped to the capture; None when nothing of it is recorded."""
        if logical is None or logical.isEmpty() or self._capture is None:
            return None
        g = logical.adjusted(-PAD_PX, -PAD_PX, PAD_PX, PAD_PX)
        native = native_union(Rect(g.x(), g.y(), g.width(), g.height()), _screens())
        if native is None:
            return None
        c = self._capture
        rel = intersect(Rect(native.x - c.x, native.y - c.y, native.w, native.h),
                        Rect(0, 0, c.w, c.h))
        return rel

    def initial(self, capture: Rect, areas) -> Tuple[Optional[Rect], ...]:
        """The boxes for the ffmpeg command line (before the first frame)."""
        self._capture, self._areas = capture, dict(areas)
        return tuple(self.native_rect(self._areas[name]()) if name in self._areas else None
                     for name in MASK_SLOTS)

    # ---------------------------------------------------------- life

    def start(self, manager, watch: List[QWidget], markers: List[QWidget]) -> None:
        self._manager = manager
        for obj in watch:
            if obj is not None:
                obj.installEventFilter(self)
                self._watched.append(obj)
        for target in markers:
            if target is not None:
                self._markers.append(MaskMarker(target))
                target.installEventFilter(self)
                self._watched.append(target)
        self._timer.start()

    def watch_popups(self, types: tuple) -> None:
        """Top-level windows of these classes are watched from the moment they
        show (application filter, removed in ``stop``)."""
        self._popup_types = tuple(types)
        app = QGuiApplication.instance()
        if self._popup_types and app is not None:
            app.installEventFilter(self)

    def stop(self) -> None:
        self._timer.stop()
        self._manager = None
        app = QGuiApplication.instance()
        if self._popup_types and app is not None:
            app.removeEventFilter(self)
        self._popup_types = ()
        for m in self._popup_markers:
            try:
                m.hide()
                m.deleteLater()
            except RuntimeError:
                pass
        self._popup_markers.clear()
        for obj in self._watched:
            try:
                obj.removeEventFilter(self)
            except RuntimeError:
                pass
        self._watched.clear()
        for m in self._markers:
            try:
                m.hide()
                m.deleteLater()
            except RuntimeError:
                pass
        self._markers.clear()

    def update(self) -> None:
        self._queued = False
        if self._manager is None:
            return
        for slot, name in enumerate(MASK_SLOTS):
            getter = self._areas.get(name)
            if getter is None:
                continue
            try:
                rect = self.native_rect(getter())
            except RuntimeError:                 # widget deleted
                rect = None
            self._manager.set_mask(slot, rect)
        for m in self._markers:
            try:
                parent = m.parentWidget()
                if parent is not None and m.geometry() != parent.rect():
                    m.setGeometry(parent.rect())
                m.raise_()
            except RuntimeError:
                pass

    def eventFilter(self, obj, event):                   # noqa: N802 (Qt API)
        t = event.type()
        if self._popup_types and isinstance(obj, self._popup_types) and obj.isWindow():
            if t in _WATCHED:
                self.update()                    # before the window is mapped and painted
                if t == QEvent.Type.Show and not obj.findChildren(MaskMarker):
                    self._popup_markers.append(MaskMarker(obj))
            return False
        if t in _WATCHED:
            self.update()                        # at once: the box must not lag
        elif t == QEvent.Type.ChildAdded and not self._queued:
            self._queued = True                  # keep the marker above rebuilt buttons
            QTimer.singleShot(0, self.update)
        return False


# ---------------------------------------------------------------- areas


def widget_area(widget_getter: Callable[[], Optional[QWidget]]) -> Callable[[], Optional[QRect]]:
    """The widget's global rectangle. While it is hidden (tab switch,
    minimised window) the LAST place is kept, so the box is already there
    when it shows again (review v0.4 F2: 13 readable frames on show)."""
    last = [None]

    def area():
        w = widget_getter()
        if w is None:
            return last[0]
        if w.isVisible() and not w.window().isMinimized():
            last[0] = QRect(w.mapToGlobal(QPoint(0, 0)), w.size())
        return last[0]
    return area


POPUP_HOLD_S = 1.5            # after a popup closes, its pixels stay until the app repaints


def popup_area(types: tuple, hold_s: float = POPUP_HOLD_S) -> Callable[[], Optional[QRect]]:
    """The client area of the open window of one of ``types`` (the chart
    search window). After it closes the box stays ``hold_s``: without a
    compositor the screen keeps the closed window's image until the window
    under it repaints, which a busy app does late (seen 2026-10-24: a sharp
    frame of the closed search window). None once that time has passed."""
    import time as _time
    last = [None, 0.0]

    def area():
        from PySide6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if isinstance(w, types) and w.isVisible():
                last[0], last[1] = QRect(w.geometry()), _time.monotonic()
                return last[0]
        if last[0] is not None and _time.monotonic() - last[1] < hold_s:
            return last[0]
        last[0] = None
        return None
    return area


def title_bar_area(window_getter: Callable[[], Optional[QWidget]]) -> Callable[[], Optional[QRect]]:
    """The window manager's title bar: the band between the frame's top and
    the client area's top, across the whole frame."""
    last = [None]

    def area():
        win = window_getter()
        if win is None or not win.isVisible() or win.isMinimized():
            return last[0]
        frame, client = win.frameGeometry(), win.geometry()
        height = client.top() - frame.top()
        if height > 0:
            last[0] = QRect(frame.left(), frame.top(), frame.width(), height)
        return last[0]
    return area
