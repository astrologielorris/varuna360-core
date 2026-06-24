# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Utility: libaditya Chart → legacy planets_data dict.

Produces the same dict shape that planets_calculator.get_all_planets_data()
historically returned, from a pre-built libaditya Chart object.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from libaditya.objects.context import EphContext, Circle
from libaditya.objects.julian_day import JulianDay
from libaditya.objects.location import Location
from libaditya.charts.chart import Chart
from libaditya import constants as const

from core.planets_calculator import (
    format_to_zodiac,
    get_sign_name,
    get_sign_index,
    get_aditya_circle_degrees,
    get_aditya_circle_name,
    get_aditya_classic_name,
    get_house_sign,
    get_calendar_flag,
)


def _deg_to_dms(decimal_degrees):
    """Convert decimal degrees to (degrees, minutes, seconds) within sign."""
    deg_in_sign = decimal_degrees % 30
    d = int(deg_in_sign)
    m_frac = (deg_in_sign - d) * 60
    m = int(m_frac)
    s = round((m_frac - m) * 60)
    if s == 60:
        s = 0
        m += 1
    if m == 60:
        m = 0
        d += 1
    return d, m, s


def _make_body_dict(ecliptic_lon, speed=None):
    """Build the standard per-body sub-dict from an ecliptic longitude."""
    sign_idx = get_sign_index(ecliptic_lon)
    d, m, s = _deg_to_dms(ecliptic_lon)
    result = {
        "decimal_degrees": ecliptic_lon,
        "formatted": format_to_zodiac(ecliptic_lon),
        "sign": get_sign_name(ecliptic_lon),
        "degrees": d,
        "minutes": m,
        "seconds": s,
        "aditya_zodiac": get_aditya_circle_name(sign_idx),
        "aditya_classic": get_aditya_classic_name(sign_idx),
        "aditya_zodiac_degrees": get_aditya_circle_degrees(ecliptic_lon),
    }
    if speed is not None:
        result["speed"] = speed
        result["is_retrograde"] = speed < 0
    return result


def chart_to_planets_data(chart, year, month, day, hour, minute,
                          lat, lon, timezone_str, second=0):
    """
    Convert a libaditya Chart into the legacy planets_data dict.

    Takes a pre-built Chart (caller handles construction) plus the original
    birth parameters for metadata fields.
    """
    try:
        rashi = chart.rashi()

        # UTC conversion for metadata
        if year < 1:
            utc_year, utc_month, utc_day = year, month, day
            utc_hour, utc_minute, utc_second = hour, minute, second
            bce_year = 1 - year
            local_time_str = f"{bce_year} BCE-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"
            utc_time_str = (f"{1-utc_year} BCE-{utc_month:02d}-{utc_day:02d} "
                            f"{utc_hour:02d}:{utc_minute:02d} UTC")
        else:
            local_dt = datetime(year, month, day, hour, minute, second,
                                tzinfo=ZoneInfo(timezone_str))
            utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
            local_time_str = local_dt.strftime('%Y-%m-%d %H:%M %Z')
            utc_time_str = (f"{utc_dt.year}-{utc_dt.month:02d}-{utc_dt.day:02d} "
                            f"{utc_dt.hour:02d}:{utc_dt.minute:02d} UTC")

        # Top-level metadata
        results = {
            "year": year,
            "month": month,
            "day": day,
            "hour": hour,
            "minute": minute,
            "second": second,
            "local_time": local_time_str,
            "utc_time": utc_time_str,
            "timezone": timezone_str,
            "latitude": lat,
            "longitude": lon,
            "julian_day": float(chart.context.timeJD.jd),
        }

        # Ascendant (Cusp 1)
        asc = rashi.cusps()[1]
        asc_lon = asc.ecliptic_longitude()
        results["Ascendant"] = _make_body_dict(asc_lon)

        # Planets
        planet_order = ["Sun", "Moon", "Mars", "Mercury", "Jupiter",
                        "Venus", "Saturn", "Uranus", "Neptune", "Pluto"]

        planets = rashi.planets()
        for name in planet_order:
            p = planets[name]
            results[name] = _make_body_dict(
                p.ecliptic_longitude(),
                speed=p.longitude_speed(),
            )

        # Rahu and Ketu
        rahu = planets["Rahu"]
        rahu_lon = rahu.ecliptic_longitude()
        rahu_speed = rahu.longitude_speed()
        results["Rahu"] = _make_body_dict(rahu_lon, speed=rahu_speed)

        ketu = planets["Ketu"]
        ketu_lon = ketu.ecliptic_longitude()
        results["Ketu"] = _make_body_dict(ketu_lon, speed=-rahu_speed)
        results["Ketu"]["is_retrograde"] = rahu_speed < 0

        # Houses (cusps from chart's house system)
        house_names = [
            "House 1 (Ascendant)", "House 2", "House 3", "House 4 (Imum Coeli)",
            "House 5", "House 6", "House 7 (Descendant)", "House 8",
            "House 9", "House 10 (Midheaven)", "House 11", "House 12"
        ]
        results["houses"] = {}
        cusps = rashi.cusps()
        for i in range(12):
            cusp = cusps[i + 1]
            cusp_lon = cusp.ecliptic_longitude()
            d, m, s = _deg_to_dms(cusp_lon)
            results["houses"][house_names[i]] = {
                "decimal_degrees": cusp_lon,
                "formatted": format_to_zodiac(cusp_lon),
                "sign": get_sign_name(cusp_lon),
                "degrees": d,
                "minutes": m,
                "seconds": s,
            }

        # Angles
        mc = cusps[10]
        mc_lon = mc.ecliptic_longitude()
        dsc_lon = (asc_lon + 180) % 360
        ic_lon = (mc_lon + 180) % 360

        results["angles"] = {
            "Ascendant": results["Ascendant"],
            "Midheaven (MC)": _make_body_dict(mc_lon),
            "Descendant (DSC)": _make_body_dict(dsc_lon),
            "Imum Coeli (IC)": _make_body_dict(ic_lon),
        }
        for angle_name in ["Midheaven (MC)", "Descendant (DSC)", "Imum Coeli (IC)"]:
            results["angles"][angle_name].pop("speed", None)
            results["angles"][angle_name].pop("is_retrograde", None)

        # Whole Sign Houses
        asc_sign_index = get_sign_index(asc_lon)
        results["whole_sign_houses"] = {}
        for house_num in range(1, 13):
            sign_name, sign_index, start_deg, end_deg = get_house_sign(
                asc_sign_index, house_num)
            # SPEC-HSY-001 §7.8: the legacy per-system cusp sub-keys are removed.
            # The per-cusp degrees they carried are now read directly from the
            # Chart (chart.rashi().cusps()), which already reflects the active
            # house system. The local cusp-degree computation is gone as dead code.
            results["whole_sign_houses"][f"House {house_num}"] = {
                "sign": sign_name,
                "sign_index": sign_index,
                "start_degree": start_deg,
                "end_degree": end_deg,
            }

        return results

    except Exception as e:
        return {"error": f"Error calculating planets: {str(e)}"}


