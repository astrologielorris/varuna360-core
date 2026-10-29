# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The one dignity overlay pass of a chart view (SPEC-DIG-001, td-m6xyo).

Each view kind (South Indian vector, classic South Indian, wheel) spells its
recipe once, as a module function next to its draw code, and that function runs
both after a rebuild and on a DIGNITY toggle (``dignity_overlay_refresh``), so
the two can never draw different sizes (R1 review F3, 2026-10-13). The
off-screen centre-box mini chart is marked once by its factory and never
decorated (INV-4).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt

from apps.widgets.dignity_overlay_items import dignity_scene

_log = logging.getLogger(__name__)
# Qt dynamic property of the centre-box mini (no Python field on the view class)
CENTRE_MINI = "dig_centre_mini"


def as_centre_mini(view):
    """Make ``view`` an off-screen centre-box mini chart: never shown on screen,
    never decorated with the dignity overlay. Returns ``view``."""
    view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    view.setProperty(CENTRE_MINI, True)
    return view


def view_pass(view, planet_type, r_ref, wheel=False, get=None):
    """THE overlay pass of one chart view. Nothing on a centre-box mini
    (INV-4). An engine error leaves the planets bare and is logged, never
    silent. Returns the planets decorated."""
    if view.property(CENTRE_MINI):
        return 0
    try:
        return dignity_scene(view.scene, view._chart, view._varga_code, planet_type,
                             r_ref, wheel, get)
    except Exception:
        _log.exception("dignity overlay pass failed on %s (varga %r)",
                       type(view).__name__, getattr(view, "_varga_code", None))
        return 0
