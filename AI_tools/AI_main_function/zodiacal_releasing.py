# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Zodiacal Releasing — application layer (chart loading + engine driving).

Sits between the pure engine (`core/zodiacal_releasing.py`, no chart deps) and
the two front ends that must agree bit-for-bit (Rule 24 / INV-5): the CLI
`pro/AI_tools/cli/show_zodiacal_releasing.py` and the GUI DashaManager (W5b).
Both call `compute_zr(birth_data, ...)`, so the periods can never drift between
them.

Frame handling (SPEC-ZR-001 §3.2, §9): the Lots are computed ONCE from the
chart's TROPICAL Ascendant/Sun/Moon longitudes — a Lot is a longitude, and a
difference of longitudes is identical in every zodiac system. Only the resulting
POSITION goes through `get_sign_index_<mode>`. So Fortune's longitude is the same
in all three modes and only its sign position changes (tropical vs aditya differ
by exactly 1). Positions never come from `lon // 30` (SPEC-ZOD-002).
"""
import datetime

from core.chart_helpers import ascendant_probe, planet_sign_probe
from core.lots import is_day_chart, lot_of_fortune, lot_of_spirit
from core.time_utils import julday
from core.zodiacal_releasing import (
    anchor_jd, build, drill, find_current, format_level,
)

VALID_MODES = ("aditya", "tropical_classic", "sidereal")


def _now_jd():
    now = datetime.datetime.now(datetime.timezone.utc)
    hour = now.hour + now.minute / 60.0 + now.second / 3600.0
    return julday(now.year, now.month, now.day, hour)


def _birth_field(birth_data, local_key, flat_key, default=None):
    """Read a local_* canonical key, falling back to the flat legacy key."""
    v = birth_data.get(local_key)
    if v is None:
        v = birth_data.get(flat_key, default)
    return v


def _tropical_positions(birth_jd_utc, lat, lon):
    """Return (asc_lon, sun_lon, moon_lon) as TROPICAL ecliptic longitudes.

    Uses the same probes the GUI chart is built from (bit-identical to the full
    Chart's longitudes per chart_helpers), always in tropical_classic so the
    values are frame-independent. ascendant_probe returns (sign, in-sign degree);
    the tropical longitude is sign*30 + degree.
    """
    asc_sign, asc_deg = ascendant_probe(birth_jd_utc, lat, lon, "tropical_classic", 100)
    asc_lon = (asc_sign * 30.0 + asc_deg) % 360.0
    sun_lon = planet_sign_probe(birth_jd_utc, lat, lon, "tropical_classic", 100, "Sun")[1] % 360.0
    moon_lon = planet_sign_probe(birth_jd_utc, lat, lon, "tropical_classic", 100, "Moon")[1] % 360.0
    return asc_lon, sun_lon, moon_lon


_LOT_PLANETS = ("Mercury", "Venus", "Mars", "Jupiter", "Saturn")


def _tropical_planet_lons(birth_jd_utc, lat, lon):
    """Tropical longitudes of the five planets the lot formulas use."""
    return {p.lower(): planet_sign_probe(birth_jd_utc, lat, lon, "tropical_classic",
                                        100, p)[1] % 360.0 for p in _LOT_PLANETS}


def _sidereal_ayanamsa_offset(birth_jd_utc, ayanamsa):
    """Birth-specific ecliptic offset shared with chart/search coordinates."""
    from core.ayanamsa_offset import birth_ayanamsa_offset
    return birth_ayanamsa_offset(birth_jd_utc, ayanamsa)



def compute_zr(birth_data, *, mode="aditya", ayanamsa=100, releaser="spirit",
               spirit_shift=True, anchor="birth", horizon_years=150,
               levels=1, on_jd=None):
    """Drive the engine for one chart. Returns a result dict:

        {mode, anchor, tz_offset_hours, birth_jd_utc, start_jd,
         asc_lon, sun_lon, moon_lon, is_day, fortune_lon, spirit_lon,
         releaser, label_token, releaser_pos, fortune_pos, releaser_lon,
         rows: [Period...],       # L1 (+L2 always; +L3/L4 drilled when levels>=3)
         current: {level: index}} # find_current per displayed level
    """
    if mode not in VALID_MODES:
        raise ValueError(f"compute_zr: invalid mode {mode!r}")

    ly = int(_birth_field(birth_data, "local_year", "year"))
    lmo = int(_birth_field(birth_data, "local_month", "month"))
    ld = int(_birth_field(birth_data, "local_day", "day"))
    # ZR is Ascendant-dependent and hour-scale, so an UNKNOWN birth time must not
    # be silently treated as 00:00 (W6 review MAJOR 2). Require at least one time
    # field to be PRESENT (a genuine midnight birth carries hour=0 explicitly);
    # if none is present the caller has no clock and the GUI takes its DD8
    # "needs a birth time" path via this ValueError.
    _time_keys = ("local_hour", "hour", "local_minute", "minute",
                  "local_second", "second")
    if not any(k in birth_data and birth_data.get(k) is not None
               for k in _time_keys):
        raise ValueError("Zodiacal Releasing needs a birth time")
    lh = int(_birth_field(birth_data, "local_hour", "hour", 0) or 0)
    lmi = int(_birth_field(birth_data, "local_minute", "minute", 0) or 0)
    lse = int(_birth_field(birth_data, "local_second", "second", 0) or 0)

    tz = birth_data.get("utc_offset_hours")
    if tz is None:
        tz = birth_data.get("utcoffset", 0.0)
    tz = float(tz or 0.0)
    lat = float(birth_data.get("latitude", 0.0))
    lon = float(birth_data.get("longitude", 0.0))

    hour_decimal = lh + lmi / 60.0 + lse / 3600.0
    birth_jd_local = julday(ly, lmo, ld, hour_decimal)
    birth_jd_utc = birth_jd_local - tz / 24.0
    start_jd = anchor_jd(birth_jd_utc, tz, anchor)

    asc_lon, sun_lon, moon_lon = _tropical_positions(birth_jd_utc, lat, lon)
    day = is_day_chart(sun_lon, asc_lon)
    fortune_lon = lot_of_fortune(asc_lon, sun_lon, moon_lon, day)
    spirit_lon = lot_of_spirit(asc_lon, sun_lon, moon_lon, day)

    inp = {
        "asc_lon": asc_lon, "sun_lon": sun_lon, "moon_lon": moon_lon,
        "mode": mode, "releaser": releaser, "spirit_shift": spirit_shift,
    }
    if str(releaser).startswith("lot:"):
        inp["planet_lons"] = _tropical_planet_lons(birth_jd_utc, lat, lon)
        inp["gender"] = birth_data.get("gender")
    if mode == "sidereal":
        inp["ayanamsa_offset"] = _sidereal_ayanamsa_offset(birth_jd_utc, ayanamsa)

    from core.zodiacal_releasing import resolve_releaser
    resolved = resolve_releaser(inp)

    rows = build(resolved["releaser_pos"], resolved["fortune_pos"], start_jd,
                 horizon_years=horizon_years)

    target = on_jd if on_jd is not None else _now_jd()
    # Drill the L2 that contains the target when the user asked for L3/L4.
    if levels >= 3:
        l2_rows = [r for r in rows if r["level"] == 2]
        idx = find_current(l2_rows, target, level=2)
        if idx < 0 and l2_rows:
            idx = 0
        if 0 <= idx < len(l2_rows):
            drilled = drill(l2_rows[idx], resolved["fortune_pos"])
            if levels == 3:
                drilled = [r for r in drilled if r["level"] == 3]
            rows = rows + drilled

    current = {}
    for lv in range(1, 5):
        i = find_current([r for r in rows if r["level"] == lv], target, level=lv)
        if i >= 0:
            current[lv] = i

    return {
        "mode": mode, "anchor": anchor, "tz_offset_hours": tz,
        "birth_jd_utc": birth_jd_utc, "start_jd": start_jd,
        "asc_lon": asc_lon, "sun_lon": sun_lon, "moon_lon": moon_lon,
        "is_day": day, "fortune_lon": fortune_lon, "spirit_lon": spirit_lon,
        "releaser": releaser, "label_token": resolved["label_token"],
        "lot_label": resolved.get("lot_label"),
        "releaser_pos": resolved["releaser_pos"],
        "fortune_pos": resolved["fortune_pos"],
        "releaser_lon": resolved["releaser_lon"],
        "target_jd": target,
        "rows": rows,
        "current": current,
    }


# ─────────────────────────────── formatting ───────────────────────────────

def format_zr_json(result, use_western=False, date_format=None, convention=None):
    import json
    r = result
    mode = r["mode"]
    tz = r["tz_offset_hours"]
    entries = []
    for lv in (1, 2, 3, 4):
        entries.extend(format_level(r["rows"], lv, now_jd=r["target_jd"],
                                    mode=mode, use_western=use_western,
                                    tz_offset_hours=tz, date_format=date_format,
                                    convention=convention))
    payload = {
        "releaser": r["releaser"],
        "label_token": r["label_token"], "lot_label": r.get("lot_label"),
        "releaser_pos": r["releaser_pos"],
        "fortune_pos": r["fortune_pos"],
        "mode": mode,
        "anchor": r["anchor"],
        "tz_offset_hours": tz,
        "fortune_lon": round(r["fortune_lon"], 6),
        "spirit_lon": round(r["spirit_lon"], 6),
        "releaser_lon": (None if r["releaser_lon"] is None
                         else round(r["releaser_lon"], 6)),
        "is_day": r["is_day"],
        "start_jd": r["start_jd"],
        "birth_jd_utc": r["birth_jd_utc"],
        "periods": r["rows"],
        "entries": entries,
    }
    return json.dumps(payload, indent=2, default=str)


def format_zr_table(result, use_western=False, max_levels=1, date_format=None,
                    convention=None):
    r = result
    mode = r["mode"]
    tz = r["tz_offset_hours"]
    lines = []
    lines.append("Zodiacal Releasing — %s | releaser: %s (%s) | anchor: %s"
                 % (mode, r["releaser"], r["label_token"], r["anchor"]))
    lines.append("Fortune lon %.3f (pos %d)  Spirit lon %.3f  |  %s chart | peaks: from Fortune"
                 % (r["fortune_lon"], r["fortune_pos"], r["spirit_lon"],
                    "day" if r["is_day"] else "night"))
    lines.append("-" * 64)
    for lv in range(1, max_levels + 1):
        entries = format_level(r["rows"], lv, now_jd=r["target_jd"], mode=mode,
                               use_western=use_western, tz_offset_hours=tz,
                               date_format=date_format, convention=convention)
        for e in entries:
            marker = "*" if e["is_current"] else " "
            lines.append("%s L%d %s" % (marker, lv, e["text"]))
    return "\n".join(lines)
