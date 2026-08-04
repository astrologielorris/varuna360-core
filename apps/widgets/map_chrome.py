# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Map furniture: the pin, the graticule, the Ascendant bands (SPEC-MAP-002 §4.2/4.3/4.6).

Stateless factories. Everything here builds a QGraphicsItem and hands it back;
the widget owns placement, layers and lifetime. Keeping it out of
`offline_map_widget.py` is deliberate — that file is the tile pipeline, and a
tile pipeline should not also be a style sheet.

Two rules run through all of it.

**Zoom invariance.** The map's zoom IS the view transform (SPEC-MAP-001 §4.1),
so an item drawn in scene units grows with the zoom. Anything that represents
UI rather than geography — the pin, every label — carries
`ItemIgnoresTransformations`, and every stroke that must stay N pixels wide
uses a cosmetic pen. Geography (the bands) scales; chrome does not.

**Theme is resolved at build time, not cached at import.** Each factory calls
the theme accessor itself, so a rebuild after a live switch produces the new
palette without anyone having to invalidate a module global.
"""

import math
from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QGraphicsDropShadowEffect, QGraphicsEllipseItem,
    QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsPolygonItem,
)

__all__ = [
    "ELEMENT_COLORS", "SIGN_ELEMENTS", "element_color_for_sign",
    "build_pin_item", "build_pulse_item", "build_graticule_item",
    "build_band_item", "build_band_edge_item", "build_band_label",
    "build_place_label",
    "graticule_step_for_zoom", "small_caps_font", "tabular_font",
    "BAND_ALPHA", "PIN_HEIGHT_PX",
]

#: Element palette. DOMAIN data, not theme data — these four colours mean
#: Fire/Earth/Air/Water everywhere in the app and must not drift per theme.
#: Source of truth: apps/widgets/wheel_items.py.
ELEMENT_COLORS = {
    "Fire": "#E57373",
    "Earth": "#A67C52",
    "Air": "#F0C75E",
    "Water": "#1E4D8C",
}

#: Element by sign index 0-11. Aries/Dhata is index 0 in EVERY zodiac system
#: (SPEC-ZOD-001), so this cycle is mode-independent — the systems differ in
#: where division #1 starts, not in which element it carries.
SIGN_ELEMENTS = ["Fire", "Earth", "Air", "Water"] * 3

#: Band fill opacity. Low enough that coastlines stay readable underneath;
#: the band is context, the map is the subject.
BAND_ALPHA = 46

PIN_HEIGHT_PX = 26.0
PIN_WIDTH_PX = 18.0

#: Halo stroke width around map label glyphs, in device-independent pixels.
HALO_WIDTH = 3.0

#: QGraphicsItem data roles carrying a label's intended colours, so a test or a
#: theme audit can read them without decoding the rendered pixmap.
INK_ROLE = 0
HALO_ROLE = 1


def _device_pixel_ratio() -> float:
    """Screen DPR, so a rasterised label is crisp on a HiDPI display."""
    app = QApplication.instance()
    try:
        screen = app.primaryScreen() if app is not None else None
        return float(screen.devicePixelRatio()) if screen is not None else 1.0
    except Exception:
        return 1.0


def element_color_for_sign(sign_index: int) -> QColor:
    from ui.qt_theme import desat_hex  # SPEC-SAT-001 (local: keep module import-light)
    return QColor(desat_hex(ELEMENT_COLORS[SIGN_ELEMENTS[sign_index % 12]]))


# ---------------------------------------------------------------------------
# Theme access
# ---------------------------------------------------------------------------

def live_palette():
    """Chrome colours re-decided from the CURRENT theme, as a dict of hex.

    The `ui.qt_theme` module constants (SURFACE, BORDER, TEXT_PRIMARY,
    TEXT_SECONDARY, BG) are frozen at import to the DARK values. Reading them
    while the app is in a light theme paints dark chrome on a light page — the
    first real-screen capture of this feature showed exactly that: a near-black
    info card floating over a light map, with a place label whose ink was
    almost the same value as its own halo.

    So the light branch derives from `get_theme_colors()`, which IS live, in
    the same shape `EditMapSubTab._map_bar_colors` already uses for the search
    bar. The dark branch keeps the constants, because in dark mode they are the
    correct values.

    Note `get_theme_colors()` has only primary*/secondary* keys — no `border`,
    no `text_primary`. Reaching for one returns None and crashes at paint time.
    """
    from ui.qt_theme import (
        BG, SURFACE, BORDER, TEXT_PRIMARY, TEXT_SECONDARY, get_theme_accent,
        get_theme_colors, is_light_theme,
    )
    light = bool(is_light_theme())
    theme = get_theme_colors()
    accent = get_theme_accent()
    return {
        "light": light,
        "accent": accent["base"],
        "accent_hover": accent["hover"],
        "surface": theme["secondary"] if light else SURFACE,
        "border": theme["secondary_light"] if light else BORDER,
        "field": theme["secondary_dark"] if light else BG,
        "text": theme["secondary_text"] if light else TEXT_PRIMARY,
        "muted": theme["secondary_text"] if light else TEXT_SECONDARY,
    }


def dim(hex_color: str, factor: float = 0.68) -> str:
    """Blend a colour toward transparency for secondary text.

    Returned as `rgba(...)` rather than a darkened hex because the card sits on
    two different surfaces depending on theme; fading is polarity-neutral,
    darkening is not.
    """
    colour = QColor(hex_color)
    return (f"rgba({colour.red()}, {colour.green()}, {colour.blue()},"
            f" {max(0.0, min(1.0, factor)):.2f})")


def _theme():
    """(accent, surface, border, text, muted, is_light) as QColors."""
    p = live_palette()
    return (QColor(p["accent"]), QColor(p["surface"]), QColor(p["border"]),
            QColor(p["text"]), QColor(p["muted"]), p["light"])


def _contrast_ink(is_light: bool) -> QColor:
    """The HALO colour — matches the tiles, so the outline reads as a glow.

    The tiles invert with the theme (SPEC-MAP-001 §4.4), so the halo behind a
    label has to invert with them or it stops being a halo.
    """
    return QColor(255, 255, 255) if is_light else QColor(18, 20, 24)


def label_ink(is_light: bool) -> QColor:
    """The GLYPH colour for text drawn on TILES. Always opposes the halo.

    Deliberately not a theme text key. Those keys describe text on a panel
    surface — `secondary_text` is the colour for text on a `secondary` chip,
    and in a light theme that is nearly white. Painting it on a white halo over
    a pale map produced exactly what the first real-screen capture showed: the
    place name rendered as an unreadable white blob.

    A map label's job is contrast against cartography, which is a different
    question from contrast against chrome, so it gets its own answer.
    """
    return QColor(26, 28, 32) if is_light else QColor(242, 244, 248)


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

def small_caps_font(point_size: Optional[int] = None,
                    bold: bool = False) -> QFont:
    """Letter-spaced small caps — the map-label voice (SPEC-MAP-002 §4.7)."""
    from ui.qt_theme import FONT_PRIMARY
    font = QFont(FONT_PRIMARY)
    if point_size:
        font.setPointSize(point_size)
    font.setBold(bold)
    font.setCapitalization(QFont.Capitalization.SmallCaps)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
    return font


def tabular_font(point_size: Optional[int] = None) -> QFont:
    """Fixed-pitch digits, so a live coordinate readout does not jitter.

    Proportional digits change width as they change value; on a readout that
    updates on every mouse move that reads as the whole line twitching.
    """
    font = QFont()
    font.setStyleHint(QFont.StyleHint.TypeWriter)
    font.setFixedPitch(True)
    font.setFamily("monospace")
    if point_size:
        font.setPointSize(point_size)
    return font


# ---------------------------------------------------------------------------
# The pin
# ---------------------------------------------------------------------------

def _pin_path() -> QPainterPath:
    """A teardrop whose tip sits exactly at the origin.

    Built as a path rather than loaded from an .svg because the pin is tinted
    with the theme accent; an SVG asset would need recolouring at load, which
    is the same work with a file dependency added.
    """
    w, h = PIN_WIDTH_PX, PIN_HEIGHT_PX
    head_r = w / 2.0
    head_cy = -h + head_r

    path = QPainterPath()
    path.moveTo(0.0, 0.0)                                   # tip
    path.cubicTo(-w * 0.28, -h * 0.42, -head_r, head_cy + head_r * 0.55,
                 -head_r, head_cy)
    path.arcTo(QRectF(-head_r, head_cy - head_r, w, w), 180.0, -180.0)
    path.cubicTo(head_r, head_cy + head_r * 0.55, w * 0.28, -h * 0.42,
                 0.0, 0.0)
    path.closeSubpath()

    # The void: a hole through the head, so the map shows through it and the
    # pin reads as a marker rather than a blob.
    hole = QPainterPath()
    hole.addEllipse(QPointF(0.0, head_cy), head_r * 0.42, head_r * 0.42)
    return path.subtracted(hole)


def build_pin_item(z_value: float = 1000.0) -> QGraphicsPathItem:
    """The selection pin. Origin is the tip, so setPos() is the exact point."""
    accent, _surface, _border, _pt, _st, is_light = _theme()

    item = QGraphicsPathItem(_pin_path())
    item.setBrush(QBrush(accent))
    pen = QPen(_contrast_ink(is_light), 1.5)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    item.setPen(pen)
    item.setZValue(z_value)
    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)

    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(8)
    shadow.setOffset(0, 2)
    shadow.setColor(QColor(0, 0, 0, 102))
    item.setGraphicsEffect(shadow)
    # Rule 18: Qt owns the effect the instant it is attached. Holding a Python
    # reference past that point is how this codebase has earned segfaults.
    del shadow

    return item


def build_pulse_item(z_value: float = 999.0) -> QGraphicsEllipseItem:
    """The ring that expands once when a pin lands. Caller drives the radius."""
    accent, _s, _b, _pt, _st, _light = _theme()
    item = QGraphicsEllipseItem(QRectF(-5, -5, 10, 10))
    pen = QPen(accent, 2.0)
    pen.setCosmetic(True)
    item.setPen(pen)
    item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
    item.setZValue(z_value)
    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
    return item


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def _halo_item(text: str, font: QFont, ink: QColor, halo: QColor,
               z_value: float, anchor: str = "center",
               gap_above: float = 0.0) -> QGraphicsPathItem:
    """Text with an outline, so it survives over both land and sea.

    The glyphs go into a QPainterPath rather than a QGraphicsSimpleTextItem for
    two reasons. A path can be translated to any anchor before it becomes an
    item — a simple-text item has no offset setter, and its position is the
    widget's to control, so there is nowhere else to put the centring. And a
    stroked path gives a real outline in one pass, which is what makes a label
    legible over both a pale coastline and dark water; the alternative is
    stacking four offset copies of the text.
    """
    path = QPainterPath()
    path.addText(0.0, 0.0, font, text)      # origin is the baseline start
    rect = path.boundingRect()

    pad = HALO_WIDTH + 1.0
    path.translate(-rect.left() + pad, -rect.top() + pad)
    width = int(math.ceil(rect.width() + pad * 2))
    height = int(math.ceil(rect.height() + pad * 2))

    dpr = _device_pixel_ratio()
    pixmap = QPixmap(max(1, int(width * dpr)), max(1, int(height * dpr)))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(dpr, dpr)
    # Halo FIRST, glyphs on top. This ordering is the whole point of rendering
    # to a pixmap: QGraphicsPathItem paints its brush then its pen, so a 3 px
    # halo pen on ~10 px glyphs covered the letterforms and the place name
    # rendered as a solid blob. Parenting a second path item behind it fixed
    # the order but made the parent own a child outside any scene, which
    # aborted the process (Rule 18 territory). One pixmap, one item, no
    # ownership question, and the paint order is explicit.
    stroke = QPen(halo, HALO_WIDTH)
    stroke.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(stroke)
    painter.setBrush(QBrush(halo))
    painter.drawPath(path)

    painter.setPen(QPen(Qt.PenStyle.NoPen))
    painter.setBrush(QBrush(ink))
    painter.drawPath(path)
    painter.end()

    item = QGraphicsPixmapItem(pixmap)
    item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
    if anchor == "above":
        item.setOffset(-width / 2.0, -gap_above - height)
    else:
        item.setOffset(-width / 2.0, -height / 2.0)
    item.setZValue(z_value)
    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
    # Tests and a future theme audit need the INTENDED ink without decoding
    # pixels; a pixmap item has no brush() to ask.
    item.setData(INK_ROLE, ink.name())
    item.setData(HALO_ROLE, halo.name())
    return item


def build_place_label(text: str, z_value: float = 1001.0) -> QGraphicsPathItem:
    """The place name above the pin, centred on it."""
    is_light = live_palette()["light"]
    return _halo_item(text, small_caps_font(bold=True), label_ink(is_light),
                      _contrast_ink(is_light), z_value,
                      anchor="above", gap_above=PIN_HEIGHT_PX + 3.0)


def build_band_label(text: str, sign_index: int,
                     z_value: float = 60.0) -> QGraphicsPathItem:
    """The sign name centred in its band."""
    is_light = live_palette()["light"]
    ink = element_color_for_sign(sign_index)
    if is_light:
        # Air (#F0C75E) and Fire (#E57373) are pale; on a white halo over a pale
        # map they read as a smudge. Deepening keeps the element identity while
        # buying back the contrast.
        ink = ink.darker(160)
    else:
        # The mirror problem: Water (#1E4D8C) all but vanishes on dark tiles.
        ink = ink.lighter(150)
    return _halo_item(text, small_caps_font(bold=True), ink,
                      _contrast_ink(is_light), z_value, anchor="center")


# ---------------------------------------------------------------------------
# Ascendant bands
# ---------------------------------------------------------------------------

def build_band_item(scene_points: Sequence[Tuple[float, float]],
                    sign_index: int,
                    z_value: float = 50.0) -> QGraphicsPolygonItem:
    """One filled Ascendant band, in element colour at BAND_ALPHA. NO outline.

    The fill deliberately carries no pen. A `QGraphicsPolygonItem` strokes its
    whole closed outline, and a band's outline is not all boundary: the segments
    that close it at the top and bottom are where the DATA stops, not where the
    Ascendant changes sign. Stroking them drew a crisp horizontal line right
    across the map at the latitude limit, indistinguishable from a real
    boundary — a drawn claim that a sign changes at 66 degrees north, which it
    does not. The two real edges are stroked separately by
    `build_band_edge_item`.
    """
    fill = QColor(element_color_for_sign(sign_index))
    fill.setAlpha(BAND_ALPHA)

    item = QGraphicsPolygonItem(
        QPolygonF([QPointF(x, y) for x, y in scene_points]))
    item.setBrush(QBrush(fill))
    item.setPen(QPen(Qt.PenStyle.NoPen))
    item.setZValue(z_value)
    return item


def build_band_edge_item(scene_points: Sequence[Tuple[float, float]],
                         sign_index: int,
                         z_value: float = 51.0) -> QGraphicsPathItem:
    """One Ascendant boundary: an OPEN polyline, so nothing is closed off."""
    edge = QColor(element_color_for_sign(sign_index))
    edge.setAlpha(150)

    path = QPainterPath()
    for i, (x, y) in enumerate(scene_points):
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)

    item = QGraphicsPathItem(path)
    item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
    pen = QPen(edge, 1.2)
    pen.setCosmetic(True)      # 1.2 device px at every zoom, not 1.2 world units
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    item.setPen(pen)
    item.setZValue(z_value)
    return item


# ---------------------------------------------------------------------------
# Graticule
# ---------------------------------------------------------------------------

def graticule_step_for_zoom(zoom: float) -> float:
    """Degrees between graticule lines. Keeps roughly 6-12 lines on screen."""
    if zoom < 3.0:
        return 30.0
    if zoom < 5.0:
        return 10.0
    if zoom < 7.0:
        return 5.0
    if zoom < 9.0:
        return 1.0
    return 0.5


def build_graticule_item(step_deg: float, to_scene, z_value: float = 40.0,
                         lat_limit: float = 85.0) -> QGraphicsPathItem:
    """The whole graticule as ONE path item.

    One item, not one per line: a QGraphicsItem carries per-item cost in the
    scene's BSP index and in culling, and a 0.5-degree graticule is 1400 lines.
    A single path draws them in one pass.
    """
    _a, _s, _b, _pt, secondary, _light = _theme()
    colour = QColor(secondary)
    colour.setAlpha(31)        # 12%

    path = QPainterPath()

    lat = -lat_limit
    while lat <= lat_limit + 1e-9:
        x0, y0 = to_scene(lat, -180.0)
        x1, y1 = to_scene(lat, 180.0)
        path.moveTo(x0, y0)
        path.lineTo(x1, y1)
        lat += step_deg

    lon = -180.0
    while lon <= 180.0 + 1e-9:
        x0, y0 = to_scene(-lat_limit, lon)
        x1, y1 = to_scene(lat_limit, lon)
        path.moveTo(x0, y0)
        path.lineTo(x1, y1)
        lon += step_deg

    item = QGraphicsPathItem(path)
    pen = QPen(colour, 0.0)
    pen.setCosmetic(True)      # width 0 + cosmetic = always exactly 1 device px
    item.setPen(pen)
    item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
    item.setZValue(z_value)
    return item
