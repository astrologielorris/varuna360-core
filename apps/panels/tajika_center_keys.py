# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The Aspects T controls of the Tajika center drawing (SPEC-TJK-003 §4.4).

- ``TajikaKeyHeader``: both headers of the Tajika matrix become compact keycaps of the
  Strength family; a body's row key and column key are one state (the lit set).
- ``VirupaRail``: the "Min. virupas" groove under the matrix, one tick per aspect.
- ``TajikaCenterToggle``: the woven-square header button after the Vedic/Tajika swap.
- ``TajikaTourKey``: "Tour" at the right end of the rail row (§4.9).
- ``TajikaCellRing``: the tour's ring around the current aspect's matrix cells.

The widgets are the shared ones of ``center_drawing_keys`` (SPEC-VAC-001 §4.0) with the
Tajika body set, labels and texts. Widgets only: the state lives in
``TajikaCenterController``; a key press calls ``on_key(body)``, the rail emits
``valueChanged(int)``.
"""
from __future__ import annotations

from functools import partial

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QPainterPath

from AI_tools.AI_main_function.tajika import TAJIKA_PLANETS
from apps.panels import center_drawing_keys as cdk
from apps.panels.table_metrics import column_header_height, table_row_height
from apps.panels.center_drawing_keys import KEY_RADIUS, RAIL_MAX, STRONG_NOTCH  # noqa: F401
from apps.widgets.south_indian_tajika_center import EXTRA_DISC, SHORT


body_disc = partial(cdk.body_disc, extra=EXTRA_DISC)   # the Strength palette, then EXTRA_DISC


_column_header_height = column_header_height                   # the panel's compact header
_row_height = partial(table_row_height, "tables", 11, 20)        # the Aspects T matrix rows


# ------------------------------------------------------------------ planet keys
class TajikaKeyHeader(cdk.PlanetKeyHeader):
    """A matrix header (either orientation) whose sections are compact planet keys."""

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, TAJIKA_PLANETS, SHORT, body_disc,
                         (_column_header_height, _row_height), parent)
        self.setObjectName("tajika_key_header")


def install_key_headers(table):
    """Give the matrix its two key headers; returns (horizontal, vertical)."""
    return cdk.install_key_headers(table, TajikaKeyHeader)


# ------------------------------------------------------------------ virupa rail
class VirupaRail(cdk.VirupaRail):
    """Min. virupas 0-60 under the Tajika matrix: one tick per aspect in its category
    colour (the shared rail)."""

    def __init__(self, parent=None):
        super().__init__("Min. virupas", "88 / 88", parent)
        self.setObjectName("tajika_virupa_rail")
        self.setToolTip("Aspects weaker than this are left out of the center drawing")


# ------------------------------------------------------------------ tour key
class TajikaTourKey(cdk.TourKey):
    """The "Tour" key at the right end of the rail row (§4.9)."""

    TOOLTIPS = ("Show the aspects one by one", "Stop the tour")

    def __init__(self, parent=None):
        super().__init__("Tour", self.TOOLTIPS, parent)
        self.setObjectName("tajika_tour_key")


class TajikaCellRing(cdk.CellMarks):
    """The tour's mark on the Tajika matrix (§4.9): an accent ring around the current
    aspect's two cells (the shared cell marks, no lane tint)."""

    def __init__(self, table):
        super().__init__(table)
        self.setObjectName("tajika_tour_cell_ring")


# ------------------------------------------------------------------ toggle
def paint_woven_square(p: QPainter, sq: QRectF, fs: float):
    """The Tajika glyph: a rounded square with two threads woven across it, over and
    under."""
    p.drawRoundedRect(sq, 3.5 * fs, 3.5 * fs)
    k = sq.width() / 14.0
    for (ax, ay, cx, cy, bx, by) in ((2, 10, 6, 1, 12, 5), (2, 4, 8, 13, 12, 9)):
        path = QPainterPath()
        path.moveTo(sq.left() + ax * k, sq.top() + ay * k)
        path.quadTo(sq.left() + cx * k, sq.top() + cy * k, sq.left() + bx * k, sq.top() + by * k)
        p.drawPath(path)


class TajikaCenterToggle(cdk.CenterToggle):
    """The woven-square button: OFF grey, ON in the theme accent with a small lit dot."""

    def __init__(self, parent=None):
        super().__init__(paint_woven_square, parent)
