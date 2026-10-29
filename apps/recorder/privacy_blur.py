# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Pop-up privacy during a take (SPEC-REC-001 INV-7, §4.7).

Since v0.4 the chart names are blurred IN THE VIDEO only
(``apps/recorder/video_masks.py``); the screen stays sharp. What a video box
cannot cover is a separate window: the tooltip, the right-click menu and the
drag pixmap of a chart button can pop up anywhere and carry a name. This
guard eats those events on each protected widget and every descendant, also
widgets attached later (review R2 F3). Plain clicks still work.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

_BLOCKED = (QEvent.Type.ToolTip, QEvent.Type.ContextMenu, QEvent.Type.WhatsThis)


class _Guard(QObject):
    def eventFilter(self, obj, event):                       # noqa: N802 (Qt API)
        t = event.type()
        if t in _BLOCKED:
            return True
        if t == QEvent.Type.MouseMove and event.buttons() != Qt.MouseButton.NoButton:
            return True                                      # no drag pixmap
        if t == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget):                   # buttons rebuilt on refresh:
                for w in [child, *child.findChildren(QWidget)]:   # the whole subtree (R2 F3)
                    w.installEventFilter(self)
        return False


class PrivacyGuard:
    """``apply(widgets)`` installs the guard; ``remove()`` is idempotent and
    safe after the widgets were deleted."""

    def __init__(self):
        self._widgets: List[QWidget] = []
        self._guard: Optional[_Guard] = None

    @property
    def active(self) -> bool:
        return bool(self._widgets)

    def apply(self, widgets) -> bool:
        widgets = [w for w in widgets if w is not None]
        if not widgets:
            return False
        if self._guard is None:
            self._guard = _Guard()
        for root in widgets:
            for w in [root, *root.findChildren(QWidget)]:
                w.installEventFilter(self._guard)
            self._widgets.append(root)
        return True

    def installed(self) -> bool:
        return self._guard is not None and bool(self._widgets)

    def remove(self) -> None:
        widgets, guard = self._widgets, self._guard
        self._widgets, self._guard = [], None
        for root in widgets:
            try:
                for w in [root, *root.findChildren(QWidget)]:
                    w.removeEventFilter(guard)
            except RuntimeError:
                pass
        if guard is not None:
            guard.deleteLater()
