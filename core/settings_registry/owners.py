# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings tab owner sets (SPEC-SET-003 INV-5, INV-15, W3e).

The keys each Settings section's Apply (or Save) writes and its Reset restores,
per edition. Ownership is its own fact: it is NOT the registry ``section``
(grouping for listings) and NOT the W0b control table (which widget changes a
key). Pro General owns neither the compatibility keys (their sub-panel has its
own Apply and Reset) nor ``ui.reduce_motion`` (Core only). Pinned equal to the
C-2 record (test/fixtures/settings_registry/c2_apply_write_sets.json) by
test_settings_registry_w3e.py. A typed section key (``chart_display``) is owned
like a leaf but restored by its own getter, never by ``reset_section``.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

_ZODIAC = frozenset((
    "cot.planet_order", "cot.show_in_chart",
    "dasha.left.ayanamsa_id", "dasha.left.mode", "dasha.right.ayanamsa_id",
    "dasha.right.mode", "dasha.year_length.nakshatra",
    "dasha.zr.anchor", "dasha.zr.releaser", "dasha.zr.spirit_shift",
    "strength.duc_method", "ui.experience_level", "ui.hd_experience_level", "zodiac.ayanamsa_id",
    "zodiac.custom_ayanamsa_name", "zodiac.custom_ayanamsa_value",
    "zodiac.custom_ayanamsa_year", "zodiac.house_system", "zodiac.mode",
    "zodiac.nakshatra_coords", "zodiac.use_western_names"))
_CHART_DISPLAY = frozenset((
    "chart.additional_bodies", "chart.aspect_tour_seconds", "chart.center_degree_numbers",
    "chart.cusp_glow_mode",
    "chart.exchange_chain_on", "chart.exchange_chain_style",
    "chart.planet_glow_mode",
    "chart.rashi_aspect_system",
    "chart.planet_label", "chart.show_element_pies", "chart.show_outer_planets",
    "chart.show_planet_names",
    "chart.retinue_strength_amount", "chart.retinue_strength_light_amount", "chart.retinue_strength_on",
    "chart.retinue_strength_ribbon_style", "chart.retinue_strength_sign_colour",
    "chart.retinue_strength_sign_ribbon", "chart.retinue_strength_source",
    "chart.show_retinue_rings", "chart.tajika_center_min_virupas", "chart.tajika_center_on",
    "chart.vedic_center_min_virupas", "chart.vedic_center_on",
    "chart.view_type", "chart.wheel_house_display",
    "chart_display", "display.additional_body_icon_set", "display.calendar_convention",
    "display.date_format", "display.planet_icon_set", "display.planet_svg_colors",
    "display.sign_display", "display.sign_number_views", "display.south_indian_style",
    "display.south_indian_vector_finish", "ui.panel.aspects_mode", "ui.panel.aspects_tab",
    "ui.panel.karakas_tab", "ui.panel.strength_tab"))
_FONTS = frozenset("display.fonts." + area for area in (
    "action_buttons", "buttons", "chart_labels", "chart_memory", "cusp_degrees",
    "house_numbers", "info_text", "panel_titles", "planet_degrees", "sidebar", "status",
    "table_headers", "tables", "tabs"))
_DISPLAY_SCALE = frozenset(("display.color_saturation", "display.font_scale"))
_AI_PROVIDERS = frozenset(("ai.default_provider", "ai.effort", "ai.local_server", "vision.effort",
                           "vision.model", "vision.provider"))
_SHARED = {"zodiac_calculation": _ZODIAC, "chart_display": _CHART_DISPLAY,
           "fonts": _FONTS, "display_scale": _DISPLAY_SCALE, "ai_providers": _AI_PROVIDERS}

OWNER_SETS: Dict[Tuple[str, str], FrozenSet[str]] = {
    **{(section, ed): keys for section, keys in _SHARED.items() for ed in ("core", "pro")},
    # Core Appearance: the language combo writes at once; Apply writes the rest.
    ("appearance", "core"): frozenset((
        "zodiac.sign_language", "appearance.deep_dark", "defaults.auto_restore_session",
        "ui.action_bar_v2", "ui.reduce_motion", "ui.restore_last_tab",
        "windows.remember_geometry")),
    ("folders", "core"): frozenset(("paths.chart_folders", "paths.default_folder",
                                    "paths.kala_path")),
    ("general", "pro"): frozenset((
        "appearance.deep_dark", "appearance.theme", "defaults.auto_restore_session",
        "ui.action_bar_v2", "ui.restore_last_tab", "windows.remember_geometry",
        "zodiac.sign_language")),
    # The Nakshatra Compatibility sub-panel (shown in Pro General only, D-24).
    ("nakshatra_compat", "pro"): frozenset((
        "nakshatra_compat.mahendra_include_19th", "nakshatra_compat.stree_deergha_scale",
        "nakshatra_compat.total_threshold")),
    ("paths", "pro"): frozenset(("paths.chart_folders", "paths.data_dir",
                                 "paths.default_folder", "paths.kala_path",
                                 "paths.screenshot_folder")),
}
