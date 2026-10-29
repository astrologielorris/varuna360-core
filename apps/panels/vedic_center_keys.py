# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The Aspects V controls of the Vedic center drawing (SPEC-VAC-001 §3.5, §4.4).

- ``VedicKeyHeader``: both headers of the Aspects V matrix become compact keycaps of the
  Strength family BY ROLE (D-3): the row keys are casters (what a planet casts), the
  column keys receivers (what a body receives); a press reports ``(role, body)``.
- ``VedicVirupaRail``: the "Min. virupas" groove under the matrix, one tick per cast.
- ``VedicCenterToggle``: the lens-and-ray header button after the Vedic/Tajika swap.
- ``VedicTourKey``: "Tour" at the right end of the rail row.
- ``VedicCellMarks``: the lane tint of the lit keys and the tour's ring, plus the matrix
  cell tooltips (``CellTips``, an event filter on the table's viewport).
- ``VedicPanelData``: the controller's current model for the panel (the matrix's own
  data, INV-4): counts, rail ticks and every panel tooltip.

The widgets are the shared ones of ``center_drawing_keys`` with the Vedic body sets,
labels and texts (``core.i18n.t``, the ``center_drawing`` catalog, D-9). Widgets only:
the state lives in ``VedicCenterController``. The header ITEMS keep their texts
(``☉Su ... ♄Sa*``, ``Su ... Ke``) for the popup, the capture and the tests; the keycaps
paint their own labels.
"""
from __future__ import annotations

from functools import partial
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip

from AI_tools.analysis.AI_aspects import SPECIAL_ASPECT_PLANETS
from apps.panels import center_drawing_keys as cdk
from apps.panels.table_metrics import column_header_height, table_row_height
from apps.widgets.south_indian_vedic_center import NODE_HUE, RAIL_BANDS
from core import vedic_center as vc
from core import vedic_center_text as vt
from core.i18n import t

CASTER, RECEIVER = "caster", "receiver"        # the two key roles (D-3)


body_disc = partial(cdk.body_disc, default=NODE_HUE)    # the Strength palette; nodes pewter


_column_header_height = column_header_height                   # the panel's compact header
_row_height = partial(table_row_height, "tables", 15, 24)        # the Aspects V matrix rows


def band_colour(virupas: float) -> str:
    """A rail tick's strength band (§3.6): S >= 45, A 30-45, B 15-30, C < 15."""
    return next((colour for low, colour in RAIL_BANDS if virupas >= low), RAIL_BANDS[-1][1])


def key_labels(vertical: bool) -> dict:
    """The keycap labels: the body code; a row (caster) key keeps the matrix's "*" of
    the planets with special aspects (MA*, JU*, SA*)."""
    bodies = vc.CASTERS if vertical else vc.BODY_ORDER
    mark = "*" if vertical else ""
    return {b: vc.CODE_OF[b] + (mark if b in SPECIAL_ASPECT_PLANETS else "") for b in bodies}


def ring_cells(key) -> list:
    """The matrix cells of a tour step (§4.6): a cast's one cell (caster row, receiver
    column), or every Y cell of a Yuti (one when a node is in it)."""
    if not key:
        return []
    if key[0] == "cast":
        return [(vc.CASTERS.index(key[1]), vc.BODY_ORDER.index(key[2]))]
    a, b = sorted(key[1], key=vc.BODY_ORDER.index)
    return [(vc.CASTERS.index(r), vc.BODY_ORDER.index(c))
            for r, c in ((a, b), (b, a)) if r in vc.CASTERS]


