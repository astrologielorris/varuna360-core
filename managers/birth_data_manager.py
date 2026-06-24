# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Birth Data Manager - Single Source of Truth for Birth Data

This module provides a canonical birth data structure that all UI views
consume consistently. It eliminates data inconsistencies across:
- Title bar display
- Edit Info panel
- CHTK Lines editor
- Chart Memory panel

The canonical structure contains both LOCAL and UTC times, with proper
timezone detection from coordinates.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any


def _fmt_dec(hours_float: float) -> str:
    """Format decimal hours as +HH:MM via format_offset (sign-safe, SPEC-TZ-001 5e)."""
    from core.time_utils import format_offset
    total_min = int(round(hours_float * 60))
    return format_offset(total_min // 60, total_min % 60)


class BirthDataManager:
    """
    Manages canonical birth data with single source of truth.

    All UI components should read from the canonical birth_data dict
    rather than interpreting raw CHTK data themselves.
    """

    @staticmethod
    def create_birth_data_from_chtk(chtk_path: str) -> Dict[str, Any]:
        """
        Parse CHTK file and create canonical birth_data dictionary.

        This is the PRIMARY entry point for loading birth data.

        Args:
            chtk_path: Path to .chtk file

        Returns:
            Canonical birth_data dict with all fields populated
        """
        from core.chtk_reader import CHTKReader

        reader = CHTKReader()
        raw_data = reader.read_chtk_file(chtk_path)

        return BirthDataManager.create_from_raw_data(raw_data, chtk_path)

    @staticmethod
    def create_from_raw_data(raw_data: Dict, chtk_path: str = None) -> Dict[str, Any]:
        """
        Create canonical birth_data from parsed CHTK data.

        Args:
            raw_data: Dict from CHTKReader.read_chtk_file()
            chtk_path: Optional path to source file

        Returns:
            Canonical birth_data dict
        """
        # Extract location info
        coords = raw_data.get('coordinates', {})
        latitude = coords.get('latitude', 0)
        longitude = coords.get('longitude', 0)

        # LOCAL time from CHTK (stored as-is in file).
        # Read BEFORE timezone parsing: pure-IANA resolution below needs the
        # birth year for historical rules (SPEC-TZ-001 ref_year rule).
        local_year = raw_data.get('year', 1970)
        local_month = raw_data.get('month', 1)
        local_day = raw_data.get('day', 1)
        local_hour = raw_data.get('hour', 12)
        local_minute = raw_data.get('minute', 0)
        local_second = raw_data.get('second', 0)

        # Get raw timezone from CHTK (may be malformed)
        chtk_tz = raw_data.get('timezone', '+00:00:00')
        time_change_flag = raw_data.get('time_change_flag', 0)
        tz_warnings: List[str] = []

        # Parse and invert CHTK timezone (CHTK uses opposite sign)
        utc_offset_hours = BirthDataManager._parse_chtk_timezone(chtk_tz)

        # Pure IANA name in the CHTK timezone field (malformed per CHTK spec):
        # _parse_chtk_timezone returns 0.0 for it (no colon after last '/').
        # The == 0.0 guard confirms the parser took that branch; hybrid forms
        # like '+Europe/Lisbon:00:00' keep a colon in the last segment and are
        # excluded. Resolve with the birth year's historical rules. NO sign
        # inversion: an IANA name denotes the zone directly (CHTK inversion
        # applies only to offset strings). SPEC-TZ-001 8a, td-n0ug source (b).
        _tz_clean = str(chtk_tz).strip() if chtk_tz else ''
        _seg = _tz_clean.rsplit('/', 1)
        if len(_seg) == 2 and ':' not in _seg[1] and utc_offset_hours == 0.0:
            # Date-aware resolution (pm-20260610-106): resolve at the actual
            # birth instant so negative-DST zones (Europe/Dublin) convert
            # correctly in BOTH seasons, not just the Jan probe date.
            try:
                from core.time_utils import resolve_total_offset
                _std, _ = resolve_total_offset(
                    _tz_clean, local_year if local_year >= 1 else 1,
                    local_month, local_day, local_hour, local_minute,
                    longitude=longitude)
                utc_offset_hours = _std
            except Exception:
                # Bad IANA name degrades to the old date-less path (which
                # returns 0, 0 on failure), keeping the existing warning.
                from core.time_utils import _parse_offset
                _h, _m = _parse_offset(
                    _tz_clean, ref_year=local_year if local_year >= 1 else 1)
                utc_offset_hours = _h + _m / 60.0
            tz_warnings.append(
                f"Timezone: CHTK timezone field contains IANA name '{_tz_clean}' "
                f"(malformed per CHTK spec); resolved standard offset "
                f"{_fmt_dec(utc_offset_hours)} using year {local_year} rules")

        # Apply DST/War Time offset (flag 1 = +1h DST, flag 2 = +2h War Time).
        # INVARIANT (m14): from here on 'utc_offset_hours' is the TOTAL offset
        # (standard + flag). All consumers expect TOTAL: panels subtract the
        # flag for standard-offset display, _compute_chtk_timezone subtracts
        # it for the CHTK field, chart builds take it as display metadata.
        # Never re-add the flag downstream.
        if time_change_flag in (1, 2):
            utc_offset_hours += time_change_flag

        # Convert to UTC (delegates to core.time_utils for both CE and BCE)
        from core.time_utils import local_to_utc_total
        utc_year, utc_month, utc_day, utc_hour, utc_minute, utc_second = (
            local_to_utc_total(local_year, local_month, local_day,
                               local_hour, local_minute, local_second,
                               utc_offset_hours))

        # Detect IANA timezone from coordinates
        iana_timezone = BirthDataManager._detect_timezone(latitude, longitude)

        # Build canonical structure
        birth_data = {
            # Identity
            'name': raw_data.get('name', 'Unknown'),
            'gender': raw_data.get('gender', 'Unknown'),

            # Location
            'city': raw_data.get('city', ''),
            'country': raw_data.get('country', ''),
            'latitude': latitude,
            'longitude': longitude,

            # LOCAL time (what's in CHTK, what user sees)
            'local_year': local_year,
            'local_month': local_month,
            'local_day': local_day,
            'local_hour': local_hour,
            'local_minute': local_minute,
            'local_second': local_second,

            # UTC time (for calculations)
            'utc_year': utc_year,
            'utc_month': utc_month,
            'utc_day': utc_day,
            'utc_hour': utc_hour,
            'utc_minute': utc_minute,
            'utc_second': utc_second,

            # Timezone info
            'iana_timezone': iana_timezone,
            'utc_offset_hours': utc_offset_hours,
            'time_change_flag': time_change_flag,
            'chtk_timezone': chtk_tz,  # Original format for saving
            'tz_warnings': tz_warnings,  # SPEC-TZ-001 8a creation-path channel

            # Raw CHTK data (for CHTK editor)
            'raw_chtk_data': raw_data,

            # Source file
            'chtk_path': str(chtk_path) if chtk_path else None,
        }

        # Log canonical birth data for DAI tracing
        # This captures the result AFTER timezone conversion (critical audit point)

        return birth_data

    @staticmethod
    def _parse_chtk_timezone(tz_str: str) -> float:
        """
        Parse CHTK timezone and return UTC offset in hours.

        CHTK uses OPPOSITE sign convention:
        - CHTK "-01:00:00" = UTC+1 (Europe/Paris winter)
        - CHTK "+05:30:00" = UTC-5:30

        Also handles malformed formats like "+Europe/Lisbon:00:00"

        Args:
            tz_str: CHTK timezone string

        Returns:
            UTC offset in hours (positive = east of UTC)
        """
        if not tz_str:
            return 0.0

        tz_str = str(tz_str).strip()

        # Handle hybrid format bug: "+Europe/Lisbon:00:00" or "-Europe/Lisbon:00:00"
        if '/' in tz_str:
            original_sign = '-' if tz_str.startswith('-') else '+'
            parts = tz_str.split('/')
            if len(parts) > 1:
                last_part = parts[-1]
                if ':' in last_part:
                    colon_parts = last_part.split(':', 1)
                    if len(colon_parts) > 1:
                        tz_str = original_sign + colon_parts[1]
                else:
                    # Pure IANA name (e.g. "Europe/Paris") in a CHTK timezone field.
                    # Cannot resolve accurately without the birth date (southern
                    # hemisphere DST would give wrong offset for a fixed probe date).
                    # Return 0.0; the caller should use _detect_timezone + ZoneInfo
                    # with the actual birth datetime for accurate resolution.
                    return 0.0

        # Strip comment markers if present
        if '>' in tz_str:
            tz_str = tz_str.split('>')[0].strip()

        # Parse ±HH:MM:SS format
        match = re.match(r'([+-])(\d{1,2}):?(\d{2})?:?(\d{2})?', tz_str)
        if not match:
            # Try just number
            try:
                return -float(tz_str)  # Invert sign
            except ValueError:
                return 0.0

        sign = match.group(1)
        hours = int(match.group(2) or 0)
        minutes = int(match.group(3) or 0)
        seconds = int(match.group(4) or 0)

        offset = hours + (minutes / 60) + (seconds / 3600)

        # INVERT the sign (CHTK convention)
        # CHTK "-" = positive UTC offset (east)
        # CHTK "+" = negative UTC offset (west)
        if sign == '-':
            return offset
        else:
            return -offset

    @staticmethod
    def _detect_timezone(latitude: float, longitude: float) -> str:
        """
        Detect IANA timezone from coordinates.

        Args:
            latitude: Decimal latitude
            longitude: Decimal longitude

        Returns:
            IANA timezone string (e.g., "Europe/Lisbon")
        """
        try:
            from timezonefinder import TimezoneFinder
            tf = TimezoneFinder()
            tz = tf.timezone_at(lat=latitude, lng=longitude)
            return tz if tz else "UTC"
        except ImportError:
            print("[BirthDataManager] timezonefinder not installed, using UTC")
            return "UTC"
        except Exception as e:
            print(f"[BirthDataManager] Timezone detection failed: {e}")
            return "UTC"

    @staticmethod
    def _compute_chtk_timezone(utc_offset_hours: float, dst_flag: int = 0) -> str:
        """Compute CHTK-format timezone string (inverted sign, standard offset only)."""
        base = utc_offset_hours - dst_flag if dst_flag in (1, 2) else utc_offset_hours
        chtk = -base
        h = int(chtk)
        m = int(abs(chtk - h) * 60)
        sign = '+' if chtk >= 0 else '-'
        return f"{sign}{abs(h):02d}:{m:02d}:00"

    @staticmethod
    def create_from_form_data(
        form_data: Dict[str, Any],
        chtk_path: str = None,
    ) -> Dict[str, Any]:
        """
        Create canonical birth_data from Edit Info form fields.

        Accepts the dict returned by EditInfoSubTab.collect_data() and
        produces the same canonical structure as create_from_raw_data().
        Uses core.time_utils.local_to_utc() for UTC conversion.

        Args:
            form_data: Dict with keys: name, year, month, day, hour, minute,
                       second, gender, city, country, latitude, longitude,
                       timezone, iana_timezone, dst, time_mode
            chtk_path: Optional path to source .chtk file

        Returns:
            Canonical birth_data dict
        """
        from core.time_utils import local_to_utc

        local_year = form_data.get('year', 1970)
        local_month = form_data.get('month', 1)
        local_day = form_data.get('day', 1)
        local_hour = form_data.get('hour', 12)
        local_minute = form_data.get('minute', 0)
        local_second = form_data.get('second', 0)

        latitude = form_data.get('latitude', 0.0)
        longitude = form_data.get('longitude', 0.0)

        tz_offset = form_data.get('timezone', '+00:00')
        iana_tz = form_data.get('iana_timezone', '')
        dst_flag = form_data.get('dst', 0)
        time_mode = form_data.get('time_mode', 'Local')

        tz_warnings: List[str] = []
        utc_input_mode = False

        if time_mode == 'UTC':
            # UTC-entered chart: utc_* == local_* by definition; the timezone
            # field stays informational. Check A is skipped via utc_input_mode
            # (SPEC-TZ-001 8a, pre-mortem pm-20260610-005).
            utc_input_mode = True
            utc_year, utc_month, utc_day = local_year, local_month, local_day
            utc_hour, utc_minute, utc_second = local_hour, local_minute, local_second
        else:
            utc_result = local_to_utc(
                local_year, local_month, local_day,
                local_hour, local_minute, local_second,
                tz_offset, dst_flag,
            )
            utc_year, utc_month, utc_day = utc_result[0], utc_result[1], utc_result[2]
            utc_hour, utc_minute, utc_second = utc_result[3], utc_result[4], utc_result[5]

        # Compute UTC offset in hours via canonical parser (SPEC-TZ-001 Section 2).
        # ref_year: IANA names must resolve with the birth year's historical
        # rules (spec Section 1); unused for +HH:MM offset strings.
        try:
            from core.time_utils import _parse_offset
            _h, _m = _parse_offset(tz_offset, ref_year=local_year if local_year >= 1 else 1)
            utc_offset_hours = _h + _m / 60.0
        except (ValueError, TypeError):
            utc_offset_hours = 0.0
            tz_warnings.append(
                f"Timezone: could not parse timezone '{tz_offset}'; "
                f"chart assumed UTC+0 (SPEC-TZ-001 5f)")

        # INVARIANT (m14): TOTAL offset from here on (see create_from_raw_data).
        if dst_flag in (1, 2):
            utc_offset_hours += dst_flag

        if not iana_tz:
            iana_tz = BirthDataManager._detect_timezone(latitude, longitude)

        gender_raw = form_data.get('gender', '')
        if gender_raw and str(gender_raw).lower() in ('male', 'm', '1'):
            gender = 'Male'
        elif gender_raw and str(gender_raw).lower() in ('female', 'f', '2'):
            gender = 'Female'
        else:
            gender = 'Unknown'

        return {
            'name': form_data.get('name', 'Unknown'),
            'gender': gender,
            'city': form_data.get('city', ''),
            'country': form_data.get('country', ''),
            'latitude': latitude,
            'longitude': longitude,
            'local_year': local_year,
            'local_month': local_month,
            'local_day': local_day,
            'local_hour': local_hour,
            'local_minute': local_minute,
            'local_second': local_second,
            'utc_year': utc_year,
            'utc_month': utc_month,
            'utc_day': utc_day,
            'utc_hour': utc_hour,
            'utc_minute': utc_minute,
            'utc_second': utc_second,
            'iana_timezone': iana_tz,
            'utc_offset_hours': utc_offset_hours,
            'time_change_flag': dst_flag,
            'chtk_timezone': BirthDataManager._compute_chtk_timezone(utc_offset_hours, dst_flag),
            'tz_warnings': tz_warnings,  # SPEC-TZ-001 8a creation-path channel
            'utc_input_mode': utc_input_mode,  # Check A skip for UTC-entered charts
            'raw_chtk_data': {},
            'chtk_path': str(chtk_path) if chtk_path else None,
        }

    @staticmethod
    def validate_birth_data(birth_data: Dict) -> List[str]:
        """
        Validate birth data and return list of warnings.

        Args:
            birth_data: Canonical birth_data dict

        Returns:
            List of warning strings (empty if valid)
        """
        warnings = []

        # Check gender
        gender = birth_data.get('gender', '')
        if not gender or gender.lower() == 'unknown':
            warnings.append("Gender is not specified")

        # Check name
        name = birth_data.get('name', '')
        if not name or name.lower() == 'unknown':
            warnings.append("Name is not specified")

        # Check location
        city = birth_data.get('city', '')
        country = birth_data.get('country', '')
        if not city:
            warnings.append("City is not specified")
        if not country:
            warnings.append("Country is not specified")

        # Check coordinates
        lat = birth_data.get('latitude', 0)
        lon = birth_data.get('longitude', 0)
        if lat == 0 and lon == 0:
            warnings.append("Coordinates appear to be missing (0, 0)")

        # Check for suspicious times
        local_hour = birth_data.get('local_hour', 0)
        local_minute = birth_data.get('local_minute', 0)
        if local_hour == 12 and local_minute == 0:
            warnings.append("Birth time is exactly noon (12:00) - may be unknown")

        # SPEC-TZ-001 8a: creation-path warnings + consistency checks.
        # 'or []' is safe here (list channel, not a numeric field).
        warnings.extend(birth_data.get('tz_warnings') or [])
        warnings.extend(BirthDataManager.verify_timezone_consistency(birth_data))

        return warnings

    @staticmethod
    def verify_timezone_consistency(birth_data: Dict) -> List[str]:
        """
        SPEC-TZ-001 Section 8a consistency checks. ADVISORY ONLY: returns
        warnings, never raises, never blocks a chart load.

        Check A (internal): local minus UTC datetime must equal
            utc_offset_hours within 1 minute. Pure integer arithmetic
            (BCE-safe, no datetime construction). Skipped for UTC-entered
            charts (utc_input_mode) where utc_* == local_* by definition.
        Check B (external): pytz TOTAL offset at the birth instant must
            equal utc_offset_hours (TOTAL vs TOTAL, never standard vs
            standard). Gated: iana_timezone known and not 'UTC',
            local_year >= 1900. Tolerance 1 minute for >= 1970,
            15 minutes for 1900-1969 (pre-1970 IANA data less reliable).
        Check C (suspicion): stored offset 0.0 with flag 0 while the zone
            resolves nonzero at that date: the signature of a silent UTC+0
            fallback (td-n0ug). Reuses Check B's single pytz resolution.

        Known blind spots (documented in SPEC-TZ-001 8a): coordinates (0,0)
        detect as 'UTC' which gates B/C off (the coordinates warning above
        covers that case); a fallback to 0.0 where the detected zone is also
        0.0 at that date is undetectable.
        """
        warnings: List[str] = []
        try:
            fields = ('local_year', 'local_month', 'local_day',
                      'local_hour', 'local_minute', 'local_second',
                      'utc_year', 'utc_month', 'utc_day',
                      'utc_hour', 'utc_minute', 'utc_second')
            vals = {k: birth_data.get(k) for k in fields}
            offset = birth_data.get('utc_offset_hours')
            flag = birth_data.get('time_change_flag')
            if flag is None:
                flag = 0

            # Check A
            if (offset is not None
                    and not birth_data.get('utc_input_mode')
                    and all(vals[k] is not None for k in fields)):
                local_date = (vals['local_year'], vals['local_month'], vals['local_day'])
                utc_date = (vals['utc_year'], vals['utc_month'], vals['utc_day'])
                day_diff = 1 if local_date > utc_date else (-1 if local_date < utc_date else 0)
                local_min = vals['local_hour'] * 60 + vals['local_minute'] + vals['local_second'] / 60.0
                utc_min = vals['utc_hour'] * 60 + vals['utc_minute'] + vals['utc_second'] / 60.0
                diff_min = (local_min - utc_min) + day_diff * 1440
                if abs(diff_min - offset * 60.0) > 1.0:
                    # The implied offset is only meaningful for pairs <= 1 day apart;
                    # the warning itself fires correctly for any corruption.
                    warnings.append(
                        f"Timezone: stored local and UTC datetimes imply offset "
                        f"{_fmt_dec(diff_min / 60.0)} but stored offset is "
                        f"{_fmt_dec(offset)}; the chart fields are inconsistent")

            # Checks B and C share one pytz resolution (performance budget:
            # at most one zone lookup per validation, no TimezoneFinder, no I/O)
            iana = birth_data.get('iana_timezone')
            local_year = vals['local_year']
            if (iana is not None and iana != 'UTC'
                    and local_year is not None and local_year >= 1900
                    and offset is not None
                    and all(vals[k] is not None for k in
                            ('local_month', 'local_day', 'local_hour', 'local_minute'))):
                import pytz
                tz = None
                try:
                    tz = pytz.timezone(iana)
                except pytz.exceptions.UnknownTimeZoneError:
                    warnings.append(
                        f"Timezone: unknown IANA zone '{iana}', offset could not be verified")
                if tz is not None:
                    dt = datetime(local_year, vals['local_month'], vals['local_day'],
                                  vals['local_hour'], vals['local_minute'])
                    try:
                        aware = tz.localize(dt, is_dst=None)
                    except (pytz.exceptions.AmbiguousTimeError,
                            pytz.exceptions.NonExistentTimeError):
                        aware = tz.localize(dt, is_dst=bool(flag))
                    actual_total = aware.utcoffset().total_seconds() / 3600.0
                    tol_min = 1.0 if local_year >= 1970 else 15.0
                    if abs(offset - actual_total) * 60.0 > tol_min:
                        if offset == 0.0 and flag == 0:
                            # Check C: the silent-fallback signature
                            warnings.append(
                                f"Timezone: offset is UTC+0 but {iana} implies "
                                f"{_fmt_dec(actual_total)} for this date; a timezone "
                                f"parse failure may have been silently ignored")
                        else:
                            # Check B: generic disagreement
                            warnings.append(
                                f"Timezone: stored offset {_fmt_dec(offset)} disagrees "
                                f"with {iana} ({_fmt_dec(actual_total)}) for this date")
        except Exception:
            # Advisory contract: the verifier itself can never break a chart load.
            pass
        return warnings

    @staticmethod
    def report_tz_warnings(warnings: List[str], status_bar=None,
                           context: str = "") -> List[str]:
        """
        Surface validation warnings non-blocking (SPEC-TZ-001 8a).

        Prints every warning to the console with a [TZ-CHECK] prefix and,
        when status_bar (anything with .showMessage) is provided, shows the
        first "Timezone: "-prefixed warning there with a (+N more) count.
        Returns the timezone sublist so callers can compose their own
        status message. Never raises.
        """
        tz = [w for w in warnings if w.startswith("Timezone:")]
        try:
            for w in warnings:
                print(f"[TZ-CHECK]{' ' + context if context else ''} {w}")
            if tz and status_bar is not None:
                more = f" (+{len(tz) - 1} more)" if len(tz) > 1 else ""
                prefix = f"{context}: " if context else ""
                status_bar.showMessage(f"{prefix}{tz[0]}{more}")
        except Exception:
            pass
        return tz

    @staticmethod
    def get_display_timezone(birth_data: Dict) -> Tuple[str, str]:
        """
        Get timezone for display purposes.

        Args:
            birth_data: Canonical birth_data dict

        Returns:
            Tuple of (abbreviation, full_string)
            e.g., ("WET", "WET (UTC+0) Europe/Lisbon")
        """
        iana_tz = birth_data.get('iana_timezone', 'UTC')
        offset_hours = birth_data.get('utc_offset_hours', 0)

        # Try to get abbreviation and offset using pytz (authoritative)
        try:
            import pytz
            tz = pytz.timezone(iana_tz)
            local_year = birth_data.get('local_year', 2000)

            # For BCE dates, pytz/datetime can't handle them
            # Use a proxy year for timezone abbreviation
            if local_year < 1:
                proxy_year = 2000  # Use modern year for tz lookup
            else:
                proxy_year = local_year

            dt = datetime(
                proxy_year,
                birth_data.get('local_month', 1),
                birth_data.get('local_day', 1),
                birth_data.get('local_hour', 12),
                birth_data.get('local_minute', 0)
            )
            # td-073c: explicit DST handling. is_dst=None raises on ambiguous
            # or non-existent instants (DST transitions); fall back to the
            # stored time_change_flag rather than pytz's silent is_dst=False.
            try:
                localized = tz.localize(dt, is_dst=None)
            except (pytz.exceptions.AmbiguousTimeError,
                    pytz.exceptions.NonExistentTimeError):
                localized = tz.localize(
                    dt, is_dst=bool(birth_data.get('time_change_flag', 0)))
            abbrev = localized.strftime('%Z')  # WET, CET, EST, etc.

            # Use pytz-computed offset (authoritative), not stored utc_offset_hours
            # which may be stale/zero for legacy charts
            pytz_offset_seconds = localized.utcoffset().total_seconds()
            actual_offset_hours = pytz_offset_seconds / 3600

            # Format offset
            if actual_offset_hours == 0:
                offset_str = "UTC+0"
            elif actual_offset_hours == int(actual_offset_hours):
                offset_str = f"UTC{int(actual_offset_hours):+d}"
            else:
                h = int(actual_offset_hours)
                m = int(abs(actual_offset_hours - h) * 60)
                offset_str = f"UTC{h:+d}:{m:02d}"

            full_string = f"{abbrev} ({offset_str}) {iana_tz}"
            return (abbrev, full_string)

        except ImportError:
            # pytz not available
            if offset_hours == 0:
                return ("UTC", f"UTC {iana_tz}")
            else:
                return ("", f"UTC{offset_hours:+.1f} {iana_tz}")
        except Exception:
            return ("UTC", f"UTC {iana_tz}")

    @staticmethod
    def format_location_string(birth_data: Dict) -> str:
        """
        Format location for display.

        Args:
            birth_data: Canonical birth_data dict

        Returns:
            Formatted string like "Coimbra, Portugal"
        """
        city = birth_data.get('city', '')
        country = birth_data.get('country', '')

        # Clean up city - remove ", 0" suffix if present
        if city.endswith(', 0'):
            city = city[:-3].strip()

        if city and country:
            # Avoid "Portugal, Portugal" duplication
            if city.lower() == country.lower():
                return city
            return f"{city}, {country}"
        elif city:
            return city
        elif country:
            return country
        else:
            return "Unknown"

    @staticmethod
    def format_date_string(birth_data: Dict) -> str:
        """
        Format birth date for display (MM/DD/YYYY format).
        Handles BCE dates (negative years) with proper display.

        Args:
            birth_data: Canonical birth_data dict

        Returns:
            Formatted date string (e.g., "01/15/12 BCE" or "07/23/1985")
        """
        month = birth_data.get('local_month', 1)
        day = birth_data.get('local_day', 1)
        year = birth_data.get('local_year', 1970)

        if year <= 0:
            # BCE year: astronomical year 0 = 1 BCE, -1 = 2 BCE, etc.
            bce_year = 1 - year  # Convert astronomical to BCE
            return f"{month:02d}/{day:02d}/{bce_year} BCE"
        else:
            return f"{month:02d}/{day:02d}/{year}"

    @staticmethod
    def format_time_string(birth_data: Dict, utc: bool = False) -> str:
        """
        Format birth time for display (HH:MM:SS format).

        Args:
            birth_data: Canonical birth_data dict
            utc: If True, return UTC time; else return local time

        Returns:
            Formatted time string
        """
        prefix = 'utc_' if utc else 'local_'
        hour = birth_data.get(f'{prefix}hour', 0)
        minute = birth_data.get(f'{prefix}minute', 0)
        second = birth_data.get(f'{prefix}second', 0)
        return f"{hour:02d}:{minute:02d}:{second:02d}"

# Convenience function for quick access
def create_birth_data_from_chtk(chtk_path: str) -> Dict[str, Any]:
    """Convenience wrapper for BirthDataManager.create_birth_data_from_chtk()"""
    return BirthDataManager.create_birth_data_from_chtk(chtk_path)
