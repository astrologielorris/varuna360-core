"""Co-located DEFAULT_SETTINGS extensions.

These default blocks live here, not inline in `settings_manager.py`, only to keep
that module under its SI-architecture line ceiling (the same co-located-defaults
pattern used for G8). `apply()` merges them into `DEFAULT_SETTINGS` at import
time; the resulting `DEFAULT_SETTINGS` is byte-for-value identical to the inline
literals these blocks replaced (pinned by
`test/test_settings_defaults_ext.py`, which deep-equals against a snapshot of the
pre-move dict). Semantics: none change. Merge only ADDS these keys under their
existing parents (`dasha`, `display`); it never overrides a key the base dict
already sets.
"""

EXT_DEFAULTS = {
    "dasha": {
        # SPEC-DSH-003: dasha year length, per family as in Kala's "Dasa Length"
        # (saura | savana | nakshatra | sidereal). `nakshatra` drives
        # Vimshottari on both panels. `rasi` is stored for the rasi-dasha
        # family (no rasi dasha engine consumes it yet; Zodiacal Releasing keeps
        # its aries-parity arithmetic). Saura is Kala's default and ours.
        "year_length": {"nakshatra": "saura", "rasi": "saura"},
        # Zodiacal Releasing (SPEC-ZR-001 W5b, DESIGN DECISION 6). anchor has no
        # GUI control in v1 (CLI --anchor and settings file only, D-2 open).
        "zr": {"releaser": "spirit", "spirit_shift": True,
               "show_age": False, "anchor": "birth"},
    },
    "display": {
        # Aditya FT (SPEC-ANT-FT-001 §3.8): the Antikythera panel's Earth-fixed
        # frame state, persisted per profile through the settings manager ONLY
        # (never session ui_state or startup_state; Rule 4b — the state lives in
        # the panel/view, not in ChartGUI). The boot deep-merge propagates these
        # keys to existing settings files. asc_deg default is the Yamakoti preset
        # longitude (165°46'E). DISPLAY-ONLY: never affects a calculation.
        "antikythera": {
            "ft": {
                "active": False,
                "preset": "yamakoti",
                "asc_deg": 165.7667,
                "direction": "solar",
                "labels": "aditya",
            }
        },
    },
}


def apply(default_settings):
    """Merge EXT_DEFAULTS into `default_settings` in place, additively.

    Only keys absent from the target's existing sub-dict are added, so a base
    value always wins over an extension; this keeps the merge a pure superset and
    order-independent.
    """
    for top, sub in EXT_DEFAULTS.items():
        target = default_settings.setdefault(top, {})
        for key, value in sub.items():
            target.setdefault(key, value)
    return default_settings
