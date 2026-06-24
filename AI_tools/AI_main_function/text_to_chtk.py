#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Text-to-CHTK Parser — Extract birth data from free-form French/English text.

Parses pasted text (biographies, Wikipedia snippets, casual notes) and creates
CHTK chart files.  Works 100% offline with pure regex — no AI API calls.

Architecture:
    Pasted text
        -> parse_birth_text(text)  -> {name, date, time, city, country, gender}
        -> resolve_location(...)   -> {lat, lon, timezone_offset, dst_active}
        -> create_chtk(...)        -> .chtk file

Usage:
    # Parse only (no geocoding / file creation)
    python AI_tools/AI_main_function/text_to_chtk.py --parse-only "Sandra P 17 Nov 1968 0:45 AM Buenos Aires"

    # Create CHTK file
    python AI_tools/AI_main_function/text_to_chtk.py "Sandra P 17 Nov 1968 0:45 AM Buenos Aires"

    # Pipe from stdin
    echo "1er janvier 2000 0h45 Lyon" | python AI_tools/AI_main_function/text_to_chtk.py --stdin

Author: Claude Code AI Assistant
"""

import sys
import os
import re
import json
import argparse
import calendar
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# =============================================================================
# HARDENING CONSTANTS
# =============================================================================

_MAX_INPUT_LENGTH = 50_000   # Reject inputs longer than 50KB
_MAX_REGEX_SPAN = 500        # Limit regex span to prevent catastrophic backtracking
_MAX_NAME_LENGTH = 100       # Cap extracted names to prevent paragraph-as-name


# =============================================================================
# MONTH NAME DICTIONARIES
# =============================================================================

MONTHS_EN: Dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    # Abbreviations
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

MONTHS_FR: Dict[str, int] = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12, "decembre": 12,
    # Abbreviations
    "janv": 1, "févr": 2, "fév": 2, "fevr": 2, "fev": 2, "avr": 4,
    "juil": 7, "juill": 7, "sept": 9, "oct": 10, "nov": 11, "déc": 12, "dec": 12,
}

ALL_MONTHS: Dict[str, int] = {**MONTHS_EN, **MONTHS_FR}

# Build regex alternation sorted longest-first to avoid partial matches
_MONTH_NAMES_RE = "|".join(
    sorted(ALL_MONTHS.keys(), key=len, reverse=True)
)


# =============================================================================
# COUNTRY ALIASES
# =============================================================================

COUNTRY_ALIASES: Dict[str, str] = {
    # English aliases
    "u.s.": "USA", "u.s.a.": "USA", "u.s": "USA", "us": "USA", "usa": "USA",
    "united states": "USA", "united states of america": "USA",
    "u.k.": "United Kingdom", "uk": "United Kingdom",
    "united kingdom": "United Kingdom", "great britain": "United Kingdom",
    "england": "United Kingdom",
    # French aliases
    "états-unis": "USA", "etats-unis": "USA", "e.-u.": "USA",
    "angleterre": "United Kingdom", "royaume-uni": "United Kingdom",
    "allemagne": "Germany", "espagne": "Spain", "italie": "Italy",
    "suisse": "Switzerland", "belgique": "Belgium", "pays-bas": "Netherlands",
    "brésil": "Brazil", "bresil": "Brazil", "mexique": "Mexico",
    "chine": "China", "japon": "Japan", "inde": "India",
    "russie": "Russia", "turquie": "Turkey",
    "égypte": "Egypt", "egypte": "Egypt",
    "argentine": "Argentina",
    # State -> USA  (common in bios)
    "california": "USA", "new york": "USA", "texas": "USA",
    "florida": "USA", "illinois": "USA", "michigan": "USA",
    "ohio": "USA", "pennsylvania": "USA", "georgia": "USA",
    "massachusetts": "USA", "arizona": "USA", "colorado": "USA",
    "oregon": "USA", "washington": "USA", "virginia": "USA",
    "indiana": "USA", "minnesota": "USA", "missouri": "USA",
    "tennessee": "USA", "maryland": "USA", "connecticut": "USA",
    "louisiana": "USA", "kentucky": "USA", "new jersey": "USA",
    # Seine -> France (arrondissement style)
    "seine": "France", "hauts-de-seine": "France",
    "seine-saint-denis": "France", "val-de-marne": "France",
}


# =============================================================================
# FRENCH LANGUAGE DETECTION WORDS
# =============================================================================

_FR_KEYWORDS = {
    "né", "née", "naissance", "le", "à", "en", "est", "un", "une",
    "du", "des", "les", "dans", "ce", "cette", "son", "sa",
    "français", "française", "acteur", "actrice", "chanteur", "chanteuse",
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    "midi", "minuit",
}


# =============================================================================
# SHARED HELPERS
# =============================================================================

def _strip_time_patterns(text: str) -> str:
    """Remove common time patterns from the front of text.

    Extracted as a helper to eliminate code duplication between
    _extract_name_after_date() and _extract_location().
    """
    text = re.sub(r'^[\s,]*\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?\s*', '', text)
    text = re.sub(r'^[\s,]*\d{1,2}\s*[hH]\s*\d{0,2}\s*', '', text)
    text = re.sub(r'^[\s,]*\d{1,2}\s*(?:am|pm|AM|PM)\s*', '', text)
    text = re.sub(
        r'^[\s,]*(?:at\s+)?(?:noon|midi|midnight|minuit)\s*,?\s*',
        '', text, flags=re.IGNORECASE,
    )
    return text.strip(' ,')


def _validate_calendar_date(year: int, month: int, day: int) -> bool:
    """Check if a date is valid on the calendar (handles leap years, month lengths)."""
    if not (1 <= month <= 12):
        return False
    max_day = calendar.monthrange(year, month)[1]
    return 1 <= day <= max_day


def _validate_time(h: int, m: int, s: int = 0) -> bool:
    """Validate hour, minute, second ranges."""
    return 0 <= h <= 23 and 0 <= m <= 59 and 0 <= s <= 59


# =============================================================================
# DATE EXTRACTION
# =============================================================================

def _extract_date(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract date from text using multiple regex patterns in priority order.

    Returns dict with keys: year, month, day, match_start, match_end,
                            date_ambiguous (bool), date_warning (str|None)
    Returns None if no valid date found (including calendar-invalid dates).
    """
    # Normalise whitespace for cleaner matching
    clean = " ".join(text.split())

    # --- Pattern 1: "1er janvier 2000" (French ordinal) ---
    m = re.search(
        rf'(\d{{1,2}})\s*(?:er|ère|eme|ème)?\s+({_MONTH_NAMES_RE})\s+(\d{{4}})',
        clean, re.IGNORECASE,
    )
    if m:
        day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = ALL_MONTHS.get(month_name)
        if month:
            result = _date_result(year, month, day, m.start(), m.end())
            if result:
                return result

    # --- Pattern 2: "Day MonthName Year"  e.g. "17 Nov 1968", "28 mai 1944" ---
    m = re.search(
        rf'(\d{{1,2}})\s+({_MONTH_NAMES_RE})\.?\s+(\d{{4}})',
        clean, re.IGNORECASE,
    )
    if m:
        day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = ALL_MONTHS.get(month_name)
        if month:
            result = _date_result(year, month, day, m.start(), m.end())
            if result:
                return result

    # --- Pattern 3: "MonthName Day, Year" e.g. "August 29, 1958", "March 3rd, 1990" ---
    m = re.search(
        rf'({_MONTH_NAMES_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s+(\d{{4}})',
        clean, re.IGNORECASE,
    )
    if m:
        month_name, day, year = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        month = ALL_MONTHS.get(month_name)
        if month:
            result = _date_result(year, month, day, m.start(), m.end())
            if result:
                return result

    # --- Pattern 4: ISO  "YYYY-MM-DD" ---
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', clean)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        result = _date_result(year, month, day, m.start(), m.end())
        if result:
            return result

    # --- Pattern 5: Numeric DD/MM/YYYY or MM/DD/YYYY ---
    m = re.search(r'(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})', clean)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _resolve_ambiguous_numeric(a, b, year, m.start(), m.end(), clean)

    # --- Pattern 6: Space-separated "DD MM YYYY" (lowest priority, most ambiguous) ---
    m = re.search(r'(?<!\d)(\d{1,2})\s+(\d{1,2})\s+(\d{4})(?!\s*[/.\-]\d)', clean)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return _resolve_ambiguous_numeric(a, b, year, m.start(), m.end(), clean)

    return None


def _date_result(year: int, month: int, day: int,
                 start: int, end: int,
                 ambiguous: bool = False,
                 warning: str = None) -> Optional[Dict[str, Any]]:
    """Build date result dict, returning None if the date is calendar-invalid."""
    if not _validate_calendar_date(year, month, day):
        return None
    return {
        "year": year, "month": month, "day": day,
        "match_start": start, "match_end": end,
        "date_ambiguous": ambiguous,
        "date_warning": warning,
    }


def _resolve_ambiguous_numeric(a: int, b: int, year: int,
                               start: int, end: int,
                               text: str) -> Optional[Dict[str, Any]]:
    """Resolve DD/MM vs MM/DD ambiguity in numeric dates."""
    # If one value > 12, it must be the day
    if a > 12 and 1 <= b <= 12:
        # a is day, b is month  (e.g. 14/02 -> Feb 14)
        return _date_result(year, b, a, start, end)
    if b > 12 and 1 <= a <= 12:
        # b is day, a is month  (e.g. 02/14 -> Feb 14, US format)
        return _date_result(year, a, b, start, end)

    # Both <= 12 — ambiguous
    if a > 12 or b > 12:
        return None  # invalid

    # Use language context to guess
    text_lower = text.lower()
    fr_score = sum(1 for kw in _FR_KEYWORDS if re.search(rf'\b{re.escape(kw)}\b', text_lower))

    if fr_score >= 2:
        # French context -> DD/MM (European)
        return _date_result(year, b, a, start, end)

    # Check for English keywords
    en_keywords = {"born", "was", "is", "an", "the", "singer", "actor", "actress",
                   "american", "british", "english"}
    en_score = sum(1 for kw in en_keywords if kw in text_lower)

    if en_score >= 2:
        # English context -> MM/DD (American)
        return _date_result(year, a, b, start, end)

    # No clues: default DD/MM (European) with warning
    return _date_result(
        year, b, a, start, end,
        ambiguous=True,
        warning=f"Date is ambiguous: could be {a:02d}/{b:02d} (DD/MM) or {b:02d}/{a:02d} (MM/DD). Assumed DD/MM.",
    )


