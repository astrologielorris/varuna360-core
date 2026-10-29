# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Where the center drawings show (SPEC-VAC-001 §4.3, SPEC-TJK-003 §4.3): the toggle's
tooltip for a status reason (``toggle_tooltip``), and the notice a press gets while the chart
on screen cannot show the drawing (``with_notice``): the wheel and the North Indian chart,
the Artistic South Indian theme, the Compass. The press still does its work (the drawing is
ON when the South Indian chart comes back); the notice only says where to look."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel

from core.i18n import t

NOTICE_MS = 6000                    # the notice stays this long (a click on it closes it)
NOTICE_NAME = "center_drawing_notice"


def toggle_tooltip(reason: str) -> str:
    """The toggle's tooltip for a status reason (§4.3), both drawings (W6 R4)."""
    draw = t("center_drawing.toggle.draw", "Draw these aspects inside the South Indian chart")
    south_indian = t("center_drawing.toggle.south_indian", "Shown on the South Indian chart")
    return {"shown": draw, "off": draw,
            "time_adjust": t("center_drawing.toggle.time_adjust", "Hidden while adjusting the time"),
            "guide": t("center_drawing.toggle.guide", "Hidden while the Ascendant Guide is shown"),
            "no_chart": t("center_drawing.toggle.no_chart", "Shown when a chart is open"),
            "varga": t("center_drawing.toggle.varga", "Shown on the D1 chart"),
            "compass": south_indian, "not_vector": south_indian}.get(reason, draw)


def notice_text(reason: str, on_south_indian: bool):
    """The notice for a press under ``reason``, or None when the drawing can show
    (``on_south_indian``: the main chart on screen is the South Indian one)."""
    if reason == "compass":
        return t("center_drawing.notice.compass",
                 "These aspects are hidden while the South Indian Compass is shown. "
                 "Turn the Compass off to see them.")
    if reason != "not_vector":
        return None
    if on_south_indian:
        return t("center_drawing.notice.artistic",
                 "These aspects are drawn only in the Conventional South Indian theme. "
                 "Switch the South Indian theme to Conventional (vector) to see them.")
    return t("center_drawing.notice.south_indian",
             "These aspects are drawn only inside the South Indian chart. They are not "
             "available on the wheel or the North Indian chart: switch to the South Indian "
             "chart to see them.")


def elsewhere_notice(controller):
    """The notice text while ``controller``'s drawing is ON and the chart on screen cannot
    show it, else None."""
    from apps.widgets.panel_controllers.center_drawing_controller import main_host
    if not (controller.state.on and controller.in_mode()):
        return None
    gui = controller._gui
    stack = getattr(gui, "chart_stack", None)
    host = main_host(gui)
    on_south_indian = host is not None and (stack is None or stack.currentWidget() is host)
    return notice_text(controller.reason(), on_south_indian)


def show_notice(table, text: str) -> QLabel:
    """``text`` in a themed note over the top of ``table``, for ``NOTICE_MS`` (one per table:
    a second press replaces the text and restarts the time)."""
    from ui.accent_ink import on_accent_ink
    from ui.qt_theme import get_theme_colors, scaled_area_px
    note = table.findChild(QLabel, NOTICE_NAME)
    if note is None:
        note = QLabel(table)
        note.setObjectName(NOTICE_NAME)
        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.mousePressEvent = lambda _e, n=note: n.hide()
        timer = QTimer(note)
        timer.setObjectName(NOTICE_NAME + "_timer")
        timer.setSingleShot(True)
        timer.timeout.connect(note.hide)
    fill = get_theme_colors()["primary"]
    note.setStyleSheet(f"QLabel#{NOTICE_NAME} {{ background-color: {fill}; "
                       f"color: {on_accent_ink(fill)}; border-radius: 6px; padding: 8px 12px; "
                       f"font-size: {scaled_area_px('tables')}px; font-weight: bold; }}")
    note.setText(text)
    width = max(120, table.width() - 24)
    note.setFixedWidth(width)
    note.adjustSize()
    note.move((table.width() - width) // 2, max(4, table.height() // 5))
    note.show()
    note.raise_()
    note.findChild(QTimer, NOTICE_NAME + "_timer").start(NOTICE_MS)
    return note


def with_notice(controller):
    """``controller``'s panel actions for ``CenterPanelWidgets.build`` (toggle, press, rail
    moved, tour), the notice after the toggle, a key press and the tour key (never the rail:
    a drag would flash it)."""
    def noticed(action):
        def run(*args):
            result = action(*args)
            text = elsewhere_notice(controller)
            table = getattr(controller._gui, controller.TABLE, None)
            if text and table is not None:
                show_notice(table, text)
            return result
        return run
    return (noticed(controller.toggle), noticed(controller.press), controller._rail_moved,
            noticed(controller.tour))
