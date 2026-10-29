# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Human labels of the settings (AI setting redesign, td-bztjj, item 5).

Every registry entry carries a label (``Setting.label``). Most entries
declare theirs where they are declared (the Settings row caption, with its
trailing colon). The entries declared without one get it here, applied once
when the registry is built (``core.settings_registry._build``):

- ``CAPTIONS``: the caption the Settings page (or the control) already shows
  for the key, as written there, without its trailing colon;
- ``WRITTEN``: a label written for a key the UI shows no caption for (listed
  in the redesign report, for Lorris's review).

``display_label`` and ``value_label`` give the words the AI setting panel's
confirmation uses (``Changed {label} to {value}.``): the label without a
trailing colon (``PANEL_LABELS`` for a caption that reads oddly off its page), and the value's own label (a choice's label, on or off for
a switch). Qt-free, data only.
"""
from __future__ import annotations

from typing import Any, Dict

from core.settings_registry.font_defaults import FONT_DEFAULTS as _FONT_DEFAULTS

# The Font Sizes page's area captions (ui/settings_tab.py FontSizesSection
# ._AREA_LABELS; test_ai_settings_labels pins the two equal).
FONT_AREA_CAPTIONS: Dict[str, str] = {
    "tabs": "Tab Bar",
    "action_buttons": "Action buttons",
    "sidebar": "Sidebar & Navigation",
    "chart_memory": "Chart Names",
    "panel_titles": "Panel Titles",
    "table_headers": "Table Headers",
    "tables": "Tables & Data",
    "status": "Status & Captions",
    "chart_labels": "Chart Labels",
    "planet_degrees": "Planet Degrees",
    "house_numbers": "House Numbers",
    "cusp_degrees": "Cusp Degrees",
    "info_text": "Info & Descriptions",
    "buttons": "Buttons & Controls",
}

# Captions the UI shows today, without the trailing colon.
CAPTIONS: Dict[str, str] = {
    **{f"display.fonts.{area}": FONT_AREA_CAPTIONS[area] for area, _ in _FONT_DEFAULTS},
    "appearance.theme": "Application Theme",               # Appearance group title
    "chart.additional_bodies": "Additional bodies",        # Chart Display row
    "display.planet_svg_colors": "SVG colors",             # Chart Display row
    "ui.action_bar_v2": "Use classic action bar",          # Appearance row (inverted)
    "ui.panel.aspects_tab": "Aspects panel",               # shares the Aspects row
    "paths.chart_folders": "Chart Folders",                # Folders group title
    "paths.default_folder": "Default Folder",              # Folders row
    "paths.kala_path": "Kala Software",                    # Folders group title
    "paths.screenshot_folder": "Screenshots",              # Pro Paths group title
    "paths.data_dir": "Application Data",                  # Pro Paths group title
}

# Labels written for keys the UI shows no caption for (redesign report).
WRITTEN: Dict[str, str] = {
    "ai.capture_hotkey": "AI capture shortcut",
    "ai.consent_acknowledged": "AI capture consent",
    "ai.task.engine": "AI task engine",
    "ai.task.claude.model": "AI task Claude model",
    "ai.task.claude.effort": "AI task Claude effort",
    "ai.task.codex.model": "AI task Codex model",
    "ai.task.codex.effort": "AI task Codex effort",
    "appearance.font_family": "Old font name (unused)",
    "appearance.font_size_preset": "Old font size preset (unused)",
    "chart.show_aspect_panel": "Rashi aspect panel",
    "chart.show_trimsamsha_degrees": "Trimsamsha degrees",
    "chart.show_tropical_rim": "Tropical rim",
    "chart_display": "South Indian artistic chart details",
    "south_indian_display": "South Indian vector chart details",
    "wheel_display": "Wheel chart details",
    "north_indian_display": "North Indian chart details",
    "dasha.zr.anchor": "Releasing anchor",
    "dasha.zr.show_age": "Releasing ages",
    "display.background": "Chart background",
    "display.planet_variations": "Planet icon variations",
    "display.zodiac_variations": "Sign icon variations",
    "display.varga_in_center": "Divisional chart beside the main chart",
    "newedit.reading_use_ai": "Read dates with AI (New & Edit)",
    "transit.reading_date_use_ai": "Read dates with AI (Transit)",
    "transit.reading_date_auto_confirm": "Confirm read dates at once (Transit)",
    "paths.default_chart_format": "Chart file format",
    "ui.hd_frame_notice_hidden": "Hide the Human Design frame notice",
    "ui.ai_settings_screenshot_notice_hidden": "Hide the screenshot notice",
    "ui.hide_human_design": "Hide the Human Design button",
    "vision.model": "Vision model",
    "zodiac.human_design": "Human Design chart",
    "zodiac.use_western_names": "Western sign names",
    **{f"font_sizes.{name}": f"Old font size: {name.replace('_', ' ')} (unused)"
       for name in ("chart_title", "chart_degree", "chart_planet", "dasha_header",
                    "dasha_body", "button", "label", "heading", "body", "small", "tiny")},
}

# The AI setting panel's words for keys whose Settings caption reads oddly
# out of its page (td-bztjj follow-up, Lorris 2026-10-11: "Left ayanamsa
# (Vimshottari)", "Left panel mode"): the Settings page's own words with the
# place said in plain words. Used by ``display_label`` only (suggestions,
# confirmations, the ask row); the Settings page keeps its captions.
PANEL_LABELS: Dict[str, str] = {
    "dasha.left.ayanamsa_id": "Ayanamsa, left dasha panel",
    "dasha.right.ayanamsa_id": "Ayanamsa, right dasha panel",
    "dasha.left.mode": "Dasha, left dasha panel",
    "dasha.right.mode": "Dasha, right dasha panel",
    "dasha.zr.releaser": "Releaser, Zodiacal Releasing",
    "display.south_indian_style": "South Indian chart style",
    "ui.hd_experience_level": "Experience level, Human Design",
    "chart.show_planet_names": "Under the planets",
    "display.font_scale": "Display scale",
    "display.color_saturation": "Colour saturation",
}

# A switch's two values, as the confirmation says them (written: no caption).
ON, OFF = "on", "off"
# Values whose label is not a registry choice label: the words the control
# shows for them.
VALUE_LABELS: Dict[str, Dict[Any, str]] = {
    # "Use classic action bar" is checked when the new bar is OFF (inverted).
    "ui.action_bar_v2": {True: OFF, False: ON},
    # The Zodiac & Calculation page's zodiac combo names the three systems.
    "zodiac.mode": {"aditya": "Aditya Circle", "tropical_classic": "Tropical Classic",
                    "sidereal": "Sidereal"},
    "ui.panel.aspects_mode": {"vedic": "Aspects (Vedic)", "tajika": "Aspects (Tajika)"},
    "chart.show_planet_names": {True: "Planet names", False: "Degrees"},
}


def label_for(key: str) -> str:
    """The label ``_build`` gives an entry declared without one ("" when
    none is listed)."""
    return CAPTIONS.get(key) or WRITTEN.get(key) or ""


def display_label(key: str) -> str:
    """The setting's label as a sentence names it: its registry label
    without a trailing colon (the key itself only for an unknown key)."""
    from core import settings_registry as registry
    if not isinstance(key, str) or not registry.has(key):
        return str(key)
    if key in PANEL_LABELS:
        return PANEL_LABELS[key]
    label = (registry.get(key).label or label_for(key) or key).strip()
    return label[:-1].rstrip() if label.endswith(":") else label


def _edition_words(key: str):
    """The words function of an AI key's values (the AI setting panel's
    model), registered by the AI capture package (``edition_hooks.VALUE_WORDS``).
    None for any other key, and in Lite, which ships no AI file (SPEC-EDN-002
    P4)."""
    from core import edition_hooks
    return (edition_hooks.resolve(edition_hooks.VALUE_WORDS) or {}).get(key)


def value_label(key: str, value: Any) -> str:
    """The value's words: its choice label, on or off for a switch, else
    the value as the panel shows it (``cli_text`` field rules)."""
    from core import settings_registry as registry
    from core.settings_registry import cli_text
    words = _edition_words(key)              # "ai.setting_panel.model": "<engine>:<model>"
    if words is not None:
        return words(value)
    special = VALUE_LABELS.get(key)
    if special is not None:
        for known, words in special.items():
            if known == value and type(known) is type(value):
                return words
    if isinstance(key, str) and registry.has(key):
        entry = registry.get(key)
        if entry.choices is not None:
            from core.settings_registry.schema import ChoicesRef
            try:
                items = (entry.choices.resolve() if isinstance(entry.choices, ChoicesRef)
                         else entry.choices)
            except Exception:                                     # noqa: BLE001
                items = ()
            for choice in items:
                if choice.value == value and type(choice.value) is type(value) and choice.label:
                    return choice.label
        if isinstance(value, bool):
            return ON if value else OFF
    return cli_text._shown(value)