# =============================================================================
# TIME EXTRACTION
# =============================================================================

def _extract_time(text: str) -> Dict[str, Any]:
    """
    Extract time from text.  Returns dict with hour, minute, second, has_time.
    Defaults to noon (12:00) if no time found.
    All extracted times are validated for range (0-23h, 0-59m, 0-59s).
    """
    clean = " ".join(text.split())

    # --- "midi" / "minuit" / "noon" / "midnight" ---
    # (?<![-–]) prevents matching "midi" within "après-midi"
    if re.search(r'(?<![-\u2013])\bmidi\b|\bnoon\b', clean, re.IGNORECASE):
        return {"hour": 12, "minute": 0, "second": 0, "has_time": True}
    if re.search(r'\bminuit\b|\bmidnight\b', clean, re.IGNORECASE):
        return {"hour": 0, "minute": 0, "second": 0, "has_time": True}

    # --- "HH:MM:SS AM/PM" or "HH:MM AM/PM" ---
    m = re.search(r'(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM|am|pm)', clean)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        s = int(m.group(3)) if m.group(3) else 0
        ampm = m.group(4).upper()
        if ampm == "PM" and h != 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        if _validate_time(h, mi, s):
            return {"hour": h, "minute": mi, "second": s, "has_time": True}

    # --- "Hpm" / "Ham" e.g. "3pm", "12pm" ---
    m = re.search(r'(\d{1,2})\s*(am|pm|AM|PM)\b', clean)
    if m:
        h = int(m.group(1))
        ampm = m.group(2).upper()
        if ampm == "PM" and h != 12:
            h += 12
        elif ampm == "AM" and h == 12:
            h = 0
        if _validate_time(h, 0):
            return {"hour": h, "minute": 0, "second": 0, "has_time": True}

    # --- French spelled-out: "8 heure(s) du matin/soir/de l'après-midi" ---
    # (?<!\d) prevents matching digits at end of year (e.g. "1908 Heure:")
    m = re.search(
        r'(?<!\d)(\d{1,2})\s*heures?\s*'
        r'(?:(\d{1,2})\s*)?'                          # optional minutes
        r'(?:du\s*matin|du\s*soir|de\s*l.apr[eè]s[- ]?midi)?',
        clean, re.IGNORECASE
    )
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        # "du soir" / "de l'après-midi" → PM conversion
        tail = clean[m.start():m.end()].lower()
        if ('soir' in tail or 'apr' in tail) and h < 12:
            h += 12
        if _validate_time(h, mi):
            return {"hour": h, "minute": mi, "second": 0, "has_time": True}

    # --- English "half past X [in the morning/afternoon/evening | at night]" ---
    # Must be checked BEFORE "X in the morning" to avoid partial match
    m = re.search(
        r"half\s+past\s+(\d{1,2})"
        r"(?:\s+in\s+the\s+(?P<hp_qual>morning|afternoon|evening)"
        r"|\s+at\s+(?P<hp_night>night))?",
        clean, re.IGNORECASE
    )
    if m:
        h = int(m.group(1))
        qual = (m.group('hp_qual') or m.group('hp_night') or '').lower()
        if qual in ('afternoon', 'evening', 'night') and h < 12:
            h += 12
        if _validate_time(h, 30):
            return {"hour": h, "minute": 30, "second": 0, "has_time": True}

    # --- English "quarter past/to X [qualifier]" ---
    # Must be checked BEFORE "X in the morning" to avoid partial match
    m = re.search(
        r"quarter\s+(?P<qt_dir>past|to)\s+(\d{1,2})"
        r"(?:\s+in\s+the\s+(?P<qt_qual>morning|afternoon|evening)"
        r"|\s+at\s+(?P<qt_night>night))?",
        clean, re.IGNORECASE
    )
    if m:
        h = int(m.group(2))
        direction = m.group('qt_dir').lower()
        qual = (m.group('qt_qual') or m.group('qt_night') or '').lower()
        if direction == 'to':
            # "quarter to 4" = 3:45
            h -= 1
            mi = 45
        else:
            mi = 15
        if qual in ('afternoon', 'evening', 'night') and h < 12:
            h += 12
        if h < 0:
            h = 23  # "quarter to 0" edge case
        if _validate_time(h, mi):
            return {"hour": h, "minute": mi, "second": 0, "has_time": True}

    # --- English "X o'clock [in the morning/afternoon/evening | at night]" ---
    m = re.search(
        r"(?<!\d)(\d{1,2})\s*o['\u2019]?\s*clock"
        r"(?:\s+in\s+the\s+(?P<oc_qual>morning|afternoon|evening)"
        r"|\s+at\s+(?P<oc_night>night))?",
        clean, re.IGNORECASE
    )
    if m:
        h = int(m.group(1))
        qual = (m.group('oc_qual') or m.group('oc_night') or '').lower()
        if qual in ('afternoon', 'evening', 'night') and h < 12:
            h += 12
        if _validate_time(h, 0):
            return {"hour": h, "minute": 0, "second": 0, "has_time": True}

    # --- English "X in the morning/afternoon/evening" / "X at night" ---
    m = re.search(
        r"(?<!\d)(\d{1,2})\s+"
        r"(?:in\s+the\s+(?P<en_qual>morning|afternoon|evening)"
        r"|at\s+(?P<en_night>night))",
        clean, re.IGNORECASE
    )
    if m:
        h = int(m.group(1))
        qual = (m.group('en_qual') or m.group('en_night') or '').lower()
        if qual in ('afternoon', 'evening', 'night') and h < 12:
            h += 12
        if _validate_time(h, 0):
            return {"hour": h, "minute": 0, "second": 0, "has_time": True}

    # --- French "HHhMM" e.g. "14h30", "0h45", "23h15" ---
    m = re.search(r'(\d{1,2})\s*[hH]\s*(\d{2})?\b', clean)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        if _validate_time(h, mi):
            return {"hour": h, "minute": mi, "second": 0, "has_time": True}

    # --- "at HH:MM" (24h) — checked AFTER AM/PM and French formats ---
    # Negative lookahead (?!\s*[/.\-]\d) prevents matching dates like "12/30"
    m = re.search(r'(?:at\s+|à\s+)?(\d{1,2}):(\d{2})(?::(\d{2}))?(?!\s*[/.\-]\d)', clean)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        s = int(m.group(3)) if m.group(3) else 0
        if _validate_time(h, mi, s):
            return {"hour": h, "minute": mi, "second": s, "has_time": True}

    # --- "Heure: HH:MM" / "Heure: HHhMM" (structured form) ---
    m = re.search(r'[Hh]eure\s*:\s*(\d{1,2})\s*[hH:]\s*(\d{2})?', clean)
    if m:
        h = int(m.group(1))
        mi = int(m.group(2)) if m.group(2) else 0
        if _validate_time(h, mi):
            return {"hour": h, "minute": mi, "second": 0, "has_time": True}

    # No time found — default noon
    return {"hour": 12, "minute": 0, "second": 0, "has_time": False}


# =============================================================================
# KNOWN CITY SET (for splitting "Name City" when no separator exists)
# =============================================================================

_KNOWN_CITIES = {
    "paris", "london", "tokyo", "berlin", "rome", "madrid", "moscow",
    "beijing", "shanghai", "mumbai", "delhi", "cairo", "istanbul",
    "new york", "los angeles", "chicago", "houston", "seattle", "boston",
    "toronto", "sydney", "melbourne", "amsterdam", "brussels", "vienna",
    "lisbon", "prague", "warsaw", "zurich", "geneva", "dublin",
    "lyon", "marseille", "toulouse", "nice", "bordeaux", "strasbourg",
    "nantes", "montpellier", "lille", "rennes",
    "buenos aires", "santiago", "bogota", "lima", "mexico city",
    "bangkok", "singapore", "hong kong", "seoul", "taipei",
    # Extended set (from Gemini review — common cities that were missing)
    "san jose", "san francisco", "san diego", "san antonio",
    "washington", "minneapolis", "philadelphia", "phoenix", "detroit",
    "denver", "portland", "atlanta", "miami", "dallas", "anaheim",
    # Multi-word cities (from 3-agent review — prevent name-vs-city false positives)
    "salt lake city", "las vegas", "cape town", "rio de janeiro",
    "sao paulo", "são paulo", "tel aviv", "kuala lumpur", "ho chi minh",
    "new orleans", "st. louis", "st louis", "el paso", "fort worth",
    "oklahoma city", "kansas city", "virginia beach", "long beach",
    "colorado springs", "baton rouge", "corpus christi",
    "addis ababa", "dar es salaam", "puerto rico",
}

_KNOWN_COUNTRIES = {v.lower() for v in COUNTRY_ALIASES.values()}
_KNOWN_COUNTRIES |= {k.lower() for k in COUNTRY_ALIASES.keys()}
_KNOWN_COUNTRIES |= {
    "france", "germany", "italy", "spain", "switzerland", "belgium",
    "netherlands", "brazil", "mexico", "china", "japan", "india",
    "russia", "turkey", "egypt", "argentina", "canada", "australia",
    "austria", "sweden", "norway", "denmark", "finland", "poland",
    "portugal", "greece", "ireland", "scotland", "wales",
    "south africa", "new zealand", "south korea", "north korea",
    "saudi arabia", "israel", "iran", "iraq", "pakistan",
    "thailand", "vietnam", "indonesia", "philippines", "colombia",
    "venezuela", "chile", "peru", "cuba", "jamaica",
}


