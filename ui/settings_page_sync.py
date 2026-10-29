# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings pages never undo a change made outside them (AI setting
redesign, td-bztjj, item 4; SPEC-SET-003 §4.5b).

A setting can change while a Settings page is built: the AI setting panel,
the Pro remote control, a toolbar toggle. Before this, the page kept showing
the value it read when it was built, and its next Apply wrote that old value
back over the new one. Two parts, both here:

1. **Refresh.** ``attach(page, reload, heads)`` subscribes the page to the
   store's change callbacks for the setting groups it shows (``heads``). A
   change made outside the page's own Apply re-reads the row it changed at
   once when the page is visible (on the next event-loop turn, one reload
   for every burst of change callbacks), or the next time it is shown (fix RD-2,
   Lorris's Q1 decision): the page's own reader runs (``reload``, its
   ``_read_from_settings``), then every input the user had edited and the
   outside change did not touch gets the user's value back, and only the
   changed key's baseline moves. The other unsaved edits keep their
   baselines, so the next Apply merges them three ways.
2. **Apply writes only the rows the user changed.** The page's Apply methods
   carry ``@page_apply``. While one runs, a write whose value is still the
   value the page read (``baseline``) is a row the user did not change: when
   the stored value moved since, the write is skipped and the newer value
   stays. A whole-group write (a dict, e.g. ``chart_display``) keeps the
   newer stored leaves and takes only the leaves the user changed. A write
   the user did change goes through as before.

When nothing changed outside the page, every write goes through unchanged
(the C-2 write-set record is the same).

No ``ChartGUI`` state (Rule 4b); the per-page state lives on a ``PageSync``
object held by the page.
"""
from __future__ import annotations

import copy
import functools
import inspect
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterable, Optional

from PySide6.QtCore import QEvent, QObject, QTimer

_MISSING = object()


def _settings():
    from managers.settings_manager import get_settings
    return get_settings()


def _walk(tree: Any, parts) -> Any:
    for part in parts:
        if not isinstance(tree, dict) or part not in tree:
            return _MISSING
        tree = tree[part]
    return tree


def merge3(base: Any, mine: Any, theirs: Any) -> Any:
    """``mine`` written over ``theirs`` where ``mine`` differs from ``base``
    (the user's edits), ``theirs`` (the stored value) everywhere else."""
    if mine == base:
        return copy.deepcopy(theirs)
    if isinstance(base, dict) and isinstance(mine, dict) and isinstance(theirs, dict):
        out = copy.deepcopy(theirs)
        for k, v in mine.items():
            b = base.get(k, _MISSING)
            if b is _MISSING:
                out[k] = copy.deepcopy(v)
            else:
                out[k] = merge3(b, v, theirs.get(k, b))
        return out
    return copy.deepcopy(mine)


def _set_path(tree: Any, parts, value: Any) -> Any:
    """``tree`` with the value at ``parts`` replaced (a copy; MISSING
    removes it)."""
    if not parts:
        return copy.deepcopy(value)
    out = copy.deepcopy(tree) if isinstance(tree, dict) else {}
    if value is _MISSING and len(parts) == 1:
        out.pop(parts[0], None)
        return out
    out[parts[0]] = _set_path(out.get(parts[0], _MISSING), parts[1:], value)
    return out


def _inputs(page):
    """The page's input widgets with a getter and a setter of what they show."""
    from PySide6.QtWidgets import (QAbstractButton, QAbstractSlider, QAbstractSpinBox,
                                   QComboBox, QLineEdit, QPlainTextEdit, QTextEdit)
    out = []
    for w in page.findChildren(QObject):
        if isinstance(w, QComboBox):
            if w.isEditable():
                out.append((w, w.currentText, w.setEditText))
            else:
                out.append((w, w.currentIndex, w.setCurrentIndex))
        elif isinstance(w, QAbstractSpinBox) and hasattr(w, "value"):
            out.append((w, w.value, w.setValue))
        elif isinstance(w, QLineEdit):
            if isinstance(w.parent(), (QAbstractSpinBox, QComboBox)):
                continue                        # the spin box's or combo's own editor
            out.append((w, w.text, w.setText))
        elif isinstance(w, QAbstractButton) and w.isCheckable():
            out.append((w, w.isChecked, w.setChecked))
        elif isinstance(w, QAbstractSlider):
            out.append((w, w.value, w.setValue))
        elif isinstance(w, QPlainTextEdit):
            out.append((w, w.toPlainText, w.setPlainText))
        elif isinstance(w, QTextEdit):
            out.append((w, w.toPlainText, w.setPlainText))
    return out


def _alive(widget) -> bool:
    try:
        import shiboken6
        return shiboken6.isValid(widget)
    except Exception:                                           # pragma: no cover
        return True


class PageSync(QObject):
    """One Settings page's baseline and refresh state."""

    def __init__(self, page, reload: Optional[Callable[[], None]],
                 heads: Iterable[str], settings=None):
        super().__init__(page)
        self._sm = settings
        self._page = page
        self._reload = reload
        self.heads = tuple(dict.fromkeys(heads))
        self._depth = 0
        self._kept_newer = False
        self._refresh_pending = False
        self.stale = False
        self.changed: Dict[str, Any] = {}       # keys changed outside, not yet re-read
        self.baseline: Dict[str, Any] = {}
        self.shown: Dict[int, Any] = {}         # what each input showed at the baseline
        self.take_baseline()
        page.installEventFilter(self)
        sm = self.settings()
        for head in self.heads:
            sm.on_changed(head, self._on_changed)
        page.destroyed.connect(lambda *_: self._detach(sm))

    def settings(self):
        return self._sm if self._sm is not None else _settings()

    # -- baseline ---------------------------------------------------------
    def take_baseline(self) -> None:
        sm = self.settings()
        self.baseline = {h: copy.deepcopy(sm.get(h, _MISSING)) for h in self.heads}
        self.take_shown()

    def take_shown(self) -> None:
        """What every input shows now: the page as read from the store."""
        try:
            self.shown = {id(w): (w, get()) for w, get, _set in _inputs(self._page)}
        except RuntimeError:                                    # pragma: no cover
            self.shown = {}

    def advance(self, key: str) -> None:
        """Move only ``key``'s baseline to the stored value."""
        sm = self.settings()
        parts = key.split(".")
        for head in self.heads:
            hp = head.split(".")
            if parts[:len(hp)] == hp:
                self.baseline[head] = _set_path(
                    self.baseline.get(head, _MISSING), parts[len(hp):],
                    copy.deepcopy(sm.get(key, _MISSING)))
            elif hp[:len(parts)] == parts:      # a whole group changed: its heads
                self.baseline[head] = copy.deepcopy(sm.get(head, _MISSING))

    def base(self, key: str) -> Any:
        parts = key.split(".")
        for head in self.heads:
            hp = head.split(".")
            if parts[:len(hp)] == hp:
                root = self.baseline.get(head, _MISSING)
                return root if root is _MISSING else _walk(root, parts[len(hp):])
        return _MISSING

    # -- refresh ----------------------------------------------------------
    def _detach(self, sm) -> None:
        for head in self.heads:
            try:
                sm.remove_on_changed(head, self._on_changed)
            except Exception:                                   # pragma: no cover
                pass

    def _on_changed(self, key_path: str, value: Any) -> None:
        if self._depth:
            return                                  # the page's own Apply
        self.stale = True
        self.changed[key_path] = True
        try:
            visible = self._page.isVisible()
        except RuntimeError:                        # page already deleted
            return
        if visible and not self._refresh_pending:
            # One reload per event-loop turn, not one per subscribed head: a
            # group write or a "*" notify (AI rollback, reset, font preset)
            # reaches this callback once for every matching head (11-29 on
            # the big pages), and each refresh is a full page re-read.
            self._refresh_pending = True
            QTimer.singleShot(0, self, lambda: self._run_pending_refresh())

    def _run_pending_refresh(self) -> None:
        self._refresh_pending = False
        if self._depth:
            return                  # inside the page's Apply: its exit re-reads
        try:
            visible = self._page.isVisible()
        except RuntimeError:                        # page already deleted
            return
        if visible:                                 # else: on the next Show
            self.refresh()

    def refresh(self) -> None:
        """Re-read the rows changed outside the page (see the module); the
        user's other unsaved edits stay, with their baselines."""
        if not self.stale:
            return
        self.stale = False
        changed, self.changed = list(self.changed), {}
        if not changed:
            if self._reload is not None:
                self._reload()
            self.take_baseline()
            return
        try:
            before = {id(w): (w, get()) for w, get, _s in _inputs(self._page)}
        except RuntimeError:                                    # pragma: no cover
            before = {}
        edited = {i: v for i, (w, v) in before.items()
                  if i in self.shown and self.shown[i][0] is w and self.shown[i][1] != v}
        if self._reload is not None:
            self._reload()
        # The inputs the outside change moved show the new value; every other
        # input the user had edited gets the user's value back.
        restored = set()
        for w, get, put in _inputs(self._page):
            i = id(w)
            if i not in edited or not _alive(w):
                continue
            was = self.shown[i][1]
            if get() == was:                        # the change did not touch it
                put(edited[i])
                restored.add(i)
        for key in changed:
            self.advance(key)
        # What the page shows at its baseline: every input as re-read, except
        # the unsaved edits given back, which keep their old baseline (R2-4:
        # an input that adopted an outside value takes it as its baseline,
        # even when that value equals the user's earlier edit).
        shown = {}
        for w, get, _s in _inputs(self._page):
            i = id(w)
            shown[i] = (w, self.shown[i][1] if i in restored else get())
        self.shown = shown

    def eventFilter(self, obj, event):
        if obj is self._page and event.type() == QEvent.Type.Show and self.stale:
            self.refresh()
        return False

    # -- Apply ------------------------------------------------------------
    @contextmanager
    def applying(self, keep_newer: bool = True):
        """The page writes its rows: its own change callbacks are not an
        outside change; with ``keep_newer``, a write of a row the user did not
        change keeps the newer stored value (see the module)."""
        sm = self.settings()
        outer = self._depth == 0
        filtering = outer and keep_newer
        if outer:
            self._kept_newer = False
            if self._refresh_pending:   # an outside change still queued: it
                self._run_pending_refresh()     # lands first, then the Apply
        if filtering:
            prior = vars(sm).get("set", _MISSING)   # an instance-level set, if any
            real_set = sm.set

            def set_(key_path, value, *args, **kwargs):
                if self._skip(sm, key_path, value):
                    return True                     # the newer stored value stays
                return real_set(key_path, self._kept(sm, key_path, value),
                                *args, **kwargs)
            sm.set = set_
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if filtering:
                if prior is _MISSING:
                    vars(sm).pop("set", None)
                else:
                    sm.set = prior
            if outer:
                # the rows show what is kept, and an outside change that
                # arrived while the Apply ran is still re-read
                self.stale = self._kept_newer or bool(self.changed)
                self.take_baseline()
                try:
                    if self.stale and self._page.isVisible():
                        self.refresh()
                except RuntimeError:                # pragma: no cover
                    pass

    def _skip(self, sm, key: str, value: Any) -> bool:
        base = self.base(key)
        if base is _MISSING:
            return False
        if value == base and sm.get(key, _MISSING) != base:
            self._kept_newer = True
            return True
        return False

    def _kept(self, sm, key: str, value: Any) -> Any:
        base = self.base(key)
        if base is _MISSING:
            return value
        theirs = sm.get(key, _MISSING)
        if theirs is _MISSING or theirs == base:
            return value
        merged = merge3(base, value, theirs)
        if merged != value:
            self._kept_newer = True
        return merged


def attach(page, reload: Optional[Callable[[], None]], heads: Iterable[str],
           settings=None) -> PageSync:
    """Give ``page`` its refresh and changed-only Apply (see the module)."""
    sync = PageSync(page, reload, heads, settings)
    page._page_sync = sync
    return sync


def _wrap(fn, keep_newer: bool):
    """The method run inside ``applying``. The wrapper takes exactly the
    method's own positional parameters: Qt passes a slot as many signal
    arguments as its code object declares (none to ``*args``)."""
    try:
        params = list(inspect.signature(fn).parameters.values())[1:]
    except (TypeError, ValueError):                 # pragma: no cover
        params = []
    n = sum(1 for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD))

    def run(self, *args, **kwargs):
        sync = getattr(self, "_page_sync", None)
        if sync is None:
            return fn(self, *args, **kwargs)
        with sync.applying(keep_newer=keep_newer):
            return fn(self, *args, **kwargs)

    if n == 0:
        def wrapper(self):
            return run(self)
    elif n == 1:
        def wrapper(self, a):
            return run(self, a)
    else:                                           # pragma: no cover
        def wrapper(self, *args, **kwargs):
            return run(self, *args, **kwargs)
    functools.update_wrapper(wrapper, fn)
    del wrapper.__wrapped__                         # Qt reads the wrapper's own arity
    return wrapper


def page_apply(fn):
    """Mark a Settings page's Apply (or a row's own save): a row the user
    did not change keeps a value changed outside the page."""
    return _wrap(fn, True)


def page_write(fn):
    """Mark a page method that writes on purpose whatever was there (Reset,
    a row that saves as it changes): its writes are the page's own, so they
    do not re-read the page."""
    return _wrap(fn, False)
