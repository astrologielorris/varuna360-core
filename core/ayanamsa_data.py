#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
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
#   id: Swiss Ephemeris constant (0-46), or custom: 98, 100, 999
#   category: Used for grouping in the dialog
#   tooltip: Rich description shown on hover

AYANAMSA_OPTIONS = [
    # ── Custom Equatorial ──
    (98, "Dhruva GC mid-Mula", "Custom Equatorial",
     "Equatorial system centering Mula nakshatra on Galactic Center (Sgr A*). "
     "Custom calculation using equatorial coordinates. Equal nakshatras (13\u00b020')."),
    (100, "Vedanga Jyotisha", "Custom Equatorial",
     "Ancient Vedic system aligning Dhanishta with winter solstice (Uttarayana). "
     "Based on Vedanga Jyotisha texts (ca. 1400 BCE). Equatorial coordinates."),
    (999, "Tropical (0\u00b0)", "Custom Equatorial",
     "No sidereal correction. Uses tropical Moon longitude directly. "
     "Western astrology standard."),

    # ── Standard Sidereal (most commonly used) ──
    (1, "Lahiri", "Standard Sidereal",
     "Official Indian government standard since 1955. N.C. Lahiri Chitrapaksha. "
     "Fixes Spica near 0\u00b0 Libra. ~23\u00b051' at J2000."),
    (27, "True Citra", "Standard Sidereal",
     "Fixes Spica at exactly 180\u00b0 always, accounting for proper motion. "
     "More precise than Lahiri by 30-60 arcseconds."),
    (5, "Krishnamurti (KP)", "Standard Sidereal",
     "K.S. Krishnamurti's ayanamsa used in the KP system. "
     "Very close to Lahiri with minor differences."),
    (3, "Raman", "Standard Sidereal",
     "B.V. Raman's ayanamsa. Based on Surya Siddhanta with fixed starting point. "
     "Smaller than Lahiri by about 2\u00b0."),
    (4, "Usha/Shashi", "Standard Sidereal",
     "Usha and Shashi ayanamsa. Close to Lahiri."),
    (2, "De Luce", "Standard Sidereal",
     "Robert DeLuce's ayanamsa for Western sidereal astrology."),
    (0, "Fagan/Bradley", "Standard Sidereal",
     "Cyril Fagan and Donald Bradley's ayanamsa. "
     "Foundation of Western sidereal astrology. Fixes Spica at 29\u00b006' Virgo."),
    (6, "Djwhal Khul", "Standard Sidereal",
     "Based on the writings attributed to Djwhal Khul."),
    (7, "Yukteshwar", "Standard Sidereal",
     "Sri Yukteshwar's ayanamsa from 'The Holy Science' (1894). "
     "Based on a 24,000-year precessional cycle."),
    (8, "J.N. Bhasin", "Standard Sidereal",
     "J.N. Bhasin's ayanamsa. Used in some North Indian traditions."),

    # ── Historical ──
    (21, "Aryabhata", "Historical",
     "Based on Aryabhata's astronomical treatise (499 CE). "
     "One of the earliest documented Indian ayanamsas."),
    (22, "Aryabhata (mean Sun)", "Historical",
     "Aryabhata's system using mean Sun instead of true Sun."),
    (25, "Surya Siddhanta", "Historical",
     "From the Surya Siddhanta text. Citra at 0\u00b0 Libra, "
     "using the text's own precessional rate."),
    (26, "Surya Siddhanta (mean Sun)", "Historical",
     "Surya Siddhanta using mean Sun position."),
    (17, "Hipparchos", "Historical",
     "Based on Hipparchos' star catalog (~130 BCE). "
     "One of the earliest Western measurements of precession."),
    (15, "Babylonian (Kugler 1)", "Historical",
     "Peter Kugler's first Babylonian ayanamsa reconstruction."),
    (16, "Babylonian (Kugler 2)", "Historical",
     "Peter Kugler's second Babylonian ayanamsa variant."),
    (13, "Babylonian (Kugler 3)", "Historical",
     "Peter Kugler's third Babylonian ayanamsa variant."),
    (11, "Babylonian (Huber)", "Historical",
     "Peter Huber's Babylonian ayanamsa reconstruction."),
    (9, "Babylonian (Mercier)", "Historical",
     "Raymond Mercier's Babylonian ayanamsa reconstruction."),
    (14, "Babylonian (Eta Piscium)", "Historical",
     "Babylonian system based on Eta Piscium."),
    (10, "Aldebaran at 15\u00b0 Tau", "Historical",
     "Fixes Aldebaran at exactly 15\u00b0 Taurus."),

    # ── Galactic ──
    (18, "Galactic Center 0\u00b0 Sag", "Galactic",
     "Places the Galactic Center at 0\u00b0 Sagittarius. "
     "Based on the Milky Way's central point."),
    (20, "Galactic Eq. IAU 1958", "Galactic",
     "Based on the IAU 1958 definition of the galactic coordinate system."),
    (19, "Galactic Eq. True", "Galactic",
     "Uses the true galactic equator as reference."),
    (34, "GC mid-Mula (Wilhelm)", "Galactic",
     "Ernst Wilhelm's Galactic Center mid-Mula ayanamsa. "
     "Centers Mula nakshatra on the Galactic Center using ecliptic coordinates."),
    (36, "GC mid-Mula (Cochrane)", "Galactic",
     "David Cochrane's variant of Galactic Center mid-Mula ayanamsa."),

    # ── Suryasiddhantic / Revati ──
    (23, "SS Revati", "Revati-based",
     "Surya Siddhanta system fixing the star Revati (Zeta Piscium) "
     "at the beginning of Aries."),
    (24, "SS Citra", "Revati-based",
     "Surya Siddhanta system fixing star Citra (Spica) at 180\u00b0."),
    (28, "True Pushya (PVRN Rao)", "Revati-based",
     "P.V.R. Narasimha Rao's True Pushya ayanamsa. "
     "Fixes Pushya nakshatra star at its traditional position."),
    (29, "True Revati", "Revati-based",
     "Fixes the star Revati (Zeta Piscium) at exactly 359\u00b050'."),
    (30, "True Mula (Chandra Hari)", "Revati-based",
     "Chandra Hari's True Mula ayanamsa, centered on Mula's principal star."),

    # ── Modern / Specialized ──
    (12, "Sassanian", "Modern / Specialized",
     "Based on Sassanian-era Persian astronomical tradition."),
    (31, "Dhruva GC mid-Mula", "Modern / Specialized",
     "Swiss Ephemeris #31: Galactic Center aligned to mid-Mula nakshatra. "
     "Ecliptic projection of our custom #98 equatorial version."),
    (32, "Lahiri (1940)", "Modern / Specialized",
     "Lahiri ayanamsa as defined by the Indian Calendar Reform Committee in 1940."),
    (33, "Lahiri (VP285)", "Modern / Specialized",
     "Lahiri ayanamsa variant VP285."),
    (35, "Aryabhata (522 CE)", "Modern / Specialized",
     "Aryabhata ayanamsa recalculated for 522 CE epoch."),
    (37, "Sunil Sheoran", "Modern / Specialized",
     "Sunil Sheoran's ayanamsa for Vedic astrology."),
    (38, "Ingress of Revati (Surya S.)", "Modern / Specialized",
     "Based on the ingress of Revati star per Surya Siddhanta."),
    (39, "Lahiri (ICRC)", "Modern / Specialized",
     "Lahiri as defined by the Indian Calendar Reform Committee. "
     "Slight variant from standard Lahiri."),
    (40, "True Pushya (Paksha)", "Modern / Specialized",
     "Pushya-paksha ayanamsa. Nakshatra-based system."),
    (41, "J2000", "Modern / Specialized",
     "Standard astronomical J2000.0 epoch (January 1, 2000, 12:00 TT). "
     "Used as reference in modern astronomy."),
    (42, "J1900", "Modern / Specialized",
     "Standard astronomical J1900.0 epoch."),
    (43, "B1950", "Modern / Specialized",
     "Besselian epoch 1950.0. Former standard astronomical reference."),
    (44, "Surya Siddhanta (Citra @ 180)", "Modern / Specialized",
     "Surya Siddhanta fixing Citra (Spica) at exactly 180\u00b0."),
    (45, "Lahiri (true Citra @ 180)", "Modern / Specialized",
     "Lahiri variant where true Citra is fixed at 180\u00b0, "
     "accounting for Spica's proper motion."),
    (46, "Lahiri (Aparajita)", "Modern / Specialized",
     "Aparajita variant of the Lahiri ayanamsa."),
]

# Category display order
CATEGORY_ORDER = [
    "Custom Equatorial",
    "Standard Sidereal",
    "Galactic",
    "Historical",
    "Revati-based",
    "Modern / Specialized",
]

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_ayanamsa_name(ayanamsa_id):
    """Return display name for an ayanamsa ID."""
    for aid, name, _cat, _tip in AYANAMSA_OPTIONS:
        if aid == ayanamsa_id:
            return name
    return f"Ayanamsa #{ayanamsa_id}"


def get_ayanamsa_tooltip(ayanamsa_id):
    """Return tooltip text for an ayanamsa ID."""
    for aid, _name, _cat, tip in AYANAMSA_OPTIONS:
        if aid == ayanamsa_id:
            return tip
    return ""
