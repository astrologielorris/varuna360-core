# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Folder and file settings (SPEC-SET-003). Defaults moved from DEFAULT_SETTINGS["paths"]
and the Pro paths section's OWNED_KEY_DEFAULTS; values unchanged."""
from dataclasses import replace

from core.settings_registry.rules import APP_AI
from core.settings_registry.schema import Choice, Setting

_F = "folders"
_PATH = replace(APP_AI, validate="core.settings_registry.validators:path")

SETTINGS = (
    Setting("paths.chart_folders", list, [], widget="custom", section=_F,
            rules=replace(APP_AI, validate="core.settings_registry.validators:text_list")),
    Setting("paths.default_folder", str, "", widget="path", section=_F, rules=_PATH),
    # SPEC-LIB-001 D-33: the research library. Empty = <Documents>/Varuna360/Library,
    # resolved per OS by core.library.paths.library_root().
    Setting("paths.library_root", str, "", widget="path", section=_F, rules=_PATH,
            label="Library folder"),
    Setting("paths.screenshot_folder", str, "", widget="path", section=_F, rules=_PATH),
    Setting("paths.kala_path", str, "", widget="path", section=_F, rules=_PATH),
    # SPEC-PERSIST-001: the format every NEW chart is written in. "toml"
    # (Open Astrology Chart) or "chtk". This governs writing only —
    # both formats are read, and nothing already on disk is converted.
    Setting("paths.default_chart_format", str, "toml",
            choices=(Choice("toml"), Choice("chtk")), rules=APP_AI),
    # Fallback-only: the Pro paths section owns it, the factory table never had it.
    Setting("paths.data_dir", str, "", persisted=False, widget="path", section=_F,
            edition="pro", rules=_PATH),
)
