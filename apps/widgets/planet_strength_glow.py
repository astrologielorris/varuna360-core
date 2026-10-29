# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Planet strength glow on the charts, "Ember Aura" (SPEC-RST-001 D-21, td-e6jsp).

While PLANET and a strength key are lit each classical planet swaps its manual
drop shadow for ONE radial gradient disc in its strength colour behind the icon,
fading to fully transparent, nothing else (no edge ring, td-ws82s), and its degree
text gets a halo. D-21a (td-647kl): every aura of a view is sized from the view's
ONE reference half size and the value, and lit from the value and the colour's
difference to the ground under the planet itself (one low-res render). Plain Qt
items with an empty shape (clicks, hover and ``items(pos)`` pass through), no blur,
no animation. OFF: one settings read, nothing added. Rule 18: items go to the scene
or under a parent at once; Qt deletes a replaced shadow."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFontMetricsF, QPainterPath, QPen
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsPathItem, QGraphicsSimpleTextItem,
                               QGraphicsTextItem)

from apps.widgets.planet_aura_items import (VALUE_ROLE, decorate_planets, discs, glyphs,
                                            sample_grounds, theme_ground, unshadow)
from core import planet_aura as pa
from core import planet_strength_glow as psg
from core.retinue_strength import contrast, duc_method_from, hex_rgb, strength_values
from ui.qt_theme import desat_hex, is_light_theme

TAG_HALO = 'psg.halo'      # data(UserRole) of every degree-text halo
HALO_RATIO = 0.11          # halo half-width / text line height (mockup: 2.6 px stroke, 9.5 px text)
WHITE, BLACK = "#FFFFFF", "#000000"


def glow_values(chart, get=None):
    """``{planet: D1 value}`` of the lit source while PLANET is lit, else None."""
    if get is None:
        from managers.settings_manager import get_settings
        get = get_settings().get
    source = psg.glow_source(get)
    if source is None or not chart:
        return None
    return strength_values(chart, source, duc_method_from(get))


class HaloItem(QGraphicsPathItem):
    def shape(self):                          # seen, never hit
        return QPainterPath()


def glow_preview_planet(item, planet, chart, r_ref, scene):
    """A transient preview icon (classic SI centre hover, not yet in the scene;
    all its planets share the one preview size, ``r_ref`` = half of it): the
    aura as the item's own children, stacked behind it, so they leave with it.
    Off: nothing."""
    values = glow_values(chart)
    if values is None or planet not in values:
        return False
    rect, reach = unshadow(item, values[planet]), pa.OWN_REACH * r_ref
    samples = sample_grounds(scene, [item.mapToScene(rect.center())], r_ref, (), reach)[0]
    ground = pa.own_ground(samples, reach)
    for disc in discs(planet, values[planet], rect.center(), r_ref, 0, ground):
        disc.setParentItem(item)              # Rule 18: the item owns its discs
        disc.setFlag(QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent, True)
    return True


def strength_colour(item):
    """The palette colour of an aura-decorated planet item, else None."""
    raw = psg.STRENGTH_PALETTE.get(getattr(item, "planet_name", None))
    return None if raw is None or item.data(VALUE_ROLE) is None else QColor(desat_hex(raw))


def halo_colour(text: QColor) -> QColor:
    """The theme ground when it stands off the text, else white or black."""
    tx, ground = hex_rgb(text.name()), theme_ground()
    if contrast(hex_rgb(ground), tx) < 3.0:
        ground = WHITE if contrast(hex_rgb(WHITE), tx) >= contrast(hex_rgb(BLACK), tx) else BLACK
    c = QColor(ground)
    c.setAlphaF(0.80 if is_light_theme() else 0.85)
    return c


def _text_path(item):
    """The glyph outline of a one-line text item, in its own coordinates."""
    font = item.font()
    if isinstance(item, QGraphicsSimpleTextItem):
        return (glyphs(item.text(), font).translated(0.0, QFontMetricsF(font).ascent()),
                item.brush().color())
    item.boundingRect()                       # lays the document out
    layout = item.document().firstBlock().layout()
    line = layout.lineAt(0) if layout is not None and layout.lineCount() else None
    if line is None:
        return QPainterPath(), item.defaultTextColor()
    x = layout.position().x() + line.x()
    y = layout.position().y() + line.y() + line.ascent()
    return glyphs(item.toPlainText(), font).translated(x, y), item.defaultTextColor()


def add_halo(item, cache=None):
    """A soft halo under the text ``item`` (its child, stacked behind it);
    ``cache``: a dict shared by one drawing pass (one halo colour per text colour)."""
    if not isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem)):
        return False
    path, colour = _text_path(item)
    if path.isEmpty():
        return False
    halo = HaloItem(path, item)
    if cache is None:
        c = halo_colour(colour)
    else:
        key = colour.rgba()
        c = cache.get(key)
        if c is None:
            c = cache[key] = halo_colour(colour)
    width = 2.0 * HALO_RATIO * QFontMetricsF(item.font()).height()
    halo.setPen(QPen(QBrush(c), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                     Qt.PenJoinStyle.RoundJoin))
    halo.setBrush(QBrush(c))
    halo.setFlag(QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent, True)
    halo.setData(Qt.ItemDataRole.UserRole, TAG_HALO)
    del halo                                  # Rule 18: the text item owns it
    return True


def glow_scene(scene, chart, is_planet, is_planet_text, r_ref, is_hidden=lambda item: False):
    """Ember Aura post-pass: each classical planet item (``is_planet``) gets its aura
    (``r_ref``: the view's reference half size, or a callable), each planet text a halo;
    ``is_hidden``: more items the ground render leaves out. Returns the planets decorated."""
    values = glow_values(chart)
    if values is None:
        return 0
    items = scene.items()
    icons = [i for i in items if is_planet(i)]
    hits = [i for i in icons if getattr(i, "planet_name", None) in values]
    if not hits:
        return 0
    r_ref = r_ref() if callable(r_ref) else r_ref    # OFF: never computed
    texts = [i for i in items if is_planet_text(i)]
    hide = icons + texts + [i for i in items if is_hidden(i)]
    decorate_planets(scene, [(i, values[i.planet_name]) for i in hits], r_ref, hide, chart)
    cache = {}
    for item in texts:
        add_halo(item, cache)
    return len(hits)
