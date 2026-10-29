# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Work a widget does when it is next shown (``when_shown``: the PLANET, DIGNITY
and Strength light redraws, the Body/Aspect arrows), and paint on show: a live chart
view hidden in a window on screen takes every state write at once but its full draw
(``PAINT``) waits for its next Show, then runs once, last, with every post-pass
(SPEC-SIC-002 amendment 2026-10-28, INV-12: data is never deferred, only pixels).
"""
from __future__ import annotations

import weakref

import shiboken6
from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QApplication

_PENDING = weakref.WeakKeyDictionary()   # widget -> {kind: job(widget)}
_CATCH_UP = []                           # the one show-event filter
PAINT = "paint"
_POST_PASSES = ("planet_pass", "exchange_chain")   # every full draw runs these itself
_DIRTY = weakref.WeakSet()                         # views whose full draw waits for Show
_FLUSHING = weakref.WeakSet()                      # drawn now for a capture (run_for_draw)


class _ShowCatchUp(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show:
            jobs = _PENDING.pop(obj, None)
            if jobs:
                obj.removeEventFilter(self)
                _run(obj, jobs.values())   # a pending PAINT is last (when_shown)
        return False


def _run(widget, jobs):
    for job in list(jobs):
        try:
            job(widget)
        except Exception:
            continue                       # one view's failure never blocks the others


def when_shown(widget, kind, job):
    """``job(widget)`` now when ``widget`` is on screen (True), else once at its
    next show (False; a later job of the same ``kind`` replaces it). ``job`` takes
    the widget as its argument so the pending table never keeps a view alive."""
    if widget.isVisible():
        jobs = _PENDING.get(widget)
        if jobs:
            jobs.pop(kind, None)           # done now: nothing left to catch up
            if not jobs:
                del _PENDING[widget]
                widget.removeEventFilter(_CATCH_UP[0])
        _run(widget, (job,))
        return True
    if kind in _POST_PASSES and widget in _DIRTY:
        return False                       # its pending full draw runs every post-pass
    jobs = _PENDING.setdefault(widget, {})
    if not jobs:
        if not _CATCH_UP:
            _CATCH_UP.append(_ShowCatchUp(QApplication.instance()))
        widget.installEventFilter(_CATCH_UP[0])
    jobs[kind] = job
    if PAINT in jobs:
        jobs[PAINT] = jobs.pop(PAINT)      # the full draw is the final word
    return False


def pending(widget):                     # the kinds of job ``widget`` runs when shown (tests)
    return tuple(_PENDING.get(widget, ()))


def paint_on_show(*views):               # live main-window chart views (never minis, CLI, exports)
    for view in views:
        view._paint_on_show = True


def hidden_live(widget):
    """Opted in and hidden in a window on screen (a window not shown yet draws at once)."""
    if not getattr(widget, "_paint_on_show", False) or widget.isVisible():
        return False
    window = widget.window()
    return window is not widget and window.isVisible()


def defer_paint(view, draw):
    """First call of a full draw ``view.<draw>()``: True when it waits for the view's
    next Show (the caller returns), False when it runs now (ending a pending one)."""
    if view in _FLUSHING or not hidden_live(view):
        _DIRTY.discard(view)
        return False
    _DIRTY.add(view)
    for kind in _POST_PASSES:
        _PENDING.get(view, {}).pop(kind, None)
    when_shown(view, PAINT, lambda v, d=draw: v in _DIRTY and getattr(v, d)())
    return True


def cancel_paint(view):                  # cleared without its full draw: a pending one is moot
    _DIRTY.discard(view)


def paint_pending(view):                 # a full draw waits for Show (tests, readers)
    return view in _DIRTY


def run_for_draw(widget):
    """``widget`` is drawn without being shown (an export, a capture: font_refresh_
    deferral.run_pending_for): run now the show-time jobs of it and of each descendant
    drawn with it, deepest first as on Show, a deferred full draw included."""
    drawn = [w for w in list(_PENDING) if shiboken6.isValid(w) and (w is widget or (
        widget.isAncestorOf(w) and w.isVisibleTo(widget)))]
    for w in sorted(drawn, key=lambda w: -sum(x.isAncestorOf(w) for x in drawn)):
        _FLUSHING.add(w)
        _CATCH_UP[0].eventFilter(w, QShowEvent())      # the Show path, now
        _FLUSHING.discard(w)
    return len(drawn)
