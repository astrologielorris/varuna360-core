"""SPEC-BAR-001 — TitleWell, ElidedPillButton, CloseGlyphButton.

The document well (.title): recessed chrome + identity stripe painted by
paint_surfaces; children are an optional role letter ("A" / "B", two-chart
mode, SPEC-DUAL-001), the name button (ElidedPillButton — the ONE expanding
control on the bar, elides FIRST before any tier drops), the meta label
(hidden whole, never elided, per mockup trimMeta), the optional pair switch
(COMPARE / ONE CHART, the retired chevron's slot) and the 18px close glyph.
Replaces the old pill's setMinimumWidth(400) (bug B1/B10 driver).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QFontMetricsF, QPainter
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from . import paint_controls, paint_surfaces
from .bar_types import (BarMetrics, META_TEXT, NAME_TEXT, draw_bar_text,
                        meta_font, name_font, scaled_font, text_advance)
from .motion import MS_INK, MS_WELL, HoverFade


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
                 parent=None, *, style=META_TEXT, italic: bool = False):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self._token_key = token_key
        self._style = style
        self._italic = bool(italic)
        self._text = ""
        self._short = ""          # SPEC-DUAL-001: the pair's short meta
        self._level = 0           # 0 full, 1 short (the controller hides 2)
        self.setFixedHeight(metrics.ctl_h)
        self._resize_to_text()

    def setText(self, text: str):
        self._text = text or ""
        self._resize_to_text()
        self.update()

    def text(self) -> str:
        return self._text

    def shown_text(self) -> str:
        return self._short if self._level == 1 else self._text

    def set_short_text(self, text: str):
        if (text or "") != self._short:
            self._short = text or ""
            self._resize_to_text()
            self.update()

    def short_text(self) -> str:
        return self._short

    def set_level(self, level: int):
        """0 = the full meta, 1 = the short one (pair density, D-22f)."""
        level = 1 if level == 1 else 0
        if level != self._level:
            self._level = level
            self._resize_to_text()
            self.update()

    def level(self) -> int:
        return self._level

    def set_italic(self, italic: bool):
        if bool(italic) != self._italic:
            self._italic = bool(italic)
            self._resize_to_text()
            self.update()

    def _font(self):
        font, k = scaled_font(*self._style, fs=self._m.fs)
        font.setItalic(self._italic)
        return font, k

    def _adv(self, text: str) -> float:
        if not self._italic:
            return text_advance(text, *self._style, fs=self._m.fs)
        font, k = self._font()
        return QFontMetricsF(font).horizontalAdvance(text) / k

    def width_for(self, level: int) -> int:
        text = self._short if level == 1 else self._text
        return round(self._adv(text)) + 1 if text else 0

    def _resize_to_text(self):
        self.setFixedWidth(round(self._adv(self.shown_text())) + 1)

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self.setFixedHeight(metrics.ctl_h)
        self._resize_to_text()

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.TextAntialiasing, True)
            p.setPen(self._tokens_fn()[self._token_key])
            if self._italic:
                font, k = self._font()
                r = QRectF(self.rect())
                p.scale(1.0 / k, 1.0 / k)
                p.setFont(font)
                p.drawText(QRectF(r.x() * k, r.y() * k, r.width() * k, r.height() * k),
                           Qt.AlignLeft | Qt.AlignVCenter, self.shown_text())
            else:
                draw_bar_text(p, QRectF(self.rect()),
                              Qt.AlignLeft | Qt.AlignVCenter, self.shown_text(),
                              *self._style, fs=self._m.fs)
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
        # the hover rim is OUTSET (:415) and painted by the parent well, so
        # a fade CHANGE also repaints the well's ring region. Never from
        # paintEvent: updating the parent region that holds this child
        # repaints the child, which looped at ~355 paints/s at idle.
        self._hover_fade = HoverFade(self, MS_INK, on_change=self._update_rim)
        self._press_fade = HoverFade(self, MS_INK, on_change=self._update_rim)

    def _update_rim(self):
        pw = self.parentWidget()
        if pw is not None:
            pw.update(self.geometry().adjusted(-2, -2, 2, 2))

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self.setFixedSize(metrics.close_d, metrics.close_d)
        self.snap_motion()                                          # Dm4-9

    def moveEvent(self, e):
        super().moveEvent(e)
        if max(self._hover_fade.value(), self._press_fade.value()) > 0.0:
            pw = self.parentWidget()        # the lit rim follows the button
            if pw is not None:
                pw.update(e.oldPos().x() - 2, e.oldPos().y() - 2,
                          self.width() + 4, self.height() + 4)
            self._update_rim()

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


class TitleWell(QWidget):
    """The recessed center well; hover brightens (paint-only).

    ``role_label`` (the "A" / "B" letter) and ``switch`` (the pair switch)
    are optional children; ``stripe`` is the painted identity: "gold",
    "steel" or "hollow" (SPEC-DUAL-001 §4.1)."""

    def __init__(self, name_btn: ElidedPillButton, meta: BarTextLabel,
                 close_btn: CloseGlyphButton, metrics: BarMetrics, tokens_fn,
                 parent=None, *, role_label=None, switch=None,
                 stripe: str = "gold"):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self.name_btn = name_btn
        self.meta = meta
        self.close_btn = close_btn
        self.role_label = role_label
        self.switch = switch
        self._stripe = stripe
        self.rim_buttons = [close_btn]   # CloseGlyphButtons whose outset rim we paint
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)       # Dm4-36/37

        lay = QHBoxLayout(self)
        # left pad + room for the painted stripe, then the standard gap
        lay.setContentsMargins(
            round(metrics.title_pad_l + metrics.stripe_w + metrics.title_gap), 0,
            metrics.title_pad_r, 0)
        lay.setSpacing(metrics.title_gap)
        if role_label is not None:
            lay.addWidget(role_label, 0)
        lay.addWidget(name_btn, 0)
        lay.addWidget(meta, 0)
        lay.addStretch(1)          # .names' leftover space (name never grows)
        if switch is not None:
            lay.addWidget(switch, 0)
        lay.addWidget(close_btn, 0)

        self.setFixedHeight(metrics.ctl_h)
        self.setMinimumWidth(self.min_width())
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
        self._hint_level = None       # SPEC-DUAL-001: the pair's meta level
        self._drop_ring = False       # T13: a chart dragged over the pill
        # M4 (Dm4-41/43): the well's 180 ms background/box-shadow fade.
        self._hover = False           # tracked, event-written (Dm4-11)
        self._well_fade = HoverFade(self, MS_WELL)

    def _notify_content_changed(self):
        cb = self.on_content_changed
        if callable(cb):
            cb()

    def set_stripe(self, stripe: str):
        if stripe != self._stripe:
            self._stripe = stripe
            self.update()

    def stripe(self) -> str:
        return self._stripe

    # the retired chevron's glyph box: title_min_w's slot for it is handed to
    # the pair switch (its gap stays), SPEC-DUAL-001 §4.1
    RETIRED_CHEVRON_PX = 11

    def _optional_extra(self) -> int:
        """Width the role letter and the switch add when shown (+ gaps)."""
        sp = self._m.title_gap
        extra = 0
        if self.role_label is not None and not self.role_label.isHidden():
            extra += self.role_label.width() + sp
        if self.switch is not None and not self.switch.isHidden():
            extra += self.switch.width() - self.RETIRED_CHEVRON_PX
        return extra

    def min_width(self) -> int:
        """The mandatory width: ``title_min_w`` (stripe, minimum elided name,
        the old chevron slot, close) with the chevron's glyph box handed to
        the switch, plus the shown role letter (SPEC-DUAL-001 §4.1)."""
        return self._m.title_min_w + self._optional_extra()

    def refresh_min_width(self):
        w = self.min_width()
        if w != self.minimumWidth():
            self.setMinimumWidth(w)

    def set_hint_level(self, level):
        """None = one-chart sizing (full meta + band); 0/1/2 = the pair's
        meta level, sized exactly (the controller decides arithmetically)."""
        if level != self._hint_level:
            self._hint_level = level
            self.updateGeometry()

    def set_drop_ring(self, on: bool):
        if bool(on) != self._drop_ring:
            self._drop_ring = bool(on)
            self.update()

    def drop_ring(self) -> bool:
        return self._drop_ring

    def _fixed_parts(self) -> tuple[int, int]:
        """(sum of the shown non-meta children, their count); the name at its
        full text (sizeHint), the rest at their boxes."""
        lay = self.layout()
        total, n = 0, 0
        for i in range(lay.count()):
            wd = lay.itemAt(i).widget()
            if wd is None or wd is self.meta or wd.isHidden():
                continue
            total += wd.sizeHint().width() if wd is self.name_btn else wd.width()
            n += 1
        return total, n

    def natural_width(self, level: int) -> int:
        """Full name + the meta at ``level`` (0 full, 1 short, 2 none)."""
        lay = self.layout()
        mg = lay.contentsMargins()
        sp = lay.spacing()
        total, n = self._fixed_parts()
        w = mg.left() + mg.right() + total + sp * max(0, n - 1)
        meta_w = self.meta.width_for(level) if level < 2 else 0
        if meta_w:
            w += sp + meta_w
        return max(round(w), self.minimumWidth())

    def sizeHint(self):
        # C8 (Lorris, via orchestrator): the well is sized to its CONTENT —
        # every shown child + padding — so it hugs a short chart yet stays
        # wide enough to SHOW the meta line (the layout controller's meta
        # band hides the meta unless well.width() >= that content; a plain
        # content-hug that dropped the hidden meta shrank the well and clipped
        # it). We count the meta's FULL width even while the band has it
        # hidden or shortened, plus the band's 16px hysteresis, so the meta
        # reveals. Maximum policy makes this the ceiling; the bar's flanking
        # spacers centre it.
        from PySide6.QtCore import QSize
        if self._hint_level is not None:
            return QSize(self.natural_width(self._hint_level), self._m.ctl_h)
        w = self.natural_width(0)
        if self.meta.text():
            w += 16          # D-9 meta-band hysteresis: clear it, don't sit on it
        return QSize(w, self._m.ctl_h)

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
        # D-1 rev2: no max width (see __init__)
        self.name_btn.set_metrics(metrics)
        self.close_btn.set_metrics(metrics)
        self.meta.set_metrics(metrics)
        for w in (self.role_label, self.switch):
            if w is not None and hasattr(w, "set_metrics"):
                w.set_metrics(metrics)
        self.setMinimumWidth(self.min_width())
        self.snap_motion()                                          # Dm4-9

    def enterEvent(self, e):
        super().enterEvent(e)
        self._hover = True            # tracked flag (Dm4-11): synthesized
        self._well_fade.to(1.0)       # QEnterEvents never set underMouse()
        self.update()

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._hover = False
        self._well_fade.to(0.0)
        self.update()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._hover = False
        self._well_fade.snap(0.0)                                   # Dm4-12

    def snap_motion(self):
        self._well_fade.snap(1.0 if self._hover else 0.0)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            tokens = self._tokens_fn()
            paint_surfaces.paint_title_well(
                p, QRectF(self.rect()), tokens, self._m,
                self.devicePixelRatioF(), hovered=self._well_fade.value(),
                stripe=self._stripe)
            if self._drop_ring:                  # T13: 1.5 px inset ring
                from PySide6.QtGui import QPen
                p.setPen(QPen(tokens["ring"], 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75),
                                  self._m.radius, self._m.radius)
            # the close glyphs' hover rim is an OUTSET box-shadow (:415) —
            # it lives on OUR pixels, just outside the child's box.
            for btn in self.rim_buttons:
                if btn.isVisible():
                    hot = max(btn._hover_fade.value(), btn._press_fade.value())
                    if hot > 0.0:
                        from PySide6.QtCore import QPoint
                        tl = btn.mapTo(self, QPoint(0, 0))
                        paint_controls.close_hover_rim(
                            p, QRectF(tl.x(), tl.y(), btn.width(), btn.height()),
                            hot, tokens, self.devicePixelRatioF())
        finally:
            p.end()
