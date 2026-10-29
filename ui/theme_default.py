# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The factory theme file, for every boot fallback (Lorris, 2026-10-29: Light Blue)."""

from ui.themes import THEME_NAME_TO_FILE


def default_theme_file() -> str:
    """The factory theme's file: ``appearance.theme``'s registry default."""
    from core.settings_registry import default
    return THEME_NAME_TO_FILE[default("appearance.theme")]