# ------------------------------------------------------------------ the panel's model
class VedicPanelData:
    """The controller's current full model (``vedic_full_model`` of the active chart) for
    the panel: counts, rail ticks and the key, cell and tick tooltips. ``sign_name(index)``
    names a sign in the chart's frame (``displayed_sign_name``)."""

    def __init__(self, sign_name: Callable[[int], str]):
        self._sign_name = sign_name
        self.full = None
        self._casts = {}
        self._yutis = {}

    def set_full(self, full):
        self.full = full
        self._casts = {(c.caster, c.receiver): c for c in full.casts} if full else {}
        self._yutis = {frozenset((y.a, y.b)): y for y in full.yutis} if full else {}

    def counts(self, min_virupas, casters, receivers):
        """(shown, total) casts, as ``vedic_center.select`` would draw them."""
        if self.full is None:
            return 0, 0
        lit = bool(casters or receivers)
        shown = sum(1 for c in self.full.casts if c.virupas >= min_virupas
                    and (not lit or c.touches(casters, receivers)))
        return shown, self.full.total

    def ticks(self):
        """(virupas, band colour) per cast, strongest first (the rail's tick order)."""
        return [(c.virupas, band_colour(c.virupas)) for c in self.full.casts] if self.full else []

    def tick_text(self, index: int) -> str:
        casts = self.full.casts if self.full else ()
        return cast_text(casts[index]) if 0 <= index < len(casts) else ""

    def cell_text(self, row: int, column: int) -> str:
        """The tooltip of a matrix cell: its cast, its Yuti, or nothing."""
        if not (0 <= row < len(vc.CASTERS) and 0 <= column < len(vc.BODY_ORDER)):
            return ""
        caster, receiver = vc.CASTERS[row], vc.BODY_ORDER[column]
        yuti = self._yutis.get(frozenset((caster, receiver)))
        if yuti is not None and caster != receiver:
            return " · ".join((vt.yuti_title(yuti, self._sign_name),
                               t("center_drawing.vedic.yuti_word", "yuti")))
        cast = self._casts.get((caster, receiver))
        return cast_text(cast) if cast is not None else ""

    def key_text(self, role: str, body: Optional[str]) -> str:
        """A key's tooltip: what the key draws and how many casts that is."""
        if not body:
            return ""
        if role == CASTER:
            count = sum(1 for c in self._casts.values() if c.caster == body)
            return t("center_drawing.vedic.key_caster",
                     {"one": "{body} as caster: draw what {body} casts ({count} cast)",
                      "other": "{body} as caster: draw what {body} casts ({count} casts)"},
                     body=body, count=count)
        count = sum(1 for c in self._casts.values() if c.receiver == body)
        return t("center_drawing.vedic.key_receiver",
                 {"one": "{body} as receiver: draw what {body} receives ({count} cast)",
                  "other": "{body} as receiver: draw what {body} receives ({count} casts)"},
                 body=body, count=count)


def cast_text(cast) -> str:
    """"Saturn casts on Jupiter · 58.1 virupas · strong" (+ " · special aspect (3rd
    house)"): the matrix cell and rail tick tooltip."""
    return " · ".join((vt.cast_title(cast), vt.cast_detail(cast)))


# ------------------------------------------------------------------ planet keys
class VedicKeyHeader(cdk.PlanetKeyHeader):
    """A matrix header whose keys have a role: the vertical header's keys are casters,
    the horizontal header's receivers. ``on_key`` receives ``(role, body)``; a hover
    names what the key draws (``texts.key_text``)."""

    def __init__(self, orientation, texts: VedicPanelData, parent=None):
        vertical = orientation == Qt.Orientation.Vertical
        super().__init__(orientation, vc.CASTERS if vertical else vc.BODY_ORDER,
                         key_labels(vertical), body_disc,
                         (_column_header_height, _row_height), parent)
        self.role = CASTER if vertical else RECEIVER
        self._texts = texts
        self.setObjectName("vedic_key_header")

    @property
    def on_key(self):
        press = self._press
        return None if press is None else (lambda body: press((self.role, body)))

    @on_key.setter
    def on_key(self, press):
        self._press = press

    def viewportEvent(self, e):
        if e.type() == QEvent.Type.ToolTip:
            text = self._texts.key_text(self.role, self.body(self.logicalIndexAt(e.pos())))
            if text:
                QToolTip.showText(e.globalPos(), text, self.viewport())
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().viewportEvent(e)


