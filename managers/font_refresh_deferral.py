# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""A font refresh reaches the surfaces on screen at once and the hidden ones
when they are next shown (td-8m3kd).

The window's font refresh (``ChartGUI._refresh_scaled_surfaces``, shared by a
per-area font change and the Display Scale) restyles every persistent
surface: the chart views, every side panel and the Settings tab. Most of them
sit on a page that is not on screen (Predictive Tools, Settings, the other
chart views), and restyling them all made a font change take seconds before
it showed. A surface on screen is refreshed now, exactly as before; a hidden
one is refreshed by the same call just before it is next shown (its Show
event, before its first paint), so it never shows the old size.

When the window itself is not on screen (startup, a test building the GUI
off screen) nothing is deferred: everything is refreshed at once, as before.

No ChartGUI attribute (Rule 4b): the pending refresh lives on a small child
object of the surface, which dies with it.
"""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt

_log = logging.getLogger(__name__)
_MARK = "_v360_font_refresh_on_show"


class _OnShow(QObject):
    """Runs the surface's pending refresh at its next Show, then goes."""

    def __init__(self, widget, fn: Callable[[], None]):
        super().__init__(widget)
        self.setObjectName(_MARK)
        self.fn = fn
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show:
            fn, self.fn = self.fn, None
            obj.removeEventFilter(self)
            self.deleteLater()
            if fn is not None:
                from ui.stylesheet_dedupe import unchanged_sheets_skipped
                try:
                    with unchanged_sheets_skipped():    # review H6: no identical re-polish
                        fn()
                except Exception:               # never into Qt's event loop
                    _log.exception("deferred font refresh of %s failed",
                                   type(obj).__name__)
        return False


def refresh_now_or_on_show(widget, fn: Callable[[], None], window=None) -> bool:
    """``fn()`` now when ``widget`` is on screen (or ``window`` is not), else
    once just before ``widget`` is next shown. A later call replaces a
    pending one (the newest sizes win). True when it ran now."""
    if not hasattr(widget, "isVisible") or not hasattr(widget, "installEventFilter"):
        fn()                                    # not a widget: nothing to wait for
        return True
    on_screen = widget.isVisible() or (window is not None and not window.isVisible())
    pending = _pending(widget)
    if on_screen:
        if pending is not None:
            pending.fn = None
            widget.removeEventFilter(pending)
            pending.deleteLater()
        fn()
        return True
    if pending is not None:
        pending.fn = fn
    else:
        _OnShow(widget, fn)
    return False


def _pending(widget):
    """The widget's own waiting refresh (a direct child: a panel's marker is
    never mistaken for one of a surface inside it), or None."""
    for child in widget.findChildren(QObject, _MARK, Qt.FindChildOption.FindDirectChildrenOnly):
        if isinstance(child, _OnShow) and child.fn is not None:
            return child
    return None


def pending(widget) -> bool:
    """A deferred refresh waits for ``widget``'s next Show (tests)."""
    return _pending(widget) is not None


def run_pending(root) -> int:
    """Run now every deferred refresh waiting under ``root`` (``root``
    included), as if each surface had been shown; returns how many ran.
    For tests that check a hidden surface right after a font change."""
    ran = 0
    for marker in list(root.findChildren(QObject, _MARK)):
        if not isinstance(marker, _OnShow) or marker.fn is None:
            continue
        fn, marker.fn = marker.fn, None
        owner = marker.parent()
        if owner is not None:
            owner.removeEventFilter(marker)
        marker.deleteLater()
        fn()
        ran += 1
    return ran


def run_pending_for(widget) -> int:
    """Before ``widget`` is drawn without being shown (an export, a PNG or
    PDF render, ``grab()`` / ``render()`` for a capture, a print): run the
    deferred refreshes that would change what it draws, so it never uses old
    font sizes. That is the waiting refresh of the widget itself, of each
    ancestor (a panel's refresh restyles the widgets inside it), and of each
    descendant drawn with it (``isVisibleTo(widget)``: a hidden page under a
    visible window is not drawn, so it keeps waiting for its own Show and a
    window grab stays cheap). A chart view's full draw deferred to its Show
    (``apps.widgets.paint_on_show``) runs too. Returns how many ran. Never raises."""
    if widget is None or not hasattr(widget, "findChildren"):
        return 0
    if hasattr(widget, "isVisible") and widget.isVisible():
        return 0      # on screen: it, its ancestors and what it draws are current
    ran = 0
    try:
        chain = []
        node = widget
        while node is not None:
            chain.append(node)
            node = node.parentWidget() if hasattr(node, "parentWidget") else None
        markers = []
        for node in reversed(chain):            # outermost first, as on Show
            markers.extend(node.findChildren(
                QObject, _MARK, Qt.FindChildOption.FindDirectChildrenOnly))
        for marker in widget.findChildren(QObject, _MARK):
            owner = marker.parent()
            if (owner is not widget and owner not in chain
                    and hasattr(owner, "isVisibleTo") and owner.isVisibleTo(widget)):
                markers.append(marker)
        for marker in markers:
            if not isinstance(marker, _OnShow) or marker.fn is None:
                continue
            fn, marker.fn = marker.fn, None
            owner = marker.parent()
            if owner is not None:
                owner.removeEventFilter(marker)
            marker.deleteLater()
            try:
                fn()
                ran += 1
            except Exception:
                _log.exception("font refresh before drawing %s failed",
                               type(widget).__name__)
        # The input fonts (combo boxes, spin boxes, line edits) of a hidden
        # widget take a scoped font change at their Show too (ui.input_font_qss).
        from ui.input_font_qss import stamp_for_draw
        stamp_for_draw(widget)
        # A chart view hidden under it runs its deferred full draw now (paint on show).
        from apps.widgets.paint_on_show import run_for_draw
        ran += run_for_draw(widget)
    except Exception:
        _log.exception("run_pending_for(%s) failed", type(widget).__name__)
    return ran