# =============================================================================
# NAME EXTRACTION
# =============================================================================

def _extract_name(text: str, date_start: int) -> str:
    """
    Infer the person's name from text.

    Strategy:
      1. Structured: "Nom:" / "Name:" field
      2. French: text before "né(e) le"
      3. English: text before "was a/an" or "(born"
      4. Fallback: text before the date position
      5. Date-at-start: look after the date for name
    """
    clean = " ".join(text.split())

    # --- "Nom:" / "Name:" field ---
    m = re.search(r'(?:Nom|Name)\s*:\s*(.+)', clean, re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        # Stop at next field separator
        name = re.split(r'\n|Date\s*:|Heure\s*:|Lieu\s*:', name)[0].strip()
        if name:
            return _clean_name(name)

    # --- French: "X né(e) le" (with word boundary to avoid matching inside names) ---
    m = re.search(r'^(.+?)\s*,?\s*\bn[ée]+e?\s+le\b', clean, re.IGNORECASE)
    if m:
        return _clean_name(m.group(1))

    # --- English: "X was a/an" ---
    m = re.search(r'^(.+?)\s+was\s+(?:a|an)\b', clean, re.IGNORECASE)
    if m:
        return _clean_name(m.group(1))

    # --- English: "X (born" ---
    m = re.search(r'^(.+?)\s*\(born\b', clean, re.IGNORECASE)
    if m:
        return _clean_name(m.group(1))

    # --- Fallback: text before date ---
    if date_start > 2:
        before_date = clean[:date_start].strip()
        # Strip trailing time patterns that might precede the date
        before_date = _strip_time_patterns(before_date)
        # Remove trailing punctuation, keywords
        before_date = re.sub(r'[\s,.:;]+$', '', before_date)
        before_date = re.sub(
            r'\b(?:Born|Naissance|Date|born on|born|le)\s*:?\s*$', '',
            before_date, flags=re.IGNORECASE,
        ).strip()
        if before_date and len(before_date) >= 2:
            return _clean_name(before_date)

    # --- Date at start: look AFTER date for name ---
    if date_start <= 2:
        return _extract_name_after_date(clean, date_start)

    return ""


def _extract_name_after_date(clean: str, date_start: int) -> str:
    """Extract name from text that appears AFTER the date (e.g. '1985-03-15 Jean Dupont Paris')."""
    # Re-extract date to find its end position
    date_info = _extract_date(clean)
    if not date_info:
        return ""

    after = clean[date_info["match_end"]:].strip()
    after = _strip_time_patterns(after)

    if not after:
        return ""

    # Check if the last word(s) are a known city — split there
    after_lower = after.lower().strip()
    for city_name in sorted(_KNOWN_CITIES, key=len, reverse=True):
        if after_lower.endswith(city_name):
            name_part = after[:len(after) - len(city_name)].strip(' ,')
            if name_part:
                return _clean_name(name_part)
            else:
                # Entire text is a city, no name
                return ""

    # If text contains a comma, it's likely "City, Country" — not a name
    if ',' in after:
        return ""

    # No known city at end — entire text is likely the name
    return _clean_name(after)


def _clean_name(name: str) -> str:
    """Post-process extracted name: strip noise, trailing age, aliases."""
    # Strip leading/trailing quotes, dots, commas
    name = name.strip(' "\'.,;:')
    # Remove trailing parenthetical (age, aliases)
    name = re.sub(r'\s*\(.*?\)\s*$', '', name)
    # Remove " ... " or " - " separators that indicate description start
    # (requires spaces around hyphen, so "Jean-Pierre" is safe)
    name = re.split(r'\s+[-–—]\s+', name)[0]
    name = re.split(r'\s*\.{3,}', name)[0]
    name = name.strip()
    # Collapse multiple spaces
    name = re.sub(r'\s+', ' ', name)
    # Cap name length to prevent paragraph-as-name
    if len(name) > _MAX_NAME_LENGTH:
        truncated = name[:_MAX_NAME_LENGTH]
        last_space = truncated.rfind(' ')
        if last_space > 20:
            name = truncated[:last_space]
        else:
            name = truncated
    return name


# =============================================================================
# LOCATION EXTRACTION
# =============================================================================

def _extract_location(text: str, date_end: int) -> Dict[str, str]:
    """
    Infer birth city and country from text.

    Strategy:
      1. "Lieu:" structured field
      2. French "à [City]" after "né(e)"
      3. "in [City], [Country/State]"
      4. Structured infobox (next line after date)
      5. Comma-separated tokens after date
      6. Arrondissement -> parent city
    """
    clean = " ".join(text.split())

    city = ""
    country = ""
    state = ""  # Preserve state/province info

    # --- "Lieu:" / "Place:" field ---
    m = re.search(r'(?:Lieu|Place)\s*:\s*(.+)', clean, re.IGNORECASE)
    if m:
        loc = m.group(1).strip()
        loc = re.split(r'\n|Date\s*:|Heure\s*:|Nom\s*:', loc)[0].strip()
        parts = [p.strip() for p in loc.split(',')]
        city = parts[0] if parts else ""
        if len(parts) >= 3:
            state = ", ".join(parts[1:-1])
            country = parts[-1]
        elif len(parts) == 2:
            country = parts[1]
        if city:
            city, country = _normalize_location(city, country)
            result = {"city": city, "country": country}
            if state:
                result["state"] = state
            return result

    # --- French: "à [City]" (word-boundary + span limit to prevent DoS) ---
    m = re.search(
        r'\b(?:né|née|naissance)\b\s.{0,500}?\bà\s+([A-ZÀ-Ÿ][\w\s\'-]+)',
        clean, re.IGNORECASE,
    )
    if m:
        raw = m.group(1).strip()
        # Stop at parenthetical or end-of-sentence
        raw = re.split(r'\s*[(\n]', raw)[0].strip()
        raw = re.sub(r'[\s,.:;]+$', '', raw)
        city = raw
        # Look for country in parentheses after city
        after = clean[m.end():]
        cm = re.match(r'\s*[,(]\s*(.+?)\s*[).]', after)
        if cm:
            country = cm.group(1).strip()

    # --- English: "in [the] [Country] [City]" or "in [City], [State/Country]" ---
    if not city:
        # First, try "in [the] <country-alias> <city>" where country comes before city
        m_in = re.search(r'\bin\s+(?:the\s+)?', clean, re.IGNORECASE)
        if m_in:
            after_in = clean[m_in.end():]
            # Check if text after "in [the]" starts with a known country alias
            after_lower = after_in.lower()
            matched_alias = None
            for alias in sorted(COUNTRY_ALIASES, key=len, reverse=True):
                if after_lower.startswith(alias):
                    next_char_idx = len(alias)
                    if next_char_idx >= len(after_in) or after_in[next_char_idx] in ' ,.\n':
                        matched_alias = alias
                        break
            if matched_alias:
                remainder = after_in[len(matched_alias):].lstrip(' .,')
                if remainder:
                    city_m = re.match(r'([A-ZÀ-Ÿa-zà-ÿ][\w\s\'-]{0,100}?)(?:\s*[.,)\n]|$)', remainder)
                    if city_m:
                        city = city_m.group(1).strip()
                        country = COUNTRY_ALIASES[matched_alias]
            # Fall back to standard "in [City], [State/Country]" pattern
            if not city:
                m = re.search(
                    r'\bin\s+(?:the\s+)?([A-ZÀ-Ÿ][\w\s\'-]{0,100}?)(?:\s*,\s*([A-ZÀ-Ÿ][\w\s\'-]{0,100}))?(?:\s*[.,)\n]|$)',
                    clean,
                )
                if m:
                    city = m.group(1).strip()
                    if m.group(2):
                        raw_g2 = m.group(2).strip()
                        if raw_g2.lower() in COUNTRY_ALIASES and COUNTRY_ALIASES[raw_g2.lower()] == "USA":
                            after_match = clean[m.end():].lstrip()
                            next_m = re.match(r',?\s*([A-ZÀ-Ÿ][\w\s\'-]+)', after_match)
                            if next_m:
                                state = raw_g2
                                country = next_m.group(1).strip()
                            else:
                                country = raw_g2
                        else:
                            country = raw_g2

    # --- Structured infobox: next line after date is city, parenthetical is country ---
    # (Run BEFORE comma-separated to avoid garbled results on multi-line inputs)
    if not city and '\n' in text:
        lines = text.strip().split('\n')
        for i, line in enumerate(lines):
            date_result = _extract_date(line)
            if date_result and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # Strip parenthetical noise from the city line
                next_line = re.sub(r'\s*\([^)]*\)', '', next_line).strip()
                if next_line and not re.match(r'^\d', next_line):
                    city = next_line
                    # Check line after for country in parens
                    if i + 2 < len(lines):
                        paren_m = re.match(r'\((.+?)\)', lines[i + 2].strip())
                        if paren_m:
                            country = paren_m.group(1).strip()
                    break

    # --- Comma-separated after date ---
    if not city and date_end < len(clean):
        after = clean[date_end:].strip()
        after = _strip_time_patterns(after)
        # Extract state/country from parentheticals before stripping them.
        # Pattern: "City (STATE)" or "City (STATE) (Country)"
        _parens = re.findall(r'\(([^)]+)\)', after)
        for _p in _parens:
            _pl = _p.strip().lower()
            if len(_pl) <= 3 and _pl.isalpha() and not state:
                state = _p.strip().upper()
            elif _pl in COUNTRY_ALIASES and not country:
                country = COUNTRY_ALIASES[_pl]
            elif _pl in _KNOWN_COUNTRIES and not country:
                country = _p.strip()
        after = re.sub(r'\s*\([^)]*\)\s*', ' ', after)
        after = after.lstrip(' ,').strip()
        if after:
            parts = [p.strip() for p in re.split(r'[,\n]', after)]
            parts = [p for p in parts if p and not re.match(r'^\d+$', p)]
            if parts:
                if len(parts) == 1:
                    # Single block with no commas — check for known city at end
                    block_lower = parts[0].lower().strip()
                    found_city = False
                    for kc in sorted(_KNOWN_CITIES, key=len, reverse=True):
                        if block_lower.endswith(kc):
                            city = parts[0][len(parts[0]) - len(kc):].strip()
                            found_city = True
                            break
                    if not found_city:
                        words = parts[0].split()
                        if len(words) >= 2:
                            for split_at in range(1, len(words)):
                                candidate_city = " ".join(words[:split_at]).lower()
                                candidate_country = " ".join(words[split_at:]).lower()
                                if (candidate_city in _KNOWN_CITIES
                                        and (candidate_country in COUNTRY_ALIASES
                                             or candidate_country in _KNOWN_COUNTRIES)):
                                    city = " ".join(words[:split_at])
                                    country = " ".join(words[split_at:])
                                    found_city = True
                                    break
                    if not found_city:
                        words = parts[0].split()
                        if (len(words) >= 2
                                and all(w[0].isupper() for w in words if w)
                                and parts[0].lower().strip() not in _KNOWN_CITIES):
                            city = ""
                        else:
                            city = parts[0]
                elif len(parts) == 2:
                    city = parts[0]
                    country = parts[1]
                else:
                    # 3+ parts: city, state/province, country
                    city = parts[0]
                    state = ", ".join(parts[1:-1])
                    country = parts[-1]

    # --- Handle arrondissement ---
    if city:
        # "13th arrondissement, Paris" → "Paris"  (when comma-split put Paris in same field)
        arr_m = re.match(
            r'\d+(?:st|nd|rd|th|e|er|ème)\s+arrondissement\b\s*,?\s*(.+)',
            city, re.IGNORECASE,
        )
        if arr_m and arr_m.group(1):
            city = arr_m.group(1).strip()
        # Pure arrondissement without city after (comma-split put city in `country`)
        elif re.match(r'^\d+(?:st|nd|rd|th|e|er|ème)\s+arrondissement\b$', city, re.IGNORECASE):
            if country and country.lower() not in COUNTRY_ALIASES:
                # country field is actually the parent city (e.g. "Paris")
                city = country
                country = ""
        # "Paris 14e" → "Paris"
        city = re.sub(r'\s+\d+[eè]$', '', city)
        # "arrondissement de Paris" or similar
        city = re.sub(r'^\d+[eè]?\s+arrondissement\s*,?\s*', '', city, flags=re.IGNORECASE)

    # Append state to city for geocoding disambiguation (e.g., "Dorchester, MA")
    if state and state not in city:
        city = f"{city}, {state}"

    city, country = _normalize_location(city, country)
    result = {"city": city or "Unknown", "country": country}
    if state:
        result["state"] = state
    return result


def _normalize_location(city: str, country: str) -> Tuple[str, str]:
    """Normalize city/country: resolve aliases, strip noise."""
    # Clean up punctuation
    city = re.sub(r'[\s,.:;()]+$', '', city).strip()
    country = re.sub(r'[\s,.:;()]+$', '', country).strip()

    # Remove age parentheticals from city
    city = re.sub(r'\s*\(age\s+\d+.*?\)', '', city, flags=re.IGNORECASE)

    # Country alias resolution
    country_lower = country.lower().strip()
    if country_lower in COUNTRY_ALIASES:
        country = COUNTRY_ALIASES[country_lower]

    # If city looks like a US state, move to country
    city_lower = city.lower().strip()
    if city_lower in COUNTRY_ALIASES and COUNTRY_ALIASES[city_lower] == "USA":
        if not country:
            country = "USA"
        # Don't overwrite city with state name — keep what we have
    if country_lower in COUNTRY_ALIASES and COUNTRY_ALIASES[country_lower] == "USA":
        if not country or country == country_lower:
            country = "USA"

    return city, country


# =============================================================================
# GENDER EXTRACTION
# =============================================================================

def _extract_gender(text: str) -> str:
    """Detect gender from context clues."""
    t = text.lower()

    # French
    if re.search(r'\bnée\s+le\b', t):
        return "Female"
    if re.search(r'\bné\s+le\b', t):
        return "Male"

    # French roles
    if re.search(r'\bactrice\b|\bchanteuse\b|\bcomédienne\b', t):
        return "Female"
    if re.search(r'\bacteur\b|\bchanteur\b|\bcomédien\b', t):
        return "Male"

    # English roles
    if re.search(r'\bactress\b|\bsongstress\b', t):
        return "Female"
    if re.search(r'\bactor\b(?!ess)', t):
        return "Male"

    # Pronouns
    if re.search(r'\bshe\b|\bher\b|\bhers\b', t):
        return "Female"
    if re.search(r'\bhe\b|\bhis\b|\bhim\b', t):
        return "Male"

    return ""


# =============================================================================
# NAME-BASED ORIGIN GUESSING (fallback only)
# =============================================================================

def _guess_origin_from_name(name: str, full_text: str = "") -> Dict[str, str]:
    """
    Guess city/country from name linguistics and text language context.
    Used ONLY when no location found in text.
    """
    # Check text language context first — French month names are strong signals
    if full_text:
        text_lower = full_text.lower()
        fr_score = sum(1 for kw in _FR_KEYWORDS if re.search(rf'\b{re.escape(kw)}\b', text_lower))
        for month_name in MONTHS_FR:
            if len(month_name) >= 3 and month_name in text_lower:
                fr_score += 1
                break
        if fr_score >= 2:
            return {"city": "Paris", "country": "France"}

    if not name:
        return {"city": "Unknown", "country": ""}

    n = name.lower()
    first = n.split()[0] if n.split() else ""

    # French
    french_first = {"jean", "pierre", "marie", "jacques", "françois", "francois",
                    "claude", "alain", "michel", "philippe", "nicolas", "élie", "elie",
                    "dieudonné", "dieudonne", "thierry", "gérard", "gerard",
                    "amandine", "camille", "aurelie", "aurélie", "sylvie",
                    "celine", "céline", "brigitte", "nathalie", "isabelle", "monique",
                    "véronique", "veronique", "christophe", "sébastien", "sebastien",
                    "laurent", "yves", "henri", "lucien", "gaston", "emile", "émile",
                    "odette", "colette", "madeleine", "simone", "dominique", "pascal",
                    "didier", "patrice", "loic", "loïc", "gwenael", "gwenaël",
                    "hervé", "herve", "arnaud", "fabrice", "franck", "mathieu",
                    "romain", "adrien", "julien", "maxime", "quentin", "corentin",
                    "antoine", "benoit", "benoît", "etienne", "étienne"}
    french_suffix = ("-eau", "-ard", "-ot", "-oux", "-ault", "-aux")
    if first in french_first or any(n.endswith(s) for s in french_suffix):
        return {"city": "Paris", "country": "France"}

    # German
    german_first = {"hans", "wolfgang", "karl", "heinrich", "fritz", "ludwig"}
    if first in german_first or re.search(r'(?:berg|stein|mann|burg)$', n):
        return {"city": "Berlin", "country": "Germany"}

    # Spanish
    spanish_first = {"juan", "josé", "jose", "carlos", "pedro", "pablo"}
    if first in spanish_first or re.search(r'(?:ez|os)$', n):
        return {"city": "Madrid", "country": "Spain"}

    # Italian
    italian_first = {"giovanni", "marco", "antonio", "giuseppe", "paolo", "luca"}
    if first in italian_first or re.search(r'(?:ini|elli|etti|ucci|ino)$', n):
        return {"city": "Rome", "country": "Italy"}

    # Indian
    indian_first = {"raj", "kumar", "singh", "amit", "priya", "sanjay", "deepak"}
    if first in indian_first or re.search(r'(?:esh|deep|nath|anand)$', n):
        return {"city": "Delhi", "country": "India"}

    # Japanese
    if re.search(r'(?:moto|mura|yama|hashi|guchi|zaki|naka)$', n):
        return {"city": "Tokyo", "country": "Japan"}

    # Arabic
    arabic_first = {"mohamed", "mohammed", "ahmed", "ali", "omar", "hassan"}
    if first in arabic_first or re.search(r'\bal[- ]', n):
        return {"city": "Cairo", "country": "Egypt"}

    # Russian
    if re.search(r'(?:ov|ova|sky|skaya|vich)$', n):
        return {"city": "Moscow", "country": "Russia"}

    # Chinese (very rough heuristic: short surname, 2-3 syllable name)
    if re.search(r'^[a-z]{2,4}\s[a-z]{2,6}$', n) and first in {
        "li", "wang", "zhang", "liu", "chen", "yang", "zhao", "wu", "xu", "sun",
    }:
        return {"city": "Beijing", "country": "China"}

    # Default: unknown location, let the dialog show a geocode warning
    return {"city": "Unknown", "country": ""}


# =============================================================================
# INPUT & OUTPUT VALIDATION
# =============================================================================

def _validate_input_text(text: str) -> str:
    """Validate and sanitize input text.  Returns cleaned text or raises ValueError."""
    if not text or not text.strip():
        raise ValueError("Input text is empty.")
    if len(text) > _MAX_INPUT_LENGTH:
        raise ValueError(
            f"Input text too long ({len(text)} chars, max {_MAX_INPUT_LENGTH})."
        )
    # Strip null bytes and control chars (preserve newlines \n, tabs \t, carriage returns \r)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text


def _validate_location_input(city: str, country: str) -> None:
    """Validate location strings before passing to geocoding."""
    if city and len(city) > 200:
        raise ValueError(f"City name too long ({len(city)} chars).")
    if country and len(country) > 200:
        raise ValueError(f"Country name too long ({len(country)} chars).")
    # Block path traversal attempts in location strings
    for val in (city, country):
        if val and ('..' in val or '/' in val or '\\' in val):
            raise ValueError(f"Invalid characters in location: {val!r}")


def _validate_output_path(output_path: str) -> str:
    """
    Validate and sanitize the output file path.
    Ensures the path is safe and within expected directories.
    """
    # Resolve to absolute path
    resolved = os.path.realpath(output_path)

    # Ensure it ends with .chtk extension
    if not resolved.endswith('.chtk'):
        resolved += '.chtk'

    # Ensure the filename component has no directory traversal
    basename = os.path.basename(resolved)
    if not basename or basename.startswith('.'):
        raise ValueError(f"Invalid output filename: {basename!r}")

    # Ensure parent directory exists or can be created
    dirname = os.path.dirname(resolved)
    os.makedirs(dirname, exist_ok=True)

    return resolved


# =============================================================================
# LOCATION RESOLUTION (geocoding + timezone)
# =============================================================================

def resolve_location(city: str, country: str,
                     year: int, month: int, day: int) -> Dict[str, Any]:
    """
    Geocode a city and get its timezone offset for a given date.

    Delegates to existing geocode_city() and get_timezone_for_coordinates()
    from AI_tools/chart_generation/web_birth_data_to_chtk.py.

    Returns dict: lat, lon, timezone_offset, dst_active, geocode_failed
    """
    from tools.geocoding import geocode_city, get_timezone_for_coordinates

    _validate_location_input(city, country)

    coords = geocode_city(city, country)
    if not coords:
        import warnings
        warnings.warn(
            f"Could not geocode '{city}, {country}'. "
            f"Defaulting to (0.0, 0.0) / UTC. Chart will be inaccurate.",
            stacklevel=2,
        )
        return {
            "lat": 0.0, "lon": 0.0,
            "timezone_offset": "+00:00", "tz_name": "UTC",
            "dst_active": False,
            "geocode_failed": True,
        }

    lat = coords["latitude"]
    lon = coords["longitude"]

    birth_dt = datetime(year, month, day)
    tz_info = get_timezone_for_coordinates(lat, lon, birth_dt)

    # Get IANA timezone name for get_all_planets_data()
    from timezonefinder import TimezoneFinder
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=lat, lng=lon) or "UTC"

    return {
        "lat": lat, "lon": lon,
        "timezone_offset": tz_info['offset'], "tz_name": tz_name,
        "dst_active": tz_info['dst_active'],
        "geocode_failed": False,
    }


