# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The AI button (SPEC-COACH-001 §4.7, MC-INTENT 11): one pill in the status
bar where the six AI pills were. A gradient from the theme's primary to
primary_dark, a sparkle and a bold "AI"; its "on" ring (primary_light, a
soft primary glow) shows while the hub is open or a coach story runs. A
short glow pulse when the closing hub lands in it."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton

from apps.ai_hub import icons, words

BUTTON_NAME = "aiHubButton"
PULSE_S = 0.7
GLOW = 4                        # px kept around the pill for the ring and glow


def _alpha(color: QColor, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


class AIButton(QAbstractButton):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName(BUTTON_NAME)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(words.BUTTON_TIP)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hub_open = False
        self.story_running = False
        self._pulse_at = 0.0
        self._pulse = QTimer(self)
        self._pulse.setInterval(16)
        self._pulse.timeout.connect(self._pulse_tick)
        self.refresh_theme()

    # ------------------------------------------------------------ state

    @property
    def on(self) -> bool:
        return self.hub_open or self.story_running

    def set_hub_open(self, on: bool) -> None:
        self.hub_open = bool(on)
        self.update()

    def set_story_running(self, on: bool) -> None:
        self.story_running = bool(on)
        self.update()

    def pulse(self) -> None:
        """The closing hub landed in the button."""
        self._pulse_at = time.monotonic()
        self._pulse.start()

    def _pulse_tick(self) -> None:
        if time.monotonic() - self._pulse_at > PULSE_S:
            self._pulse.stop()
        self.update()

    # ------------------------------------------------------------ size

    def _font(self) -> QFont:
        # the status bar's caption size, as the pills it replaces
        from ui.qt_theme import scaled_tier_size
        f = QFont("Inter")
        f.setPixelSize(max(7, scaled_tier_size(11.0, "status")))
        f.setWeight(QFont.Weight.Bold)
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 104)
        return f

    def _pill_height(self) -> int:
        return QFontMetrics(self._font()).height() + 8

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self._font())
        h = self._pill_height()
        w = int(h * 0.38) + int(h * 0.6) + 6 + fm.horizontalAdvance(words.BUTTON) + int(h * 0.5)
        return QSize(w + 2 * GLOW, h + 2 * GLOW)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def refresh_theme(self) -> None:
        self.setFixedSize(self.sizeHint())
        self.updateGeometry()
        self.update()

    # ------------------------------------------------------------ paint

    def paintEvent(self, _event) -> None:
        from ui.qt_theme import get_theme_colors
        c = get_theme_colors()
        primary, dark = QColor(c["primary"]), QColor(c["primary_dark"])
        from ui.accent_ink import on_accent_ink
        light, ink = QColor(c["primary_light"]), QColor(on_accent_ink(c["primary"]))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rect = QRectF(self.rect()).adjusted(GLOW, GLOW, -GLOW, -GLOW)
        r = rect.height() / 2
        pulse = 0.0
        if self._pulse.isActive():
            t = (time.monotonic() - self._pulse_at) / PULSE_S
            pulse = max(0.0, 1.0 - t) * (1.0 if t > 0.15 else t / 0.15)
        glow = max(0.6 if self.on else 0.0, pulse)
        if glow > 0:
            for i in range(GLOW, 0, -1):
                p.setPen(QPen(_alpha(primary, 0.16 * glow * (GLOW - i + 1) / GLOW), 1))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(rect.adjusted(-i, -i, i, i), r + i, r + i)
        fill = QLinearGradient(rect.topLeft(), rect.bottomRight())
        lift = 0.12 if self.underMouse() else 0.0
        fill.setColorAt(0, primary.lighter(int(100 + 100 * lift)))
        fill.setColorAt(1, dark)
        p.setPen(QPen(_alpha(QColor("#FFFFFF"), 0.08), 1))
        p.setBrush(fill)
        p.drawRoundedRect(rect, r, r)
        if self.on:
            p.setPen(QPen(light, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), r + 1, r + 1)
        h = rect.height()
        icon = QRectF(rect.left() + h * 0.38, rect.center().y() - h * 0.3, h * 0.6, h * 0.6)
        QSvgRenderer(icons.icon_svg(icons.SPARKLE, ink.name(), filled=True)).render(p, icon)
        p.setFont(self._font())
        p.setPen(ink)
        text = QRectF(icon.right() + 6, rect.top(), rect.right() - icon.right() - 6, h)
        p.drawText(text, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   words.BUTTON)
        p.end()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)
