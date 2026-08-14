#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Full-fidelity transit/custom outer ring renderer (SPEC-TRN-004).

This module renders the "full_wheel" transit ring: a flush, closed replica of
the natal planet band drawn as an annulus of 12 element-colored sign-sector
wedges, containing full-size planet icons, element-colored indicator lines,
natal-style planet labels, a contained degree ruler, and natal-style sector
dividers.

Design lineage (D12): every building block here is derived from the ORIGINAL
natal wheel routines parameterized by radius:
  - colored sectors      -> zodiac_renderer.draw_zodiac_sectors
  - sector dividers       -> zodiac_renderer.draw_sector_dividers
  - planet placement      -> wheel_view.calculate_band_positions (natal algorithm)
  - planet labels         -> WheelView._draw_planet_label (natal path)
  - degree ruler          -> WheelView._draw_degree_ruler logic, drawn inward
None of the miniature rim's visual vocabulary (dark TropicalOuterRimBackground,
TropicalSectorDivider, 40% icons, scaled_area_font labels) is used here.

The renderer receives the live WheelView as `view` for context (Rule 4 spirit;
wheel_view.py is already large). It draws directly into `view.scene`.

Z-order contract (4.1), from back to front:
  ring sectors        z = _Z_SECTORS      (2.0) -> below the natal ruler (z=3)
  ring sector dividers z = _Z_DIVIDERS     (2.5)
  natal degree ruler  z = 3 (drawn by WheelView) -> reads above the ring sectors
  ring degree ruler   z = base_z           (>=15) -> above the natal ruler
  ring indicator lines z = base_z + 0.3
  ring planet icons    z = base_z + 1.0
  ring planet labels   z = base_z + 1.5 (via _draw_planet_label, which uses z=9;
                        icons intentionally sit above labels, as in the natal band)
