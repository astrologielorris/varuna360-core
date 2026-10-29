# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""DEFAULT_SETTINGS, built from the registry (SPEC-SET-003 W2).

``build_default_settings()`` returns the factory table the SettingsManager has
always used: every PERSISTED registry entry plus the app state below, which is
not a preference and is not registered. Fallback-only entries
(``persisted=False``) are never added: the manager deep-merges this table into
every saved file at load, so an added key would silently land in users' files.
"""
from __future__ import annotations

import copy
from typing import Any, Dict

# App state kept in the factory table (core.settings_registry.APP_STATE_KEYS).
APP_STATE_DEFAULTS: Dict[str, Any] = {
    "version": "2.0",
    "chart": {
        # aspect_split_fraction persists the Body Graph splitter proportion as
        # the LEFT pane's share of the width (float 0-1, or None until the
        # reader drags it). It replaces the old aspect_splitter_sizes, which
        # stored absolute pixels and was written on every drag but read
        # nowhere. A new key rather than a reused one: the stored pixel pairs
        # were produced by the superseded 70/30 default, so honouring them
        # would have resurrected a default nobody chose.
        "aspect_split_fraction": None,
    },
    "ui": {
        "last_active_tab": 0,
        "action_bar_v2_default_migrated": False,     # SPEC-BAR-001 D-15
        "exchange_chain_on_default_migrated": False,  # SPEC-EXCH-002 4.5
        "layout": {"dasha_right_position": "full", "dasha_right_user_rail": False, "info_panels_auto": True, "info_panels_folded": "", "info_stack_fractions": "", "info_magazine_fractions": ""},  # noqa: E501  SPEC-LAYOUT-001 app state; meaning in SPEC-LAYOUT-001 §5
    },
    # Flat dict keyed by full dot-path strings (e.g. "chart.view_type").
    # Value True means the setting is "frozen": runtime changes are not
    # written back, so the stored value survives across restarts.
    # NOTE: intentionally flat — do NOT nest by section. Access it directly
    # via self._settings["locks"][full_dot_path], never via self.get(...).
    "locks": {},
    "windows": {
        "main": {"width": 1920, "height": 1080},
        "last_position": {"x": None, "y": None},
    },
    "defaults": {"aditya_mode": "aditya"},
}

# Top-level order of the historical literal (cosmetic: saved-file key order).
_TOP_ORDER = ("version", "nakshatra_compat", "appearance", "font_sizes", "display",
              "chart", "zodiac", "cot", "dasha", "transit", "ai", "vision", "ui",
              "locks", "windows", "paths", "defaults")


def _merge(base: dict, extra: dict) -> None:
    for key, value in extra.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge(base[key], value)
        elif key in base:
            raise ValueError(f"factory table: {key!r} is both app state and a setting")
        else:
            base[key] = copy.deepcopy(value)


def build_default_settings() -> Dict[str, Any]:
    from core.settings_registry import factory_tree
    merged: Dict[str, Any] = factory_tree()
    _merge(merged, APP_STATE_DEFAULTS)
    ordered = {k: merged.pop(k) for k in _TOP_ORDER if k in merged}
    ordered.update(merged)
    return ordered