def install_key_headers(table, texts: VedicPanelData):
    """Give the Aspects V matrix its receiver keys (columns) and caster keys (rows);
    returns (horizontal, vertical)."""
    return cdk.install_key_headers(
        table, lambda orientation, parent: VedicKeyHeader(orientation, texts, parent))


# ------------------------------------------------------------------ virupa rail, tour key
class VedicVirupaRail(cdk.VirupaRail):
    """Min. virupas 0-60 under the Aspects V matrix: one tick per cast in its strength
    band colour (the shared rail); a tick names its cast."""

    def __init__(self, parent=None):
        super().__init__(t("center_drawing.rail.label", "Min. virupas"), "88 / 88", parent)
        self.setObjectName("vedic_virupa_rail")
        self.setToolTip(t("center_drawing.vedic.rail_tip",
                          "Casts weaker than this are left out of the center drawing"))


class VedicTourKey(cdk.TourKey):
    """The "Tour" key at the right end of the Aspects V rail row."""

    def __init__(self, parent=None):
        super().__init__(t("center_drawing.tour.label", "Tour"),
                         (t("center_drawing.tour.start", "Show the aspects one by one"),
                          t("center_drawing.tour.stop", "Stop the tour")), parent)
        self.setObjectName("vedic_tour_key")


# ------------------------------------------------------------------ cell marks, tooltips
class VedicCellMarks(cdk.CellMarks):
    """The lit keys' lane tint and the tour's ring on the Aspects V matrix (§3.5), with
    the cell tooltips (``CellTips``) kept alive beside it."""

    def __init__(self, table, texts: VedicPanelData):
        super().__init__(table)
        self.setObjectName("vedic_cell_marks")
        self.tips = CellTips(table, texts, self)


class CellTips(QObject):
    """The matrix cell tooltips: ``QEvent.ToolTip`` on the table's viewport -> the cell
    under the cursor -> its text from the panel's current model. Items and delegate are
    untouched, so the table refresh that recreates every item cannot erase them."""

    def __init__(self, table, texts: VedicPanelData, parent=None):
        super().__init__(parent)
        self._table = table
        self._texts = texts
        table.viewport().installEventFilter(self)

    def text_at(self, pos) -> str:
        index = self._table.indexAt(pos)
        return self._texts.cell_text(index.row(), index.column()) if index.isValid() else ""

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.ToolTip:
            return False
        text = self.text_at(event.pos())
        if text:
            QToolTip.showText(event.globalPos(), text, obj)
        else:
            QToolTip.hideText()
            event.ignore()
        return True


# ------------------------------------------------------------------ toggle
def paint_lens_ray(p: QPainter, sq: QRectF, fs: float):
    """The Stained Light glyph (the mockup's icon, its 20-unit box): a ray into a lens
    ring, the focused light leaving it as a small cone."""
    k = sq.width() * 1.25 / 20.0
    ox, oy = sq.center().x() - 9.6 * k, sq.center().y() - 8.8 * k

    def at(x, y):
        return QPointF(ox + x * k, oy + y * k)

    pen = QPen(p.pen())
    ray = QPen(pen)
    ray.setWidthF(max(pen.widthF(), 2.6 * k))
    ray.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(ray)
    p.drawLine(at(2.5, 6.5), at(11.5, 9.0))
    ring = QPen(pen)
    ring.setWidthF(max(1.0, 1.4 * k))
    p.setPen(ring)
    p.drawEllipse(at(12.5, 9.3), 3.0 * k, 3.0 * k)
    cone = QPainterPath(at(14.8, 8.2))
    cone.lineTo(at(18.0, 10.0))
    cone.lineTo(at(14.8, 11.0))
    cone.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(pen.color()))
    p.drawPath(cone)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(pen)


class VedicCenterToggle(cdk.CenterToggle):
    """The lens-and-ray button: OFF grey, ON in the theme accent with a small lit dot."""

    def __init__(self, parent=None):
        super().__init__(paint_lens_ray, parent)
        self.setObjectName("vedic_center_toggle")
