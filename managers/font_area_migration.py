# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""One-time carry-over of the retired Chart Display "House number size" (2026-10-08).

The size moved from ``chart_display.house_number.font_size`` (factory 23) to
Font Sizes > House Numbers (``display.fonts.house_numbers``, SPEC-FONT-001
§11.9). A stored old value other than 23 is copied once if the new key is unset.
The file is read raw and BEFORE the manager is built: its in-memory settings
are merged with the factory tree, and its own one-time migrations may save
that tree (23) while built: ``get_settings()`` reads, builds, then applies.
The read-only CLI manager applies it in memory. Kept out of settings_manager.
"""
import json
import os

OLD_FACTORY = 23
NEW_KEY = "display.fonts.house_numbers"
CONFIG_FILE = "app_settings.json"   # SettingsManager.CONFIG_FILE
_BOUNDS = (7, 48)


def _section(node, key):
    """``node[key]`` if both are dicts, else {} (a hand-edited file may hold anything)."""
    value = node.get(key) if isinstance(node, dict) else None
    return value if isinstance(value, dict) else {}


def legacy_house_number_size(raw):
    """The old stored size to carry over, or None (``raw``: the file as stored)."""
    fonts = _section(_section(raw, "display"), "fonts")
    if "house_numbers" in fonts:
        return None
    old = _section(_section(raw, "chart_display"), "house_number").get("font_size")
    try:
        old = int(round(float(old)))
    except (TypeError, ValueError):
        return None
    return None if old == OLD_FACTORY else max(_BOUNDS[0], min(_BOUNDS[1], old))


def pending_house_number_size(config_dir=None):
    """The size to carry over, read from the file before the manager exists."""
    if config_dir is None:
        from state.user_data import get_user_data_dir   # as SettingsManager.__init__
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_dir = str(get_user_data_dir() or project_root)
    try:
        with open(os.path.join(config_dir, CONFIG_FILE), encoding="utf-8") as handle:
            return legacy_house_number_size(json.load(handle))
    except (OSError, ValueError):
        return None


def apply_house_number_size(manager, size):
    """Write the carried-over size (no-op for None). Returns it."""
    if size is not None:
        manager.set(NEW_KEY, size, save=True)
    return size
