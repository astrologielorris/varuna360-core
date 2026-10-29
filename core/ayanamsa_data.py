#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Ayanamsa Data Module
====================
Pure data constants for ayanamsa options, nakshatra calculation types,
and helper functions. No GUI dependencies.
"""

# ============================================================================
# AYANAMSA OPTIONS DATA
# ============================================================================
# Each entry: (id, display_name, category, tooltip)
#   id: Swiss Ephemeris sidereal mode (0-46), or one of ours: 98, 100, 999,
#       and CUSTOM_AYANAMSA_ID (255, the user's own definition from Settings)
#   display_name: for 0-46 EXACTLY swe.get_ayanamsa_name(id); the id decides the
#       computation, so the name must be the one Swiss Ephemeris computes
#       (pinned by test/test_ayanamsa_labels_match_swiss.py)
#   category: Used for grouping in the dialog
#   tooltip: Rich description shown on hover

CUSTOM_AYANAMSA_ID = 255   # == swe.SIDM_USER; defined in Settings (libaditya.custom_ayanamsa)

AYANAMSA_OPTIONS = [
    # ── Custom Equatorial ──
    (98, "Dhruva GC mid-Mula", "Custom Equatorial",
     "Equatorial system centering Mula nakshatra on the Galactic Center (Sgr A*). "
     "Nakshatras use equatorial coordinates; signs use Swiss #36 "
     "(Dhruva/Gal.Center/Mula, Wilhelm). Equal nakshatras (13°20')."),
    (100, "Vedanga Jyotisha", "Custom Equatorial",
     "Ancient Vedic system aligning Dhanishta with the winter solstice (Uttarayana). "
     "Based on Vedanga Jyotisha texts (ca. 1400 BCE). Equatorial coordinates."),
    (999, "Tropical (0°)", "Custom Equatorial",
     "No sidereal correction. Uses tropical Moon longitude directly. "
     "Western astrology standard."),

    # ── Your own definition ──
    # Its tooltip goes through the i18n API (get_ayanamsa_tooltip; review
    # 2026-10-13 H9), so the row holds none.
    (CUSTOM_AYANAMSA_ID, "Custom ayanamsa", "Custom", ""),

    # ── Standard Sidereal (most commonly used) ──
    (1, "Lahiri", "Standard Sidereal",
     "Official Indian government standard since 1955 (N.C. Lahiri, Chitrapaksha). "
     "Spica near 0° Libra."),
    (27, "True Citra", "Standard Sidereal",
     "Fixes Spica at exactly 180° at every date, following the star's "
     "proper motion."),
    (46, "Lahiri ICRC", "Standard Sidereal",
     "Lahiri as defined by the Indian Calendar Reform Committee."),
    (43, "Lahiri 1940", "Standard Sidereal",
     "Lahiri ayanamsa in its 1940 definition."),
    (44, "Lahiri VP285", "Standard Sidereal",
     "Lahiri variant with the vernal point at 0° Aries in 285 CE."),
    (5, "Krishnamurti", "Standard Sidereal",
     "K.S. Krishnamurti's ayanamsa, used in the KP system. Very close to Lahiri."),
    (45, "Krishnamurti-Senthilathiban", "Standard Sidereal",
     "Krishnamurti ayanamsa as revised by Senthilathiban."),
    (3, "Raman", "Standard Sidereal",
     "B.V. Raman's ayanamsa. Smaller than Lahiri by about 1°27'."),
    (4, "Usha/Shashi", "Standard Sidereal",
     "Usha and Shashi's ayanamsa."),
    (0, "Fagan/Bradley", "Standard Sidereal",
     "Cyril Fagan and Donald Bradley's ayanamsa. Foundation of Western "
     "sidereal astrology. Spica at 29°06' Virgo."),
    (2, "De Luce", "Standard Sidereal",
     "Robert DeLuce's ayanamsa for Western sidereal astrology."),
    (6, "Djwhal Khul", "Standard Sidereal",
     "Based on the writings attributed to Djwhal Khul."),
    (7, "Yukteshwar", "Standard Sidereal",
     "Sri Yukteshwar's ayanamsa from 'The Holy Science' (1894)."),
    (8, "J.N. Bhasin", "Standard Sidereal",
     "J.N. Bhasin's ayanamsa."),
    (39, "\"Vedic\"/Sheoran", "Standard Sidereal",
     "Sunil Sheoran's \"Vedic\" ayanamsa."),

    # ── Galactic ──
    (36, "Dhruva/Gal.Center/Mula (Wilhelm)", "Galactic",
     "Ernst Wilhelm's ayanamsa: the Galactic Center in the middle of Mula "
     "nakshatra. Our Dhruva GC mid-Mula (98) uses it for the signs."),
    (17, "Galact. Center = 0 Sag", "Galactic",
     "Places the Galactic Center at 0° Sagittarius."),
    (40, "Cochrane (Gal.Center = 0 Cap)", "Galactic",
     "David Cochrane's ayanamsa: the Galactic Center at 0° Capricorn."),
    (30, "Galactic Center (Gil Brand)", "Galactic",
     "Rafael Gil Brand's Galactic Center ayanamsa."),
    (31, "Galactic Equator (IAU1958)", "Galactic",
     "Based on the galactic equator as defined by the IAU in 1958."),
    (32, "Galactic Equator", "Galactic",
     "Based on the true galactic equator."),
    (33, "Galactic Equator mid-Mula", "Galactic",
     "The galactic equator placed in the middle of Mula nakshatra."),
    (41, "Galactic Equator (Fiorenza)", "Galactic",
     "Nick Anthony Fiorenza's galactic equator ayanamsa."),
    (34, "Skydram (Mardyks)", "Galactic",
     "Raymond Mardyks' Skydram ayanamsa."),

    # ── Indian texts and fixed stars ──
    (21, "Suryasiddhanta", "Indian Texts & Stars",
     "From the Surya Siddhanta, using the true Sun."),
    (22, "Suryasiddhanta, mean Sun", "Indian Texts & Stars",
     "Surya Siddhanta, using the mean Sun."),
    (23, "Aryabhata", "Indian Texts & Stars",
     "From Aryabhata's astronomy (499 CE), using the true Sun."),
    (24, "Aryabhata, mean Sun", "Indian Texts & Stars",
     "Aryabhata, using the mean Sun."),
    (37, "Aryabhata 522", "Indian Texts & Stars",
     "Aryabhata ayanamsa with its zero point in 522 CE."),
    (25, "SS Revati", "Indian Texts & Stars",
     "Surya Siddhanta frame with the star Revati (Zeta Piscium) at 359°50'."),
    (26, "SS Citra", "Indian Texts & Stars",
     "Surya Siddhanta frame with the star Citra (Spica) at 180°."),
    (28, "True Revati", "Indian Texts & Stars",
     "Fixes the star Revati (Zeta Piscium) at 359°50' at every date."),
    (29, "True Pushya (PVRN Rao)", "Indian Texts & Stars",
     "P.V.R. Narasimha Rao's True Pushya: the star of Pushya fixed at 106°."),
    (35, "True Mula (Chandra Hari)", "Indian Texts & Stars",
     "Chandra Hari's True Mula: the star of Mula fixed at the start of Mula (240°)."),

    # ── Babylonian and Hellenistic ──
    (9, "Babylonian/Kugler 1", "Babylonian & Hellenistic",
     "Franz Xaver Kugler's first Babylonian reconstruction."),
    (10, "Babylonian/Kugler 2", "Babylonian & Hellenistic",
     "Franz Xaver Kugler's second Babylonian reconstruction."),
    (11, "Babylonian/Kugler 3", "Babylonian & Hellenistic",
     "Franz Xaver Kugler's third Babylonian reconstruction."),
    (12, "Babylonian/Huber", "Babylonian & Hellenistic",
     "Peter Huber's Babylonian reconstruction."),
    (13, "Babylonian/Eta Piscium", "Babylonian & Hellenistic",
     "Babylonian frame based on the star Eta Piscium."),
    (14, "Babylonian/Aldebaran = 15 Tau", "Babylonian & Hellenistic",
     "Babylonian frame with Aldebaran at 15° Taurus."),
    (38, "Babylonian/Britton", "Babylonian & Hellenistic",
     "John P. Britton's Babylonian reconstruction."),
    (15, "Hipparchos", "Babylonian & Hellenistic",
     "Based on Hipparchos' star catalogue (about 130 BCE)."),
    (16, "Sassanian", "Babylonian & Hellenistic",
     "Based on the Sassanian Persian tradition."),
    (42, "Vettius Valens", "Babylonian & Hellenistic",
     "Reconstructed from Vettius Valens (2nd century CE)."),

    # ── Astronomical epochs ──
    (18, "J2000", "Astronomical Epochs",
     "Positions referred to the fixed equinox of J2000.0 (offset 0° on "
     "1 January 2000)."),
    (19, "J1900", "Astronomical Epochs",
     "Positions referred to the fixed equinox of J1900.0."),
    (20, "B1950", "Astronomical Epochs",
     "Positions referred to the fixed equinox of B1950.0."),
]

# Category display order
CATEGORY_ORDER = [
    "Custom Equatorial",
    "Custom",
    "Standard Sidereal",
    "Galactic",
    "Indian Texts & Stars",
    "Babylonian & Hellenistic",
    "Astronomical Epochs",
]

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_ayanamsa_name(ayanamsa_id):
    """Return display name for an ayanamsa ID (255: the name set in Settings)."""
    if ayanamsa_id == CUSTOM_AYANAMSA_ID:
        from libaditya.custom_ayanamsa import get_custom_ayanamsa
        return get_custom_ayanamsa()[0]
    for aid, name, _cat, _tip in AYANAMSA_OPTIONS:
        if aid == ayanamsa_id:
            return name
    return f"Ayanamsa #{ayanamsa_id}"


def get_ayanamsa_tooltip(ayanamsa_id):
    """Return tooltip text for an ayanamsa ID (read it here, not from the
    table: the custom ayanamsa's text comes from the i18n API)."""
    if ayanamsa_id == CUSTOM_AYANAMSA_ID:
        from core.i18n import t
        return t("ayanamsa.custom.tooltip",
                 "Your own ayanamsa: a value in degrees at a reference year, moved by "
                 "precession from there. Set its name, value and year in Settings, "
                 "Zodiac & Calculation.")
    for aid, _name, _cat, tip in AYANAMSA_OPTIONS:
        if aid == ayanamsa_id:
            return tip
    return ""


def today_jd():
    """Julian Day (UT) of now."""
    from datetime import datetime, timezone
    import swisseph as swe
    now = datetime.now(timezone.utc)
    return swe.julday(now.year, now.month, now.day,
                      now.hour + now.minute / 60.0 + now.second / 3600.0)


def chart_jd(chart):
    """The chart's Julian Day, or None when there is no chart."""
    try:
        return chart.context.timeJD.jd
    except AttributeError:
        return None


def ayanamsa_offset_deg(ayanamsa_id, jd=None):
    """Degrees the ayanamsa subtracts from tropical longitudes at ``jd`` (default now).

    The engine's own sign offset (core.ayanamsa_offset), nutation included: the exact
    amount between a tropical and a sidereal sign position. 98 shows the Swiss #36
    value its signs use; a negative value (Vedanga 100) is added, not subtracted.
    The nakshatra frames of 98 and 100 (and any id with equatorial nakshatra
    coordinates) are equatorial projections, not one scalar shift, so for nakshatras
    and dasha seeds this is the sign offset only. None when the engine cannot compute it.
    """
    from core.ayanamsa_offset import birth_ayanamsa_offset
    try:
        value = birth_ayanamsa_offset(today_jd() if jd is None else jd, ayanamsa_id)
    except Exception:
        return None
    if value > 180.0:          # e.g. Cochrane 356.8 is a -3.2 shift
        value -= 360.0
    return value


def format_dms(degrees):
    """23.8567 -> 23\u00b051'24\"; negative values keep a minus sign."""
    sign = "-" if degrees < 0 else ""
    total = round(abs(degrees) * 3600)
    d, rem = divmod(total, 3600)
    m, sec = divmod(rem, 60)
    return f"{sign}{d}\u00b0{m:02d}'{sec:02d}\""


def name_with_offset(ayanamsa_id, jd=None):
    """'Lahiri (23\u00b051'24")': the name plus the exact offset at ``jd``."""
    name = get_ayanamsa_name(ayanamsa_id)
    if ayanamsa_id == 999:     # the name already says 0\u00b0
        return name
    value = ayanamsa_offset_deg(ayanamsa_id, jd)
    return name if value is None else f"{name} ({format_dms(value)})"
