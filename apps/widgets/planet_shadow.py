#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Shared Planet Shadow Factory

Creates QGraphicsDropShadowEffect for planet icons using Chart Display settings
from app_settings.json. Supports global and per-planet shadow overrides.

Used by: chart_view.py, wheel_items.py, north_indian_items.py (and via PlanetItem,
also antikythera_map_view.py).

IMPORTANT: Caller MUST `del` the returned effect after setGraphicsEffect()
to avoid a Qt/Python dual-ownership crash. Once Qt owns the effect, the
Python-side reference must be released so the C++ destructor isn't called
twice.
"""
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from PySide6.QtGui import QColor


def resolve_planet_shadow(planet_name=None, display=None):
    """The shadow settings dict that applies to ``planet_name``.

    The per-planet override precedence lives HERE and nowhere else. Any second
    reader that re-implements "per-planet if enabled, else global" will agree
    with this one right up until someone changes one of the two, and the
    disagreement shows as a planet wearing one colour in one view and another
    colour in another — with nothing to say which is right.

    Args:
        planet_name: body name, or None to force the global settings.
        display: an already-fetched ``get_chart_display()`` dict. Pass it when
            resolving several planets in a row: that call deep-merges the whole
            chart-display tree against its defaults on every invocation.

    Returns:
        The settings dict to read, or None when shadows are switched off.
    """
    if display is None:
        from managers.settings_manager import get_settings
        display = get_settings().get_chart_display()

    shadow_settings = display.get("shadow", {})
    if not shadow_settings.get("enabled", True):
        return None

    planet_shadows = display.get("planet_shadows", {})
    use_override = (
        planet_name is not None
        and planet_shadows.get("enabled", False)
        and planet_name in planet_shadows
        and planet_shadows[planet_name].get("enabled", False)
    )
    return planet_shadows[planet_name] if use_override else shadow_settings


def planet_shadow_color(planet_name=None, display=None, fallback="#000000"):
    """The planet's own colour, OPAQUE — the hue without the shadow's alpha.

    This is the colour a body already wears in the chart views, so anything
    else that wants to mark a planet by colour should ask for it here rather
    than carry a table of its own. ``core.aditya_data.PLANET_COLORS`` is a
    different set for a different purpose and is not what the charts draw.

    The stored ``opacity`` is deliberately NOT applied: it is tuned for a
    drop-shadow under an icon, and a caller compositing a glow or a stroke owns
    its own alpha. Returns ``QColor`` — falling back to ``fallback`` when
    shadows are off or the body has no entry (Chiron, Earth, Ecliptic).
    """
    s = resolve_planet_shadow(planet_name, display)
    return QColor((s or {}).get("color") or fallback)


def create_planet_shadow(planet_name=None):
    """Create shadow effect using Chart Display settings.

    Supports global and per-planet shadow overrides from app_settings.json.
    Caller MUST `del` the returned effect after setGraphicsEffect() (Rule #18).

    Args:
        planet_name: Optional planet name for per-planet override lookup.

    Returns:
        QGraphicsDropShadowEffect or None if shadows are disabled.
    """
    s = resolve_planet_shadow(planet_name)
    if s is None:
        return None

    color = QColor(s.get("color", "#000000"))
    color.setAlpha(s.get("opacity", 120))

    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(s.get("blur_radius", 12))
    effect.setOffset(s.get("offset_x", 4), s.get("offset_y", 4))
    effect.setColor(color)
    return effect
