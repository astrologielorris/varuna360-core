#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Aditya Mode Calculator
Calculates sign positions for both Tropical Classic and Aditya Circle modes.

This module can be invoked standalone to verify calculations:
    python core/aditya_mode.py Lorris.chtk

The same functions are used by the GUI - one source of truth.
"""

import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.i18n import term  # noqa: E402
from core.i18n.languages import ENGLISH  # noqa: E402

# Sign names
ADITYA_NAMES = ['Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
                'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya']

TROPICAL_NAMES = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                  'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']

# Localized Western sign names and planet display names (SPEC-LOC-001, SPEC-PLM-001)
# now live in the i18n catalogs as terms (SPEC-LOC-002 §4.4):
# i18n/<code>/terms/sign.json and planet.json; English is generated from
# TROPICAL_NAMES and the engine planet names. The two names below stay importable
# as plain dicts built from the catalogs on access (never a second copy):
#   LOCALIZED_SIGN_NAMES[code] -> 12 sign names, for each non-English language
#                                 that has its own sign terms ("en" falls back
#                                 to TROPICAL_NAMES, not listed, as before)
#   PLANET_DISPLAY_NAMES[code] -> {planet: name}, for each language with planet terms
# FRENCH_NAMES (backward compat alias) is LOCALIZED_SIGN_NAMES["fr"].


def _languages_with_terms(kind, include_english):
    """Registry languages with their own i18n/<code>/terms/<kind>.json."""
    from core.i18n import languages as langs
    root = langs.data_root()
    return [lang.code for lang in langs.user_languages()
            if (include_english or lang.code != ENGLISH)
            and (root / lang.code / "terms" / f"{kind}.json").is_file()]


# Built once from the catalogs on first access (no load at import), then served
# from memory: cache/chart_index_cache.py reads LOCALIZED_SIGN_NAMES per chart.
# Cleared with the i18n caches (core.i18n.languages.clear_caches), the one
# invalidation entry point. Each access returns a fresh copy, so a caller that
# edits its mapping never changes the cache.
_COMPAT_CACHE = {}


def _build_compat(name):
    from core.i18n.catalog import term_idents
    if name == "LOCALIZED_SIGN_NAMES":
        return {code: tuple(term("sign", i, lang=code) for i in range(12))
                for code in _languages_with_terms("sign", False)}
    return {code: {p: term("planet", p, lang=code) for p in term_idents("planet", code)}
            for code in _languages_with_terms("planet", True)}


def _compat(name):
    table = _COMPAT_CACHE.get(name)
    if table is None:
        table = _COMPAT_CACHE[name] = _build_compat(name)
    return table


def __getattr__(name):
    if name == "LOCALIZED_SIGN_NAMES":
        return {code: list(names) for code, names in _compat(name).items()}
    if name == "PLANET_DISPLAY_NAMES":
        return {code: dict(names) for code, names in _compat(name).items()}
    if name == "FRENCH_NAMES":      # backward compat alias
        return list(_compat("LOCALIZED_SIGN_NAMES")["fr"])
    raise AttributeError(name)


def _register_compat_invalidation():
    from core.i18n import languages as _i18n_languages
    _i18n_languages.on_clear(_COMPAT_CACHE.clear)


_register_compat_invalidation()


# Ordinal equivalence: Division #1 = Dhata = Aries (SPEC-ZOD-001 §4.2)
ADITYA_CIRCLE_TO_WESTERN = {
    'Dhata': 'Aries', 'Aryama': 'Taurus', 'Mitra': 'Gemini',
    'Varuna': 'Cancer', 'Indra': 'Leo', 'Vivasvan': 'Virgo',
    'Tvasta': 'Libra', 'Vishnu': 'Scorpio', 'Amzu': 'Sagittarius',
    'Bhaga': 'Capricorn', 'Pusha': 'Aquarius', 'Parjanya': 'Pisces',
}
# Sky-band conversion: Aditya Circle sign → Tropical Classic sign at same ecliptic region.
# Aditya Circle is -30° from Classic, so Aryama (0-30°) = Classic Dhata (0-30°), etc.
ADITYA_CIRCLE_TO_CLASSIC = {
    'Aryama': 'Dhata', 'Mitra': 'Aryama', 'Varuna': 'Mitra',
    'Indra': 'Varuna', 'Vivasvan': 'Indra', 'Tvasta': 'Vivasvan',
    'Vishnu': 'Tvasta', 'Amzu': 'Vishnu', 'Bhaga': 'Amzu',
    'Pusha': 'Bhaga', 'Parjanya': 'Pusha', 'Dhata': 'Parjanya',
}


def get_sign_index_tropical(decimal_degrees):
    """Get tropical sign index (0-11) from decimal degrees."""
    return int((decimal_degrees % 360) // 30)


def get_sign_index_aditya(decimal_degrees):
    """Get Aditya Circle sign index (0-11) from tropical decimal degrees.

    In Aditya Circle, we add 30° to tropical degrees, then divide by 30.
    This is equivalent to (tropical_index + 1) % 12.

    Example:
        Tropical 50° (Taurus, index 1) → Aditya 80° → index 2 (Mitra)
    """
    aditya_degrees = decimal_degrees + 30
    return int((aditya_degrees % 360) // 30)


def get_sidereal_longitude(tropical_degrees, ayanamsa_offset):
    """Convert tropical longitude to sidereal by subtracting ayanamsa.

    Args:
        tropical_degrees: Tropical ecliptic longitude (0-360)
        ayanamsa_offset: Ayanamsa value in degrees (e.g. ~23.85 for Lahiri)

    Returns:
        float: Sidereal longitude (0-360)
    """
    return (tropical_degrees - ayanamsa_offset) % 360


def get_sign_index_sidereal(decimal_degrees, ayanamsa_offset):
    """Get sidereal sign index (0-11) from tropical decimal degrees.

    Subtracts the ayanamsa offset (~23° for Lahiri) before computing sign.

    Args:
        decimal_degrees: Tropical ecliptic longitude
        ayanamsa_offset: Ayanamsa value in degrees

    Returns:
        int: Sign index 0-11 in sidereal zodiac
    """
    sidereal_degrees = get_sidereal_longitude(decimal_degrees, ayanamsa_offset)
    return int((sidereal_degrees % 360) // 30)


def displayed_sign_name(sign_index, aditya_mode, use_western_names, sign_language="en"):
    """Return the sign LABEL shown to the user for a wheel ordinal (0-11).

    Single source of truth for sign labels, matching the chart wheel
    (apps/widgets/wheel_items.py SignNameItem) exactly. There are only two label
    sets (Aditya names and the Western set), and the choice depends on BOTH the
    zodiac mode and the use_western_names toggle (SPEC-ZOD-001, SPEC-FIND-001):

        use_western_names=True:  Western names (Aries, Taurus ...)
        use_western_names=False: Aditya names (Dhata, Aryama ...)

    sign_language only affects the Western set (term("sign", idx) in that
    language, SPEC-LOC-002; an unknown code reads English). The index is never
    re-mapped (ordinal Dhata = Aries); only the list is swapped.
    """
    idx = sign_index % 12
    show_aditya = not use_western_names
    if show_aditya:
        return ADITYA_NAMES[idx]
    return term("sign", idx, lang=sign_language or ENGLISH)


def get_planet_display_name(lang, planet):
    """Return localized planet name, falling back to English, then raw key
    (a facade over term("planet", ...) with an explicit language)."""
    return term("planet", planet, lang=lang or ENGLISH)


def get_ascendant_sign(pdata, mode="aditya", ayanamsa_offset=0.0):
    """Get the ascendant sign name for a given mode.

    Args:
        pdata: Renderer dict (legacy) keyed by planet name → planet info dict.
        mode: "aditya" for Aditya Circle, "tropical_classic" for Tropical Classic,
              "sidereal" for Sidereal
        ayanamsa_offset: Ayanamsa value in degrees (only used when mode="sidereal")

    Returns:
        tuple: (sign_name, sign_index, decimal_degrees)
    """
    if "Ascendant" not in pdata:
        return None, None, None

    asc_data = pdata["Ascendant"]
    decimal_degrees = asc_data.get("decimal_degrees", 0)

    if mode == "aditya":
        sign_index = get_sign_index_aditya(decimal_degrees)
        sign_name = ADITYA_NAMES[sign_index]
    elif mode == "sidereal":
        sign_index = get_sign_index_sidereal(decimal_degrees, ayanamsa_offset)
        sign_name = TROPICAL_NAMES[sign_index]
    else:
        sign_index = get_sign_index_tropical(decimal_degrees)
        sign_name = TROPICAL_NAMES[sign_index]

    return sign_name, sign_index, decimal_degrees


def get_planet_sign(planet_info, mode="aditya", ayanamsa_offset=0.0):
    """Get the sign for a planet in the given mode.

    Args:
        planet_info: Dictionary with planet data (must have decimal_degrees)
        mode: "aditya" for Aditya Circle, "tropical_classic" for Tropical Classic,
              "sidereal" for Sidereal
        ayanamsa_offset: Ayanamsa value in degrees (only used when mode="sidereal")

    Returns:
        tuple: (sign_name, sign_index)
    """
    decimal_degrees = planet_info.get("decimal_degrees", 0)

    if mode == "aditya":
        sign_index = get_sign_index_aditya(decimal_degrees)
        sign_name = ADITYA_NAMES[sign_index]
    elif mode == "sidereal":
        sign_index = get_sign_index_sidereal(decimal_degrees, ayanamsa_offset)
        sign_name = TROPICAL_NAMES[sign_index]
    else:
        sign_index = get_sign_index_tropical(decimal_degrees)
        sign_name = TROPICAL_NAMES[sign_index]

    return sign_name, sign_index


def print_chart_signs(pdata, mode="aditya"):
    """Print all planet signs for verification.

    Args:
        pdata: Renderer dict keyed by planet name.
        mode: "aditya" for Aditya Circle, "tropical_classic" for Tropical Classic
    """
    mode_label = "Aditya Circle" if mode == "aditya" else "Tropical Classic"
    print(f"\n{'='*60}")
    print(f"Mode: {mode_label}")
    print(f"{'='*60}")

    # Ascendant
    sign_name, sign_index, degrees = get_ascendant_sign(pdata, mode)
    if sign_name:
        print(f"ASCENDANT: {sign_name} (index {sign_index}) at {degrees:.2f}°")

    # Planets
    planet_order = ["Sun", "Moon", "Mars", "Mercury", "Jupiter",
                    "Venus", "Saturn", "Rahu", "Ketu"]

    print(f"\n{'Planet':<12} {'Sign':<12} {'Index':<6} {'Degrees':<10}")
    print("-" * 45)

    for planet_name in planet_order:
        if planet_name in pdata:
            planet_info = pdata[planet_name]
            sign_name, sign_index = get_planet_sign(planet_info, mode)
            degrees = planet_info.get("decimal_degrees", 0)
            print(f"{planet_name:<12} {sign_name:<12} {sign_index:<6} {degrees:.2f}°")


def load_chart_from_chtk(chtk_path, mode="aditya"):
    """Load a Chart from a CHTK file via BirthDataManager + chart_factory.

    Args:
        chtk_path: Path to CHTK file
        mode: aditya_mode ("aditya"/"tropical_classic"/"sidereal")

    Returns:
        Chart: libaditya Chart object with mode-aware positions.
    """
    from managers.birth_data_manager import BirthDataManager
    from core.chart_factory import build_chart_from_params

    # SPEC-IMPORT-001 §6.1: format-agnostic dispatch (.chtk or .toml).
    bd = BirthDataManager.create_birth_data_from_file(str(chtk_path), canonicalize=False)

    # SPEC-IMPORT-001 §5.3 ("jd wins"): a .toml carries an authoritative,
    # sub-second julian_day. Re-deriving JD from the integer civil fields would
    # truncate that precision, so prefer the stored value (mirrors chart_manager).
    # Single birth-data -> JD home (td-7q5s.3 C1): honors the stored julian_day,
    # else computes via the calendar-aware time_utils.julday. Same rule as
    # chart_manager, so load-from-CHTK and load-from-file cannot drift.
    from core.chart_factory import jd_from_birth_data
    jd = jd_from_birth_data(bd)

    utcoffset = bd.get('utc_offset_hours', 0.0)
    chart = build_chart_from_params(
        jd=jd, lat=bd['latitude'], lon=bd['longitude'],
        mode=mode, utcoffset=utcoffset, ayanamsa=1,
    )
    return chart


def main():
    """Main entry point for standalone invocation."""
    if len(sys.argv) < 2:
        print("Usage: python core/aditya_mode.py <chart.chtk>")
        print("       python core/aditya_mode.py Lorris.chtk")
        sys.exit(1)

    chart_name = sys.argv[1]

    # Find chart file
    chart_path = Path(chart_name)
    if not chart_path.exists():
        # Try in project root
        chart_path = PROJECT_ROOT / chart_name
    if not chart_path.exists():
        # Try in chtk_files folder
        chart_path = PROJECT_ROOT / "chtk_files" / chart_name

    if not chart_path.exists():
        print(f"Error: Chart file not found: {chart_name}")
        sys.exit(1)

    print(f"Loading: {chart_path}")

    chart = load_chart_from_chtk(chart_path)

    if not chart:
        print("Error: Failed to load chart data")
        sys.exit(1)

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from core.chart_factory import chart_to_dict
        pdata = chart_to_dict(chart)

    # Print in both modes for comparison
    print_chart_signs(pdata, mode="tropical_classic")
    print_chart_signs(pdata, mode="aditya")

    # Summary comparison
    print(f"\n{'='*60}")
    print("SUMMARY - Ascendant Comparison")
    print(f"{'='*60}")

    asc_data = pdata["Ascendant"]
    asc_degrees = asc_data["decimal_degrees"]

    tropical_idx = get_sign_index_tropical(asc_degrees)
    aditya_idx = get_sign_index_aditya(asc_degrees)

    print(f"Tropical Degrees:       {asc_degrees:.2f}°")
    print(f"Tropical Sign:          {TROPICAL_NAMES[tropical_idx]} (index {tropical_idx})")
    print(f"Aditya Sign:            {ADITYA_NAMES[aditya_idx]} (index {aditya_idx})")
    print(f"\nExpected shift: Tropical index + 1 = Aditya index")
    print(f"Actual: {tropical_idx} + 1 = {(tropical_idx + 1) % 12} (should equal {aditya_idx})")

    if (tropical_idx + 1) % 12 == aditya_idx:
        print("✓ CORRECT - Shift is working properly")
    else:
        print("✗ ERROR - Shift calculation is wrong!")

    # Now simulate what chart_view.py does
    print(f"\n{'='*60}")
    print("SIMULATING chart_view.py _draw_ascendant_stripe()")
    print(f"{'='*60}")

    # Classic mode — uses raw tropical decimal_degrees
    degrees_classic = asc_data.get("decimal_degrees", 0)
    sign_index_classic = int((degrees_classic % 360) / 30)
    print(f"Classic mode: degrees={degrees_classic:.2f}, sign_index={sign_index_classic}")
    print(f"  -> Cell should be: {TROPICAL_NAMES[sign_index_classic]} / {ADITYA_NAMES[sign_index_classic]}")

    # Zodiac mode — Aditya labels the SIGN (planet.sign() in libaditya), the
    # raw tropical degree is unchanged. Issue 14 retired the +30° "azd" shim.
    sign_index_zodiac = (sign_index_classic + 1) % 12
    print(f"Zodiac mode: tropical degrees={degrees_classic:.2f}, aditya sign_index={sign_index_zodiac}")
    print(f"  -> Cell should be: {ADITYA_NAMES[sign_index_zodiac]}")

    # Regression test removed: it depended on the legacy raw-dict path that
    # Issue 14 retires. The Chart-API equivalent is to construct a chart
    # without TZ conversion and compare; that path is exercised by
    # test/ test files now, not by this CLI.


if __name__ == "__main__":
    main()
