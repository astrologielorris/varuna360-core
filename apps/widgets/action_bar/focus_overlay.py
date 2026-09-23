"""SPEC-BAR-001 M4 — the keyboard focus ring (A18/A19/A20, Dm4-33..37).

One bar-wide, mouse-transparent overlay widget painting ONE ring for the
focused bar control. This AMENDS D-14 (Dm4-34): the mockup's ring is
`outline` at `outline-offset:1px` lifted by `z-index:3/4` — it OVERLAPS the
neighbouring segments and the tray, and a cluster has no inter-control gaps
(`lay.setSpacing(0)`) nor any way for a parent to paint above its children.
The overlay is INV-2-clean by the invariant's own text ("the focus ring …
is an overlay, excluded from the child-rect overlap assertion") and
INV-1-clean because no box changes and no padding is reserved.

The ring is INSTANT in both directions (Dm4-33: `outline` is in no
transition list anywhere in the mockup) — so it needs no motion clock and
behaves identically in LIVE/REDUCED/POSE.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from . import paint_controls
from .segment_button import SegmentButton
from .title_well import CloseGlyphButton

_SUPPRESSED_REASONS = (Qt.FocusReason.MouseFocusReason,
                       Qt.FocusReason.PopupFocusReason)


class FocusOverlay(QWidget):
    """Bar-wide, mouse-transparent, always on top. Paints ONE ring."""

    def __init__(self, bar, tokens_fn):
        super().__init__(bar)
        self._bar = bar
        self._tokens_fn = tokens_fn
        # Dm4-36 belt-and-braces: TabFocus everywhere means a click never
        # focuses, but an Alt+key/popup path must not surprise us either —
        # the app-level filter records the last FocusIn's reason.
        self._last_reason = Qt.FocusReason.OtherFocusReason
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setGeometry(bar.rect())
        app = QApplication.instance()
        app.focusChanged.connect(self._on_focus_changed)
        # Reason capture rides PER-CHILD filters, never an app-wide one: an
        # app filter runs Python for EVERY event in the process, and each
        # additional live overlay multiplies that (a test process that only
        # deleteLater()s its bars accumulated 60+ and turned a 0.1 s focus
        # walk into 10 s / an OOM). Only the bar's own focusable descendants
        # can wear the ring, so only they need filtering; they all exist by
        # the time create_action_bar mounts the overlay (last).
        bar.installEventFilter(self)
        for w in bar.findChildren(QWidget):
            w.installEventFilter(self)
        self.show()
        self.raise_()

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.FocusIn:
            try:
                self._last_reason = e.reason()
            except Exception:
                pass
        return False

    def _on_focus_changed(self, _old, _new):
        self.update()

    def _focused_control(self):
        w = QApplication.focusWidget()
        if (w is None or w is self._bar or not self._bar.isAncestorOf(w)
                or not w.isVisible()):
            return None
        if w.isWindow():
            # the lazy overflow QMenu is a bar-parented POPUP WINDOW; it is
            # not filtered (created after mount), so its PopupFocusReason
            # never reaches _last_reason — exclude windows structurally.
            return None
        if self._last_reason in _SUPPRESSED_REASONS:
            return None
        return w

    def _ring_geometry(self, w) -> tuple[QRectF, tuple]:
        """The control's own box in BAR coordinates + its per-corner radii
        (Dm4-34: the ring wears the control's shape, not a generic pill)."""
        m = self._bar.metrics
        top_left = w.mapTo(self._bar, QPoint(0, 0))
        rect = QRectF(top_left.x(), top_left.y(), w.width(), w.height())
        local = QRectF(0, 0, w.width(), w.height())
        if isinstance(w, SegmentButton):
            radii = paint_controls._corner_radii(w._pos, w.spec.role,
                                                 local, m)
        elif isinstance(w, CloseGlyphButton):
            r = min(local.width(), local.height()) / 2.0     # .xbtn circle
            radii = (r, r, r, r)
        else:                                    # pill / well / labels
            r = float(m.radius)
            radii = (r, r, r, r)
        return rect, radii

    def paintEvent(self, event):
        w = self._focused_control()
        if w is None:
            return
        m = self._bar.metrics
        fs = m.fs
        width = 2.0 * fs                        # Dm4-35: scales with fs
        offset = 1.0 * fs
        e = offset + width / 2.0                # pen centre-line expansion
        rect, radii = self._ring_geometry(w)
        ring_rect = rect.adjusted(-e, -e, e, e)
        ring_radii = tuple(r + e if r > 0 else 0.0 for r in radii)
        p = QPainter(self)
        try:
            # NOT device-snapped (report 06 §6): a snapped 2px ring on a 6px
            # radius reads jagged.
            p.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(self._tokens_fn()["ring"], width)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(paint_controls._rounded_path(ring_rect, ring_radii))
        finally:
            p.end()
