# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The 60 px memory pane strip (MC-INTENT "Memory pane strip").

Action-bar surface (bar-a -> bar-b gradient, 0.5 px top gloss); left the chip
tray (stretch), then a 0.5 px hairline 38 px tall fading at both ends, then
ONE unit of three 52 px blocks, right-aligned: [profile well] [D-pad]
[2x2 actions]. The window width picks the step (resizeEvent) and the step is
applied as one set of geometry changes; nothing is ever hidden except the
three secondary actions at S3, which then live in the ⋯ menu.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from apps.widgets.action_bar.paint_surfaces import draw_hline, hairline_width, snap_to_device

from .actions import MARGIN, ActionPills
from .chip import CHIP_W
from .paint import area_factor, dpr_of
from .steps import S0, Step, step_for_width
from .tokens import pane_tokens
from .tray import ChipTray
from .well import WELL_H, ProfileWell

STRIP_H = 60
PAD_L, PAD_R = 8, 10
ZONE_GAP = 10
SEP_H = 38
PAD_W, PAD_H = 77, 52          # the D-pad at 0.9 scale (85 x 58 design)


class MemoryPaneStrip(QWidget):
    """Owns geometry only; ChartMemoryPanel wires the behaviour."""

    step_changed = Signal(object)

    def __init__(self, nav_pad: QWidget, parent=None):
        super().__init__(parent)
        self.setObjectName("memoryPaneStrip")
        self.setFixedHeight(STRIP_H)
        self.tray = ChipTray(self)
        self.well = ProfileWell(self)
        self.nav_pad = nav_pad
        nav_pad.setParent(self)
        nav_pad.setFixedSize(PAD_W, PAD_H)
        self.actions = ActionPills(self)
        self.step: Step = S0
        self._sep_x = 0.0
        self._width_override = None
        self.apply_step(S0, force=True)

    # -- steps --------------------------------------------------------------

    def reference_width(self) -> int:
        """The window width that picks the step (the pane spans the window)."""
        if self._width_override is not None:
            return self._width_override
        win = self.window()
        if win is not None and win is not self and win.width() > 0:
            return win.width()
        return self.width()

    def set_width_override(self, width):
        """Tests and captures: pick the step from ``width`` instead."""
        self._width_override = width
        self.apply_step(step_for_width(self.reference_width()))

    def apply_step(self, step: Step, force: bool = False):
        changed = step != self.step
        self.step = step
        g = max(1.0, area_factor("buttons"))
        self.well.setFixedWidth(round(step.well_w * g))
        self.well.set_compact(step.well_compact)
        self.actions.apply_step(round(step.col1 * g), round(step.col2 * g), step.labels)
        self.tray.set_chip_width(round(CHIP_W * max(1.0, area_factor("chart_memory"))))
        self._layout()
        if changed or force:
            self.step_changed.emit(step)

    def controls_width(self) -> int:
        """Width of the right-hand unit (well + D-pad + actions + gaps)."""
        acts = self.actions.width() - 2 * MARGIN
        return self.well.width() + self.step.unit_gap * 2 + PAD_W + acts

    def _layout(self):
        w = self.width()
        top = (STRIP_H - WELL_H) // 2
        gap = self.step.unit_gap
        right = w - PAD_R
        ax = right - (self.actions.width() - MARGIN)
        self.actions.move(ax, top - MARGIN)
        px = ax + MARGIN - gap - PAD_W
        self.nav_pad.move(px, top)
        wx = px - gap - self.well.width()
        self.well.move(wx, top)
        self._sep_x = wx - ZONE_GAP - 0.5
        tray_w = max(0, int(self._sep_x - ZONE_GAP - PAD_L))
        self.tray.setGeometry(PAD_L, top, tray_w, self.tray.height())
        self.update()

    def resizeEvent(self, e):
        step = step_for_width(self.reference_width())
        if step != self.step:
            self.apply_step(step)
        else:
            self._layout()
        super().resizeEvent(e)

    # -- paint --------------------------------------------------------------

    def paintEvent(self, _e):
        tok = pane_tokens()
        dpr = dpr_of(self)
        p = QPainter(self)
        r = QRectF(self.rect())
        p.fillRect(r, tok["secondary"])
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0.0, tok["bar_a"])
        g.setColorAt(1.0, tok["bar_b"])
        p.fillRect(r, g)
        draw_hline(p, 0.0, 0.0, r.width(), tok["bar_gloss"], dpr)
        # the separator: a 0.5 px element hairline fading at both ends
        x = snap_to_device(p, self._sep_x, dpr, False)
        y0 = (STRIP_H - SEP_H) / 2.0
        hair = tok["hair"]
        clear = QColor(hair)
        clear.setAlphaF(0.0)
        sg = QLinearGradient(x, y0, x, y0 + SEP_H)
        sg.setColorAt(0.0, clear)
        sg.setColorAt(0.2, hair)
        sg.setColorAt(0.8, hair)
        sg.setColorAt(1.0, clear)
        p.fillRect(QRectF(x, y0, hairline_width(dpr), SEP_H), sg)
        p.end()
