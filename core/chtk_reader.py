# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
CHTK File Reader and Writer
Integrates with Kala astrology software format
Used for South Indian Chart calculation
"""

import re
from pathlib import Path
from datetime import datetime

class CHTKReader:
    """Read CHTK files (Kala astrology format) and extract birth data."""

    def read_chtk_file(self, chtk_path):
        """
        Read and parse a CHTK file.

        Args:
            chtk_path: Path to .chtk file

        Returns:
            dict: Birth data with keys:
                - name: Person's name
                - gender: Person's gender (Male/Female/Unknown)
                - birth_date: dict with year, month, day
                - birth_time: dict with hour, minute, second
                - birth_place: Location string
                - coordinates: dict with latitude, longitude
                - timezone: Timezone offset (±HH:MM:SS)
                - time_change_flag: 0=Standard, 1=DST, 2=War time
        """
        chtk_path = Path(chtk_path)

        if not chtk_path.exists():
            raise FileNotFoundError(f"CHTK file not found: {chtk_path}")

        # Read file lines - try UTF-16 first (for Kala exports), then UTF-8
        try:
            with open(chtk_path, 'r', encoding='utf-16') as f:
                lines = [line.rstrip('\n') for line in f.readlines()]
        except (UnicodeDecodeError, UnicodeError):
            # Fall back to UTF-8 if UTF-16 fails
            with open(chtk_path, 'r', encoding='utf-8') as f:
                lines = [line.rstrip('\n') for line in f.readlines()]

        # Parse CHTK format (standard: 28 lines, minimum: 14 for basic birth data)
        # See docs/CHTK_FORMAT_SPECIFICATION.md for full format
        if len(lines) < 14:
            raise ValueError(f"Invalid CHTK file: expected at least 14 lines, got {len(lines)}")

        # Extract fields - handle decimal points and various formats
        def parse_int_flexible(val, default=0):
            """Parse integer, handling decimals, letters, and invalid values"""
            try:
                s = str(val).strip()
                if not s:
                    return default
                # Remove decimal point if present (e.g., "5." -> "5")
                s = s.split('.')[0].replace(',', '')
                # Remove non-digit characters (e.g., "5m" -> "5")
                s = ''.join(c for c in s if c.isdigit() or c in '+-')
                if s and s not in ['+', '-']:
                    return int(s)
            except (ValueError, TypeError, AttributeError):
                pass
            return default

        name = lines[0].strip()
        year = parse_int_flexible(lines[1], 1970)
        month = parse_int_flexible(lines[2], 1)
        day = parse_int_flexible(lines[3], 1)
        hour = parse_int_flexible(lines[4], 12)
        minute = parse_int_flexible(lines[5], 0)
        second = parse_int_flexible(lines[6], 0)

        # Parse gender from Line 8
        gender_raw = lines[7].strip() if len(lines) > 7 else ''
        gender = 'Unknown'

        # Check for gender codes directly
        if gender_raw.lower() in ['m', '1']:
            gender = 'Male'
        elif gender_raw.lower() in ['f', '2']:
            gender = 'Female'
        elif 'gender' in gender_raw.lower():
            # Extract the number from gender line (before or after " >gender")
            gender_num = ''
            for char in gender_raw:
                if char.isdigit():
                    gender_num += char
                elif gender_num and not char.isdigit() and char != ' ':
                    break

            if gender_num:
                gender_num = gender_num[0]  # Take first digit
                gender = 'Male' if gender_num == '1' else 'Female' if gender_num == '0' else 'Unknown'
            else:
                # Check for female codes: 'f', 'F', '2'
                if gender_raw.lower() in ['f', '2']:
                    gender = 'Female'

        time_change_flag = parse_int_flexible(lines[13], 0)  # Line 14: DST flag (0=Standard, 1=DST, 2=War time)

        country = lines[8].strip()
        city = lines[9].strip()  # Line 10 is the city field
        longitude_str = lines[10].strip()
        latitude_str = lines[11].strip()
        timezone = lines[12].strip()

        # Clean city field: remove ", 0" suffix if present (Kala convention)
        if city.endswith(', 0'):
            city = city[:-3].strip()

        # Smart parsing: if country is empty/unknown but city contains comma,
        # try to extract country from city
        if (not country or country.lower() in ['unknown', '', 'na', 'n/a']) and ',' in city:
            # Split city by comma
            parts = [part.strip() for part in city.split(',')]

            # Remove any trailing numeric codes (like "0" at the end)
            cleaned_parts = []
            for part in parts:
                # Check if the part is just a number (common in Kala exports)
                if part.isdigit():
                    continue
                # Check if the part ends with a number (e.g., "CA 0" -> "CA")
                if ' ' in part and part.split()[-1].isdigit():
                    part = ' '.join(part.split()[:-1])
                cleaned_parts.append(part)

            if len(cleaned_parts) >= 2:
                # Assume last part is country, everything before is city/state
                city = ', '.join(cleaned_parts[:-1])
                country = cleaned_parts[-1]
            elif len(cleaned_parts) == 1:
                # Only one part, keep as city
                city = cleaned_parts[0]
                country = ''
        # else: city already contains the correct value from line 9

        # Normalize timezone format to ±HH:MM:SS (some files have incomplete format like +7:00)
        if timezone:
            # Parse the timezone and ensure it's in ±HH:MM:SS format
            timezone = self._normalize_timezone_format(timezone)

        # Parse coordinates from DMS format
        latitude = self.dms_to_decimal(latitude_str)
        longitude = self.dms_to_decimal(longitude_str)

        # Build birth_place string
        birth_place = f"{city}, {country}" if city and country and country.lower() not in ['unknown', '', 'na', 'n/a'] else city

        result = {
            'name': name,
            'gender': gender,
            'birth_date': f"{day} {self.month_to_name(month)} {year}",
            'birth_time': f"{hour:02d}:{minute:02d}:{second:02d}",
            'birth_place': birth_place,
            'coordinates': {
                'latitude': latitude,
                'longitude': longitude,
                'latitude_dms': latitude_str,
                'longitude_dms': longitude_str,
            },
            'timezone': timezone,
            'time_change_flag': time_change_flag,
            'year': year,
            'month': month,
            'day': day,
            'hour': hour,
            'minute': minute,
            'second': second,
            'country': country,
            'city': city,  # Changed from 'location' to 'city'
        }

        # Log parsed birth data for DAI tracing

        return result

    def _normalize_timezone_format(self, tz_str):
        """
        Normalize timezone format to ±HH:MM:SS
        Handles incomplete formats like +7:00 or +07:00
        Also strips comment markers like '>timezone' found in some CHTK files

        ALSO handles malformed hybrid formats like "+Europe/Lisbon:00:00"
        where an IANA timezone name got mixed into the offset field.
        """
        if not tz_str:
            return '+00:00:00'

        tz_str = str(tz_str).strip()

        # Strip comment markers (e.g., ">timezone", ">flag") found in some CHTK files
        if '>' in tz_str:
            tz_str = tz_str.split('>')[0].strip()

        # Handle hybrid format bug: "+Europe/Lisbon:00:00" or "-America/New_York:00:00"
        # This happens when IANA timezone name gets mixed with offset format
        if '/' in tz_str:
            # Extract original sign before processing
            original_sign = '+'
            if tz_str.startswith('-'):
                original_sign = '-'
            elif tz_str.startswith('+'):
                original_sign = '+'

            # Find the IANA name and extract what comes after
            # e.g., "+Europe/Lisbon:00:00" -> need to extract "00:00"
            parts = tz_str.split('/')
            if len(parts) > 1:
                # Take the part after the IANA name: "Lisbon:00:00" or just "Lisbon"
                last_part = parts[-1]
                if ':' in last_part:
                    # "Lisbon:00:00" -> split to get ["Lisbon", "00", "00"]
                    colon_parts = last_part.split(':')
                    # Find the first numeric part
                    numeric_parts = []
                    for p in colon_parts:
                        try:
                            numeric_parts.append(int(p))
                        except ValueError:
                            continue

                    if len(numeric_parts) >= 2:
                        # Got hours:minutes (maybe seconds)
                        hours = numeric_parts[0]
                        minutes = numeric_parts[1]
                        seconds = numeric_parts[2] if len(numeric_parts) > 2 else 0
                        return f"{original_sign}{abs(hours):02d}:{abs(minutes):02d}:{abs(seconds):02d}"

                # Pure IANA name with no numeric offset (e.g. "Europe/Paris").
                # Preserve it so BirthDataManager can resolve via ZoneInfo.
                stripped = tz_str.lstrip('+-')
                return stripped

        # Extract sign
        if tz_str.startswith('-'):
            sign = '-'
            tz_str = tz_str[1:]
        elif tz_str.startswith('+'):
            sign = '+'
            tz_str = tz_str[1:]
        else:
            sign = '+'

        # Split by colon
        parts = tz_str.split(':')

        # Get hours, minutes, seconds (float() handles "10.00" from LMT-era CHTK files)
        try:
            hours = int(float(parts[0].strip())) if len(parts) > 0 else 0
            minutes = int(float(parts[1].strip())) if len(parts) > 1 else 0
            seconds = int(float(parts[2].strip())) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            return '+00:00:00'

        # Return normalized format
        return f"{sign}{abs(hours):02d}:{abs(minutes):02d}:{abs(seconds):02d}"

    def dms_to_decimal(self, dms_str):
        """
        Convert DMS format to decimal degrees.
        Input: "48N49'00" or "002E08'54"
        Output: 48.8167 or 2.1483
        """
        if not dms_str:
            return 0.0

        dms_str = str(dms_str).strip()

        # Parse DMS format: DDxMM'SS where x is N/S/E/W
        pattern = r'(\d+)([NSEW])(\d+)[\'′]?(\d*)'
        match = re.match(pattern, dms_str)

        if not match:
            return 0.0

        degrees = float(match.group(1))
        direction = match.group(2)
        minutes = float(match.group(3))
        seconds = float(match.group(4)) if match.group(4) else 0

        # Calculate decimal
        decimal = degrees + (minutes / 60) + (seconds / 3600)

        # Apply direction (S and W are negative)
        if direction in ['S', 'W']:
            decimal = -decimal

        return decimal

    def month_to_name(self, month):
        """Convert month number to name."""
        months = [
            'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'
        ]
        if 1 <= month <= 12:
            return months[month - 1]
        return 'January'

    def timezone_to_offset(self, timezone_str):
        """
        Convert timezone string to hours offset.
        Input: "+00:00:00" or "-05:30:00"
        Output: 0 or -5.5
        """
        if not timezone_str:
            return 0

        # Parse ±HH:MM:SS format
        pattern = r'([+-])(\d+):(\d+):(\d+)'
        match = re.match(pattern, str(timezone_str).strip())

        if not match:
            return 0

        sign = 1 if match.group(1) == '+' else -1
        hours = int(match.group(2))
        minutes = int(match.group(3))
        seconds = int(match.group(4))

        offset = hours + (minutes / 60) + (seconds / 3600)
        return sign * offset

class CHTKWriter:
    """Write birth data to CHTK format files."""

    def generate_chtk(self, birth_data, name=None):
        """
        Generate CHTK file content from birth data.

        Args:
            birth_data: dict with birth information
            name: optional name override

        Returns:
            str: CHTK content (28 lines - see docs/CHTK_FORMAT_SPECIFICATION.md)
        """
        # Extract values, supporting both BirthDataManager keys (local_year etc.)
        # and legacy keys (year, hour, etc.). Use 'in' checks, not 'or',
        # because 0 is valid (midnight, year 0 = 1 BCE).
        year = birth_data['local_year'] if 'local_year' in birth_data else birth_data.get('year', 1970)
        month = birth_data['local_month'] if 'local_month' in birth_data else birth_data.get('month', 1)
        day = birth_data['local_day'] if 'local_day' in birth_data else birth_data.get('day', 1)
        hour = birth_data['local_hour'] if 'local_hour' in birth_data else birth_data.get('hour', 12)
        minute = birth_data['local_minute'] if 'local_minute' in birth_data else birth_data.get('minute', 0)
        second = birth_data['local_second'] if 'local_second' in birth_data else birth_data.get('second', 0)
        time_change_flag = birth_data.get('time_change_flag', 0)

        # Gender - convert to CHTK format (1=Male, 2=Female)
        gender = birth_data.get('gender', 'Unknown')
        if isinstance(gender, str):
            if gender.lower() in ['male', 'm', '1']:
                gender_code = '1'
            elif gender.lower() in ['female', 'f', '2']:
                gender_code = '2'
            else:
                gender_code = '2'  # Default to Female if unknown
        else:
            gender_code = '1' if int(gender) == 1 else '2'

        # City and Country
        country = birth_data.get('country', 'Unknown')
        city = birth_data.get('city', '')
        if not city:
            # Try to extract from birth_place
            birth_place = birth_data.get('birth_place', '')
            if birth_place:
                city = birth_place.split(',')[0].strip()

        # Coordinates: BirthDataManager uses flat keys, legacy uses nested 'coordinates'
        coords = birth_data.get('coordinates', {})
        longitude_dms = coords.get('longitude_dms', '000E00\'00')
        latitude_dms = coords.get('latitude_dms', '00N00\'00')

        if not longitude_dms or longitude_dms == '000E00\'00':
            longitude = birth_data['longitude'] if 'longitude' in birth_data else coords.get('longitude', 0)
            longitude_dms = self.decimal_to_dms(longitude, is_longitude=True)

        if not latitude_dms or latitude_dms == '00N00\'00':
            latitude = birth_data['latitude'] if 'latitude' in birth_data else coords.get('latitude', 0)
            latitude_dms = self.decimal_to_dms(latitude, is_longitude=False)

        # Timezone: BirthDataManager uses 'chtk_timezone', legacy uses 'timezone'
        timezone = birth_data['chtk_timezone'] if 'chtk_timezone' in birth_data else birth_data.get('timezone', '+00:00:00')

        # Check if timezone is IANA name (e.g., "Europe/Rome", "UTC") and convert to offset
        import re
        if timezone and not re.match(r'^[+-]?\d{1,2}:\d{2}:\d{2}$', timezone):
            try:
                from core.time_utils import lmt_corrected_offset
                longitude_dec = birth_data['longitude'] if 'longitude' in birth_data else coords.get('longitude', 0)
                offset_h = lmt_corrected_offset(
                    timezone, year, month, day, hour, minute, second,
                    float(longitude_dec)
                )

                # Subtract DST for CHTK storage (standard offset + flag).
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(timezone)
                dt = datetime(year, month, day, hour, minute, second, tzinfo=tz)
                if dt.tzname() != 'LMT':
                    dst_offset = dt.dst()
                    if dst_offset and time_change_flag:
                        dst_secs = int(dst_offset.total_seconds())
                        offset_h -= int(dst_secs / 3600)

                total_secs = int(round(offset_h * 3600))
                # CHTK sign convention: invert (CHTK -01:00 = UTC+1).
                chtk_total = -total_secs
                chtk_sign = '+' if chtk_total >= 0 else '-'
                offset_hours, _rem = divmod(abs(chtk_total), 3600)
                offset_minutes = _rem // 60
                offset_seconds = _rem % 60
                timezone = f"{chtk_sign}{offset_hours:02d}:{offset_minutes:02d}:{offset_seconds:02d}"
            except Exception as e:
                print(f"[CHTK] Timezone conversion failed for '{timezone}': {e}")
                timezone = '+00:00:00'

        if country.upper() == 'USA':
            # Remove sign for USA timezone
            if timezone.startswith('+') or timezone.startswith('-'):
                timezone = timezone[1:]

        # Name
        if not name:
            name = birth_data.get('name', 'Unknown')

        # Build CHTK (standard 28 lines with residence section)
        # Format city field: ", 0" suffix for non-USA, no suffix for USA
        if country.upper() == 'USA':
            city_formatted = city
        else:
            city_formatted = f"{city}, 0" if city else ", 0"

        lines = [
            name,                      # Line 1: Name
            str(year),                 # Line 2: Year
            str(month),                # Line 3: Month
            str(day),                  # Line 4: Day
            str(hour),                 # Line 5: Hour
            str(minute),               # Line 6: Minute
            str(second),               # Line 7: Second
            gender_code,               # Line 8: Gender (1=Male, 2=Female)
            country,                   # Line 9: Country
            city_formatted,            # Line 10: City (with ", 0" suffix for non-USA)
            longitude_dms,             # Line 11: Longitude (DMS)
            latitude_dms,              # Line 12: Latitude (DMS)
            timezone,                  # Line 13: Timezone
            str(time_change_flag),     # Line 14: DST flag (0=Standard, 1=DST)
            ' ',                       # Line 15: Notes (empty)
            '~end of notes~',          # Line 16: End notes marker
            ' ',                       # Line 17: Empty
            '~end of muhurtas~',       # Line 18: End muhurtas marker
            '0',                       # Line 19: Final 0
        ]

        # Add residence information (same as birth city as default)
        # Residence timezone EQUALS birth timezone (both use same format per country)
        residence_tz = timezone  # Use exact same timezone format as birth

        # Extract residence identifier based on country
        # USA: Extract state code from city (e.g., "New York Hospital, NY" -> "NY1")
        # Others: Just country name (e.g., "France") per Kala convention
        if country.upper() == 'USA':
            city_parts = city.split(',') if city else []
            if len(city_parts) > 1:
                state_code = city_parts[-1].strip()
                residence_id = state_code + '1'
            else:
                residence_id = 'USA1'
        else:
            residence_id = country if country else 'Unknown'

        # Line 27 uses "country, 0" format for non-USA
        residence_id_27 = residence_id if country.upper() == 'USA' else (
            f"{country}, 0" if country else ", 0"
        )

        lines.extend([
            residence_id,              # Line 20: Residence identifier (just country)
            country,                   # Line 21: Residence country
            city_formatted,            # Line 22: Residence city
            longitude_dms,             # Line 23: Residence longitude
            latitude_dms,              # Line 24: Residence latitude
            residence_tz,              # Line 25: Residence timezone
            str(time_change_flag),     # Line 26: Residence DST flag
            residence_id_27,           # Line 27: Identifier (country, 0 for non-USA)
            '',                        # Line 28: Empty end line
        ])

        return '\n'.join(lines)

    def decimal_to_dms(self, decimal, is_longitude=False):
        """
        Convert decimal degrees to DMS format.
        """
        decimal = float(decimal)
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

        if is_longitude:
            direction = 'E' if is_positive else 'W'
            return f"{degrees:03d}{direction}{minutes:02d}'{seconds:02d}"
        else:
            direction = 'N' if is_positive else 'S'
            return f"{degrees:02d}{direction}{minutes:02d}'{seconds:02d}"

    def save_chtk_file(self, birth_data, name=None, output_path=None):
        """
        Generate and save CHTK file.

        Args:
            birth_data: dict with birth information
            name: optional name override
            output_path: path to save file (auto-generates if None)

        Returns:
            Path: path to saved file
        """
        chtk_content = self.generate_chtk(birth_data, name)

        # Auto-generate filename if not provided
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            person_name = (name or birth_data.get('name', 'anonymous')).replace(' ', '_')
            city = birth_data.get('city', '').replace(' ', '_')

            if city:
                filename = f"{person_name}_{city}_{timestamp}.chtk"
            else:
                filename = f"{person_name}_{timestamp}.chtk"

            output_path = Path.cwd() / filename
        else:
            output_path = Path(output_path)

        # Ensure directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Write as UTF-16-LE with explicit BOM and CRLF line endings (Kala format)
        with open(output_path, 'w', encoding='utf-16-le', newline='') as f:
            f.write('\ufeff')  # Explicit BOM
            f.write(chtk_content.replace('\n', '\r\n'))

        return output_path

    def update_chtk_birth_data(self, chtk_path, birth_data):
        """
        Update only the birth-data lines (1-14) of an existing CHTK file,
        preserving notes, muhurtas, and residence blocks (lines 15-28+).

        Args:
            chtk_path: Path to existing .chtk file
            birth_data: Canonical birth_data dict from BirthDataManager

        Returns:
            True on success

        Raises:
            IOError: If the file cannot be read or written
        """
        import os
        import tempfile
        from pathlib import Path

        chtk_path = Path(chtk_path)
        if not chtk_path.exists():
            raise IOError(f"CHTK file not found: {chtk_path}")

        # Read existing file to preserve lines 15+
        for enc in ('utf-16-le', 'utf-16', 'utf-8'):
            try:
                raw = chtk_path.read_text(encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            raise IOError(f"Cannot decode CHTK file: {chtk_path}")

        raw = raw.lstrip('﻿')
        existing_lines = raw.replace('\r\n', '\n').replace('\r', '\n').split('\n')

        # Map canonical birth_data keys to CHTK line format
        lat = birth_data.get('latitude', 0)
        lon = birth_data.get('longitude', 0)
        lat_dms = self.decimal_to_dms(lat, is_longitude=False)
        lon_dms = self.decimal_to_dms(lon, is_longitude=True)

        # Compute CHTK timezone (inverted sign, without DST)
        utc_offset = birth_data.get('utc_offset_hours', 0)
        tcf = birth_data.get('time_change_flag', 0)
        base_offset = utc_offset - tcf if tcf in (1, 2) else utc_offset
        chtk_offset = -base_offset
        chtk_h = int(chtk_offset)
        chtk_m = int(abs(chtk_offset - chtk_h) * 60)
        chtk_sign = '+' if chtk_offset >= 0 else '-'
        tz_str = f"{chtk_sign}{abs(chtk_h):02d}:{chtk_m:02d}:00"

        gender = birth_data.get('gender', 'Unknown')
        if isinstance(gender, str):
            if gender.lower() in ('male', 'm', '1'):
                gender_code = '1'
            elif gender.lower() in ('female', 'f', '2'):
                gender_code = '2'
            else:
                gender_code = '2'
        else:
            gender_code = str(gender)

        city = birth_data.get('city', '')
        country = birth_data.get('country', '')
        if country.upper() != 'USA' and city:
            city_formatted = f"{city}, 0"
        elif not city:
            city_formatted = ", 0" if country.upper() != 'USA' else ""
        else:
            city_formatted = city

        # USA timezone format: no sign prefix
        tz_line = tz_str
        if country.upper() == 'USA' and tz_line.startswith(('+', '-')):
            tz_line = tz_line.lstrip('+-')

        # Build replacement lines 1-14
        new_birth_lines = [
            birth_data.get('name', 'Unknown'),
            str(birth_data.get('local_year', 1970)),
            str(birth_data.get('local_month', 1)),
            str(birth_data.get('local_day', 1)),
            str(birth_data.get('local_hour', 12)),
            str(birth_data.get('local_minute', 0)),
            str(birth_data.get('local_second', 0)),
            gender_code,
            country,
            city_formatted,
            lon_dms,
            lat_dms,
            tz_line,
            str(tcf),
        ]

        # Preserve lines 15+ from the original file (notes, muhurtas, residence)
        if len(existing_lines) > 14:
            preserved = existing_lines[14:]
        else:
            preserved = [
                ' ', '~end of notes~', ' ', '~end of muhurtas~', '0',
                country, country, city_formatted, lon_dms, lat_dms,
                tz_line, str(tcf), country, '',
            ]

        final_lines = new_birth_lines + preserved
        chtk_content = '\n'.join(final_lines)

        # Atomic write: temp file in SAME directory, then os.replace
        fd, tmp_path = tempfile.mkstemp(
            dir=str(chtk_path.parent), suffix='.chtk.tmp',
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-16-le', newline='') as f:
                f.write('﻿')
                f.write(chtk_content.replace('\n', '\r\n'))
            os.replace(tmp_path, str(chtk_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return True

    def read_notes(self, filepath):
        """
        Read notes section from CHTK file.

        Notes are stored between line 15 and the '~end of notes~' marker.
        May contain biography sections like:
        - "---------- Biography section simple search:"
        - "---------- Biography section deep search:"
        - "---------- Biography section astrodient profile:"

        Args:
            filepath: Path to CHTK file

        Returns:
            str: Notes content, or empty string if no notes
        """
        filepath = Path(filepath)
        if not filepath.exists():
            return ""

        try:
            # Try UTF-16 first (Kala native format)
            try:
                with open(filepath, 'r', encoding='utf-16') as f:
                    lines = f.read().splitlines()
            except (UnicodeDecodeError, UnicodeError):
                # Fall back to UTF-8
                with open(filepath, 'r', encoding='utf-8') as f:
                    lines = f.read().splitlines()

            # Find the ~end of notes~ marker
            end_marker_idx = None
            for i, line in enumerate(lines):
                if '~end of notes~' in line:
                    end_marker_idx = i
                    break

            if end_marker_idx is None or end_marker_idx <= 14:
                # No notes or invalid format
                return ""

            # Notes are from line 15 (index 14) to just before the marker
            # Line 15 may just be a space if no notes
            notes_lines = lines[14:end_marker_idx]

            # Join and strip
            notes_text = '\n'.join(notes_lines).strip()

            # If it's just whitespace, return empty
            if not notes_text or notes_text.isspace():
                return ""

            return notes_text

        except Exception as e:
            print(f"Error reading notes from {filepath}: {e}")
            return ""

# Example usage and testing
if __name__ == "__main__":
    # Test data for writing
    test_birth_data = {
        'name': 'Test Person',
        'year': 1970,
        'month': 3,
        'day': 29,
        'hour': 15,
        'minute': 25,
        'second': 0,
        'country': 'United States',
        'city': 'Fort Collins, CO',  # Changed from 'location' to 'city'
        'birth_place': 'Fort Collins, CO, USA',
        'coordinates': {
            'latitude': 40.5853,
            'longitude': -105.0844,
        },
        'timezone': '-07:00:00',
        'time_change_flag': 0,
    }

    # Test writing
    writer = CHTKWriter()
    chtk_content = writer.generate_chtk(test_birth_data)
    print("Generated CHTK:")
    print(chtk_content)
