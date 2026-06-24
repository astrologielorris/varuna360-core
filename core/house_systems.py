# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""House system mapping (SPEC-HSY-001).

Single source of truth for converting the settings-stored house system
human key (e.g. "campanus") to the Swiss Ephemeris single-character code
(e.g. "C") that swe.houses() / swe.house_pos() / EphContext.hsys consume.

This lives in a standalone constants module (not chart_factory.py) because
bala_calculator.py also needs the mapping and importing chart_factory there
would risk a circular import in core/ (SPEC-HSY-001 §11).

Representation boundary rule (SPEC-HSY-001 §4.2): all persistent storage
(settings_manager, ChartState, recipes, session data) uses human keys.
SE codes are transient locals produced only by get_house_system_code() at
the point of consumption. No module may store or pass an SE code.
"""

HOUSE_SYSTEM_CODES = {
    "campanus":       "C",
    "placidus":       "P",
    "koch":           "K",
    "equal":          "E",
    "whole_sign":     "W",
    "porphyry":       "O",
    "regiomontanus":  "R",
}


def get_house_system_code(settings_value):
    """Convert a settings house_system human key to a Swiss Ephemeris code.

    Falls back to "C" (Campanus) for unknown/missing values.
    """
    return HOUSE_SYSTEM_CODES.get(settings_value, "C")
