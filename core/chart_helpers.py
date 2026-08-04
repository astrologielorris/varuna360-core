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


def ascendant_probe(jd, lat, lon, mode, ayanamsa):
    """Fast Ascendant-only probe: (0-11 sign index, in-sign degree).

    Builds ONLY the house cusps (one swe.houses_ex2 call via libaditya's Cusps
    object, ~0.3 ms) instead of a full Chart (~59 ms) — a ~130x-200x speedup
    used by the eclipse asc-zone boundary search (td-tagx.7) and the CLI map
    renderers (td-tagx.13). No caching: within one zone draw every (lat, lon)
    pair is unique, so a cache would get zero hits on a first draw.

    Parity with the full-chart Ascendant is exact by construction: the same
    Circle/sysflg/ayanamsa/hsys are baked via
    chart_factory.mode_to_circle_sysflg, and Cusps(ctx)[1] is a Longitude whose
    .sign()/real_in_sign_longitude() are the SAME methods
    get_planet_sign_index()/get_planet_in_sign_longitude() read on the full
    chart's Ascendant. Locked by test/test_ascendant_probe.py across all three
    modes; if that test goes red this fast path is no longer sanctioned under
    the epic sign-matching constraint (SPEC-ECL-001, SPEC-PRO-MIG-001).

    Args:
        jd: Julian Day (float, UTC).
        lat: latitude (positive = north).
        lon: longitude (positive = east).
        mode: "aditya" | "tropical_classic" | "sidereal".
        ayanamsa: ayanamsa id (only consulted when mode == "sidereal").

    Returns:
        (sign_index_0_11, in_sign_degree) on the same basis as
        get_planet_sign_index(chart, "Ascendant") and
        get_planet_in_sign_longitude(chart, "Ascendant").
    """
    from core.chart_factory import mode_to_circle_sysflg
    from libaditya.objects.context import EphContext
    from libaditya.objects.julian_day import JulianDay
    from libaditya.objects.location import Location
    from libaditya.objects.cusps import Cusps

    circle, sysflg, sign_names = mode_to_circle_sysflg(mode)
    ctx = EphContext(
        timeJD=JulianDay(jd, utcoffset=0.0),
        location=Location(lat=lat, long=lon, alt=0, utcoffset=0.0),
        sysflg=sysflg,
        amsha=1,
        ayanamsa=ayanamsa,
        hsys="C",
        circle=circle,
        signize=True,
        toround=(True, 3),
        names_type="mixed",
        sign_names=sign_names,
    )
    asc = Cusps(ctx)[1]  # cusp #1 = Ascendant / lagna
    return ((asc.sign() - 1) % 12, asc.real_in_sign_longitude())


# Lazily-populated planet-name -> Swiss Ephemeris id map. Kept empty at import
# so this module stays swe-free until a probe is actually called (same reason
# ascendant_probe imports swe inside the function). Rahu maps to MEAN_NODE by
# convention (see planet_sign_probe NODE CONVENTION); Ketu is the caller-side
# +180 mirror of Rahu, so it is intentionally absent here.
_PROBE_PLANET_IDS = {}


def _resolve_probe_planet_id(swe, planet_name: str):
    """Resolve a planet name to its Swiss Ephemeris id (MEAN_NODE for Rahu)."""
    if not _PROBE_PLANET_IDS:
        _PROBE_PLANET_IDS.update({
            "Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
            "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
            "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
            "Pluto": swe.PLUTO, "Rahu": swe.MEAN_NODE,
        })
    try:
        return _PROBE_PLANET_IDS[planet_name]
    except KeyError:
        raise ValueError(f"planet_sign_probe: unknown planet {planet_name!r}")


