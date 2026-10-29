# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Value checks named by ``Rules.validate`` (SPEC-SET-003 §3.1, W3e).

Each takes the value and returns True when it may be stored. Structured
values get a real check; a free value (text, a path, a name from a catalog
that changes at run time) is marked free on purpose, so T-1 can tell a free
key from one that was never classified. Engines are imported inside the
check, never at import: the registry stays cheap and engine-free.
"""
from __future__ import annotations

import re
from typing import Any


def free_text(value: Any) -> bool:
    """Any text: a font family, a background id, a dead key with no reader."""
    return isinstance(value, str)


def free_number(value: Any) -> bool:
    """Any number: a key with no control and no range in the GUI."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def path(value: Any) -> bool:
    """A folder or file path; "" is unset. Existence is not checked (an
    external drive can be offline)."""
    return isinstance(value, str)


def catalog_name(value: Any) -> bool:
    """A name from a catalog that changes at run time (AI providers, vision
    providers and models, themes): checked by its catalog at use, never by a
    copied list. None = nothing picked yet (nullable keys)."""
    return value is None or isinstance(value, str)


def text_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def optional_bodies(value: Any) -> bool:
    """A list of optional-body names from the catalog the Settings checkboxes
    are built from (libaditya.optional_bodies.BODIES); an unknown name is
    refused, as get_chart_retinue_rings refuses it. Order and repeats are not
    checked: the consumers keep catalog order and ignore repeats."""
    if not text_list(value):
        return False
    from libaditya.optional_bodies import BODY_BY_NAME
    return all(v in BODY_BY_NAME for v in value)


def text_map(value: Any) -> bool:
    """A dict keyed by names."""
    return isinstance(value, dict) and all(isinstance(k, str) for k in value)


def variation_map(value: Any) -> bool:
    """Name -> variation number, as the pickers store it (an int >= 1,
    planet_dialog.get_selected_variation); the numbers that exist depend on
    the installed image packs, checked at use (td-ieso2, W3e review N6)."""
    return isinstance(value, dict) and all(isinstance(k, str) and type(v) is int and v >= 1
                                           for k, v in value.items())


_ZR_SIGNS = frozenset(f"sign:{i}" for i in range(12))


# --- shortcuts (ai.capture_hotkey): core/settings_registry/shortcut_keys.py --

def shortcut(value: Any) -> bool:
    """One key combination in Qt portable text holding Ctrl, Alt or Meta
    ("Ctrl+Alt+S"), the syntax and modifier rule set_hotkey enforces. Not
    checked here: a clash with the app's other shortcuts, which depends on the
    open window and stays at the application boundary (set_hotkey refuses it)."""
    from core.settings_registry.shortcut_keys import is_shortcut
    return is_shortcut(value)


# --- SVG colours (display.planet_svg_colors) ---------------------------------
# One Qt-free check shared with the app's cleaner
# (apps/widgets/planet_icon_palette.clean_scheme, behind colors_from).

def rgb_color(value: Any) -> bool:
    """``#rrggbb``."""
    return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


def color_scheme(value: Any) -> bool:
    """One solid colour, or an ``{"outer": ..., "inner": ...}`` pair (the two
    choices of the Settings SVG colour editor)."""
    if rgb_color(value):
        return True
    return isinstance(value, dict) and rgb_color(value.get("outer")) and rgb_color(value.get("inner"))


def color_schemes(value: Any) -> bool:
    """A dict of name -> colour scheme. A value the cleaner would drop (a list,
    a bad colour) is refused; names are not checked here: the name list lives
    in GUI modules and the cleaner ignores an unknown name."""
    return isinstance(value, dict) and all(
        isinstance(k, str) and color_scheme(v) for k, v in value.items())


def zr_releaser(value: Any) -> bool:
    """Exactly a token the Settings releaser combo offers: ``spirit``,
    ``fortune``, ``lot:<name>`` for each lot in core.lots.LOT_ORDER, or
    ``sign:0`` to ``sign:11`` (SPEC-ZR-001 DD6). Matched as whole tokens, never
    parsed, so no input can raise."""
    if not isinstance(value, str):
        return False
    if value in ("spirit", "fortune") or value in _ZR_SIGNS:
        return True
    if value.startswith("lot:"):
        from core.lots import LOT_ORDER
        return value[4:] in LOT_ORDER
    return False

