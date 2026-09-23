"""Stateless natal planet and ascendant painters."""
from apps.widgets.additional_body_glyphs import make_planet_item
import math
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsTextItem, QGraphicsLineItem
from ui.qt_theme import GOLD, get_theme_colors, desat_hex, scaled_tier_size
from visualizations.wheel_constants import ELEMENT_COLORS, get_element_for_sign, element_text_color
from core.aditya_mode import displayed_sign_name, get_planet_display_name
from apps.widgets.south_indian_geometry import *
from apps.widgets.south_indian_items import SignCardItem, HoverZoneItem, SignIconItem, ClickablePlanetItem
from apps.widgets.south_indian_material import WoodBoardItem, WoodFaceItem, rounded, JoshGlyphItem, glyph_svg_passes
def draw_planets(scene, snapshot, style, layout, signals):
    by_sign = {}
    for planet in snapshot.planets:
        by_sign.setdefault(planet.cell, []).append((planet.name, planet, planet.degree))
    for sign, planets in by_sign.items():
        draw_planets_in_sign(scene, snapshot, style, layout, signals, sign, planets, style.display.get('planet_sizes', {}))


def draw_planets_in_sign(scene, snapshot, style, layout, signals, sign_idx, planets_in_sign, planet_sizes):
    """Degree-ordered, evenly spaced planet row at 60% card height
        (SPEC-SIC-001 / INV-6; classic :2864-2884 geometry adapted to the
        488px card with uniform CONTENT_PADDING)."""
    rect = cell_rect(sign_idx)
    pad = CONTENT_PADDING
    planets_in_sign = sorted(planets_in_sign, key=lambda item: item[2])
    num_planets = len(planets_in_sign)
    y_pos = rect.top() + CARD_SIZE * PLANET_ROW_HEIGHT_FRACTION
    available_width = CARD_SIZE - 2 * pad
    spacing = available_width / num_planets
    text_color = style.ink('main', element_text_color(get_element_for_sign(sign_idx)))
    text_color.setAlphaF(0.85)
    deg_settings = style.display.get('planet_degrees', {})
    deg_weight = QFont.Weight.Bold if deg_settings.get('font_weight', 'normal') == 'bold' else QFont.Weight.Normal
    text_font = QFont('Inter', scaled_tier_size(deg_settings.get('font_size', 14), 'chart_labels'), deg_weight)
    fm = QFontMetricsF(text_font)
    for i, (planet_name, planet, place_deg) in enumerate(planets_in_sign):
        if num_planets == 1:
            third = available_width / 3
            x_pos = rect.left() + pad + lone_planet_zone(place_deg) * third + third / 2
        else:
            x_pos = rect.left() + pad + i * spacing + spacing / 2
        base_size = planet_sizes.get(planet_name, style.planet_sizes.get(planet_name, 128))
        planet_size = crowded_planet_size(base_size, num_planets)
        house_item, h_bounds, item_h, planet_size = prepare_house(snapshot, layout, sign_idx, planet, planet_size, y_pos, text_color, deg_settings, deg_weight)
        icon_top, icon_bottom = draw_planet_icon(scene, style, signals, planet_name, planet, x_pos, y_pos, planet_size)
        draw_planet_labels(scene, snapshot, style, planet_name, place_deg, x_pos, icon_bottom, fm, text_font, text_color)
        if house_item is not None:
            house_item.setPos(x_pos - h_bounds.width() / 2, icon_top - 2 - item_h)
            house_item.setZValue(80)
            house_item.setData(Qt.ItemDataRole.UserRole, TAG_COMPASS_HOUSE)
            house_item.setToolTip(planet.sky_label)
            scene.addItem(house_item)

def prepare_house(snapshot, layout, sign_idx, planet, planet_size, y_pos, text_color, deg_settings, deg_weight):
    h_bounds, item_h = (None, 0)
    house = planet.house if snapshot.compass_mode else None
    house_item = None
    if house is not None:
        emphasised = house == snapshot.location_house
        h_font = QFont('Inter', scaled_tier_size(deg_settings.get('font_size', 14) + (4 if emphasised else 0), 'chart_labels'), QFont.Weight.Bold if emphasised else deg_weight)
        house_item = QGraphicsTextItem(str(house))
        house_item.setFont(h_font)
        h_color = QColor(text_color)
        h_color.setAlphaF(1.0 if emphasised else text_color.alphaF())
        house_item.setDefaultTextColor(h_color)
        h_bounds = house_item.boundingRect()
        item_h = h_bounds.height()
        band = layout.badge_band.get(sign_idx)
        band_bottom = band[2] + band[3] if band else 0.0
        floor = max(band_bottom, layout.pill_bottom.get(sign_idx, 0.0)) + 2
        need_top = floor + 2 + item_h
        planet_size = max(64, int(min(planet_size, 2 * (y_pos - need_top))))
    return (house_item, h_bounds, item_h, planet_size)

