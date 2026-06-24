# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Shared Zodiac Wheel Renderer — Pure Functions Module

Stateless drawing functions used by BOTH:
  - WheelView (main zodiac wheel)
  - NakshatraWheelView (mini inner zodiac)

Every function takes explicit parameters (scene, cx, cy, radii, etc.)
and adds QGraphicsItems directly to the scene. No `self`, no class state.

Items classes (ZodiacSectorItem, SectorDividerLine, etc.) remain in wheel_items.py.
Geometry helpers come from visualizations/wheel_geometry.py.
"""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

from .wheel_items import (
    ZodiacSectorItem, SectorDividerLine, AscendantGlowItem,
    CenterCircleItem, HouseNumberItem, SignNameItem, ZodiacSymbolItem
)
from visualizations.wheel_geometry import (
    get_sector_start_angle, get_sector_center_angle, polar_to_cartesian
)

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Western names for icon filenames (shared constant)
WESTERN_NAMES = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]


# ── Icon Loading ──────────────────────────────────────────────────

def load_zodiac_icon(zodiac_index, size, variation_settings, icon_cache):
    """
    Load a zodiac sign PNG icon with variation support and caching.

    Args:
        zodiac_index: 0-11 sign index
        size: Pixel size to scale to
        variation_settings: dict mapping Western name -> variation number
        icon_cache: dict used as cache (caller owns it)

    Returns:
        QPixmap or None
    """
    western_name = WESTERN_NAMES[zodiac_index]
    variation = variation_settings.get(western_name, 1)
    cache_key = f"zodiac_{zodiac_index}_v{variation}_{size}"

    if cache_key in icon_cache:
        return icon_cache[cache_key]

    # Try the selected variation file (e.g. Leo3.webp for variation 3).
    icon_path = PROJECT_ROOT / f"img/sign/{western_name}{variation}.webp"
    if not icon_path.exists():
        # Fallback to variation 1, which Core always ships for every sign
        # (the single default retained by the 2026-04-08 cleanup). A healthy
        # Core build will always hit this path when the selected variant is
        # missing, so no further fallback is needed. The proprietary edition
        # may add more variants via an overlay path.
        icon_path = PROJECT_ROOT / f"img/sign/{western_name}1.webp"
    if not icon_path.exists():
        icon_cache[cache_key] = None
        return None

    qimage = QImage(str(icon_path))
    if qimage.isNull():
        icon_cache[cache_key] = None
        return None

    qimage = qimage.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation
    )
    pixmap = QPixmap.fromImage(qimage)
    icon_cache[cache_key] = pixmap
    return pixmap


# ── Drawing Functions ─────────────────────────────────────────────

def draw_ascendant_glow(scene, cx, cy, radius, glow_radius=102, z_base=-5):
    """Draw golden glow at Ascendant position (always at 180° / 9 o'clock).

    Args:
        scene: QGraphicsScene to add items to
        cx, cy: Center of wheel
        radius: Radius where Ascendant sits (middle ring edge)
        glow_radius: Size of glow ellipse
        z_base: Z-value for layering
    """
    item = AscendantGlowItem(cx, cy, radius, glow_radius=glow_radius)
    item.setZValue(z_base)
    scene.addItem(item)


def draw_zodiac_sectors(scene, cx, cy, inner_r, outer_r, rotation_offset, z_base=0):
    """Draw 12 element-colored zodiac sectors.

    Args:
        scene: QGraphicsScene
        cx, cy: Center
        inner_r: Inner radius of sectors
        outer_r: Outer radius of sectors
        rotation_offset: Degrees to rotate all sectors
        z_base: Z-value for layering
    """
    items = {}
    for i in range(12):
        start_angle = get_sector_start_angle(i, rotation_offset)
        item = ZodiacSectorItem(cx, cy, inner_r, outer_r, start_angle, i)
        item.setZValue(z_base)
        scene.addItem(item)
        items[i] = item
    return items


def draw_sector_dividers(scene, cx, cy, inner_r, outer_r, rotation_offset, z_base=1):
    """Draw 12 radial lines separating zodiac sectors.

    Args:
        scene: QGraphicsScene
        cx, cy: Center
        inner_r: Start radius of lines
        outer_r: End radius of lines
        rotation_offset: Degrees rotation
        z_base: Z-value
    """
    for i in range(12):
        angle = get_sector_start_angle(i, rotation_offset)
        item = SectorDividerLine(cx, cy, inner_r, outer_r, angle)
        item.setZValue(z_base)
        scene.addItem(item)


def draw_zodiac_icons(scene, cx, cy, radius, icon_size, rotation_offset,
                      icon_loader, z_base=4, display_size=None):
    """Draw 12 zodiac sign PNG icons at sector centers.

    Args:
        scene: QGraphicsScene
        cx, cy: Center
        radius: Radius for icon placement
        icon_size: Size in pixels to LOAD (determines zoom quality)
        rotation_offset: Degrees rotation
        icon_loader: callable(zodiac_index, size) -> QPixmap or None
        z_base: Z-value
        display_size: Scene units to DISPLAY at (default=icon_size).
                      Load high-res, scale down for display, keep detail for zoom.
    """
    scale_factor = display_size / icon_size if display_size else None

    for i in range(12):
        center_angle = get_sector_center_angle(i, rotation_offset)
        x, y = polar_to_cartesian(cx, cy, radius, center_angle)

        pixmap = icon_loader(i, icon_size)
        if pixmap:
            item = ZodiacSymbolItem(pixmap, x, y, i)
            if scale_factor:
                item.setScale(scale_factor)
            item.setZValue(z_base)
            scene.addItem(item)


def draw_sign_names(scene, cx, cy, radius, rotation_offset,
                    aditya_mode, use_western_names, sign_language,
                    display_settings, z_base=5):
    """Draw Aditya or Western sign names at sector centers.

    Args:
        scene: QGraphicsScene
        cx, cy: Center
        radius: Radius for label placement
        rotation_offset: Degrees rotation
        aditya_mode: "aditya" or "tropical_classic"
        use_western_names: bool
        sign_language: "en", "fr", "es", "pt", "pt-PT", "de", "it", "ru", or "zh"
        display_settings: dict with sign_name sub-dict (font_size, font_color, etc.)
        z_base: Z-value
    """
    sign_settings = display_settings.get("sign_name", {})
    font_size = sign_settings.get("font_size", 26)
    font_color = sign_settings.get("font_color", None)
    font_weight = sign_settings.get("font_weight", "bold")
    offset_x = sign_settings.get("offset_x", 0)
    offset_y = sign_settings.get("offset_y", 0)

    for i in range(12):
        center_angle = get_sector_center_angle(i, rotation_offset)
        x, y = polar_to_cartesian(cx, cy, radius, center_angle)

        item = SignNameItem(
            x, y, i, aditya_mode,
            font_size=font_size,
            use_western_names=use_western_names,
            font_color=font_color,
            font_weight=font_weight,
            offset_x=offset_x,
            offset_y=offset_y,
            sign_language=sign_language
        )
        item.setZValue(z_base)
        scene.addItem(item)


def draw_center_circle(scene, cx, cy, radius, z_base=2):
    """Draw the center circle with dark gradient.

    Args:
        scene: QGraphicsScene
        cx, cy: Center
        radius: Circle radius
        z_base: Z-value
    """
    item = CenterCircleItem(cx, cy, radius)
    item.setZValue(z_base)
    scene.addItem(item)


def draw_house_numbers(scene, cx, cy, number_radius, font_size,
                       rotation_offset, asc_degrees, z_base=6,
                       hover_signal=None, cusp_angles=None):
    """Draw house numbers 1-12 in the center circle.

    Args:
        scene: QGraphicsScene
        cx, cy: Center
        number_radius: Radius for number placement
        font_size: Font size in points
        rotation_offset: Degrees rotation
        asc_degrees: Ascendant degrees (determines which sign = House 1)
        z_base: Z-value
    """
    items = {}
    if cusp_angles is None:
        # Ernst mode: equal 30-degree sectors aligned to signs
        asc_sign_index = int(asc_degrees // 30)
        asc_sign_start = asc_sign_index * 30
        for house_num in range(1, 13):
            house_center_deg = (asc_sign_start + (house_num - 1) * 30 + 15) % 360
            visual_angle = (house_center_deg + rotation_offset) % 360
            x, y = polar_to_cartesian(cx, cy, number_radius, visual_angle)
            item = HouseNumberItem(x, y, house_num, font_size=font_size,
                                   hover_signal=hover_signal)
            item.setZValue(z_base)
            scene.addItem(item)
            items[house_num] = item
    else:
        # Western mode: unequal sectors from cusp angles
        for house_num in range(1, 13):
            cusp_start = cusp_angles[house_num - 1]
            cusp_end = cusp_angles[house_num % 12]
            # Arc span, handling wrap-around
            span = (cusp_end - cusp_start) % 360
            # Midpoint of the arc
            mid_deg = (cusp_start + span / 2) % 360
            visual_angle = (mid_deg + rotation_offset) % 360

            # Narrow sector font scaling (SPEC-WHD-001 section 5.10)
            effective_font = font_size
            if span < 12:
                scale = max(0.5, span / 12)
                effective_font = max(int(font_size * scale), 10)

            x, y = polar_to_cartesian(cx, cy, number_radius, visual_angle)
            item = HouseNumberItem(x, y, house_num, font_size=effective_font,
                                   hover_signal=hover_signal)
            item.setZValue(z_base)
            scene.addItem(item)
            items[house_num] = item
    return items


def draw_whole_sign_dividers(scene, cx, cy, inner_r, outer_r,
                             rotation_offset, asc_degrees, z_base=6.5):
    """Draw Whole Sign house divider lines in the center circle.

    Args:
        scene: QGraphicsScene
        cx, cy: Center
        inner_r: Inner radius of divider lines
        outer_r: Outer radius of divider lines
        rotation_offset: Degrees rotation
        asc_degrees: Ascendant degrees (determines house boundaries)
        z_base: Z-value
    """
    asc_sign_index = int(asc_degrees // 30)
    asc_sign_start = asc_sign_index * 30

    for house in range(12):
        house_start_deg = (asc_sign_start + house * 30) % 360
        visual_angle = (house_start_deg + rotation_offset) % 360

        item = SectorDividerLine(cx, cy, inner_r, outer_r, visual_angle)
        item.setZValue(z_base)
        scene.addItem(item)
