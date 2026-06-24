# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Chart helper functions — convenience wrappers around libaditya Chart API.

Renamed from chart_data_adapter.py during Chart-Everywhere Wave 3 Final.
Dict fallback paths removed. All functions now require libaditya Chart input.
"""

_IAST_TO_ASCII = {
    # Lowercase IAST (libaditya sign_name() output)
    "dhātā": "Dhata",
    "aryamā": "Aryama",
    "mitra": "Mitra",
    "varuṇa": "Varuna",
    "indra": "Indra",
    "vivasvān": "Vivasvan",
    "tvaṣṭā": "Tvasta",
    "viṣṇu": "Vishnu",
    "aṃśu": "Amzu",
    "bhaga": "Bhaga",
    "pūṣā": "Pusha",
    "parjanya": "Parjanya",
    # Title-Case IAST (legacy / other sources)
    "Dhātā": "Dhata",
    "Aryamā": "Aryama",
    "Mitrā": "Mitra",
    "Varuṇa": "Varuna",
    "Indra": "Indra",
    "Vivasvān": "Vivasvan",
    "Tvaṣṭā": "Tvasta",
    "Viṣṇu": "Vishnu",
    "Aṁśu": "Amzu",
    "Aṃśu": "Amzu",
    "Bhaga": "Bhaga",
    "Pūṣā": "Pusha",
    "Parjanya": "Parjanya",
    # ASCII pass-through (already normalized)
    "Dhata": "Dhata", "Aryama": "Aryama", "Mitra": "Mitra",
    "Varuna": "Varuna", "Vivasvan": "Vivasvan", "Tvasta": "Tvasta",
    "Vishnu": "Vishnu", "Amzu": "Amzu", "Pusha": "Pusha",
}

ADITYA_NAMES = ['Dhata', 'Aryama', 'Mitra', 'Varuna', 'Indra', 'Vivasvan',
                'Tvasta', 'Vishnu', 'Amzu', 'Bhaga', 'Pusha', 'Parjanya']

TROPICAL_NAMES = ['Aries', 'Taurus', 'Gemini', 'Cancer', 'Leo', 'Virgo',
                  'Libra', 'Scorpio', 'Sagittarius', 'Capricorn', 'Aquarius', 'Pisces']


def normalize_planet_name(name):
    """Normalize planet name: strip whitespace and title-case."""
    if not isinstance(name, str):
        return str(name) if name is not None else ""
    return name.strip().title()


def _normalize_sign_name(name):
    """Map libaditya IAST -> legacy ASCII; pass-through for already-ASCII names."""
    if not isinstance(name, str):
        return name
    return _IAST_TO_ASCII.get(name, name)


def _is_chart(obj) -> bool:
    """True iff obj is a libaditya Chart-like. Used by pro panels for
    dual-input handling (eclipse_panel, lunar_new_year_panel)."""
    try:
        from libaditya.charts.chart import Chart
        return isinstance(obj, Chart)
    except ImportError:
        return False



def _get_planet_object(chart, name: str):
    """Resolve a planet/angle name on a Chart's rashi(). Returns None if absent."""
    rashi = chart.rashi()
    if name == "Ascendant":
        cusps = rashi.cusps()
        try:
            return cusps[1]
        except (KeyError, IndexError):
            return None
    planets = rashi.planets()
    try:
        return planets[name]
    except (KeyError, AttributeError):
        return None


def get_planet_sign_name(chart, planet_name: str, default: str = "Unknown") -> str:
    """Return the sign name for a planet from a Chart."""
    obj = _get_planet_object(chart, planet_name)
    if obj is None:
        return default
    if not hasattr(obj, "sign_name"):
        return default
    return _normalize_sign_name(obj.sign_name())


def get_planet_aditya_degrees(chart, planet_name: str, default: float = 0.0) -> float:
    """Return the 0-360 Aditya degree value for a planet.

    Computed as (sign() - 1) * 30 + real_in_sign_longitude().
    """
    obj = _get_planet_object(chart, planet_name)
    if obj is None:
        return default
    try:
        return ((obj.sign() - 1) % 12) * 30.0 + obj.real_in_sign_longitude()
    except Exception:
        return default


def get_planet_decimal_degrees(chart, planet_name: str, default: float = 0.0) -> float:
    """Return tropical ecliptic longitude (0-360) for a planet."""
    obj = _get_planet_object(chart, planet_name)
    if obj is None:
        return default
    try:
        return float(obj.ecliptic_longitude())
    except Exception:
        return default


def get_planet_in_sign_longitude(chart, planet_name: str, default: float = 0.0) -> float:
    """Return the within-sign degree (0-30) for a planet."""
    obj = _get_planet_object(chart, planet_name)
    if obj is None:
        return default
    try:
        return float(obj.real_in_sign_longitude())
    except Exception:
        return default


def get_planet_sign_index(chart, planet_name: str, default: int = 0) -> int:
    """Return the 0-11 sign index for a planet (libaditya signs are 1-indexed)."""
    obj = _get_planet_object(chart, planet_name)
    if obj is None:
        return default
    try:
        return (obj.sign() - 1) % 12
    except Exception:
        return default


def has_planet(chart, planet_name: str) -> bool:
    """True if the chart has data for planet_name."""
    return _get_planet_object(chart, planet_name) is not None