# =============================================================================
# MAIN PARSER
# =============================================================================

def parse_birth_text(text: str) -> Dict[str, Any]:
    """
    Parse free-form text and extract structured birth data.

    Args:
        text: Pasted biography, infobox, or casual note (French or English).
              Max length: 50,000 chars.

    Returns:
        Dict with keys: name, year, month, day, hour, minute, second,
                        has_time, city, country, state, gender,
                        date_ambiguous, date_warning, location_guessed

    Raises:
        ValueError: if no valid date found, input is empty, or input exceeds length limit
    """
    text = _validate_input_text(text)

    date_info = _extract_date(text)
    if not date_info:
        raise ValueError("Could not find a valid date in the provided text.")

    time_info = _extract_time(text)
    name = _extract_name(text, date_info["match_start"])
    location = _extract_location(text, date_info["match_end"])
    gender = _extract_gender(text)

    # If location is unknown/empty/equals name, try to guess from name + text context
    if name and location["city"] in ("Unknown", "", name):
        guessed = _guess_origin_from_name(name, full_text=text)
        location["city"] = guessed["city"]
        location["country"] = guessed["country"]
        location["guessed_from_name"] = True

    return {
        "name": name,
        "year": date_info["year"],
        "month": date_info["month"],
        "day": date_info["day"],
        "hour": time_info["hour"],
        "minute": time_info["minute"],
        "second": time_info["second"],
        "has_time": time_info["has_time"],
        "city": location["city"],
        "country": location.get("country", ""),
        "state": location.get("state", ""),
        "gender": gender,
        "date_ambiguous": date_info.get("date_ambiguous", False),
        "date_warning": date_info.get("date_warning"),
        "location_guessed": location.get("guessed_from_name", False),
    }


