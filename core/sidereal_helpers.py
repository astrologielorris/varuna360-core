# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Sidereal Helpers — sign-name constants + sidereal-planet projection.

Extracted from managers/panel_update_manager.py during Phase 4 Wave W0.5.
Four PanelControllers (karakas, strength, avastha, shame) need these helpers
once panel_update_manager dissolves; keeping them as module-level functions
in core/ removes the dependency on the manager being alive.

Pre-mortem fixes embedded:
- pm-20260503-001: get_sign_ruler must outlive panel_update_manager.py — it is
  called by core_gui_qt.py:1834 _get_sign_ruler delegation, plus W2.4 karakas
  controller. Extracting to core/ breaks that coupling cleanly.
- pm-20260503-004: 4 sidereal-aware controllers would have duplicated this
  logic if it stayed inside the manager — single source of truth here.

This module is import-safe: no Qt deps, no instance state.
"""

# Module-level sign name arrays (shared by sidereal-aware controllers + karakas)
ADITYA_NAMES = [
    "Dhata", "Aryama", "Mitra", "Varuna", "Indra", "Vivasvan",
    "Tvasta", "Vishnu", "Amzu", "Bhaga", "Pusha", "Parjanya",
]

TROPICAL_NAMES = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]


def get_sign_ruler(sign: str) -> str:
    """Return the ruling planet for a zodiac sign.

    Accepts either Aditya names (Dhata, Aryama, ...) or Tropical names
    (Aries, Taurus, ...). Returns "Unknown" for any unrecognized input.

    Same rulership table as the original PanelUpdateManager.get_sign_ruler —
    the Aditya-zodiac mapping is the +1-shifted version of Tropical rulership
    (the Aditya-zodiac mapping is +1-shifted from Tropical rulership).
    """
    rulers = {
        # Aditya zodiac names
        "Dhata": "Mars", "Aryama": "Venus", "Mitra": "Mercury",
        "Varuna": "Moon", "Indra": "Sun", "Vivasvan": "Mercury",
        "Tvasta": "Venus", "Vishnu": "Mars", "Amzu": "Jupiter",
        "Bhaga": "Saturn", "Pusha": "Saturn", "Parjanya": "Jupiter",
        # Western zodiac (fallback)
        "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury",
        "Cancer": "Moon", "Leo": "Sun", "Virgo": "Mercury",
        "Libra": "Venus", "Scorpio": "Mars", "Sagittarius": "Jupiter",
        "Capricorn": "Saturn", "Aquarius": "Saturn", "Pisces": "Jupiter",
    }
    return rulers.get(sign, "Unknown")


def compute_ayanamsa_for_dt(dt_utc, ayanamsa_id: int) -> float:
    """Compute the ayanamsa offset (degrees) for an arbitrary UTC datetime.

    Use for events distant from the natal chart (transits, eclipses, returns):
    the natal `chart_ayanamsa_offset` is fixed at birth_jd, but ayanamsa drifts
    ~50 arcsec/year, so reusing it for events years away introduces error
    (~1° per 72 years). Each event gets its own ayanamsa.

    Parameters
    ----------
    dt_utc : datetime
        UTC datetime of the event. Must have year/month/day/hour/minute and
        optionally second.
    ayanamsa_id : int
        Swiss Ephemeris sidereal mode id. 999 = Tropical (returns 0.0).
        98/100 = custom equatorial (falls back to Lahiri ecliptic).

    Returns 0.0 on any error or for tropical mode.
    """
    if dt_utc is None:
        return 0.0
    if ayanamsa_id == 999:
        return 0.0
    try:
        from libaditya import swe
        hour = dt_utc.hour + dt_utc.minute / 60.0 + getattr(dt_utc, 'second', 0) / 3600.0
        jd_ut = swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)
        if ayanamsa_id in (98, 100):
            swe.set_sid_mode(1)
        else:
            swe.set_sid_mode(ayanamsa_id)
        return swe.get_ayanamsa_ut(jd_ut)
    except Exception as e:
        print(f"[WARNING] Failed to compute ayanamsa for {dt_utc}: {e}")
        return 0.0


def make_sidereal_planets(pdata: dict, ayanamsa_offset: float) -> dict:
    """Return a sidereal copy of pdata without mutating the original.

    Shifts decimal_degrees by -ayanamsa_offset, recomputes sign, aditya_zodiac,
    and in-sign degrees/minutes/seconds. The aditya_zodiac field is overwritten
    with the TROPICAL sign name at the sidereal position so that functions that
    hard-code reads of aditya_zodiac (avastha.py, shame.py, dominant.py) receive
    the correct sidereal sign.

    Pure function: same input → same output, no side effects, returns a new dict.

    Chart-Everywhere Issue 14: deprecated. New code paths should construct a
    sidereal Chart via core.chart_factory.build_chart_from_params(mode="sidereal")
    instead of post-hoc shifting a tropical dict. Removed in Issue 11.
    """
    result = {}
    for key, data in pdata.items():
        if not isinstance(data, dict):
            result[key] = data
            continue

        entry = dict(data)  # shallow copy — never mutates original

        if "decimal_degrees" in entry:
            trop = entry["decimal_degrees"]
            sid = (trop - ayanamsa_offset) % 360

            sign_idx = int(sid // 30) % 12
            sign_name = TROPICAL_NAMES[sign_idx]
            deg_in_sign = sid % 30
            d = int(deg_in_sign)
            min_frac = (deg_in_sign - d) * 60
            m = int(min_frac)
            s = round((min_frac - m) * 60)
            if s == 60:
                s = 0
                m += 1
            if m == 60:
                m = 0
                d += 1

            entry["decimal_degrees"] = sid
            entry["sign"] = sign_name
            entry["aditya_zodiac"] = sign_name  # overwrite so avastha/shame read sidereal sign
            entry["degrees"] = d
            entry["minutes"] = m
            entry["seconds"] = s
            # Drop the deprecated +30° key (Chart-Everywhere Issue 14): the
            # input may still carry it from chart_to_renderer_dict; leaving it
            entry.pop("aditya_zodiac_degrees", None)

        result[key] = entry

    return result
