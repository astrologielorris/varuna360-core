"""SPEC-DUAL-001 §4.1 — the pair switch, the swap segment, well B, the pill pair.

One-chart mode keeps today's single title well, with the retired chevron's
slot now holding the ``PairSwitch`` ("COMPARE"). Two-chart mode shows
``[well A] [⇄] [well B]``: well A gains an "A" letter, well B carries a steel
stripe, "B", the name, the meta (or the italic empty hint) and "ONE CHART".

Everything here is painted from ``bar_tokens()`` at paint time with the bar's
own fractional text primitives (INV-4 of SPEC-BAR-001: no QSS, no hex). The
pair lives on the bar (``bar.pair``), never on the GUI (Rule 4b): clicks are
emitted as signals and the action bar routes them to ``gui.chart_pair``.

The pair container is also the pill's drop target (T13): a chart dragged onto
it rings well A and shows a "◇ Overlay on <A>" cue; the drop goes to
``ChartOverlayManager.handle_drop``, like TRANSIT.
"""
from __future__ import annotations

import math

from PySide6.QtCore import (QEasingCurve, QEvent, QPoint, QPointF, QRectF,
                            QSize, Qt, QVariantAnimation, Signal)
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from core.i18n import t

from . import paint_surfaces
from .bar_types import META_TEXT, BarMetrics, draw_bar_text, text_advance
from .motion import MS_INK, HoverFade, lerp_premul
from .title_well import (BarTextLabel, CloseGlyphButton, ElidedPillButton,
                         TitleWell)

# (px, weight, tracking-em) — spec §4.1
SWITCH_TEXT = (10.0, 600, 0.07)          # 10 px, 600, tracking 0.7 px
ROLE_TEXT = (9.5, 650, 0.5 / 9.5)        # "A" / "B": 9.5 px, 650, 0.5 px
HINT_TEXT = (11.0, 490, 0.0)             # empty B hint, italic
CUE_TEXT = (12.0, 500, 0.0)
CUE_NAME = (12.0, 650, 0.0)

PAIR_GAP = 5.0                           # x fs, between the wells and ⇄
SWAP_W, SWAP_H = 28.0, 24.0              # x fs
SWAP_GLYPH = 13.0                        # x fs
SWAP_MS = 200
CUE_H = 24.0
CUE_OFFSET = 7.0


def _reduce_motion() -> bool:
    try:
        from managers.settings_manager import get_settings
        return bool(get_settings().get("ui.reduce_motion"))
    except Exception:
        return False


def switch_labels() -> tuple[str, str]:
    return (t("chart.pair.switch.compare", "COMPARE"),
            t("chart.pair.switch.one", "ONE CHART"))


class RoleLabel(QWidget):
    """The "A" / "B" letter of a paired well (muted, painted)."""

    def __init__(self, text: str, metrics: BarMetrics, tokens_fn, parent=None):
        super().__init__(parent)
        self._text = text
        self._m = metrics
        self._tokens_fn = tokens_fn
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._resize()

    def text(self) -> str:
        return self._text

    def set_text(self, text: str):
        self._text = text
        self._resize()
        self.update()

    def _resize(self):
        w = math.ceil(text_advance(self._text, *ROLE_TEXT, fs=self._m.fs)) + 1
        self.setFixedSize(w, self._m.ctl_h)

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self._resize()

    def paintEvent(self, _e):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.TextAntialiasing, True)
            p.setPen(self._tokens_fn()["muted"])
            draw_bar_text(p, QRectF(self.rect()), Qt.AlignLeft | Qt.AlignVCenter,
                          self._text, *ROLE_TEXT, fs=self._m.fs)
        finally:
            p.end()