def build_chart_from_dict(planets_data):
    """Build a libaditya Chart from a planets_data dict's stored julian_day and location.

    Must match chtk_to_context() settings so chart.varga(N) produces
    identical sign numbers as the primary load path.
    """
    import warnings
    warnings.warn(
        "build_chart_from_dict() is deprecated — Chart objects are passed directly. "
        "Will be deleted in Chart-Everywhere Issue 11.",
        DeprecationWarning, stacklevel=2,
    )
    _utcoffset = planets_data.get("utcoffset", 0.0)
    jd = JulianDay(planets_data["julian_day"], utcoffset=_utcoffset)
    loc = Location(lat=planets_data["latitude"], long=planets_data["longitude"],
                   alt=0, placename="", utcoffset=_utcoffset)
    ctx = EphContext(
        timeJD=jd,
        location=loc,
        sysflg=const.TROP,
        circle=Circle.ADITYA,
        sign_names="adityas",
        signize=True,
        toround=(True, 3),
    )
    return Chart(ctx)


def _varga_to_dict(varga, source_pdata, is_aditya=False):
    """Convert a libaditya Varga object to the legacy renderer-dict shape.

    Moved from apps/core_gui_qt.py (Issue H1, Bug 5) to break the
    core/ → apps/ circular import. Used by chart_factory.varga_to_renderer_dict
    and core_gui_qt._switch_varga during the dict transition.
    Removed in Issue 11 along with the rest of the dict pipeline.
    """
    sign_offset = 2 if is_aditya else 1

    def _project(obj):
        return ((obj.sign() - sign_offset) % 12) * 30 + obj.real_in_sign_longitude()

    results = {}
    for key in ("year", "month", "day", "hour", "minute", "second",
                "local_time", "utc_time", "timezone", "latitude", "longitude",
                "julian_day"):
        if key in source_pdata:
            results[key] = source_pdata[key]

    planet_order = ["Sun", "Moon", "Mars", "Mercury", "Jupiter",
                    "Venus", "Saturn", "Uranus", "Neptune", "Pluto",
                    "Rahu", "Ketu"]
    planets = varga.planets()
    for name in planet_order:
        p = planets[name]
        results[name] = _make_body_dict(_project(p), speed=p.longitude_speed())

    cusps = varga.cusps()
    asc_lon = _project(cusps[1])
    results["Ascendant"] = _make_body_dict(asc_lon)

    house_names = [
        "House 1 (Ascendant)", "House 2", "House 3", "House 4 (Imum Coeli)",
        "House 5", "House 6", "House 7 (Descendant)", "House 8",
        "House 9", "House 10 (Midheaven)", "House 11", "House 12"
    ]
    results["houses"] = {}
    for i in range(12):
        cusp_lon = _project(cusps[i + 1])
        results["houses"][house_names[i]] = {
            "decimal_degrees": cusp_lon,
            "formatted": format_to_zodiac(cusp_lon),
            "sign": get_sign_name(cusp_lon),
        }

    mc_lon = _project(cusps[10])
    dsc_lon = (asc_lon + 180) % 360
    ic_lon = (mc_lon + 180) % 360
    results["angles"] = {
        "Ascendant": results["Ascendant"],
        "Midheaven (MC)": _make_body_dict(mc_lon),
        "Descendant (DSC)": _make_body_dict(dsc_lon),
        "Imum Coeli (IC)": _make_body_dict(ic_lon),
    }

    asc_sign_index = get_sign_index(asc_lon)
    results["whole_sign_houses"] = {}
    for house_num in range(1, 13):
        sign_name, sign_index, start_deg, end_deg = get_house_sign(
            asc_sign_index, house_num)
        results["whole_sign_houses"][f"House {house_num}"] = {
            "sign": sign_name,
            "sign_index": sign_index,
            "start_degree": start_deg,
            "end_degree": end_deg,
        }

    return results
