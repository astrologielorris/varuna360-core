"""Stateless cell/chrome painters. All inputs are scoped to this paint pass."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsTextItem, QGraphicsLineItem
from ui.qt_theme import GOLD, get_theme_colors, desat_hex, scaled_tier_size
from visualizations.wheel_constants import ELEMENT_COLORS, get_element_for_sign, element_text_color
from core.aditya_mode import displayed_sign_name, get_planet_display_name
from apps.widgets.south_indian_geometry import *
from apps.widgets.south_indian_items import SignCardItem, HoverZoneItem, ClickablePlanetItem
from apps.widgets.south_indian_material import WoodBoardItem, WoodFaceItem, rounded
from apps.widgets.south_indian_sign_glyph import accompaniment_item
from apps.widgets.cot_index_item import CotPlaque
from apps.widgets.south_indian_badge_layout import draw_sign_badge_layout

def draw_chrome(scene, snapshot, style, layout, signals, center_enabled, center_draw, cot_faces, dpr):
    """Chart-independent layers: frame → medallion → cards → badges →
        hover zones.

        With ``center_box_enabled=False`` this is the INERT mini view
        (SPEC-SIC-003 INV-6): no medallion (which is what would recurse into
        another transit render), no outer gold frame (it would sit inside
        the host medallion's gold ring as a double frame), and no hover
        zones (nothing to hover in an off-screen render)."""
    if style.wood and (not style.foreground_only):
        scene.addItem(WoodBoardItem(rounded(QRectF(0, 0, SCENE_SIZE, SCENE_SIZE), 46), style.finish))
    if center_enabled:
        draw_frame(scene, style)
        center_draw()
    for sign in range(12):
        if style.wood:
            element = get_element_for_sign(sign)
            wash = style.wood['washAir'] if element == 'Air' else style.wood['wash']
            wood_face(scene, style, cell_rect(sign), TAG_CARD, style.wood['stain'][element]['c'], wash)
        else:
            card = SignCardItem(sign, cell_rect(sign))
            scene.addItem(card)
    layout.badge_band.clear()
    layout.pill_bottom.clear()
    for sign in range(12):
        draw_sign_badge(scene, snapshot, style, layout, signals, sign)
    draw_cot_indices(scene, layout, cot_faces, dpr)
    if center_enabled:
        for sign in range(12):
            scene.addItem(HoverZoneItem(cell_rect(sign), sign))

def draw_frame(scene, style):
    """4px gold rounded frame at sceneRect inset 2px (pen half-clip trap,
        spec §4.2)."""
    rect = QRectF(0, 0, SCENE_SIZE, SCENE_SIZE).adjusted(2, 2, -2, -2)
    if style.wood:
        wood_face(scene, style, rect, TAG_FRAME, radius=46)
        return
    path = QPainterPath()
    path.addRoundedRect(rect, CARD_RADIUS, CARD_RADIUS)
    item = QGraphicsPathItem(path)
    item.setBrush(Qt.BrushStyle.NoBrush)
    item.setPen(QPen(QColor(GOLD), 4))
    item.setZValue(0)
    item.setData(Qt.ItemDataRole.UserRole, TAG_FRAME)
    scene.addItem(item)

def fit_font(text: str, base_size, weight, max_width: float) -> QFont:
    """Shrink Inter from base_size toward the 10pt floor until the text
        fits max_width. Built with the same pipeline as the medallion
        headline (QFont + setPointSizeF + setWeight) so badge and center
        typography render identically (T-8 revision, spec v0.6)."""
    size = max(float(MIN_BADGE_FONT_SIZE), float(base_size))
    font = QFont('Inter')
    font.setPointSizeF(size)
    font.setWeight(weight)
    while size > MIN_BADGE_FONT_SIZE and QFontMetricsF(font).horizontalAdvance(text) > max_width:
        size -= 1
        font.setPointSizeF(size)
    return font

def draw_sign_badge(scene, snapshot, style, layout, signals, sign_index):
    return draw_sign_badge_layout(
        scene, snapshot, style, layout, signals, sign_index,
        badge_icon, badge_text, draw_badge_pill)

def badge_icon(scene, style, signals, sign_index, rect):
    pad = CONTENT_PADDING
    icon_item = accompaniment_item(style, sign_index, signals)
    icon_w = icon_item.boundingRect().width() if icon_item else 0
    icon_h = icon_item.boundingRect().height() if icon_item else 0
    icon_x = rect.right() - pad - icon_w
    icon_y = rect.top() + pad
    if icon_item:
        icon_item.setPos(icon_x, icon_y)
        icon_item.setZValue(4.5)
        icon_item.setData(Qt.ItemDataRole.UserRole, TAG_SIGN_ICON)
        scene.addItem(icon_item)
    return (bool(icon_item), icon_w, icon_h, icon_x, icon_y)

def badge_text(snapshot, style, sign_index, rect, icon_item, icon_w, icon_h, icon_x, icon_y):
    pad = CONTENT_PADDING
    colors = get_theme_colors()
    name = displayed_sign_name(sign_index, snapshot.aditya_mode, snapshot.use_western_names, style.language)
    sign_settings = style.display.get('sign_name', {})
    # F-B1/F-C4 (Release 5 font audit): scale the per-element Chart Display size
    # by the chart_labels area + display scale so resolution presets and the
    # Display Scale reach the SI labels, while the user's per-element size stays
    # as a relative override. At default chart_labels(16)+scale(1.0) the factor
    # is 1.0 -> byte-identical parity. Single-source helper (SPEC-FONT-001 B5).
    # float() preserves the prior tolerance of fit_font (which coerced the raw
    # setting) so a hand-edited non-int font_size cannot raise inside the paint.
    base_size = scaled_tier_size(float(sign_settings.get('font_size', 24)), 'chart_labels')
    weight = QFont.Weight.Bold if sign_settings.get('font_weight', 'bold') == 'bold' else QFont.Weight.Normal
    emphasise = snapshot.compass_mode and snapshot.location_cell == sign_index
    if emphasise:
        base_size = int(round(base_size * 1.25))
    pill_left = rect.left() + pad
    band_right = icon_x - 8 if icon_item else rect.right() - pad
    text_budget = band_right - pill_left - 2 * BADGE_PILL_PAD_X
    font = fit_font(name, base_size, weight, text_budget)
    fits_beside = QFontMetricsF(font).horizontalAdvance(name) <= text_budget
    if not fits_beside:
        text_budget = rect.width() - 2 * pad - 2 * BADGE_PILL_PAD_X
        font = fit_font(name, base_size, weight, text_budget)
    label = QGraphicsTextItem(name)
    label.setFont(font)
    label.setDefaultTextColor(style.ink('main', colors['primary'] if emphasise else colors['secondary_text']))
    bounds = label.boundingRect()
    lx = pill_left + BADGE_PILL_PAD_X
    if fits_beside:
        ly = icon_y + (icon_h - bounds.height()) / 2 if icon_item else rect.top() + pad + BADGE_PILL_PAD_Y
    else:
        ly = icon_y + icon_h + 4 + BADGE_PILL_PAD_Y
    pill_rect = QRectF(lx - BADGE_PILL_PAD_X, ly - BADGE_PILL_PAD_Y, bounds.width() + 2 * BADGE_PILL_PAD_X, bounds.height() + 2 * BADGE_PILL_PAD_Y)
    return (label, lx, ly, pill_rect, fits_beside, emphasise)

def draw_badge_pill(scene, style, sign_index, rect, pill_rect, emphasise):
    pad = CONTENT_PADDING
    colors = get_theme_colors()
    pill_path = QPainterPath()
    pill_path.addRoundedRect(pill_rect, pill_rect.height() / 2, pill_rect.height() / 2)
    pill = QGraphicsPathItem(pill_path)
    fill = QColor(colors['secondary'])
    fill.setAlphaF(0 if style.wood else 0.88)
    pill.setBrush(QBrush(fill))
    border = style.ink('brass', GOLD)
    border.setAlphaF((1.0 if emphasise else 0) if style.wood else 1.0 if emphasise else 0.55)
    pill.setPen(QPen(border, 2.5 if emphasise else 1.5))
    pill.setZValue(4.4)
    pill.setData(Qt.ItemDataRole.UserRole, TAG_BADGE_PILL)
    scene.addItem(pill)
    if style.wood:
        slip = wood_face(scene, style, QRectF(rect.left() + pad, rect.top() + pad + 3, 9, 40), 'si.vector.wood.slip', style.wood['stain'][get_element_for_sign(sign_index)]['c'], 0.92, pocket=True, radius=4)
        slip.setZValue(4.5)


def draw_cot_indices(scene, layout, cot_faces, dpr):
    """One rank+suit plaque per sign, in the gap the sign badge left free.

        Lordship, not occupancy: Aries shows Mars's card, Leo the Sun's, and
        Capricorn and Aquarius both show Saturn's — twelve signs onto seven
        planetary positions, so five cards legitimately appear twice.

        The plaque exists because the element cards are strongly coloured in
        both themes: a bare red pip on the red Dhata card would vanish. It uses
        the sign-name pill's recipe (theme secondary fill, gold hairline) so it
        reads as a peer of the name, and the suit ink is then contrasted against
        the pill rather than against whichever element the sign happens to be.
        """
    faces = cot_faces
    if not faces:
        return
    dpr = dpr or 1.0
    for sign_index, card in faces.items():
        band = layout.badge_band.get(sign_index)
        if band is None:
            continue
        gap_left, gap_right, band_top, band_h = band
        if gap_right - gap_left < COT_INDEX_MIN_GAP:
            continue
        plaque = CotPlaque(card, dpr=dpr)
        if plaque.width > gap_right - gap_left:
            continue
        plaque.add_to(scene, (gap_left + gap_right) / 2.0, band_top + band_h / 2.0, tag=TAG_COT_CARD)

def draw_house_numbers(scene, snapshot, style):
    """'H {n}' bottom-left of each card. T-8 revision (spec v0.6, D-6
        superseded): element text color (INV-7) instead of gold — readable
        on all four element gradients, including Air."""
    asc = snapshot.ascendant_sign
    si_size = scaled_tier_size(style.house_number_font, 'chart_labels')
    font = QFont('Inter', si_size)
    fm = QFontMetricsF(font)
    pad = CONTENT_PADDING
    for sign in range(12):
        house = house_number_for_sign(sign, asc)
        color = style.ink('soft', element_text_color(get_element_for_sign(sign)))
        color.setAlphaF(0.85)
        item = QGraphicsTextItem(f'H {house}')
        item.setFont(font)
        item.setDefaultTextColor(color)
        rect = cell_rect(sign)
        item.setPos(rect.left() + pad, rect.bottom() - pad - fm.height())
        item.setZValue(5)
        item.setData(Qt.ItemDataRole.UserRole, TAG_HOUSE_NUMBER)
        scene.addItem(item)

def draw_cusps(scene, snapshot, style):
    """'C{n} {deg}°' bottom-right, same quiet element-colored style as
        the house numbers (T-8 revision, spec v0.6) — only for Campanus
        cusps the chart provides; skipped silently when unavailable."""
    per_sign = dict(snapshot.cusps)
    font = QFont('Inter', scaled_tier_size(HOUSE_NUMBER_FONT_SIZE, 'chart_labels'))
    fm = QFontMetricsF(font)
    pad = CONTENT_PADDING
    for sign, labels in per_sign.items():
        color = style.ink('soft', element_text_color(get_element_for_sign(sign)))
        color.setAlphaF(0.7)
        text = ' '.join(labels)
        item = QGraphicsTextItem(text)
        item.setFont(font)
        item.setDefaultTextColor(color)
        rect = cell_rect(sign)
        item.setPos(rect.right() - pad - fm.horizontalAdvance(text), rect.bottom() - pad - fm.height())
        item.setZValue(5)
        item.setData(Qt.ItemDataRole.UserRole, TAG_CUSP)
        scene.addItem(item)

def wood_face(scene, style, rect, tag, fill=None, opacity=0, pocket=False, radius=28):
    item = WoodFaceItem(rect, style.finish, radius, fill, opacity, pocket)
    item.setData(Qt.ItemDataRole.UserRole, tag)
    item.setZValue(1)
    scene.addItem(item)
    return item
