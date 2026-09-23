# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Open retinue details for the clicked chart, independently of ChartGUI state."""
import logging

from PySide6.QtCore import Qt

_LOG = logging.getLogger(__name__)


def show_chart_sector(view, sign_name: str, ring: str, being_type: str) -> None:
    """Use the embedded view's Chart and frame; avastha remains D1 as in main.

    A predictive chart must not borrow the main window's natal summaries.
    Summary calculation is deferred until a click, never a chart redraw.
    """
    from apps.widgets.sector_dialog import SectorInfoDialog
    from AI_tools.AI_main_function.avastha_sign import sign_summaries_all_views

    summaries = None
    if view._chart is not None:
        try:
            summaries = sign_summaries_all_views(
                view._chart, view._aditya_mode, sign_name, ring, being_type)
        except Exception:
            # Match the main dialog's structure-only fallback, with diagnostics.
            _LOG.exception('Could not calculate sector summaries for %s', sign_name)
    dialog = SectorInfoDialog(
        sign_name, focus_ring=ring, focus_type=being_type,
        avastha_summaries=summaries, layer=ring, parent=view.window())
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
        view._is_dragging = False
        view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