def planet_sign_probe(jd, lat, lon, mode, ayanamsa, planet_name):
    """Fast single-planet probe: (Circle-correct sign index, raw lon, raw speed).

    Companion to ascendant_probe (above). It mirrors ascendant_probe's
    EphContext construction — the same Circle/sysflg/ayanamsa/hsys basis
    chart_factory.mode_to_circle_sysflg bakes — but computes the planet via a
    direct swe.calc_ut call (NOT the Cusps trick), so it works for any planet,
    not just the Ascendant. It issues the identical swe.calc_ut(jd, id,
    sysflg | FLG_SPEED) call the full Chart's planet issues (planets.py
    init_coords), so the raw longitude is bit-identical to the Chart planet's
    ecliptic_longitude(); since varga(1) is the identity, binning both through
    Longitude.amsha_sign_index() cannot diverge (parity is structural, not
    approximate — locked by test/test_planet_probe.py).

    NUMERIC CONTRACT (pm-003/pm-015 — load-bearing for the Wave 3 byte-identical
    baseline gate in placement_reverse_calculator): `longitude_raw`/`speed_raw`
    are the UNROUNDED floats straight from swe.calc_ut ([0][0] / [0][3]). They
    are NEVER routed through celestial_object.speed()/real_in_sign_longitude(),
    which round to 3 dp (context.toround) and would silently drift the frozen
    I7 baselines. The probe supplies the Circle-correct sign LABEL only; the
    numerics stay bit-identical with the legacy swe.calc_ut engine.

    NODE CONVENTION (pm-003): Rahu uses swe.MEAN_NODE and Ketu is its exact
    180-degree mirror (matching placement_reverse_calculator's MEAN_NODE +
    KETU_PSEUDO_ID pattern, the I7 consumer). Do NOT switch nodes to TRUE_NODE:
    parity is measured against the MEAN_NODE frozen numerics, not libaditya's
    TRUE_NODE default — which is exactly why the full-Chart parity test excludes
    the nodes. Ketu's speed equals Rahu's (the rigid 180-mirror derivative).

    Sidereal (mode == "sidereal") replays the exact set_sid_mode preamble the
    Chart's planets run (the 98->36 ayanamsa remap and the 97 true-sidereal
    special case), so the sidereal longitude is ayanamsa-correct by
    construction (downstream this closes td-prb5). Sidereal correctness is
    bounded by the probe parity net; there is no independent oracle.

    Args:
        jd: Julian Day (float, UTC).
        lat: latitude (positive = north).
        lon: longitude (positive = east).
        mode: "aditya" | "tropical_classic" | "sidereal".
        ayanamsa: ayanamsa id (only consulted when mode == "sidereal").
        planet_name: "Sun".."Pluto", "Rahu", "Ketu".

    Returns:
        (sign_index_0_11, longitude_raw, speed_raw) on the same basis as
        get_planet_sign_index(chart, planet_name) for the same mode (nodes
        excepted, see NODE CONVENTION). For Ketu, longitude_raw is the +180
        mirror and speed_raw equals Rahu's.
    """
    from core.chart_factory import mode_to_circle_sysflg
    from libaditya import swe
    from libaditya import constants as const
    from libaditya import utils
    from libaditya.objects.context import EphContext
    from libaditya.objects.julian_day import JulianDay
    from libaditya.objects.location import Location
    from libaditya.objects.longitude import Longitude

    circle, sysflg, sign_names = mode_to_circle_sysflg(mode)

    is_ketu = (planet_name == "Ketu")
    swe_id = swe.MEAN_NODE if is_ketu else _resolve_probe_planet_id(swe, planet_name)

    # Sidereal: replay the exact set_sid_mode preamble chart_factory planets run
    # (planets.py init_coords) so the ayanamsa correction matches the Chart.
    if sysflg == const.SID:
        eff_ayanamsa = 36 if ayanamsa == 98 else ayanamsa
        swe.set_sid_mode(eff_ayanamsa)
        if eff_ayanamsa == 97:
            utils.set_swe_true_sidereal_ayanamsa()

    res = swe.calc_ut(jd, swe_id, sysflg | swe.FLG_SPEED)[0]
    longitude_raw = res[0]
    speed_raw = res[3]
    if is_ketu:
        # Ketu = Rahu's exact 180-degree mirror (KETU_PSEUDO_ID pattern); its
        # speed is the rigid-mirror derivative, i.e. Rahu's speed unchanged.
        longitude_raw = (longitude_raw + 180.0) % 360.0

    ctx = EphContext(
        timeJD=JulianDay(jd, utcoffset=0.0),
        location=Location(lat=lat, long=lon, alt=0, utcoffset=0.0),
        sysflg=sysflg,
        amsha=1,
        ayanamsa=ayanamsa,
        hsys="C",
        circle=circle,
        signize=True,
        toround=(True, 3),
        names_type="mixed",
        sign_names=sign_names,
    )
    sign_index = Longitude(longitude_raw, amsha=1, context=ctx).amsha_sign_index()
    return sign_index, longitude_raw, speed_raw


def has_planet(chart, planet_name: str) -> bool:
    """True if the chart has data for planet_name."""
    return _get_planet_object(chart, planet_name) is not None
