"""SPEC-BAR-001 — TitleWell, ElidedPillButton, CloseGlyphButton.

The document well (.title): recessed chrome + gold stripe + chevron painted
by paint_surfaces; children are the name button (ElidedPillButton — the ONE
expanding control on the bar, elides FIRST before any tier drops), the meta
QLabel (hidden whole, never elided, per mockup trimMeta), and the 18px close
glyph. Replaces the old pill's setMinimumWidth(400) (bug B1/B10 driver).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFontMetricsF, QPainter
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from . import paint_controls, paint_surfaces
from .bar_types import (BarMetrics, META_TEXT, NAME_TEXT, draw_bar_text,
                        meta_font, name_font, scaled_font, text_advance)
from .motion import MS_CHEV, MS_INK, MS_WELL, HoverFade


class ElidedPillButton(QPushButton):
    """The chart-name control: full text kept in a property, paints
    middle-elided text, tooltip = full text when elided (spec §4)."""

    def __init__(self, metrics: BarMetrics, tokens_fn, parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self._full_text = "No Chart Loaded"
        self.setFont(name_font(metrics.fs))
        self.setCursor(Qt.PointingHandCursor)
        # Dm4-36: TabFocus uniformly — StrongFocus would flash the focus
        # ring on every mouse click (report 06 §4's exact failure).
        self.setFocusPolicy(Qt.TabFocus)
        # mockup .nm{flex:0 1 auto}: the name SHRINKS under pressure but never
        # grows past its text — Maximum policy = sizeHint is the ceiling. The
        # well's trailing stretch absorbs leftover space so meta sits right
        # after the name (an Expanding name pushed meta to the far edge and
        # broke the golden's ink-run probe).
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setFixedHeight(metrics.ctl_h)
        self.setMinimumWidth(round(40 * metrics.fs))

    def sizeHint(self):
        from PySide6.QtCore import QSize
        import math
        # ceil, not round: the paint path elides at (width - 2), so a hint of
        # round(adv)+2 can sit a fraction BELOW the true advance and elide a
        # fully-fitting name (caught at fs 1.25: advance 104.38, box 106,
        # avail 104 -> "Now Saturd…" and a -19px ink FAIL at CP-2).
        return QSize(
            math.ceil(text_advance(self._full_text, *NAME_TEXT,
                                   fs=self._m.fs)) + 2,
            self._m.ctl_h)

    def setText(self, text: str):  # keep QPushButton API (INV-5 consumers)
        self._full_text = text or ""
        self._sync_tooltip()
        self.updateGeometry()      # content change, not state change (INV-1 ok)
        self.update()

    def text(self) -> str:
        return self._full_text

    def full_text(self) -> str:
        return self._full_text

    def _elided(self) -> str:
        # elide with the SCALED font's metrics (true fractional advances),
        # in k-space, then the paint scales back down.
        font, k = scaled_font(*NAME_TEXT, fs=self._m.fs)
        fm = QFontMetricsF(font)
        return fm.elidedText(self._full_text, Qt.ElideMiddle,
                             max(0.0, (self.width() - 2.0) * k))

    def _sync_tooltip(self):
        adv = text_advance(self._full_text, *NAME_TEXT, fs=self._m.fs)
        self.setToolTip(self._full_text if adv > self.width() - 2.0 else "")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_tooltip()

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self.setFont(name_font(metrics.fs))
        self.setFixedHeight(metrics.ctl_h)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.TextAntialiasing, True)
            p.setPen(self._tokens_fn()["primary_text"])
            draw_bar_text(p, QRectF(self.rect()),
                          Qt.AlignLeft | Qt.AlignVCenter, self._elided(),
                          *NAME_TEXT, fs=self._m.fs)
        finally:
            p.end()


class BarTextLabel(QWidget):
    """A QLabel stand-in whose text paints at the true fractional pixel size
    (the meta line, 10.5px wght 490). Keeps setText/text API for consumers."""

    def __init__(self, metrics: BarMetrics, tokens_fn, token_key: str = "muted",
                 parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self._token_key = token_key
        self._text = ""
        self.setFixedHeight(metrics.ctl_h)
        self._resize_to_text()

    def setText(self, text: str):
        self._text = text or ""
        self._resize_to_text()
        self.update()

    def text(self) -> str:
        return self._text

    def _resize_to_text(self):
        self.setFixedWidth(
            round(text_advance(self._text, *META_TEXT, fs=self._m.fs)) + 1)

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self.setFixedHeight(metrics.ctl_h)
        self._resize_to_text()

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.TextAntialiasing, True)
            p.setPen(self._tokens_fn()[self._token_key])
            draw_bar_text(p, QRectF(self.rect()),
                          Qt.AlignLeft | Qt.AlignVCenter, self._text,
                          *META_TEXT, fs=self._m.fs)
        finally:
            p.end()


class CloseGlyphButton(QPushButton):
    """The 18x18 circular close (.xbtn); attribute gui.chart_close_button."""

    def __init__(self, metrics: BarMetrics, tokens_fn, parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self.setFixedSize(metrics.close_d, metrics.close_d)
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)       # Dm4-36: never focus on click
        self.setToolTip("Close chart")
        # M4 (Dm4-42/43): tracked hover + one 160 ms `ease` clock each for
        # hover and press; underMouse()/isDown() polling cannot see the edge.
        self._hover = False           # tracked, event-written (Dm4-11)
        self._hover_fade = HoverFade(self, MS_INK)
        self._press_fade = HoverFade(self, MS_INK)

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self.setFixedSize(metrics.close_d, metrics.close_d)
        self.snap_motion()                                          # Dm4-9

    def enterEvent(self, e):
        super().enterEvent(e)
        self._hover = True            # tracked flag (Dm4-11): synthesized
        self._hover_fade.to(1.0)      # QEnterEvents never set underMouse()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._hover = False
        self._hover_fade.to(0.0)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self._press_fade.to(1.0 if self.isDown() else 0.0)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._press_fade.to(1.0 if self.isDown() else 0.0)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._hover = False
        self._hover_fade.snap(0.0)                                  # Dm4-12
        self._press_fade.snap(0.0)

    def snap_motion(self):
        self._hover_fade.snap(1.0 if self._hover else 0.0)
        self._press_fade.snap(1.0 if self.isDown() else 0.0)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            paint_controls.paint_close_button(
                p, QRectF(self.rect()),
                self._hover_fade.value(), self._press_fade.value(),
                self._tokens_fn(), self._m, self.devicePixelRatioF())
        finally:
            p.end()
        # the hover rim is OUTSET (:415) and painted by the parent well —
        # keep its ring region in step with this widget's fade ticks.
        pw = self.parentWidget()
        if pw is not None:
            pw.update(self.geometry().adjusted(-2, -2, 2, 2))


class TitleWell(QWidget):
    """The recessed center well; hover brightens (paint-only)."""

    def __init__(self, name_btn: ElidedPillButton, meta: BarTextLabel,
                 close_btn: CloseGlyphButton, metrics: BarMetrics, tokens_fn,
                 parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self.name_btn = name_btn
        self.meta = meta
        self.close_btn = close_btn
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)       # Dm4-36/37

        lay = QHBoxLayout(self)
        # left pad + room for the painted stripe, then the standard gap
        lay.setContentsMargins(
            round(metrics.title_pad_l + metrics.stripe_w + metrics.title_gap), 0,
            metrics.title_pad_r, 0)
        lay.setSpacing(metrics.title_gap)
        lay.addWidget(name_btn, 0)
        lay.addWidget(meta, 0)
        lay.addStretch(1)          # .names' leftover space (name never grows)
        # chevron is painted chrome; reserve its slot with spacing on close
        lay.addWidget(close_btn, 0)

        self.setFixedHeight(metrics.ctl_h)
        self.setMinimumWidth(metrics.title_min_w)
        # C8 (2026-08-29, Lorris): the well HUGS its content (Maximum = sizeHint
        # is the ceiling) instead of absorbing all surplus, so the name/meta box
        # is no wider than it needs. The surplus now goes to a spacer the bar
        # inserts to the well's RIGHT (see action_bar assemble), so the left and
        # right clusters STILL hug the bar ends — no dead backdrop caps at the
        # edges (the D-1 rev2 failure the old 560*fs *centre* cap caused).
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        # M2: the layout controller's meta band re-evaluates on every well
        # width/content change (doc §1.5 trigger set). LayoutRequest covers
        # name/meta setText (both call updateGeometry / setFixedWidth);
        # resizeEvent covers the well itself.
        self.on_content_changed = None
        # M4 (Dm4-41/43): two clocks, one trigger — the well's 180 ms
        # background/box-shadow fade and the chevron's own 160 ms colour.
        self._hover = False           # tracked, event-written (Dm4-11)
        self._well_fade = HoverFade(self, MS_WELL)
        self._chev_fade = HoverFade(self, MS_CHEV)

    def _notify_content_changed(self):
        cb = self.on_content_changed
        if callable(cb):
            cb()

    def sizeHint(self):
        # C8 (Lorris, via orchestrator): the well is sized to its CONTENT —
        # name + meta + chevron slot + padding — so it hugs a short chart yet
        # stays wide enough to SHOW the meta line (the layout controller's meta
        # band hides the meta unless well.width() >= that content; a plain
        # content-hug that dropped the hidden meta shrank the well and clipped
        # it). We count the meta's own fixed width even while the band has it
        # hidden, plus the band's 16px hysteresis, so the meta reveals. Maximum
        # policy makes this the ceiling; the bar's flanking spacers centre it.
        from PySide6.QtCore import QSize
        lay = self.layout()
        mg = lay.contentsMargins()
        sp = lay.spacing()
        name_w = self.name_btn.sizeHint().width()
        meta_w = self.meta.width() if self.meta.text() else 0
        close_w = self.close_btn.sizeHint().width()
        w = mg.left() + mg.right() + name_w + close_w + 3 * sp + meta_w
        if meta_w:
            w += 16          # D-9 meta-band hysteresis: clear it, don't sit on it
        return QSize(max(round(w), self.minimumWidth()), self._m.ctl_h)

    def event(self, e):
        from PySide6.QtCore import QEvent
        handled = super().event(e)
        if e.type() == QEvent.LayoutRequest:
            # C8: a child (name/meta) size change already invalidates our layout
            # and re-queries sizeHint; do NOT call updateGeometry() here — it
            # re-posts a LayoutRequest and thrashes (shrink/grow sweep timeout).
            self._notify_content_changed()
        return handled

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._notify_content_changed()

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        lay = self.layout()
        lay.setContentsMargins(
            round(metrics.title_pad_l + metrics.stripe_w + metrics.title_gap), 0,
            metrics.title_pad_r, 0)
        lay.setSpacing(metrics.title_gap)
        self.setFixedHeight(metrics.ctl_h)
        self.setMinimumWidth(metrics.title_min_w)
        # D-1 rev2: no max width (see __init__)
        self.name_btn.set_metrics(metrics)
        self.close_btn.set_metrics(metrics)
        self.meta.set_metrics(metrics)
        self.snap_motion()                                          # Dm4-9

    def enterEvent(self, e):
        super().enterEvent(e)
        self._hover = True            # tracked flag (Dm4-11): synthesized
        self._well_fade.to(1.0)       # QEnterEvents never set underMouse()
        self._chev_fade.to(1.0)
        self.update()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._hover = False
        self._well_fade.to(0.0)
        self._chev_fade.to(0.0)
        self.update()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._hover = False
        self._well_fade.snap(0.0)                                   # Dm4-12
        self._chev_fade.snap(0.0)

    def snap_motion(self):
        t = 1.0 if self._hover else 0.0
        self._well_fade.snap(t)
        self._chev_fade.snap(t)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            tokens = self._tokens_fn()
            paint_surfaces.paint_title_well(
                p, QRectF(self.rect()), tokens, self._m,
                self.devicePixelRatioF(), hovered=self._well_fade.value(),
                chev_t=self._chev_fade.value())
            # the close button's hover rim is an OUTSET box-shadow (:415) —
            # it lives on OUR pixels, just outside the child's box.
            btn = self.close_btn
            if btn.isVisible():
                hot = max(btn._hover_fade.value(), btn._press_fade.value())
                paint_controls.close_hover_rim(
                    p, QRectF(btn.geometry()), hot, tokens,
                    self.devicePixelRatioF())
        finally:
            p.end()