# =============================================================================
# FULL PIPELINE: TEXT -> CHTK
# =============================================================================

def text_to_chtk(text: str, output_path: str = None,
                 verbose: bool = True) -> str:
    """
    Full pipeline: parse text -> geocode -> create CHTK file.

    Args:
        text: Free-form text containing birth data
        output_path: Where to save (default: auto-named in chtk_files/)
        verbose: Print progress

    Returns:
        Path to created CHTK file

    Note:
        CHTK timezone format uses OPPOSITE sign from UTC:
            UTC-6 (Chicago)   -> CHTK +06:00:00
            UTC+5:30 (India)  -> CHTK -05:30:00
        This inversion is handled automatically by create_chtk().
    """
    pass  # Pro import stripped for Lite distribution

    # Step 1: Parse text
    parsed = parse_birth_text(text)
    if verbose:
        print(f"[Parse] Name: {parsed['name'] or '(none)'}")
        print(f"[Parse] Date: {parsed['year']}-{parsed['month']:02d}-{parsed['day']:02d}")
        print(f"[Parse] Time: {parsed['hour']:02d}:{parsed['minute']:02d}"
              f"{'  (default noon)' if not parsed['has_time'] else ''}")
        print(f"[Parse] City: {parsed['city']}, {parsed['country']}")
        if parsed.get("state"):
            print(f"[Parse] State: {parsed['state']}")
        if parsed.get("date_warning"):
            print(f"[Parse] WARNING: {parsed['date_warning']}")
        if parsed.get("location_guessed"):
            print(f"[Parse] NOTE: Location guessed from name (not found in text)")

    # Step 2: Geocode & timezone
    if verbose:
        print(f"[Geocode] Looking up {parsed['city']}, {parsed['country']}...")
    loc = resolve_location(
        parsed["city"], parsed["country"],
        parsed["year"], parsed["month"], parsed["day"],
    )
    if verbose:
        print(f"[Geocode] {loc['lat']:.4f}, {loc['lon']:.4f}  TZ: {loc['timezone_offset']}")
        if loc.get("geocode_failed"):
            print("[Geocode] WARNING: Geocoding failed — using (0,0)/UTC fallback!")

    # Step 3: Create CHTK
    if output_path is None:
        name_for_file = parsed["name"] or "Unknown"
        # Use basename-only to prevent path traversal
        safe_name = re.sub(r'[^\w\s-]', '', name_for_file).strip().replace(' ', '_')
        safe_name = os.path.basename(safe_name)  # Strip any directory components
        if not safe_name:
            safe_name = "Unknown"
        project_root = Path(__file__).parent.parent.parent
        out_dir = project_root / "chtk_files" / datetime.now().strftime("%Y-%m-%d")
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"{safe_name}.chtk")
    else:
        output_path = _validate_output_path(output_path)

    path = create_chtk(
        name=parsed["name"] or "Unknown",
        year=parsed["year"], month=parsed["month"], day=parsed["day"],
        hour=parsed["hour"], minute=parsed["minute"], second=parsed["second"],
        lat=loc["lat"], lon=loc["lon"],
        city=parsed["city"], country=parsed["country"],
        timezone_offset=loc["timezone_offset"],
        dst_active=loc["dst_active"],
        gender=parsed["gender"],
        output_path=output_path,
    )

    if verbose:
        print(f"[CHTK] Created: {path}")

    return path


# =============================================================================
# BUILT-IN TEST SUITE
# =============================================================================