def draw_planet_icon(scene, style, signals, planet_name, planet, x_pos, y_pos, planet_size):
    from apps.widgets.planet_shadow import create_planet_shadow
    icon_bottom = y_pos
    icon_top = y_pos
    pixmap = style.planet_icon(planet_name, size=planet_size)
    if pixmap:
        planet_item = make_planet_item(ClickablePlanetItem, planet_name, pixmap, planet_name, dict(planet.payload), signals.planet)
        planet_item.setOffset(-pixmap.width() / 2, -pixmap.height() / 2)
        planet_item.setPos(x_pos, y_pos)
        shadow = None if style.wood else create_planet_shadow(planet_name=planet_name)
        if shadow:
            planet_item.setGraphicsEffect(shadow)
            del shadow
        scene.addItem(planet_item)
        icon_bottom = y_pos + pixmap.height() / 2
        icon_top = y_pos - pixmap.height() / 2
    return icon_top, icon_bottom

def draw_planet_labels(scene, snapshot, style, planet_name, place_deg, x_pos, icon_bottom, fm, text_font, text_color):
    abbrev = planet_name[:2]
    if snapshot.show_planet_names:
        degrees_text = get_planet_display_name(style.language, planet_name)
    else:
        deg, mins = (int(place_deg), int(place_deg % 1 * 60))
        degrees_text = f"{deg}°{mins:02d}'"
    abbrev_y = icon_bottom + 4
    degrees_y = abbrev_y + fm.height() + 2
    for text, ty in ((abbrev, abbrev_y), (degrees_text, degrees_y)):
        label = QGraphicsTextItem(text)
        label.setFont(text_font)
        label.setDefaultTextColor(text_color)
        label.setPos(x_pos - label.boundingRect().width() / 2, ty)
        label.setZValue(80)
        label.setData(Qt.ItemDataRole.UserRole, TAG_PLANET_TEXT)
        scene.addItem(label)


def draw_lagna_stripe(scene, snapshot, style):
    """Two parallel diagonal strikes calibrated to the ascendant card's
        top-right corner, BEHIND the badge icon, + a quiet 'ASC d°mm'' label
        (SPEC-NIC-001 §3.2 format, §3.3 varga-aware degree). Hidden under
        the F4 override.

        Calibration (T-8 rev 2, spec v0.7) — perfect square math, no fudge
        offsets: each strike is a 45° line whose ROUND CAPS kiss the top and
        right card edges exactly (endpoints inset by precisely pen.width()/2
        perpendicular to the edge they touch, so nothing spills into the
        gutter). Inner strike reach = CARD_SIZE/3 — an exact fraction of the
        card, like tick marks on a well-made dial. The air between the two
        strikes is exactly one stroke width (perpendicular), so the outer
        strike's reach shrinks by 2*w*sqrt(2) along the edges.

        Overlap choice (documented): the strikes sit BEHIND the badge icon
        (z=2 < pills 4.4 < icons 4.5 < labels 5), element-colored
        lighter(150) at 45% so they read on their own card — glyph corners
        are transparent enough for the marks to show around the icon, and
        the inner strike's reach (CARD_SIZE/3 ≈ 163px) extends ~40px past
        the icon column so the mark is always visible. The ASC label sits
        directly below the badge icon, right-aligned with it, in the same
        quiet style as the house numbers (Lorris, T-8 rev 2: the strikes
        alone advertise the ascendant).

        Under an F4 / sign-column override the strikes MOVE to the overridden
        card — they are the only on-chart signal that an override is active
        (SPEC-SIC-003 INV-2, classic parity at chart_view.py:2306). Only the
        degree label is suppressed, because an invented Ascendant has no real
        degree (classic parity at chart_view.py:2378)."""
    if not snapshot.has_chart:
        return
    sign_index = snapshot.ascendant_sign
    rect = cell_rect(sign_index)
    stripe_color = QColor(desat_hex(ELEMENT_COLORS[get_element_for_sign(sign_index)])).lighter(150)
    stripe_color.setAlphaF(0.45)
    pen = QPen(stripe_color)
    pen.setWidth(max(6, int(CARD_SIZE * 0.035)))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    w = pen.width()
    half = w / 2
    top = rect.top()
    right = rect.right()
    reach = CARD_SIZE / 3
    gap = 2 * w * math.sqrt(2)
    for r in (reach, reach - gap):
        line = QGraphicsLineItem(right - r, top + half, right - half, top + r)
        line.setPen(pen)
        line.setZValue(2)
        line.setData(Qt.ItemDataRole.UserRole, TAG_LAGNA)
        scene.addItem(line)
    if snapshot.ascendant_override is not None:
        return
    deg, mins = snapshot.ascendant_degrees
    label = QGraphicsTextItem(f"ASC {deg}°{mins:02d}'")
    label.setFont(QFont('Inter', scaled_tier_size(HOUSE_NUMBER_FONT_SIZE, 'chart_labels')))
    color = style.ink('asc', element_text_color(get_element_for_sign(sign_index)))
    color.setAlphaF(0.9)
    label.setDefaultTextColor(color)
    label.setPos(rect.right() - CONTENT_PADDING - label.boundingRect().width(), rect.top() + CONTENT_PADDING + SIGN_ICON_SIZE + 6)
    label.setZValue(5)
    label.setData(Qt.ItemDataRole.UserRole, TAG_LAGNA_LABEL)
    scene.addItem(label)
