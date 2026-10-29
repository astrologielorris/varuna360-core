# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Open retinue details for the clicked chart, independently of ChartGUI state."""
import logging
from functools import partial

from PySide6.QtCore import Qt

_LOG = logging.getLogger(__name__)


def show_chart_sector(view, sign_name: str, ring: str, being_type: str) -> None:
    """Use the embedded view's Chart and frame; avastha remains D1 as in main.

    A predictive chart must not borrow the main window's natal summaries.
    Summary calculation is deferred until a click, never a chart redraw.
    """
    from apps.widgets.sector_dialog import SectorInfoDialog
    from apps.widgets.sector_popup_follow import follow_duc_method, sector_summaries
    compute = partial(sector_summaries, view._chart, view._aditya_mode, sign_name, ring,
                      being_type)       # by the DUC Bala method (SPEC-STR-001 §7.5)
    summaries = None
    if view._chart is not None:
        try:
            summaries = compute()
        except Exception:
            # Match the main dialog's structure-only fallback, with diagnostics.
            _LOG.exception('Could not calculate sector summaries for %s', sign_name)
    dialog = SectorInfoDialog(
        sign_name, focus_ring=ring, focus_type=being_type,
        avastha_summaries=summaries, layer=ring, parent=view.window())
    follow_duc_method(dialog, compute)          # an open popup follows a method change
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
        view._is_dragging = False
        view.viewport().setCursor(Qt.CursorShape.ArrowCursor)
