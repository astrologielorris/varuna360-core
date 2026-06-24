#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Nisarga Dasha - Natural Planetary Ages (fixed for everyone)

Based on Brihat Parashara Hora Shastra (Longevity 16-17) and
Yavana Jataka of Sphujidhvaja (39, 4-5).

Unlike Vimshottari (nakshatra-based, unique per chart), Nisarga periods
are universal - the same 7 planetary age periods apply to everyone.

Level 1: 7 main periods + maturation ages section at bottom
Level 2: Sub-periods (each main period divided into 12 sub-periods)

Source: Ernst Wilhelm, "Ages of the Grahas"
"""

from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

# Short planet abbreviations (standard: Mo, Ma, Me, Ve, Ju, Su, Sa)
PLANET_ABBREV = {
    "Moon": "Mo", "Mars": "Ma", "Mercury": "Me", "Venus": "Ve",
    "Jupiter": "Ju", "Sun": "Su", "Saturn": "Sa",
    "Rahu": "Ra", "Ketu": "Ke",
}

# ---- NISARGA PERIODS (Level 1 main periods) --------------------------------
# Moon=1, Mars=2, Mercury=9, Venus=20, Jupiter=18, Sun=20, Saturn=50 = 120y

NISARGA_PERIODS = [
    {"lord": "Moon",    "start_age": 0,   "end_age": 1,   "duration": 1,
     "description": "Infancy"},
    {"lord": "Mars",    "start_age": 1,   "end_age": 3,   "duration": 2,
     "description": "Teething"},
    {"lord": "Mercury", "start_age": 3,   "end_age": 12,  "duration": 9,
     "description": "Learning"},
    {"lord": "Venus",   "start_age": 12,  "end_age": 32,  "duration": 20,
     "description": "Youth"},
    {"lord": "Jupiter", "start_age": 32,  "end_age": 50,  "duration": 18,
     "description": "Productive"},
    {"lord": "Sun",     "start_age": 50,  "end_age": 70,  "duration": 20,
     "description": "Middle Age"},
    {"lord": "Saturn",  "start_age": 70,  "end_age": 120, "duration": 50,
     "description": "Old Age"},
]

# ---- MATURATION AGES (shown at bottom of Level 1) --------------------------
# Planet matures during the year BEFORE the listed age (e.g. Jupiter: 15->16)

NISARGA_MATURATION = [
    {"lord": "Jupiter", "age": 16},
    {"lord": "Sun",     "age": 21},
    {"lord": "Moon",    "age": 24},
    {"lord": "Venus",   "age": 25},
    {"lord": "Mars",    "age": 28},
    {"lord": "Mercury", "age": 32},
    {"lord": "Saturn",  "age": 36},
    {"lord": "Rahu",    "age": 42},
    {"lord": "Ketu",    "age": 48},
]

# Number of sub-periods per main period (Level 2)
SUB_PERIOD_COUNT = 12


def calculate_current_age(birth_year, birth_month, birth_day):
    """Calculate current age as a float (e.g. 33.7 years).

    Returns:
        float: Current age in years, or None if birth date is in the future
    """
    today = date.today()
    try:
        birth = date(int(birth_year), int(birth_month), int(birth_day))
    except (ValueError, TypeError):
        return None

    if birth > today:
        return None

    days_lived = (today - birth).days
    return days_lived / 365.25


def get_current_nisarga_index(age):
    """Find which Nisarga period contains the given age.

    Returns:
        int: Index into NISARGA_PERIODS, or None if age > 120
    """
    if age is None or age < 0:
        return None

    for i, period in enumerate(NISARGA_PERIODS):
        if period["start_age"] <= age < period["end_age"]:
            return i

    return None


def get_current_maturation_index(age):
    """Find if the person is currently in a maturation year.

    Maturation occurs from (age-1) to age. E.g. Jupiter matures at 16,
    meaning the maturation period is age 15.0 to 16.0.

    Returns:
        int: Index into NISARGA_MATURATION, or None
    """
    if age is None or age < 0:
        return None

    for i, mat in enumerate(NISARGA_MATURATION):
        mat_start = mat["age"] - 1
        mat_end = mat["age"]
        if mat_start <= age < mat_end:
            return i

    return None


def _birth_date(birth_year, birth_month, birth_day):
    """Helper to create a date object from birth components."""
    try:
        return date(int(birth_year), int(birth_month), int(birth_day))
    except (ValueError, TypeError):
        return None


def _age_str(total_months):
    """Format age as 'Xy Zm' from total months."""
    years = total_months // 12
    months = total_months % 12
    return f"{years}y {months}m"


def format_nisarga_level1(birth_year, birth_month, birth_day):
    """Format Level 1: natural periods + maturation section at bottom.

    Returns list of dicts, each with:
        - text: display string
        - is_current: bool (primary highlight for current period)
        - is_maturation: bool (gold highlight for current maturation year)
        - is_separator: bool (section header, not a real entry)
        - lord: planet name (or None for separators)
    """
    age = calculate_current_age(birth_year, birth_month, birth_day)
    current_period_idx = get_current_nisarga_index(age)
    current_mat_idx = get_current_maturation_index(age)
    birth = _birth_date(birth_year, birth_month, birth_day)

    entries = []

    # --- Natural Periods section ---
    for i, period in enumerate(NISARGA_PERIODS):
        is_current = (i == current_period_idx)
        lord = period["lord"]
        start = period["start_age"]
        end = period["end_age"]
        dur = period["duration"]
        desc = period["description"]

        # Calculate actual dates from birth
        start_str = ""
        end_str = ""
        if birth:
            try:
                start_dt = birth + relativedelta(years=start)
                end_dt = birth + relativedelta(years=end)
                start_str = start_dt.strftime("%m/%d/%Y")
                end_str = end_dt.strftime("%m/%d/%Y")
            except (ValueError, OverflowError):
                pass

        arrow = "\u25b6 " if is_current else "  "
        if start_str and end_str:
            text = f"{arrow}{lord:8}  {start}-{end}y  ({start_str} - {end_str})"
        else:
            text = f"{arrow}{lord:8}  {start}-{end}y  ({dur}y)  {desc}"

        entries.append({
            "text": text,
            "is_current": is_current,
            "is_maturation": False,
            "is_separator": False,
            "lord": lord,
        })

    # --- Separator ---
    entries.append({
        "text": "  ---- Maturation Years ----",
        "is_current": False,
        "is_maturation": False,
        "is_separator": True,
        "lord": None,
    })

    # --- Maturation Ages section ---
    for i, mat in enumerate(NISARGA_MATURATION):
        is_mat_current = (i == current_mat_idx)
        lord = mat["lord"]
        mat_age = mat["age"]
        start = mat_age - 1

        start_str = ""
        end_str = ""
        if birth:
            try:
                start_dt = birth + relativedelta(years=start)
                end_dt = birth + relativedelta(years=mat_age)
                start_str = start_dt.strftime("%m/%d/%Y")
                end_str = end_dt.strftime("%m/%d/%Y")
            except (ValueError, OverflowError):
                pass

        arrow = "\u25b6 " if is_mat_current else "  "
        if start_str and end_str:
            text = f"{arrow}{lord:8}  {start}-{mat_age}y  ({start_str} - {end_str})"
        else:
            text = f"{arrow}{lord:8}  {start}-{mat_age}y  matures at {mat_age}"

        entries.append({
            "text": text,
            "is_current": False,
            "is_maturation": is_mat_current,
            "is_separator": False,
            "lord": lord,
        })

    return entries


def format_nisarga_level2(birth_year, birth_month, birth_day):
    """Format Level 2: sub-periods (each main period divided into 12).

    Sub-periods: Mo/1, Mo/2... Mo/12, Ma/1, Ma/2...
    Each main period is divided into 12 equal sub-periods.

    Returns list of dicts with: text, is_current, lord, sub_index
    """
    age = calculate_current_age(birth_year, birth_month, birth_day)
    birth = _birth_date(birth_year, birth_month, birth_day)
    today = date.today()

    entries = []

    for period in NISARGA_PERIODS:
        lord = period["lord"]
        abbrev = PLANET_ABBREV.get(lord, lord[:2])
        start_age = period["start_age"]
        duration_years = period["duration"]

        # Duration in days for precise sub-period calculation
        if birth:
            period_start_dt = birth + relativedelta(years=start_age)
            period_end_dt = birth + relativedelta(years=period["end_age"])
            total_days = (period_end_dt - period_start_dt).days
            sub_days = total_days / SUB_PERIOD_COUNT
        else:
            total_days = int(duration_years * 365.25)
            sub_days = total_days / SUB_PERIOD_COUNT

        for sub_idx in range(1, SUB_PERIOD_COUNT + 1):
            # Calculate sub-period start date and age
            if birth:
                sub_start_dt = period_start_dt + timedelta(days=(sub_idx - 1) * sub_days)
                date_str = sub_start_dt.strftime("%m/%d/%Y")
                time_str = sub_start_dt.strftime("%H:%M")

                # Age string
                delta = relativedelta(sub_start_dt, birth)
                age_months = delta.years * 12 + delta.months
                age_text = _age_str(age_months)

                # Is this sub-period current?
                sub_end_dt = period_start_dt + timedelta(days=sub_idx * sub_days)
                is_current = (sub_start_dt <= today < sub_end_dt)
            else:
                date_str = ""
                time_str = ""
                age_text = ""
                is_current = False

            arrow = "\u25b6 " if is_current else "  "
            text = f"{arrow}{abbrev}/{sub_idx:<3}  {date_str}  {age_text}"

            entries.append({
                "text": text,
                "is_current": is_current,
                "is_separator": False,
                "is_maturation": False,
                "lord": lord,
                "sub_index": sub_idx,
            })

    return entries
