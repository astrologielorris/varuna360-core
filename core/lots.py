# -*- coding: utf-8 -*-
"""Hellenistic lots (Arabic parts): Fortune and Spirit, with sect.

Pure module — no Qt, no GUI, no chart objects. Everything here operates on
tropical ecliptic longitudes in degrees (0..360). A lot is a *longitude*, not a
sign: the difference of two longitudes is identical in every zodiac system, so
Fortune and Spirit are frame-independent. Only later, when a lot seeds Zodiacal
Releasing, is it mapped to a sign POSITION in the chart's active mode
(SPEC-ZR-001 §3.2, §9).

Contract (SPEC-ZR-001 §3.2, decisions D-9):

    is_day_chart(sun_lon, asc_lon) -> bool
        Diurnal iff 180 <= (sun_lon - asc_lon) % 360 < 360.
        This is a horizon-arc test on ecliptic longitude, NOT whole-sign house
        membership: the Sun is above the horizon (day) when it lies in the
        half-circle from the Descendant through the MC to the Ascendant.
        Half-open (D-9): Sun exactly on the Descendant -> DAY,
                         Sun exactly on the Ascendant  -> NIGHT.

    lot_of_fortune(asc, sun, moon, is_day) -> lon
        day:   asc + moon - sun   (mod 360)
        night: asc + sun  - moon  (mod 360)

    lot_of_spirit(asc, sun, moon, is_day) -> lon
        day:   asc + sun  - moon  (mod 360)
        night: asc + moon - sun   (mod 360)

Spirit is the sect-mirror of Fortune about the Ascendant:
    lot_of_spirit(...) == (2 * asc - lot_of_fortune(...)) % 360
for either sect (the day/night formulas swap Sun and Moon), which T-6 uses as a
cross-check.
"""

__all__ = ["is_day_chart", "lot_of_fortune", "lot_of_spirit",
           "LOT_REGISTRY", "LOT_ORDER", "lot_longitude"]


def is_day_chart(sun_lon, asc_lon):
    """Return True for a diurnal (day) chart, False for a nocturnal (night) one.

    Half-open horizon-arc rule (SPEC-ZR-001 D-9):
        180 <= (sun_lon - asc_lon) % 360 < 360  ->  day
    so the Sun exactly on the Descendant (arc 180) is day and exactly on the
    Ascendant (arc 0) is night. There is no tolerance band and no third state.
    """
    arc = (float(sun_lon) - float(asc_lon)) % 360.0
    return 180.0 <= arc < 360.0


def lot_of_fortune(asc, sun, moon, is_day):
    """Lot of Fortune longitude (0..360).

    day:   asc + moon - sun   night: asc + sun - moon   (mod 360)
    """
    asc = float(asc)
    sun = float(sun)
    moon = float(moon)
    if is_day:
        return (asc + moon - sun) % 360.0
    return (asc + sun - moon) % 360.0


def lot_of_spirit(asc, sun, moon, is_day):
    """Lot of Spirit (Daimon) longitude (0..360).

    day:   asc + sun - moon   night: asc + moon - sun   (mod 360)

    Spirit is Fortune's sect-mirror about the Ascendant:
        lot_of_spirit(...) == (2 * asc - lot_of_fortune(...)) % 360
    """
    asc = float(asc)
    sun = float(sun)
    moon = float(moon)
    if is_day:
        return (asc + sun - moon) % 360.0
    return (asc + moon - sun) % 360.0


# ─────────────────────── Hellenistic lots usable as ZR releasers ───────────────────────
# SPEC-ZR-001 v1.1 (2026-08-25). Convention: lot = ASC + A - B, i.e. Valens's
# "distance from B to A, counted from the Ascendant". `night` is the formula
# used when is_day_chart() is False; None means "same as day" (no sect
# reversal). `female` overrides (day, night) for a female native.
# Sources per lot: proprietary_docs/docs/research/2026-08-25-hellenistic-lots-for-zr.md.
# Where aries/Morinus ships the part (Res/Opts/arabic_parts.json) the formula
# matches it exactly (Eros, Children, Union); the rest follow Valens/Paulus.
#
# Body keys resolved from the `lons` dict: asc sun moon mercury venus mars
# jupiter saturn fortune spirit; "aries0"/"taurus0" are the 0° sign points.

LOT_REGISTRY = {
    # Hermetic (Paulus §23), all sect-reversed
    "eros":        {"label": "Eros",        "day": ("venus", "spirit"),   "night": ("spirit", "venus")},
    "necessity":   {"label": "Necessity",   "day": ("fortune", "mercury"), "night": ("mercury", "fortune")},
    "courage":     {"label": "Courage",     "day": ("fortune", "mars"),    "night": ("mars", "fortune")},
    "victory":     {"label": "Victory",     "day": ("jupiter", "spirit"),  "night": ("spirit", "jupiter")},
    "nemesis":     {"label": "Nemesis",     "day": ("fortune", "saturn"),  "night": ("saturn", "fortune")},
    # Topical lots
    "union":       {"label": "Union",       "day": ("venus", "saturn"),    "night": None,
                    "female": (("saturn", "venus"), None)},               # Dorotheus/Paulus, = aries
    "children":    {"label": "Children",    "day": ("saturn", "jupiter"),  "night": ("jupiter", "saturn")},  # = aries
    "journeys":    {"label": "Journeys",    "day": ("mars", "saturn"),     "night": None},   # Valens II.29 Foreign Lands
    "intercourse": {"label": "Intercourse", "day": ("venus", "sun"),       "night": None,
                    "female": (("mars", "moon"), None)},                  # Valens II.38
    "exaltation":  {"label": "Exaltation",  "day": ("aries0", "sun"),      "night": ("taurus0", "moon"),
                    "whole_sign": True},                                   # Valens II.18, counted in SIGNS (II.21)
}

LOT_ORDER = ("eros", "necessity", "courage", "victory", "nemesis",
             "union", "children", "journeys", "intercourse", "exaltation")


def lot_longitude(name, lons, is_day, gender=None):
    """Longitude (0..360) of LOT_REGISTRY[name] from a dict of tropical
    longitudes. `lons` must hold asc/sun/moon; fortune and spirit are derived
    if absent; the planets the formula names must be present (KeyError
    otherwise, never a silent 0). `gender` "Female" (case-insensitive) picks
    the female form for gendered lots; anything else uses the male form
    (Valens gives the male form first; Unknown falls back to it)."""
    spec = LOT_REGISTRY[name]
    lons = {k.lower(): float(v) for k, v in lons.items()}
    lons.setdefault("aries0", 0.0)
    lons.setdefault("taurus0", 30.0)
    if "fortune" not in lons:
        lons["fortune"] = lot_of_fortune(lons["asc"], lons["sun"], lons["moon"], is_day)
    if "spirit" not in lons:
        lons["spirit"] = lot_of_spirit(lons["asc"], lons["sun"], lons["moon"], is_day)
    day, night = spec["day"], spec["night"]
    if spec.get("female") and str(gender or "").lower().startswith("f"):
        day, night = spec["female"]
    a, b = day if (is_day or night is None) else night
    if spec.get("whole_sign"):
        # Valens counts this lot in whole signs (II.21 examples): the number
        # of signs from B's sign to A's sign, counted from the ASC's sign.
        # Returned as the 0° point of that sign so any degree-based binning
        # lands in it (GPT Sol lots review MAJOR 2).
        sign = lambda x: int(x // 30) % 12
        return float(((sign(lons["asc"]) + sign(lons[a]) - sign(lons[b])) % 12) * 30)
    return (lons["asc"] + lons[a] - lons[b]) % 360.0
