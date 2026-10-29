# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The info rail and the info drawer of two-chart mode (SPEC-DUAL-001 §4.3).

``InfoRail`` is the 36 px bar-styled strip at the right edge of the Chart tab
row while two charts are shown: the bar gradient, a hairline, a left chevron
and the info frames' titles written bottom-to-top. A click toggles the drawer.

``InfoDrawerHost`` floats over chart B at the rail's left edge and holds the
sign-selector column and the info column (today's widgets, reparented once per
mode entry by ChartLayoutManager). It paints a soft shadow on its left edge and
slides in from the right. Both read their colors from ``bar_tokens()`` /
``get_theme_colors()`` at paint time (Rule 20, no stored stylesheet, no
graphics effect).
"""
from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, QPoint, QPointF, QRect, QRectF, Qt,
                            QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ui.qt_theme import bar_tokens, scaled_px

RAIL_BASE = 36
SLIDE_MS = 200
SHADOW_BASE = 14


def _reduce_motion() -> bool:
    try:
        from managers.settings_manager import get_settings
        return bool(get_settings().get("ui.reduce_motion"))
    except Exception:
        return False


class InfoRail(QWidget):
    """36 px rail; ``clicked`` toggles the info drawer."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels = []
        self._hover = False
        self._offset = 0.0               # slide-in offset (px to the right)
        self._anim = None
        self._gen = 0
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(scaled_px(RAIL_BASE))

    # ---------------------------------------------------------------- API
    def set_labels(self, labels) -> None:
        self._labels = [str(x).upper() for x in labels]
        self.update()

    def labels(self):
        return list(self._labels)

    def refresh_theme(self) -> None:
        self.setFixedWidth(scaled_px(RAIL_BASE))
        self.update()

    def slide_in(self) -> None:
        """Show with a 200 ms slide from the right (0 ms with reduce motion)."""
        self.stop_slide()
        self.show()
        ms = 0 if _reduce_motion() else SLIDE_MS
        if ms == 0:
            self._offset = 0.0
            self.update()
            return
        self._gen += 1
        gen = self._gen
        anim = QVariantAnimation(self)
        anim.setStartValue(float(self.width()))
        anim.setEndValue(0.0)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def frame(v, gen=gen):
            if gen == self._gen:
                self._offset = float(v)
                self.update()
        anim.valueChanged.connect(frame)
        anim.finished.connect(lambda gen=gen: self._slide_done(gen))
        self._anim = anim
        self._offset = float(self.width())
        anim.start()

    def _slide_done(self, gen) -> None:
        if gen != self._gen:
            return                       # a late callback of a stopped slide
        anim, self._anim = self._anim, None
        self._offset = 0.0
        if anim is not None:
            anim.deleteLater()
        self.update()

    def stop_slide(self) -> None:
        """Settle: jump to the end state; a late ``finished`` is a no-op."""
        self._gen += 1
        anim, self._anim = self._anim, None
        if anim is not None:
            anim.stop()
            anim.deleteLater()
        self._offset = 0.0
        self.update()

    def sliding(self) -> bool:
        return self._anim is not None

    # --------------------------------------------------------------- events
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mousePressEvent(self, event):
        event.accept()                   # the drawer's outside-press filter skips the rail

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        tok = bar_tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.translate(self._offset, 0)
        r = QRectF(self.rect()).adjusted(0.25, 0.25, -0.25, -0.25)
        rad = scaled_px(6)
        path = QPainterPath()
        path.moveTo(r.right(), r.top())
        path.lineTo(r.left() + rad, r.top())
        path.quadTo(r.left(), r.top(), r.left(), r.top() + rad)
        path.lineTo(r.left(), r.bottom() - rad)
        path.quadTo(r.left(), r.bottom(), r.left() + rad, r.bottom())
        path.lineTo(r.right(), r.bottom())
        path.closeSubpath()
        p.fillPath(path, tok["canvas_core"])
        grad = QLinearGradient(r.topLeft(), r.topRight())
        grad.setColorAt(0.0, tok["bar_a"])
        grad.setColorAt(1.0, tok["bar_b"])
        p.fillPath(path, grad)
        if self._hover:                  # hover lightens (mockup #rail:hover)
            hv = QColor(tok["ctl_h"])
            hv.setAlpha(int(hv.alpha() * 0.6))
            p.fillPath(path, hv)
        pen = QPen(tok["hair"], 0.5)
        p.setPen(pen)
        p.drawPath(path)

        # chevron (points left: "open the panels")
        muted = tok["muted"]
        cx, top = r.center().x(), r.top() + scaled_px(8)
        s = scaled_px(12) / 12.0
        cp = QPen(muted, 1.4 * s)
        cp.setCapStyle(Qt.PenCapStyle.RoundCap)
        cp.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(cp)
        ox, oy = cx - 6 * s, top + 3 * s
        p.drawPolyline([QPointF(ox + 7.4 * s, oy + 0), QPointF(ox + 4.4 * s, oy + 3 * s),
                        QPointF(ox + 7.4 * s, oy + 6 * s)])

        # labels bottom-to-top, top-aligned under the chevron
        f = QFont(self.font())
        f.setPixelSize(scaled_px(11))
        f.setWeight(QFont.Weight(560))
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.9)
        p.setFont(f)
        fm = p.fontMetrics()
        pad = scaled_px(12)
        y = top + scaled_px(18)
        for i, text in enumerate(self._labels):
            w = fm.horizontalAdvance(text)
            h = w + 2 * pad
            p.save()
            p.translate(cx, y + h / 2.0)
            p.rotate(-90)
            p.setPen(tok["secondary_text"])
            p.drawText(QRectF(-h / 2.0, -fm.height() / 2.0, h, fm.height()),
                       Qt.AlignmentFlag.AlignCenter, text)
            p.restore()
            y += h
            if i < len(self._labels) - 1:
                p.setPen(QPen(tok["hair_soft"], 1))
                p.drawLine(QPointF(r.left() + scaled_px(6), y), QPointF(r.right() - scaled_px(6), y))
        p.end()


