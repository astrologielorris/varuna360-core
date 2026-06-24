#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
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


def create_planet_shadow(planet_name=None):
    """Create shadow effect using Chart Display settings.

    Supports global and per-planet shadow overrides from app_settings.json.
    Caller MUST `del` the returned effect after setGraphicsEffect() (Rule #18).

    Args:
        planet_name: Optional planet name for per-planet override lookup.

    Returns:
        QGraphicsDropShadowEffect or None if shadows are disabled.
    """
    from managers.settings_manager import get_settings
    display = get_settings().get_chart_display()
    shadow_settings = display.get("shadow", {})

    # Check if shadows are enabled globally
    if not shadow_settings.get("enabled", True):
        return None

    # Check for per-planet shadow override
    planet_shadows = display.get("planet_shadows", {})
    use_override = (
        planet_name is not None
        and planet_shadows.get("enabled", False)
        and planet_name in planet_shadows
        and planet_shadows[planet_name].get("enabled", False)
    )

    if use_override:
        s = planet_shadows[planet_name]
    else:
        s = shadow_settings

    color = QColor(s.get("color", "#000000"))
    color.setAlpha(s.get("opacity", 120))

    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(s.get("blur_radius", 12))
    effect.setOffset(s.get("offset_x", 4), s.get("offset_y", 4))
    effect.setColor(color)
    return effect