class PairSwitch(QPushButton):
    """The text switch: "COMPARE" (one chart) / "ONE CHART" (two charts).

    18 px tall, padding 9 / 6, radius 0 4 4 0, a 0.5 px hairline on its left;
    ``muted`` idle, ``primary_text`` + a ``ctl_h`` wash on hover. Its box is
    sized from the WIDER of the two measured ``t()`` labels on every metrics
    or language change, so hover and the label flip never move it (D-25).
    """

    def __init__(self, metrics: BarMetrics, tokens_fn, parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self._two = False
        self._hover = False
        self._fade = HoverFade(self, MS_INK)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.refresh_labels()

    def box_width(self) -> int:
        adv = max(text_advance(x, *SWITCH_TEXT, fs=self._m.fs) for x in switch_labels())
        return math.ceil(adv + (9.0 + 6.0) * self._m.fs)

    def refresh_labels(self):
        self.setFixedSize(self.box_width(), round(18 * self._m.fs))
        self._sync_tip()
        self.update()

    def _sync_tip(self):
        self.setToolTip(t("chart.pair.switch.one_tip", "Back to one chart (Alt+2)")
                        if self._two else
                        t("chart.pair.switch.compare_tip", "Two charts (Alt+2)"))

    def set_two(self, two: bool):
        if bool(two) != self._two:
            self._two = bool(two)
            self._sync_tip()
            self.update()

    def is_two(self) -> bool:
        return self._two

    def label(self) -> str:
        return switch_labels()[1 if self._two else 0]

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self.refresh_labels()
        self.snap_motion()

    def snap_motion(self):
        self._fade.snap(1.0 if self._hover else 0.0)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.LanguageChange:
            self.refresh_labels()

    def enterEvent(self, e):
        super().enterEvent(e)
        self._hover = True
        self._fade.to(1.0)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._hover = False
        self._fade.to(0.0)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._hover = False
        self._fade.snap(0.0)

    def paintEvent(self, _e):
        from .paint_controls import _rounded_path
        tok = self._tokens_fn()
        h = self._fade.value()
        fs = self._m.fs
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            rect = QRectF(self.rect())
            if h > 0.0:
                r = 4.0 * fs
                p.setPen(Qt.NoPen)
                p.setBrush(lerp_premul(None, tok["ctl_h"], h))
                p.drawPath(_rounded_path(rect, (0.0, r, r, 0.0)))
            paint_surfaces.draw_vline(p, 0.0, rect.top(), rect.height(), tok["hair"],
                                      self.devicePixelRatioF(), css_px=0.5)
            p.setRenderHint(QPainter.TextAntialiasing, True)
            p.setPen(lerp_premul(tok["muted"], tok["primary_text"], h))
            text_r = rect.adjusted(9.0 * fs, 0, -6.0 * fs, 0)
            draw_bar_text(p, text_r, Qt.AlignCenter, self.label(), *SWITCH_TEXT, fs=fs)
        finally:
            p.end()


class SwapSegment(QPushButton):
    """⇄: a 28 x 24 bar segment (ctl fill, hairline, gloss); hover turns the
    glyph 180 degrees in 200 ms (0 ms with reduce motion)."""

    def __init__(self, metrics: BarMetrics, tokens_fn, parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self._hover = False
        self._angle = 0.0
        self._anim = None
        self._fade = HoverFade(self, MS_INK)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(t("chart.pair.swap_tip", "Swap A and B (Ctrl+Shift+2)"))
        self.set_metrics(metrics)

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self.setFixedSize(round(SWAP_W * metrics.fs), round(SWAP_H * metrics.fs))
        self.snap_motion()

    def angle(self) -> float:
        return self._angle

    def snap_motion(self):
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        self._angle = 180.0 if self._hover else 0.0
        self._fade.snap(1.0 if self._hover else 0.0)
        self.update()

    def _turn_to(self, target: float):
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
            self._anim = None
        ms = 0 if _reduce_motion() else round(SWAP_MS * abs(target - self._angle) / 180.0)
        if ms <= 0:
            self._angle = target
            self.update()
            return
        anim = QVariantAnimation(self)
        anim.setStartValue(float(self._angle))
        anim.setEndValue(float(target))
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def frame(v):
            self._angle = float(v)
            self.update()
        anim.valueChanged.connect(frame)
        self._anim = anim
        anim.start()

    def enterEvent(self, e):
        super().enterEvent(e)
        self._hover = True
        self._fade.to(1.0)
        self._turn_to(180.0)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._hover = False
        self._fade.to(0.0)
        self._turn_to(0.0)

    def hideEvent(self, e):
        super().hideEvent(e)
        self._hover = False
        self.snap_motion()

    def paintEvent(self, _e):
        tok = self._tokens_fn()
        m = self._m
        h = self._fade.value()
        p = QPainter(self)
        try:
            rect = QRectF(self.rect())
            paint_surfaces.paint_cluster(p, rect, tok, m, self.devicePixelRatioF())
            if h > 0.0:
                path = QPainterPath()
                path.addRoundedRect(rect, m.radius, m.radius)
                p.setPen(Qt.NoPen)
                p.fillPath(path, lerp_premul(None, tok["ctl_h"], h))
            # the ⇄ glyph (the mockup's 16-unit swap icon on a 13 px box)
            s = SWAP_GLYPH * m.fs / 16.0
            p.setRenderHint(QPainter.Antialiasing, True)
            p.translate(rect.center())
            p.rotate(self._angle)
            p.scale(s, s)
            p.translate(-8.0, -8.0)
            pen = QPen(lerp_premul(tok["secondary_text"], tok["primary_text"], h), 1.3)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawLine(QPointF(3.0, 5.5), QPointF(12.5, 5.5))
            p.drawPolyline([QPointF(10.0, 3.0), QPointF(12.5, 5.5), QPointF(10.0, 8.0)])
            p.drawLine(QPointF(13.0, 10.5), QPointF(3.5, 10.5))
            p.drawPolyline([QPointF(6.0, 8.0), QPointF(3.5, 10.5), QPointF(6.0, 13.0)])
        finally:
            p.end()


class WellB(TitleWell):
    """Chart B's well: steel stripe, "B", name, meta, ONE CHART, ✕. Empty B:
    a hollow stripe, "B" and the italic hint ("drag a chart onto the right
    frame", else "empty", else nothing — the meta's yield rule)."""

    def __init__(self, metrics: BarMetrics, tokens_fn, parent=None):
        name = ElidedPillButton(metrics, tokens_fn)
        meta = BarTextLabel(metrics, tokens_fn, token_key="muted")
        meta.setObjectName("bar_meta_b")
        close = CloseGlyphButton(metrics, tokens_fn)
        close.setToolTip(t("chart.pair.close_b_tip", "Back to one chart"))
        role = RoleLabel(t("chart.pair.label_b", "B"), metrics, tokens_fn)
        switch = PairSwitch(metrics, tokens_fn)
        switch.set_two(True)
        super().__init__(name, meta, close, metrics, tokens_fn, parent,
                         role_label=role, switch=switch, stripe="hollow")
        self._empty = True
        self.set_empty()

    def is_empty(self) -> bool:
        return self._empty

    def set_chart(self, name: str, full: str, short: str):
        self._empty = False
        self.set_stripe("steel")
        self.name_btn.setText(name or "")
        self.name_btn.show()
        self.meta._style = META_TEXT
        self.meta.set_italic(False)
        self.meta.setText(full or "")
        self.meta.set_short_text(short or "")
        self.refresh_min_width()
        self.updateGeometry()

    def set_empty(self):
        self._empty = True
        self.set_stripe("hollow")
        self.name_btn.setText("")
        self.name_btn.hide()
        self.meta._style = HINT_TEXT
        self.meta.set_italic(True)
        self.meta.setText(t("chart.pair.hint_long", "drag a chart onto the right frame"))
        self.meta.set_short_text(t("chart.pair.hint_short", "empty"))
        self.refresh_min_width()
        self.updateGeometry()


class DropCue(QWidget):
    """"◇ Overlay on <A>": a mouse-transparent label 7 px under the pill,
    a child of the window and never a drop target."""

    def __init__(self, metrics: BarMetrics, tokens_fn, parent=None):
        super().__init__(parent)
        self._m = metrics
        self._tokens_fn = tokens_fn
        self._lead = ""
        self._name = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAcceptDrops(False)
        self.hide()

    def set_text(self, name: str):
        tpl = t("chart.pair.overlay_cue", "Overlay on {a}", a="\x00")
        lead, _, tail = tpl.partition("\x00")
        self._lead, self._name, self._tail = "◇ " + lead, name or "", tail
        fs = self._m.fs
        w = (text_advance(self._lead, *CUE_TEXT, fs=fs)
             + text_advance(self._name, *CUE_NAME, fs=fs)
             + text_advance(self._tail, *CUE_TEXT, fs=fs) + 2 * 10.0 * fs)
        self.setFixedSize(math.ceil(w), round(CUE_H * fs))
        self.update()

    def text(self) -> str:
        return f"{self._lead}{self._name}{getattr(self, '_tail', '')}"

    def paintEvent(self, _e):
        tok = self._tokens_fn()
        fs = self._m.fs
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            path = QPainterPath()
            path.addRoundedRect(r, 6.0 * fs, 6.0 * fs)
            p.fillPath(path, tok["menu_fill"])
            p.setPen(QPen(tok["hair"], 0.5))
            p.drawPath(path)
            x = 10.0 * fs
            for text, style, key in ((self._lead, CUE_TEXT, "secondary_text"),
                                     (self._name, CUE_NAME, "primary_text"),
                                     (getattr(self, "_tail", ""), CUE_TEXT, "secondary_text")):
                if not text:
                    continue
                w = text_advance(text, *style, fs=fs)
                p.setPen(tok[key])
                draw_bar_text(p, QRectF(x, 0, w + 1, self.height()),
                              Qt.AlignLeft | Qt.AlignVCenter, text, *style, fs=fs)
                x += w
        finally:
            p.end()


class PillPair(QWidget):
    """The single well, or ``[well A] [⇄] [well B]`` (SPEC-DUAL-001 §4.1)."""

    toggle_requested = Signal()
    swap_requested = Signal()
    close_b_requested = Signal()

    def __init__(self, well_a: TitleWell, gui, metrics: BarMetrics, tokens_fn,
                 parent=None):
        super().__init__(parent)
        self._gui = gui
        self._m = metrics
        self._tokens_fn = tokens_fn
        self.well_a = well_a
        self.swap = SwapSegment(metrics, tokens_fn)
        self.well_b = WellB(metrics, tokens_fn)
        self._mode = "one"
        self._b = None
        self._level = 0
        self._cue = None
        self.on_pair_changed = None          # the layout controller's hook
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(round(PAIR_GAP * metrics.fs))
        lay.addWidget(well_a, 0)
        lay.addWidget(self.swap, 0)
        lay.addWidget(self.well_b, 0)
        self.swap.hide()
        self.well_b.hide()
        if well_a.role_label is not None:
            well_a.role_label.hide()
        well_a.refresh_min_width()
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setFixedHeight(metrics.ctl_h)
        self.setAcceptDrops(True)
        if well_a.switch is not None:
            well_a.switch.clicked.connect(self.toggle_requested)
        self.well_b.switch.clicked.connect(self.toggle_requested)
        self.swap.clicked.connect(self.swap_requested)
        self.well_b.close_btn.clicked.connect(self.close_b_requested)

    # ------------------------------------------------------------------ state
    def set_mode(self, mode: str, a: dict | None = None, b: dict | None = None):
        """``mode`` "one" | "two"; ``a`` = {"short", "close_tip"} for well A;
        ``b`` = None (empty B) or {"name", "full", "short"}."""
        two = mode == "two"
        a = a or {}
        before = (self._mode, None if self._b is None else tuple(sorted(self._b.items())),
                  self.min_width())
        self._mode = "two" if two else "one"
        self._b = dict(b) if b else None
        wa = self.well_a
        if wa.role_label is not None:
            wa.role_label.setVisible(two)
        if wa.switch is not None:
            wa.switch.set_two(two)
            wa.switch.setVisible(not two)    # mockup: ONE CHART lives at the end of well B
        wa.meta.set_short_text(a.get("short", "") if two else "")
        if two:
            wa.close_btn.setToolTip(a.get("close_tip", ""))
            if self._b is None:
                self.well_b.set_empty()
            else:
                self.well_b.set_chart(self._b.get("name", ""), self._b.get("full", ""),
                                      self._b.get("short", ""))
        self.swap.setVisible(two and self._b is not None)
        self.well_b.setVisible(two)
        if not two:
            self.set_meta_level(0)
        wa.refresh_min_width()
        self.well_b.refresh_min_width()
        self.updateGeometry()
        after = (self._mode, None if self._b is None else tuple(sorted(self._b.items())),
                 self.min_width())
        if after != before and callable(self.on_pair_changed):
            self.on_pair_changed()

    def mode(self) -> str:
        return self._mode

    def is_pair(self) -> bool:
        return self._mode == "two"

    def b_filled(self) -> bool:
        return self._b is not None

    def gap(self) -> int:
        return self.layout().spacing()

    def min_width(self) -> int:
        """The mandatory width (SPEC-DUAL-001 §4.1 bar budget)."""
        if not self.is_pair():
            return self.well_a.min_width()
        w = self.well_a.min_width() + self.gap() + self.well_b.min_width()
        if self._b is not None:
            w += self.gap() + self.swap.width()
        return w

    def natural_width(self, level: int) -> int:
        """Both wells at full names with the given meta level (0 full,
        1 short, 2 none) + ⇄ + gaps: the three-level density's arithmetic."""
        w = self.well_a.natural_width(level) + self.gap() + self.well_b.natural_width(level)
        if self._b is not None:
            w += self.gap() + self.swap.width()
        return w

    def meta_level(self) -> int:
        return self._level

    def set_meta_level(self, level: int):
        """One decision for both wells (D-22f): 0 full, 1 short, 2 names only."""
        self._level = level
        two = self.is_pair()
        for well in (self.well_a, self.well_b):
            well.set_hint_level(level if two else None)
            well.meta.set_level(1 if (two and level == 1) else 0)
        if two:
            self.well_b.meta.setVisible(level < 2 and bool(self.well_b.meta.shown_text()))

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self.layout().setSpacing(round(PAIR_GAP * metrics.fs))
        self.setFixedHeight(metrics.ctl_h)
        if self._cue is not None:
            self._cue._m = metrics

    def sizeHint(self):
        lay = self.layout()
        w, n = 0, 0
        for wd in (self.well_a, self.swap, self.well_b):
            if not wd.isHidden():
                w += wd.sizeHint().width()
                n += 1
        return QSize(w + lay.spacing() * max(0, n - 1), self._m.ctl_h)

    def minimumSizeHint(self):
        return QSize(self.min_width(), self._m.ctl_h)

    # ------------------------------------------------------------ drop (T13)
    def _kind(self, mime):
        from apps.widgets.chart_drop_common import chart_payload_kind
        return chart_payload_kind(mime)

    def _show_cue(self):
        win = self.window()
        if win is None or win is self:
            return
        if self._cue is None or self._cue.parentWidget() is not win:
            self._cue = DropCue(self._m, self._tokens_fn, win)
        self._cue.set_text(self.well_a.name_btn.full_text())
        wa = self.well_a
        bottom = wa.mapTo(win, QPoint(0, wa.height()))
        cx = wa.mapTo(win, QPoint(wa.width() // 2, 0)).x()
        x = max(0, min(win.width() - self._cue.width(), cx - self._cue.width() // 2))
        self._cue.move(x, bottom.y() + round(CUE_OFFSET * self._m.fs))
        self._cue.show()
        self._cue.raise_()

    def _hide_cue(self):
        self.well_a.set_drop_ring(False)
        if self._cue is not None:
            self._cue.hide()

    def cue(self):
        return self._cue

    def dragEnterEvent(self, event):
        if self._kind(event.mimeData()) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.acceptProposedAction()
            self.well_a.set_drop_ring(True)
            self._show_cue()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._kind(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event):
        self._hide_cue()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._hide_cue()
        mime = event.mimeData()
        kind = self._kind(mime)
        if kind is None:
            super().dropEvent(event)
            return
        event.acceptProposedAction()           # INV-8: accept, then refuse
        if kind == "folder":
            try:
                self._gui.statusBar().showMessage(t(
                    "chart.pair.overlay_refuse_folder",
                    "A folder cannot be overlaid. Drop a single chart."), 5000)
            except Exception:
                pass
            return
        mgr = getattr(self._gui, "chart_overlay_manager", None)
        if mgr is not None:
            mgr.handle_drop(mime)

    def hideEvent(self, event):
        self._hide_cue()
        super().hideEvent(event)