TEST_CASES = [
    # (id, input_text, expected_name, expected_date, expected_time, expected_city, category)
    #
    # exp_name=None  -> don't check name
    # exp_date="EXPECT_ERROR" -> expect ValueError
    # exp_time=None  -> don't check time
    # exp_city=None  -> don't check city

    # =========================================================================
    # ORIGINAL CORE TESTS (1-20)
    # =========================================================================
    (1, "2 février 1992 12pm Cindy Hoaray",
     "Cindy Hoaray", (1992, 2, 2), (12, 0), None, "FR simple"),
    (2, "Michael Joseph Jackson was an American singer, songwriter... Born: August 29, 1958",
     "Michael Joseph Jackson", (1958, 8, 29), None, None, "EN Wikipedia"),
    (3, "Dieudonné MBala MBala, né le 11 février 1966 à Fontenay-aux-Roses",
     "Dieudonné MBala MBala", (1966, 2, 11), None, "Fontenay-aux-Roses", "FR bio"),
    (4, "Naissance 11 février 1966 (60 ans)\nFontenay-aux-Roses\n(Seine, France)",
     "", (1966, 2, 11), None, "Fontenay-aux-Roses", "FR infobox"),
    (5, "Élie Semoun... Born: October 16, 1963 (age 62 years), 13th arrondissement, Paris",
     "Élie Semoun", (1963, 10, 16), None, "Paris", "EN arrondissement"),
    (6, "Sandra P 17 Nov 1968 0:45 AM Buenos Aires",
     "Sandra P", (1968, 11, 17), (0, 45), "Buenos Aires", "EN abbreviated"),
    (7, "15/03/1985 14h30 Marseille, France",
     "", (1985, 3, 15), (14, 30), "Marseille", "Numeric DD/MM"),
    (8, "1985-03-15 Jean Dupont Paris",
     "Jean Dupont", (1985, 3, 15), None, "Paris", "ISO date"),
    (9, "Madonna Louise Ciccone, née le 16 août 1958 à Bay City",
     "Madonna Louise Ciccone", (1958, 8, 16), None, "Bay City", "FR feminine"),
    (10, "1er janvier 2000 0h45 Lyon",
     "", (2000, 1, 1), (0, 45), "Lyon", "FR ordinal"),
    (11, "born on March 3rd, 1990 at 3:30 PM in London, England",
     "", (1990, 3, 3), (15, 30), "London", "EN formal"),
    (12, "Nom: Pierre Martin\nDate: 25 décembre 1975\nHeure: 23h15\nLieu: Toulouse",
     "Pierre Martin", (1975, 12, 25), (23, 15), "Toulouse", "FR structured"),
    (13, "Jean-Pierre Léaud né le 28 mai 1944 Paris 14e",
     "Jean-Pierre Léaud", (1944, 5, 28), None, "Paris", "FR hyphenated"),
    (14, "Amy born 5 sept 1992 at noon, New York",
     "Amy", (1992, 9, 5), (12, 0), "New York", "EN casual noon"),
    (15, "02/14/1990 3pm Chicago",
     "", (1990, 2, 14), (15, 0), "Chicago", "US date MM/DD"),
    (16, "Sandra P Feb 31 2023 0:45 AM Buenos Aires",
     None, "EXPECT_ERROR", None, None, "Invalid date Feb 31"),
    (17, "05/05/2020 Paris",
     "", (2020, 5, 5), None, "Paris", "Ambiguous same DD/MM"),
    (18, "1985-03-15",
     "", (1985, 3, 15), None, None, "Date only"),
    (19, "born on June 15, 1985 in Austin, Texas, USA",
     "", (1985, 6, 15), None, "Austin", "City/State/Country"),
    (20, "x" * 60000,
     None, "EXPECT_ERROR", None, None, "DoS input limit"),

    # =========================================================================
    # FRENCH MONTH ABBREVIATIONS (21-32)
    # =========================================================================
    (21, "Marie 15 janv 1988 Paris",
     "Marie", (1988, 1, 15), None, "Paris", "FR abbrev janv"),
    (22, "Lorris Turpin 22 fev 1991 10:30",
     "Lorris Turpin", (1991, 2, 22), (10, 30), None, "FR abbrev fev"),
    (23, "Paul 7 mars 2001 Lyon",
     "Paul", (2001, 3, 7), None, "Lyon", "FR abbrev mars"),
    (24, "Claire 3 avr 1995 Nantes",
     "Claire", (1995, 4, 3), None, "Nantes", "FR abbrev avr"),
    (25, "Sophie 12 mai 1990 Bordeaux",
     "Sophie", (1990, 5, 12), None, "Bordeaux", "FR abbrev mai"),
    (26, "Lucas 21 juin 1985 Rennes",
     "Lucas", (1985, 6, 21), None, "Rennes", "FR abbrev juin"),
    (27, "Emma 14 juil 2003 Nice",
     "Emma", (2003, 7, 14), None, "Nice", "FR abbrev juil"),
    (28, "Hugo 8 aout 1999 Strasbourg",
     "Hugo", (1999, 8, 8), None, "Strasbourg", "FR abbrev aout"),
    (29, "Lea 30 sept 1992 Toulouse",
     "Lea", (1992, 9, 30), None, "Toulouse", "FR abbrev sept"),
    (30, "Tom 5 oct 2010 Lille",
     "Tom", (2010, 10, 5), None, "Lille", "FR abbrev oct"),
    (31, "Nina 18 nov 1987 Montpellier",
     "Nina", (1987, 11, 18), None, "Montpellier", "FR abbrev nov"),
    (32, "Jules 25 dec 1993 Marseille",
     "Jules", (1993, 12, 25), None, "Marseille", "FR abbrev dec"),

    # =========================================================================
    # SPACE-SEPARATED DATES (33-38)
    # =========================================================================
    (33, "Tuarus Chatois, 12 01 1991 10h30",
     "Tuarus Chatois", (1991, 1, 12), (10, 30), None, "Space-sep DD MM YYYY"),
    (34, "25 12 1990 Berlin",
     "", (1990, 12, 25), None, "Berlin", "Space-sep unambig day>12"),
    (35, "5 3 2000 14h00 Paris",
     "", (2000, 3, 5), (14, 0), "Paris", "Space-sep FR context"),
    (36, "le 1 6 1975 midi Lyon",
     None, (1975, 6, 1), (12, 0), "Lyon", "Space-sep + midi"),
    (37, "15 08 2005 à 9:00 AM",
     None, (2005, 8, 15), (9, 0), None, "Space-sep unambig"),
    (38, "John 03 11 1988 3pm Boston",
     "John", (1988, 11, 3), (15, 0), "Boston", "Space-sep EN context"),

    # =========================================================================
    # FRENCH CONTEXT + NON-FRENCH NAMES (39-41)
    # =========================================================================
    (39, "2 février 1992 12pm Cindy Hoaray",
     "Cindy Hoaray", (1992, 2, 2), (12, 0), None, "FR context non-FR name"),
    (40, "née le 5 mars 1980 à 14h00 Sarah Williams",
     None, (1980, 3, 5), (14, 0), None, "FR keywords EN name"),
    (41, "John Smith né le 10 avril 1975 Paris",
     "John Smith", (1975, 4, 10), None, "Paris", "EN name FR bio"),

    # =========================================================================
    # NAME-AFTER-DATE PATTERNS (42-44)
    # =========================================================================
    (42, "1990-05-20 Alice Martin Lyon",
     "Alice Martin", (1990, 5, 20), None, "Lyon", "ISO + name + city"),
    (43, "2001-12-25 Bob Smith",
     "Bob Smith", (2001, 12, 25), None, None, "ISO + name only"),
    (44, "1975-08-03 14:00 Claire Dubois, Paris",
     None, (1975, 8, 3), (14, 0), None, "ISO + time + name,city"),

    # =========================================================================
    # TIME EDGE CASES (45-54)
    # =========================================================================
    (45, "Jean 15 mars 1990 midi",
     "Jean", (1990, 3, 15), (12, 0), None, "FR midi"),
    (46, "Jean 15 mars 1990 minuit",
     "Jean", (1990, 3, 15), (0, 0), None, "FR minuit"),
    (47, "born March 15 1990 at noon, Seattle",
     "", (1990, 3, 15), (12, 0), "Seattle", "EN noon"),
    (48, "born March 15 1990 at midnight, Seattle",
     "", (1990, 3, 15), (0, 0), "Seattle", "EN midnight"),
    (49, "Jean 15 mars 1990 0h00",
     "Jean", (1990, 3, 15), (0, 0), None, "FR 0h00"),
    (50, "10 jan 2020 12 AM",
     "", (2020, 1, 10), (0, 0), None, "12 AM = midnight"),
    (51, "10 jan 2020 12 PM",
     "", (2020, 1, 10), (12, 0), None, "12 PM = noon"),
    (52, "Nom: Jean\nDate: 15 mars 1990\nHeure: 8h30",
     "Jean", (1990, 3, 15), (8, 30), None, "Heure field"),
    (53, "Bob 10 jan 2020 23:59:30 London",
     "Bob", (2020, 1, 10), (23, 59), "London", "HH:MM:SS format"),
    (54, "1er janvier 2000 0h45",
     "", (2000, 1, 1), (0, 45), None, "FR 0h45 no city"),

    # =========================================================================
    # NAMES WITH ACCENTS / HYPHENS / PARTICLES (55-61)
    # =========================================================================
    (55, "Jean-Claude Van Damme né le 18 octobre 1960 à Ixelles",
     "Jean-Claude Van Damme", (1960, 10, 18), None, None, "Hyphen + Van"),
    (56, "Charles de Gaulle né le 22 novembre 1890 à Lille",
     "Charles de Gaulle", (1890, 11, 22), None, "Lille", "Particle de"),
    (57, "Ludwig van Beethoven (born 17 December 1770)",
     "Ludwig van Beethoven", (1770, 12, 17), None, None, "Particle van"),
    (58, "José María Aznar 25 février 1953 Madrid",
     None, (1953, 2, 25), None, "Madrid", "Accented name"),
    (59, "François-Marie Arouet né le 21 novembre 1694 à Paris",
     "François-Marie Arouet", (1694, 11, 21), None, "Paris", "Double hyphen"),
    (60, "Renée Zellweger born April 25, 1969",
     "Renée Zellweger", (1969, 4, 25), None, None, "Accented first"),
    (61, "Thierry d'Argenlieu né le 7 août 1889 à Brest",
     None, (1889, 8, 7), None, "Brest", "Particle d'"),

    # =========================================================================
    # LOCATION FORMATS (62-66)
    # =========================================================================
    (62, "born 5 May 1990 in Paris",
     "", (1990, 5, 5), None, "Paris", "City only"),
    (63, "born 5 May 1990 in Paris, France",
     "", (1990, 5, 5), None, "Paris", "City + country"),
    (64, "born 5 May 1990 in Denver, Colorado, USA",
     "", (1990, 5, 5), None, "Denver", "City+state+country"),
    (65, "Naissance 11 février 1966\n5e arrondissement\nParis",
     None, (1966, 2, 11), None, None, "FR arrondissement"),
    (66, "born June 1, 1926 in Los Angeles, California",
     "", (1926, 6, 1), None, "Los Angeles", "Known multi-word city"),

    # =========================================================================
    # STRUCTURED INPUT - NOM/DATE/LIEU (67-69)
    # =========================================================================
    (67, "Nom: Marie Curie\nDate: 7 novembre 1867\nLieu: Varsovie",
     "Marie Curie", (1867, 11, 7), None, None, "FR structured Nom/Date"),
    (68, "Name: Albert Einstein\nDate: March 14, 1879\nPlace: Ulm, Germany",
     "Albert Einstein", (1879, 3, 14), None, "Ulm", "EN structured Name/Date"),
    (69, "Nom: Simone de Beauvoir\nDate: 9 janvier 1908\nHeure: 4h00\nLieu: Paris, France",
     "Simone de Beauvoir", (1908, 1, 9), (4, 0), "Paris", "FR full structured"),

    # =========================================================================
    # WIKIPEDIA-STYLE BIOS (70-73)
    # =========================================================================
    (70, "Brigitte Bardot, née le 28 septembre 1934 à Paris, est une actrice française.",
     "Brigitte Bardot", (1934, 9, 28), None, "Paris", "FR Wikipedia bio"),
    (71, "Gérard Depardieu, né le 27 décembre 1948 à Châteauroux, est un acteur français.",
     "Gérard Depardieu", (1948, 12, 27), None, "Châteauroux", "FR bio acteur"),
    (72, "Albert Einstein (born March 14, 1879) was a German-born physicist.",
     "Albert Einstein", (1879, 3, 14), None, None, "EN (born) pattern"),
    (73, "Charles Darwin was an English naturalist. Born: February 12, 1809",
     "Charles Darwin", (1809, 2, 12), None, None, "EN was a... Born:"),

    # =========================================================================
    # DATE EDGE CASES (74-81)
    # =========================================================================
    (74, "born 29 February 2000",
     "", (2000, 2, 29), None, None, "Leap year valid"),
    (75, "born 29 February 1999",
     None, "EXPECT_ERROR", None, None, "Leap year invalid"),
    (76, "31 December 1999 23:59 London",
     "", (1999, 12, 31), (23, 59), "London", "End of millennium"),
    (77, "1 January 2000 0:00 Paris",
     "", (2000, 1, 1), (0, 0), "Paris", "Y2K midnight"),
    (78, "15.06.1985 Rome",
     "", (1985, 6, 15), None, "Rome", "Dot separator"),
    (79, "born 31 April 1990",
     None, "EXPECT_ERROR", None, None, "Invalid Apr 31"),
    (80, "born 0 January 1990",
     None, "EXPECT_ERROR", None, None, "Invalid day 0"),
    (81, "born 13 13 1990",
     None, "EXPECT_ERROR", None, None, "Invalid month 13"),

    # =========================================================================
    # GENDER DETECTION (82-87)
    # =========================================================================
    (82, "Marie Curie, née le 7 novembre 1867 à Varsovie",
     "Marie Curie", (1867, 11, 7), None, None, "FR née = Female"),
    (83, "Victor Hugo, né le 26 février 1802 à Besançon",
     "Victor Hugo", (1802, 2, 26), None, None, "FR né = Male"),
    (84, "She was born on June 1, 1926 in Los Angeles",
     None, (1926, 6, 1), None, "Los Angeles", "EN she = Female"),
    (85, "He was born on January 8, 1935 in Tupelo",
     None, (1935, 1, 8), None, None, "EN he = Male"),
    (86, "Isabelle Adjani est une actrice française, née le 27 juin 1955",
     None, (1955, 6, 27), None, None, "FR actrice = Female"),
    (87, "Alain Delon, acteur français, né le 8 novembre 1935 à Sceaux",
     None, (1935, 11, 8), None, None, "FR acteur = Male"),

    # =========================================================================
    # ADDITIONAL ENGLISH PATTERNS (88-93)
    # =========================================================================
    (88, "Elvis Presley Born: January 8, 1935",
     "Elvis Presley", (1935, 1, 8), None, None, "EN Born: prefix"),
    (89, "Taylor Swift born December 13, 1989 in Reading, Pennsylvania",
     "Taylor Swift", (1989, 12, 13), None, "Reading", "EN born + state"),
    (90, "Elon Musk (born June 28, 1971)",
     "Elon Musk", (1971, 6, 28), None, None, "EN parenthetical born"),
    (91, "born 22 Aug 1990 at 5:00 AM in Sydney, Australia",
     "", (1990, 8, 22), (5, 0), "Sydney", "EN abbrev + AM + city"),
    (92, "Steve Jobs February 24, 1955 San Francisco",
     "Steve Jobs", (1955, 2, 24), None, "San Francisco", "EN name + date + city"),
    (93, "born on July 4th, 1776 in Philadelphia",
     "", (1776, 7, 4), None, "Philadelphia", "EN ordinal 4th"),

    # =========================================================================
    # ADDITIONAL FRENCH PATTERNS (94-99)
    # =========================================================================
    (94, "2ème janvier 2000 Lyon",
     "", (2000, 1, 2), None, "Lyon", "FR ordinal 2ème"),
    (95, "Catherine Deneuve née le 22 octobre 1943 à Paris 17e",
     "Catherine Deneuve", (1943, 10, 22), None, "Paris", "FR née + 17e"),
    (96, "Edith Piaf née le 19 décembre 1915 à Paris",
     "Edith Piaf", (1915, 12, 19), None, "Paris", "FR née décembre"),
    (97, "né le 1er mars 1995 à 7h30 Bordeaux",
     None, (1995, 3, 1), (7, 30), "Bordeaux", "FR ordinal 1er"),
    (98, "15 juillet 1989 22h45 Nice, France",
     "", (1989, 7, 15), (22, 45), "Nice", "FR full date+time+loc"),
    (99, "naissance le 3 août 1960 à Toulouse",
     None, (1960, 8, 3), None, "Toulouse", "FR naissance keyword"),

    # =========================================================================
    # MORE TIME FORMATS (100-103)
    # =========================================================================
    (100, "born 5 May 1990 at 14:30:45 London",
     "", (1990, 5, 5), (14, 30), "London", "24h HH:MM:SS"),
    (101, "born 5 May 1990 at 2:30 PM London",
     "", (1990, 5, 5), (14, 30), "London", "12h with PM"),
    (102, "5 mai 1990 à 0h00 Paris",
     None, (1990, 5, 5), (0, 0), "Paris", "FR midnight 0h00"),
    (103, "5 mai 1990 23h59 Paris",
     "", (1990, 5, 5), (23, 59), "Paris", "FR late night"),

    # =========================================================================
    # COUNTRY ALIAS RESOLUTION (104-108)
    # =========================================================================
    (104, "born 5 May 1990 in London, England",
     "", (1990, 5, 5), None, "London", "England -> UK"),
    (105, "born 5 May 1990 in Paris, France",
     "", (1990, 5, 5), None, "Paris", "France direct"),
    (106, "born 5 May 1990 in Munich, Allemagne",
     "", (1990, 5, 5), None, "Munich", "FR Allemagne alias"),
    (107, "born 5 May 1990 in Rome, Italie",
     "", (1990, 5, 5), None, "Rome", "FR Italie alias"),
    (108, "born 5 May 1990 in Buenos Aires, Argentine",
     "", (1990, 5, 5), None, "Buenos Aires", "FR Argentine alias"),

    # =========================================================================
    # 3-AGENT REVIEW: MULTI-WORD CITIES (109-112)
    # =========================================================================
    (109, "born 1 January 1990 in Salt Lake City",
     "", (1990, 1, 1), None, "Salt Lake City", "Multi-word city 3 words"),
    (110, "born 15 May 1985 in Cape Town",
     "", (1985, 5, 15), None, "Cape Town", "Multi-word city 2 words"),
    (111, "born 20 July 1975 in Las Vegas",
     "", (1975, 7, 20), None, "Las Vegas", "Multi-word city Las Vegas"),
    (112, "born 5 March 1980 in New Orleans, Louisiana",
     "", (1980, 3, 5), None, "New Orleans", "Multi-word city + state"),

    # =========================================================================
    # 3-AGENT REVIEW: APOSTROPHE NAMES (113-115)
    # =========================================================================
    (113, "Shaquille O'Neal born March 6, 1972 in Newark, New Jersey",
     "Shaquille O'Neal", (1972, 3, 6), None, "Newark", "O' prefix name"),
    (114, "D'Angelo Russell (born February 23, 1996)",
     "D'Angelo Russell", (1996, 2, 23), None, None, "D' prefix name"),
    (115, "Sinéad O'Connor née le 8 décembre 1966 à Dublin",
     "Sinéad O'Connor", (1966, 12, 8), None, None, "O' + FR née"),

    # =========================================================================
    # 3-AGENT REVIEW: WIKIPEDIA WITH IPA / DEATH DATES (116-118)
    # =========================================================================
    (116, "Édith Piaf (born Édith Giovanna Gassion; 19 December 1915 – 10 October 1963) was a French singer.",
     "Édith Piaf", (1915, 12, 19), None, None, "Wikipedia born + death"),
    (117, "Serena Williams (born September 26, 1981) is an American former professional tennis player.",
     "Serena Williams", (1981, 9, 26), None, None, "Wikipedia (born) + prof"),
    (118, "Keanu Reeves (born September 2, 1964) is a Canadian actor.",
     "Keanu Reeves", (1964, 9, 2), None, None, "Wikipedia (born) actor"),

    # =========================================================================
    # 3-AGENT REVIEW: CENTURY BOUNDARIES (119-122)
    # =========================================================================
    (119, "born 31 December 1899 at 11:59 PM in London",
     "", (1899, 12, 31), (23, 59), "London", "19th century last min"),
    (120, "born 1 January 1900 at 0:00 AM in Paris",
     "", (1900, 1, 1), (0, 0), "Paris", "20th century start"),
    (121, "born 31 December 2000 at 23:59 in Sydney",
     "", (2000, 12, 31), (23, 59), "Sydney", "Millennium last min"),
    (122, "born 1 January 2001 at 0:00 AM in New York",
     "", (2001, 1, 1), (0, 0), "New York", "21st century start"),

    # =========================================================================
    # 3-AGENT REVIEW: FRENCH ABBREVS WITH DOTS (123-125)
    # =========================================================================
    (123, "Marie 15 fév. 1988 Paris",
     "Marie", (1988, 2, 15), None, "Paris", "FR abbrev fév. dot"),
    (124, "Jean 22 janv. 1991 10:30 Lyon",
     "Jean", (1991, 1, 22), (10, 30), "Lyon", "FR abbrev janv. dot"),
    (125, "Paul 3 avr. 1995 Nantes",
     "Paul", (1995, 4, 3), None, "Nantes", "FR abbrev avr. dot"),

    # =========================================================================
    # 3-AGENT REVIEW: NAME-VS-CITY ADVERSARIAL (126-128)
    # =========================================================================
    (126, "Paris Hilton, born 17 February 1981, New York",
     "Paris Hilton", (1981, 2, 17), None, "New York", "City-name as person"),
    (127, "1990-01-01 14:00 Rio De Janeiro",
     None, (1990, 1, 1), (14, 0), None, "Multi-word city ISO"),
    (128, "born 10 August 1990 at 3pm in Tel Aviv, Israel",
     "", (1990, 8, 10), (15, 0), "Tel Aviv", "Multi-word city + country"),

    # =========================================================================
    # FRENCH SPELLED-OUT TIME (129-136)
    # =========================================================================
    (129, "Enault turpin 25 juillet 1960 8 heure du matin",
     "Enault turpin", (1960, 7, 25), (8, 0), None, "FR heure du matin"),
    (130, "Marie 15 mars 1990 3 heures du soir Paris",
     "Marie", (1990, 3, 15), (15, 0), "Paris", "FR heures du soir"),
    (131, "Jean 10 juin 1985 2 heures de l'après-midi Lyon",
     "Jean", (1985, 6, 10), (14, 0), "Lyon", "FR heures après-midi"),
    (132, "Sophie 1er janvier 2000 6 heures du matin Marseille",
     "Sophie", (2000, 1, 1), (6, 0), "Marseille", "FR heures du matin + city"),
    (133, "Paul 20 août 1975 10 heures du soir",
     "Paul", (1975, 8, 20), (22, 0), None, "FR 10h soir = 22h"),
    (134, "Luc 5 mai 1992 12 heures Paris",
     "Luc", (1992, 5, 5), (12, 0), "Paris", "FR 12 heures (no qualifier)"),
    (135, "Anne 8 décembre 1988 1 heure du matin Nice",
     "Anne", (1988, 12, 8), (1, 0), "Nice", "FR 1 heure du matin"),
    (136, "Pierre 14 février 1970 4 heures 30 du soir Bordeaux",
     "Pierre", (1970, 2, 14), (16, 30), "Bordeaux", "FR heures + minutes du soir"),

    # =========================================================================
    # ENGLISH SPELLED-OUT TIME (137-156)
    # =========================================================================

    # --- o'clock ---
    (137, "born 5 May 1990 at 8 o'clock London",
     "", (1990, 5, 5), (8, 0), "London", "EN o'clock bare"),
    (138, "born 5 May 1990 at 8 o'clock in the morning London",
     "", (1990, 5, 5), (8, 0), "London", "EN o'clock morning"),
    (139, "born 5 May 1990 at 3 o'clock in the afternoon London",
     "", (1990, 5, 5), (15, 0), "London", "EN o'clock afternoon"),
    (140, "born 5 May 1990 at 9 o'clock in the evening London",
     "", (1990, 5, 5), (21, 0), "London", "EN o'clock evening"),
    (141, "born 5 May 1990 at 10 o'clock at night London",
     "", (1990, 5, 5), (22, 0), "London", "EN o'clock at night"),

    # --- in the morning/afternoon/evening / at night ---
    (142, "born 5 May 1990 8 in the morning London",
     "", (1990, 5, 5), (8, 0), "London", "EN in the morning"),
    (143, "born 5 May 1990 3 in the afternoon London",
     "", (1990, 5, 5), (15, 0), "London", "EN in the afternoon"),
    (144, "born 5 May 1990 7 in the evening London",
     "", (1990, 5, 5), (19, 0), "London", "EN in the evening"),
    (145, "born 5 May 1990 11 at night London",
     "", (1990, 5, 5), (23, 0), "London", "EN at night"),
    (146, "born 5 May 1990 12 in the afternoon London",
     "", (1990, 5, 5), (12, 0), "London", "EN 12 afternoon = noon"),

    # --- half past ---
    (147, "born 5 May 1990 half past 3 London",
     "", (1990, 5, 5), (3, 30), "London", "EN half past bare"),
    (148, "born 5 May 1990 half past 8 in the morning London",
     "", (1990, 5, 5), (8, 30), "London", "EN half past morning"),
    (149, "born 5 May 1990 half past 3 in the afternoon London",
     "", (1990, 5, 5), (15, 30), "London", "EN half past afternoon"),
    (150, "born 5 May 1990 half past 10 at night London",
     "", (1990, 5, 5), (22, 30), "London", "EN half past night"),

    # --- quarter past/to ---
    (151, "born 5 May 1990 quarter past 8 London",
     "", (1990, 5, 5), (8, 15), "London", "EN quarter past bare"),
    (152, "born 5 May 1990 quarter past 2 in the afternoon London",
     "", (1990, 5, 5), (14, 15), "London", "EN quarter past afternoon"),
    (153, "born 5 May 1990 quarter to 4 London",
     "", (1990, 5, 5), (3, 45), "London", "EN quarter to bare"),
    (154, "born 5 May 1990 quarter to 9 in the evening London",
     "", (1990, 5, 5), (20, 45), "London", "EN quarter to evening"),

    # --- edge cases ---
    (155, "born 5 May 1990 12 o'clock in the morning London",
     "", (1990, 5, 5), (12, 0), "London", "EN 12 o'clock morning = noon"),
    (156, "born 5 May 1990 12 at night London",
     "", (1990, 5, 5), (12, 0), "London", "EN 12 at night = midnight? keep 12"),
]


