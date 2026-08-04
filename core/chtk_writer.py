"""
CHTK file creation from birth data dicts (web search results).

Extracted for Lite-First access.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

from core.fs_safety import windows_safe_filename


def decimal_to_dms(decimal: float, is_latitude: bool = True) -> str:
    """Convert decimal degrees to CHTK DMS format (e.g. '27N57\\'00' or '082W27\\'36')."""
    is_positive = decimal >= 0
    abs_decimal = abs(decimal)

    degrees = int(abs_decimal)
    minutes_decimal = (abs_decimal - degrees) * 60
    minutes = int(minutes_decimal)
    seconds = int(round((minutes_decimal - minutes) * 60))

    if seconds >= 60:
        seconds -= 60
        minutes += 1
    if minutes >= 60:
        minutes -= 60
        degrees += 1

    if is_latitude:
        direction = 'N' if is_positive else 'S'
        return f"{degrees:02d}{direction}{minutes:02d}'{seconds:02d}"
    else:
        direction = 'E' if is_positive else 'W'
        return f"{degrees:03d}{direction}{minutes:02d}'{seconds:02d}"


def convert_to_utc(
    year: int, month: int, day: int,
    hour: int, minute: int, second: int,
    timezone_offset: str,
    dst_flag: int = 0
) -> tuple:
    """Convert local time to UTC using standard-sign offset (NOT CHTK-inverted)."""
    from core.time_utils import local_to_utc
    return local_to_utc(year, month, day, hour, minute, second,
                        timezone_offset, dst_flag)


def standard_to_chtk_timezone(timezone_offset: str) -> str:
    """Convert standard UTC offset to CHTK format (inverted sign).

    CHTK uses opposite sign: standard +05:00 (UTC+5) -> CHTK -05:00:00.
    Always outputs an explicit sign prefix.
    """
    # Input convention: STANDARD offset string (e.g. '+05:30'), never CHTK-inverted.
    from core.time_utils import _parse_offset, format_offset

    tz = timezone_offset.strip()
    if not tz:
        raise ValueError("empty timezone offset")
    if tz[0] not in ('+', '-'):
        # Historical behavior: unsigned standard input treated as negative (UTC-west).
        tz = '-' + tz
    if '/' in tz:
        raise ValueError(f"IANA name not accepted here; resolve to an offset first: {timezone_offset}")
    h, m = _parse_offset(tz)
    return format_offset(-h, -m) + ":00"


# CHTK gender codes. THREE of them, not two (td-n0z9): Kala itself writes 0
# for a chart with no gender set — verified in Kala-authored files, and 31
# charts in the reference database carry it.
CHTK_GENDER_MALE = "1"
CHTK_GENDER_FEMALE = "2"
CHTK_GENDER_UNSET = "0"


def gender_to_chtk_code(gender) -> str:
    """The ONE mapping from a gender value to a CHTK line-8 code.

    There used to be two, and they disagreed: create_chtk sent an
    unrecognised value to '1' (Male) and CHTKWriter.generate_chtk sent it to
    '2' (Female), so the same chart came out male or female depending on
    which path touched it. They also accepted different inputs — one took
    'M'/'f'/'1', the other only the full words.

    Anything not recognisably male or female maps to 0, which the reader
    turns back into 'Unknown'. A free string from a TOML source ('Other',
    'Nonbinary') still loses its detail, but it comes back as unknown rather
    than as the wrong gender, and the TOML side keeps the original string.
    """
    if gender is None:
        return CHTK_GENDER_UNSET
    if not isinstance(gender, str):
        try:
            code = int(gender)
        except (TypeError, ValueError):
            return CHTK_GENDER_UNSET
        return str(code) if code in (0, 1, 2) else CHTK_GENDER_UNSET
    value = gender.strip().lower()
    if value in ("male", "m", "1"):
        return CHTK_GENDER_MALE
    if value in ("female", "f", "2"):
        return CHTK_GENDER_FEMALE
    return CHTK_GENDER_UNSET


def create_chtk(
    name: str,
    year: int, month: int, day: int,
    hour: int, minute: int, second: int,
    lat: float, lon: float,
    city: str, country: str,
    timezone_offset: str,
    dst_active: bool = False,
    gender: str = "",
    output_path: str = None,
    notes: str = ""
) -> str:
    """Create a 28-line CHTK file from birth data. Returns path to created file."""
    if output_path is None:
        # replace()-only sanitising left ':' intact, and a chart name very
        # often carries one ("Eclipse 11:14 UT"). Windows rejects the whole
        # path in that case, so the save failed there and only there.
        safe_name = windows_safe_filename(
            name.replace(" ", "_").replace("/", "_"))
        output_path = f"{safe_name}.chtk"

    lat_dms = decimal_to_dms(lat, is_latitude=True)
    lon_dms = decimal_to_dms(lon, is_latitude=False)
    chtk_timezone = standard_to_chtk_timezone(timezone_offset)
    gender_code = gender_to_chtk_code(gender)
    dst_flag = "1" if dst_active else "0"
    country_code = country.lower().replace(" ", "")[:10] + "3"
    country_lower = country.lower().replace(" ", "")[:10]

    chtk_lines = [
        name,                       # 1: Name
        str(year),                  # 2: Year
        str(month),                 # 3: Month
        str(day),                   # 4: Day
        str(hour),                  # 5: Hour (LOCAL)
        str(minute),                # 6: Minute
        str(second),                # 7: Second
        gender_code,                # 8: Gender (1=Male, 2=Female)
        country,                    # 9: Country
        city,                       # 10: City
        lon_dms,                    # 11: Longitude
        lat_dms,                    # 12: Latitude
        chtk_timezone,              # 13: Timezone (CHTK inverted format)
        dst_flag,                   # 14: Time change flag
        notes if notes else " ",    # 15: Notes
        "~end of notes~",           # 16: End notes marker
        " ",                        # 17: Muhurtas
        "~end of muhurtas~",        # 18: End muhurtas marker
        "0",                        # 19: Separator
        country_code,               # 20: Country code (residence)
        country_lower,              # 21: Country name (residence)
        city,                       # 22: Residence city
        lon_dms,                    # 23: Residence longitude
        lat_dms,                    # 24: Residence latitude
        chtk_timezone,              # 25: Residence timezone
        "0",                        # 26: Flag
        country_code,               # 27: Country code
        "",                         # 28: Empty line
    ]

    chtk_content = "\n".join(chtk_lines)
    with open(output_path, 'w', encoding='utf-16-le', newline='') as f:
        f.write('﻿')
        f.write(chtk_content.replace('\n', '\r\n'))

    return output_path


def create_chtk_from_web_data(
    birth_data: Dict[str, Any],
    output_dir: Path,
    verbose: bool = True
) -> Optional[Path]:
    """Create CHTK file from a web search result dict."""
    try:
        name = birth_data.get("name", "Unknown")
        safe_name = re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_')
        # The regex above already drops every character Windows forbids; this
        # catches what it cannot see — an empty result and the DOS device
        # names (a chart literally named "Nul" would produce nul.chtk, which
        # Windows treats as the null device and silently discards).
        safe_name = windows_safe_filename(safe_name)
        filename = f"{safe_name}.chtk"
        output_path = output_dir / filename

        notes = birth_data.get("ascendant_raw", "")
        if not birth_data.get("hasBirthTime", True):
            notes = "noon-default" if not notes else f"noon-default {notes}"

        create_chtk(
            name=name,
            year=birth_data["year"],
            month=birth_data["month"],
            day=birth_data["day"],
            hour=birth_data.get("hour", 12),
            minute=birth_data.get("minute", 0),
            second=birth_data.get("second", 0),
            lat=birth_data.get("latitude", 0.0),
            lon=birth_data.get("longitude", 0.0),
            city=birth_data.get("city", "Unknown"),
            country=birth_data.get("country", "Unknown"),
            timezone_offset=birth_data.get("timezone", "+00:00"),
            dst_active=birth_data.get("dst_active", False),
            gender="",
            output_path=str(output_path),
            notes=notes,
        )

        if verbose:
            print(f"[CHTK] Created: {output_path}")

        return output_path

    except Exception as e:
        print(f"[ERROR] Failed to create CHTK: {e}")
        return None