class InfoDrawerHost(QWidget):
    """The floating drawer that holds the sign column + info column."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._open = False
        self._anim = None
        self._gen = 0
        self._target = QRect()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(scaled_px(SHADOW_BASE), 0, 0, 0)
        lay.setSpacing(5)
        self.hide()

    def content_layout(self) -> QHBoxLayout:
        return self.layout()

    def shadow_width(self) -> int:
        return scaled_px(SHADOW_BASE)

    def set_target_geometry(self, rect: QRect) -> None:
        """The open geometry (its right edge touches the rail)."""
        self._target = QRect(rect)
        if self._open and self._anim is None:
            self.setGeometry(self._target)

    def target_geometry(self) -> QRect:
        return QRect(self._target)

    def is_open(self) -> bool:
        return self._open

    def open(self, animated: bool = True) -> None:
        self.stop()
        self._open = True
        self.setGeometry(self._target)
        self.show()
        self.raise_()
        ms = 0 if (not animated or _reduce_motion()) else SLIDE_MS
        if ms == 0:
            return
        self._gen += 1
        gen = self._gen
        start = self._target.topLeft() + QPoint(scaled_px(24), 0)
        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(self._target.topLeft())
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v, gen=gen: gen == self._gen and self.move(v))
        anim.finished.connect(lambda gen=gen: self._done(gen))
        self._anim = anim
        self.move(start)
        anim.start()

    def close(self, animated: bool = False) -> bool:     # noqa: D401 (QWidget.close shadow)
        """Close the drawer (instant by default: Esc / outside press)."""
        self.stop()
        self._open = False
        self.hide()
        return True

    def _done(self, gen) -> None:
        if gen != self._gen:
            return
        anim, self._anim = self._anim, None
        if anim is not None:
            anim.deleteLater()
        if self._open:
            self.setGeometry(self._target)

    def stop(self) -> None:
        """Settle any running slide at its end state (late callbacks disarmed)."""
        self._gen += 1
        anim, self._anim = self._anim, None
        if anim is not None:
            anim.stop()
            anim.deleteLater()
        if self._open:
            self.setGeometry(self._target)

    def paintEvent(self, _event):
        tok = bar_tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        sw = self.shadow_width()
        body = QRectF(sw, 0, self.width() - sw, self.height())
        # soft shadow on the left edge (-14 px, mockup: -14px 0 34px -12px)
        g = QLinearGradient(QPointF(0, 0), QPointF(sw, 0))
        c0 = QColor(tok["menu_drop"])
        c0.setAlpha(0)
        c1 = QColor(tok["menu_drop"])
        c1.setAlpha(int(c1.alpha() * 0.45))
        g.setColorAt(0.0, c0)
        g.setColorAt(1.0, c1)
        p.fillRect(QRectF(0, scaled_px(6), sw, self.height() - scaled_px(12)), g)
        bg = self.parentWidget().palette().color(self.parentWidget().backgroundRole()) \
            if self.parentWidget() is not None else tok["secondary"]
        path = QPainterPath()
        path.addRoundedRect(body, scaled_px(6), scaled_px(6))
        p.fillPath(path, bg)
        p.setPen(QPen(tok["hair"], 0.5))
        p.drawPath(path)
        p.end()