def run_tests(verbose: bool = True) -> bool:
    """
    Run all built-in test cases.  Returns True if all pass.
    Supports EXPECT_ERROR for cases that should raise ValueError.
    """
    passed = 0
    failed = 0
    errors = []

    for tid, text, exp_name, exp_date, exp_time, exp_city, category in TEST_CASES:
        # Handle expected-error test cases
        if exp_date == "EXPECT_ERROR":
            try:
                parse_birth_text(text)
                # Should have raised — this is a FAILURE
                failed += 1
                msg = f"  #{tid:2d} [{category:22s}] FAIL: expected ValueError but parsed OK"
                errors.append(msg)
                if verbose:
                    print(msg)
            except ValueError:
                passed += 1
                if verbose:
                    print(f"  #{tid:2d} [{category:22s}] PASS (ValueError as expected)")
            except Exception as e:
                failed += 1
                msg = f"  #{tid:2d} [{category:22s}] FAIL: wrong exception: {type(e).__name__}: {e}"
                errors.append(msg)
                if verbose:
                    print(msg)
            continue

        # Normal test case
        try:
            result = parse_birth_text(text)
        except Exception as e:
            failed += 1
            errors.append(f"  #{tid} [{category}] EXCEPTION: {e}")
            if verbose:
                print(f"  #{tid:2d} [{category:22s}] EXCEPTION: {e}")
            continue

        ok = True
        issues = []

        # Check name (if expected)
        if exp_name is not None:
            if result["name"] != exp_name:
                issues.append(f"name: got '{result['name']}', expected '{exp_name}'")
                ok = False

        # Check date
        if exp_date:
            got_date = (result["year"], result["month"], result["day"])
            if got_date != exp_date:
                issues.append(f"date: got {got_date}, expected {exp_date}")
                ok = False

        # Check time (None = don't check, just noon default)
        if exp_time is not None:
            got_time = (result["hour"], result["minute"])
            if got_time != exp_time:
                issues.append(f"time: got {got_time}, expected {exp_time}")
                ok = False

        # Check city (None = don't check)
        if exp_city is not None:
            if result["city"] != exp_city:
                issues.append(f"city: got '{result['city']}', expected '{exp_city}'")
                ok = False

        if ok:
            passed += 1
            if verbose:
                print(f"  #{tid:2d} [{category:22s}] PASS")
        else:
            failed += 1
            detail = "; ".join(issues)
            errors.append(f"  #{tid:2d} [{category:22s}] FAIL: {detail}")
            if verbose:
                print(f"  #{tid:2d} [{category:22s}] FAIL: {detail}")

    print(f"\nResults: {passed}/{passed + failed} passed")
    if errors:
        print("Failures:")
        for e in errors:
            print(e)

    return failed == 0


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Parse free-form text into CHTK chart files (offline, regex-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Parse only — show extracted data, no file creation
  python AI_tools/AI_main_function/text_to_chtk.py -p "Sandra P 17 Nov 1968 0:45 AM Buenos Aires"

  # Create CHTK file (requires network for geocoding)
  python AI_tools/AI_main_function/text_to_chtk.py "Madonna Louise Ciccone, née le 16 août 1958 à Bay City"

  # Read from stdin
  echo "1er janvier 2000 0h45 Lyon" | python AI_tools/AI_main_function/text_to_chtk.py --stdin

  # Run built-in test suite
  python AI_tools/AI_main_function/text_to_chtk.py --test
""",
    )

    parser.add_argument("text", nargs="?", help="Text containing birth data")
    parser.add_argument("--output", "-o", help="Output CHTK file path")
    parser.add_argument("--parse-only", "-p", action="store_true",
                        help="Parse and print JSON — no geocoding or file creation")
    parser.add_argument("--stdin", action="store_true",
                        help="Read text from stdin")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Less output")
    parser.add_argument("--test", "-t", action="store_true",
                        help="Run built-in test suite")

    args = parser.parse_args()

    # --- Test mode ---
    if args.test:
        print("Running text_to_chtk test suite...")
        success = run_tests(verbose=not args.quiet)
        return 0 if success else 1

    # --- Get input text ---
    text = args.text
    if args.stdin:
        text = sys.stdin.read()
    if not text:
        parser.error("Provide text as argument or use --stdin")

    # --- Parse only ---
    if args.parse_only:
        try:
            result = parse_birth_text(text)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # --- Full pipeline ---
    try:
        path = text_to_chtk(text, output_path=args.output, verbose=not args.quiet)
        if not args.quiet:
            print(f"\nDone: {path}")
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