"""

from PySide6.QtWidgets import QGraphicsTextItem, QGraphicsPixmapItem
from PySide6.QtGui import QColor

from .zodiac_renderer import draw_zodiac_sectors, draw_sector_dividers
from .wheel_items import DegreeTickItem, PlanetIndicatorLine
from visualizations.wheel_geometry import polar_to_cartesian, get_planet_angle
from ui.qt_theme import scaled_area_font, is_light_theme

# Ring band geometry relative to the ring inner radius (SPEC-TRN-004 4.1).
#
# The band is WIDER than the natal planet annulus (358) on purpose. The natal
# band reserves 90 px of inner clearance (r_center + 90) so full-size icons
# (up to ~151 px) never touch the inner edge, and lets icons overflow OUTWARD
# into the sign band (harmless). The ring has no sign band to absorb overflow
# and a degree ruler at its outer edge, so to keep FULL-SIZE icons (D3/Option A)
# fully inside the ring we reproduce the natal 90 px inner clearance + the same
# 258 px placement zone, then add room for icon overflow + the ruler beyond it:
#   90 (clearance) + 258 (zone) + ~68 (outer icon overflow) + ~54 (ruler) = 470.
_BAND_WIDTH = 470
_RETINUE_OFFSET = 300      # ring starts flush above the trimsamsa outer edge
# Planet placement zone: inner + 90 .. inner + 348 (90 px clearance + 258 px zone,
# identical to the natal band r_center+90 .. r_inner-10, so the zig-zag spread and
# relative planet positions match the natal band exactly).
_PLANET_ZONE_INNER = 90
_PLANET_ZONE_OUTER = 348

# Z layering (see module docstring).
_Z_SECTORS = 2.0
_Z_DIVIDERS = 2.5
# Cusp glow lines sit above the ring sectors and the natal ruler (3) but below
# the ring planets (base_z, >=15) so icons draw over them, exactly as the natal
# cusp glow lines (z 3.7) sit under the natal planets.
_Z_CUSP_LINE = 6.0
_Z_CUSP_LABEL = 19.0    # cusp/ASC labels sit beyond the ring, on top

# Natal cusp-glow colors (mirror WheelView._draw_cusp_glow_lines exactly).
_CUSP_ANGLE_HOUSES = frozenset({1, 4, 7, 10})
_CUSP_ANGLE_LABELS = {1: "ASC", 4: "IC", 7: "DESC", 10: "MC"}
_CUSP_ANGLE_COLOR = "#FFD700"   # gold for ASC/IC/DESC/MC
_CUSP_OTHER_COLOR = "#888888"   # gray for the intermediate cusps
# The cusp/ASC glow LINE stays gold (it reads over any element sector in both
# themes), but gold TEXT washes out on a light background. The writing follows
# the live theme: dark text on a light theme, gold on a dark theme.
_CUSP_LABEL_LIGHT_THEME_COLOR = "#1A1A1A"   # near-black writing for light themes

# Ruler tick lengths (drawn inward from the ring outer edge; containment 4.1).
_RULER_EDGE_INSET = 4      # ruler outer end sits this far inside the ring edge
_TICK_MAJOR = 31
_TICK_MINOR = 15
_TICK_MICRO = 8
_RULER_LABEL_INSET = 46    # number labels sit this far inside the ring edge
_RULER_COLOR = "#888888"   # readable over every element color (natal ruler treatment)
_MICRO_ZOOM_GATE = 1.5     # 1 degree micro ticks only appear when zoomed in
# Ring ruler NUMBER labels are illegible at fit zoom and are the costliest ruler
# items (text layout). Gate them like the micro ticks so a zoomed-out time-slider
# sweep skips 24 QGraphicsTextItems per frame (SPEC-TRN-004 criterion 11 budget).
_RULER_LABEL_ZOOM_GATE = 0.6


def ring_radii(view):
    """Return (ring_inner, ring_outer) for the active stacking configuration (4.1).

    Two configurations only:
      no retinue  -> inner = r_outer,        outer = r_outer + 358
      retinue on  -> inner = r_outer + 300,  outer = r_outer + 658
    """
    ring_inner = view.r_outer + (_RETINUE_OFFSET if view.show_retinue_rings else 0)
    return ring_inner, ring_inner + _BAND_WIDTH


def draw_full_outer_ring(view, planets_data, base_z, line_color=None,
                         label_color="#AAAAAA", tooltip_prefix="Overlay"):
    """Render the full-fidelity outer ring into view.scene (SPEC-TRN-004 4.1, 4.2).

    Args:
        view: the WheelView (context: geometry, settings, scene, helpers).
        planets_data: dict name -> {"decimal_degrees": float} (Ascendant handled
            separately by WheelView._draw_outer_rim_ascendant).
        base_z: base z-value for the ring's upper elements (ruler/lines/icons).
        line_color: fixed indicator-line color, or None to use element colors.
        label_color: unused for the full ring (labels use the natal planet_degrees
            settings); kept for dispatcher signature parity.
        tooltip_prefix: tooltip prefix for the icons ("Transit", "Eclipse", ...).
    """
    scene = view.scene
    cx, cy = view.cx, view.cy
    rotation_offset = view.rotation_offset
    ring_inner, ring_outer = ring_radii(view)

    # --- Background: 12 element-colored sector wedges (D11). Non-interactive:
    # we do NOT register them in view._zodiac_sector_items, so the hover/click
    # machinery (keyed on that dict + a r_outer+40 hit-test early-out) ignores them.
    sector_items = draw_zodiac_sectors(scene, cx, cy, ring_inner, ring_outer,
                                       rotation_offset, z_base=_Z_SECTORS)
    del sector_items  # scene owns them; drop our ref (Rule 18)

    # --- Sector divider lines at sign boundaries (natal treatment at ring radii).
    draw_sector_dividers(scene, cx, cy, ring_inner, ring_outer,
                         rotation_offset, z_base=_Z_DIVIDERS)

    # --- Contained degree ruler (ticks + labels inward from the ring edge).
    _draw_ring_degree_ruler(view, ring_inner, ring_outer, base_z)

    # --- Planets: icons, indicator lines, labels (natal path at ring radii).
    _draw_ring_planets(view, planets_data, ring_inner, base_z,
                       line_color, tooltip_prefix)


def draw_ring_cusps_and_ascendant(view, cusps, asc_sign_name):
    """Draw the overlay chart's Ascendant + cusps on the ring, mirroring the wheel.

    Per D12 and the user requirement, the overlay's Ascendant and cusps use the
    natal wheel's cusp-glow rendering ONLY, NOT the miniature triangle marker and
    NOT a separate glow/label. There is exactly ONE Ascendant indicator: the gold
    cusp-glow line with an "ASC <deg> <SignName>" label.

    Cusps mirror WheelView._draw_cusp_glow_lines, gated by the SAME
    view.cusp_glow_mode (F9): 0 = off, 1 = angles (ASC/IC/DESC/MC), 2 = all 12.
    Gold for angles, gray otherwise. The ASC (house 1) label carries the
    mode-aware sign name; IC/DESC/MC and the intermediate cusps are degree-only
    exactly like the natal wheel. Lines span the ring band at a z below the ring
    planets, so icons draw over them (as natal planets draw over natal cusp lines).

    Args:
        view: the WheelView (geometry, settings, scene, cusp_glow_mode).
        cusps: the overlay chart's cusps (1..12 indexable), or None.
        asc_sign_name: mode-aware Ascendant sign name (already resolved).
    """
    scene = view.scene
    cx, cy = view.cx, view.cy
    rotation_offset = view.rotation_offset
    ring_inner, ring_outer = ring_radii(view)

    cusp_glow_mode = getattr(view, "cusp_glow_mode", 0)
    if cusps is None or cusp_glow_mode == 0:
        return

    houses = _CUSP_ANGLE_HOUSES if cusp_glow_mode == 1 else set(range(1, 13))
    line_settings = view.display_settings.get("indicator_line", {})
    glow = max(3, line_settings.get("glow_radius", 40) // 5)
    width = 1
    for house_num in range(1, 13):
        if house_num not in houses:
            continue
        try:
            cusp = cusps[house_num]
        except (IndexError, KeyError, TypeError):
            continue
        cusp_deg = (cusp.sign() - 1) * 30 + cusp.real_in_sign_longitude()
        visual_angle = (cusp_deg + rotation_offset) % 360
        deg_in_sign = int(cusp.real_in_sign_longitude())
        is_angle = house_num in _CUSP_ANGLE_HOUSES
        cl = _CUSP_ANGLE_COLOR if is_angle else _CUSP_OTHER_COLOR

        sx, sy = polar_to_cartesian(cx, cy, ring_inner, visual_angle)
        ex, ey = polar_to_cartesian(cx, cy, ring_outer + 40, visual_angle)
        line = PlanetIndicatorLine(
            sx, sy, ex, ey, color=cl, glow_intensity=glow, line_width=width,
        )
        line.setZValue(_Z_CUSP_LINE)
        scene.addItem(line)

        label_r = ring_outer + 60
        lx, ly = polar_to_cartesian(cx, cy, label_r, visual_angle)
        if house_num == 1:
            # The single ASC indicator carries the mode-aware sign name.
            text = f"ASC {deg_in_sign}° {asc_sign_name}"
        elif is_angle:
            text = f"{_CUSP_ANGLE_LABELS[house_num]} {deg_in_sign}°"
        else:
            text = f"C{house_num} {deg_in_sign}°"
        lbl = QGraphicsTextItem(text)
        lbl.setFont(scaled_area_font('chart_labels', family='Inter'))
        # Line keeps its gold/gray identity; the writing follows the theme so it
        # stays legible on a light background (black in light, gold/gray in dark).
        text_color = _CUSP_LABEL_LIGHT_THEME_COLOR if is_light_theme() else cl
        lbl.setDefaultTextColor(QColor(text_color))
        lbl.setPos(lx - lbl.boundingRect().width() / 2,
                   ly - lbl.boundingRect().height() / 2)
        lbl.setZValue(_Z_CUSP_LABEL)
        scene.addItem(lbl)


def _draw_ring_degree_ruler(view, ring_inner, ring_outer, base_z):
    """Draw the 10/5/1 degree ruler inside the ring band (4.1 containment).

    Same tick logic as WheelView._draw_degree_ruler, but the ticks grow INWARD
    from the ring outer edge and the number labels sit inside the band, so
    nothing draws beyond ring_outer (containment invariant).
    """
    scene = view.scene
    cx, cy = view.cx, view.cy
    rotation_offset = view.rotation_offset
    zoom_factor = view.zoom_factor

    tick_outer = ring_outer - _RULER_EDGE_INSET  # outer end of every tick
    label_r = ring_outer - _RULER_LABEL_INSET

    for deg in range(360):
        visual_angle = (deg + rotation_offset) % 360
        deg_in_sign = deg % 30

        if deg_in_sign % 10 == 0:
            tick_len = _TICK_MAJOR
            tick_type = "major"
            if deg_in_sign in (10, 20) and zoom_factor >= _RULER_LABEL_ZOOM_GATE:
                lx, ly = polar_to_cartesian(cx, cy, label_r, visual_angle)
                label = QGraphicsTextItem(str(deg_in_sign))
                label.setFont(scaled_area_font('chart_labels', family='Inter'))
                label.setDefaultTextColor(QColor(_RULER_COLOR))
                label.setPos(lx - label.boundingRect().width() / 2,
                             ly - label.boundingRect().height() / 2)
                label.setZValue(base_z)
                scene.addItem(label)
        elif deg_in_sign % 5 == 0:
            tick_len = _TICK_MINOR
            tick_type = "minor"
        elif zoom_factor >= _MICRO_ZOOM_GATE:
            tick_len = _TICK_MICRO
            tick_type = "micro"
        else:
            continue

        # Ticks grow inward: inner end = tick_outer - tick_len, outer end = tick_outer.
        x1, y1 = polar_to_cartesian(cx, cy, tick_outer - tick_len, visual_angle)
        x2, y2 = polar_to_cartesian(cx, cy, tick_outer, visual_angle)
        item = DegreeTickItem(x1, y1, x2, y2, tick_type)
        item.setZValue(base_z)  # override the item's default z (3) to clear the natal ruler
        scene.addItem(item)


def _draw_ring_planets(view, planets_data, ring_inner, base_z,
                       line_color, tooltip_prefix):
    """Place full-size icons, element-colored indicator lines, and natal labels.

    Planet placement reuses the natal collision-avoidance algorithm
    (calculate_band_positions) mapped onto the ring planet zone (4.1):
    min_r = ring_inner + 30, max_r = ring_inner + 290.
    """
    from .wheel_view import calculate_band_positions

    scene = view.scene
    cx, cy = view.cx, view.cy
    rotation_offset = view.rotation_offset

    # Planet name set (outer planets filtered at render time by show_outer_planets, 4.4).
    planet_names = ["Sun", "Moon", "Mars", "Mercury", "Jupiter",
                    "Venus", "Saturn", "Rahu", "Ketu"]
    if view.show_outer_planets:
        planet_names.extend(["Uranus", "Neptune", "Pluto"])

    # Assemble planet dicts (degrees + sign_index for placement, deg_in_sign + name
    # for the natal label path). Ascendant is drawn separately.
    planets_list = []
    for name in planet_names:
        if name not in planets_data:
            continue
        deg = planets_data[name].get("decimal_degrees", 0)
        # Sign index from the Chart object when available (no manual sign math,
        # SPEC-ZOD-002); fall back to the raw longitude bucket otherwise.
        if view._transit_planets and name in view._transit_planets:
            sign_index = (view._transit_planets[name].sign() - 1) % 12
        elif view._outer_rim_planets and name in view._outer_rim_planets:
            sign_index = (view._outer_rim_planets[name].sign() - 1) % 12
        else:
            sign_index = int(deg / 30) % 12
        planets_list.append({
            "name": name,
            "degrees": deg,
            "deg_in_sign": deg % 30,
            "sign_index": sign_index,
        })

    if not planets_list:
        return

    # Natal placement algorithm mapped onto the ring planet zone.
    positions = calculate_band_positions(
        planets_list,
        ring_inner + _PLANET_ZONE_INNER,
        ring_inner + _PLANET_ZONE_OUTER,
        cx, cy, rotation_offset,
    )

    line_settings = view.display_settings.get("indicator_line", {})
    glow_radius = line_settings.get("glow_radius", 40)
    line_width = line_settings.get("line_width", 3)
    planet_sizes = view.display_settings.get("planet_sizes", {})

    for planet, (x, y, radius, label_offset) in positions:
        # Indicator line: from the icon to the true position at the ring inner
        # radius (D5). ALWAYS element-colored by the planet's sign, exactly like
        # the natal wheel's planet lines (Varuna -> blue, etc.). Per D12 the full
        # ring derives from the wheel, NOT the miniature; the miniature's fixed
        # line_color (e.g. the custom-rim eclipse orange #FF8C00) is miniature
        # visual vocabulary and must not leak into the full path, so line_color is
        # intentionally ignored here for the lines.
        true_angle = get_planet_angle(planet["degrees"], rotation_offset)
        inner_x, inner_y = polar_to_cartesian(cx, cy, ring_inner, true_angle)
        line = PlanetIndicatorLine(
            x, y, inner_x, inner_y, sign_index=planet["sign_index"],
            glow_intensity=glow_radius, line_width=line_width,
        )
        line.setZValue(base_z + 0.3)
        scene.addItem(line)

        # Full-size icon, tooltip-only (plain pixmap item, NOT clickable PlanetItem).
        planet_size = planet_sizes.get(planet["name"], 120)
        pixmap = view.load_planet_image(planet["name"], size=planet_size)
        if pixmap:
            icon = QGraphicsPixmapItem(pixmap)
            icon.setPos(x - planet_size / 2, y - planet_size / 2)
            icon.setZValue(base_z + 1.0)
            icon.setToolTip(
                f"{tooltip_prefix} {planet['name']}: {planet['degrees'] % 30:.1f}° "
                f"({planet['degrees']:.1f}° abs)"
            )
            scene.addItem(icon)

        # Label via the natal planet_degrees path (font/color/weight/offsets, F10,
        # sign_language). Natal offsets the label 51 px below the icon.
        view._draw_planet_label(x, y + 51, planet, label_offset)
