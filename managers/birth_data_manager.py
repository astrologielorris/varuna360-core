# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
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
    """Format decimal hours as +HH:MM:SS (sign-safe, SPEC-TZ-001 5e, td-5mg6)."""
    from core.time_utils import format_offset_from_hours
    return format_offset_from_hours(hours_float)


class BirthDataManager:
    """
    Manages canonical birth data with single source of truth.

    All UI components should read from the canonical birth_data dict
    rather than interpreting raw CHTK data themselves.
    """

    @staticmethod
    def create_birth_data_from_file(
        path: str, canonicalize: bool = True,
    ) -> Dict[str, Any]:
        """
        Generic dispatcher: build canonical birth_data from any supported file.

        Dispatch by file extension (SPEC-IMPORT-001 §3.2, §6.1).

        Args:
            path: Path to a .chtk or .toml chart file
            canonicalize: when True (interactive default) and a .toml file has
                no [moment].jd, the TOML reader writes the computed JD back to
                the file (§4.3 Step 2). Pass False for read-only / batch paths
                (e.g. index build) that must NEVER mutate user files. Ignored
                for the .chtk branch (CHTK has no auto-canonicalize write-back).

        Returns:
            Canonical birth_data dict

        Raises:
            ValueError: if the extension is not a supported chart format
        """
        ext = Path(path).suffix.lower()
        if ext == '.chtk':
            return BirthDataManager.create_birth_data_from_chtk(path)
        elif ext == '.toml':
            return BirthDataManager.create_birth_data_from_toml(
                path, canonicalize=canonicalize)
        else:
            raise ValueError(f"Unsupported chart format: {ext}")

    @staticmethod
    def create_birth_data_from_toml(
        path: str, canonicalize: bool = True,
    ) -> Dict[str, Any]:
        """
        Read a .toml (Open Astrology Chart) file and produce canonical birth_data.

        The TOMLChartReader returns the spec §4.2 raw dict (flat lat/lon floats,
        utc_offset_hours = BASE float, year/month/day/hour/minute/second ints,
        gender str, rodden/tags/notes/julian_day/dst_offset_hours, _toml_extra).
        _build_canonical consumes that documented interface directly.

        Args:
            path: Path to .toml file
            canonicalize: forwarded to TOMLChartReader.read_toml_file. When
                True (default) a missing [moment].jd is computed and written
                back to the file; pass False for read-only / batch paths that
                must not mutate user files (SPEC-IMPORT-001 §6.5 GATE).

        Returns:
            Canonical birth_data dict
        """
        # Lazy import: core.toml_chart is built in parallel (bead .2).
        from core.toml_chart import TOMLChartReader

        raw = TOMLChartReader().read_toml_file(path, canonicalize=canonicalize)
        return BirthDataManager._build_canonical(
            raw, chtk_path=path, source_format='toml')

    @staticmethod
    def create_birth_data_from_chtk(chtk_path: str) -> Dict[str, Any]:
        """
        Parse a CHTK file and create the canonical birth_data dictionary.

        This is the PRIMARY entry point for loading CHTK birth data. It reads
        the file, normalizes CHTK-specific shapes (flatten the nested
        coordinates dict, parse the inverted-sign timezone string into a
        standard-sign BASE float), then delegates to the shared
        _build_canonical() (SPEC-IMPORT-001 §3.2, §3.2.1).

        Args:
            chtk_path: Path to .chtk file

        Returns:
            Canonical birth_data dict with all fields populated
        """
        from core.chtk_reader import CHTKReader

        reader_output = CHTKReader().read_chtk_file(chtk_path)

        # --- CHTK-specific normalization (runs BEFORE _build_canonical) ---
        # Normalize a COPY so the pristine reader output is preserved verbatim
        # as raw_chtk_data (Appendix C: "original reader output"; 112 consumers
        # historically saw the un-normalized CHTK dict with nested coordinates).
        raw = dict(reader_output)
        # 1. Flatten nested coordinates dict to flat lat/lon.
        coords = raw.pop('coordinates', {})
        raw['latitude'] = coords.get('latitude', 0.0)
        raw['longitude'] = coords.get('longitude', 0.0)

        # 2. Parse and invert the CHTK timezone string (CHTK uses opposite
        #    sign) into a standard-sign BASE float. The original 'timezone'
        #    string is left in raw so _build_canonical can preserve it verbatim
        #    as chtk_timezone (lossless write-back) and resolve a pure IANA name
        #    left in that field. The CHTKReader emits 'timezone'; the default
        #    matches the previous create_from_raw_data behavior ('+00:00:00').
        chtk_tz = raw.get('timezone', '+00:00:00')
        raw['timezone'] = chtk_tz
        raw['utc_offset_hours'] = BirthDataManager._parse_chtk_timezone(chtk_tz)
        # NOTE: CHTK does not carry rodden/tags/notes/julian_day/
        # dst_offset_hours. They are intentionally NOT injected; _build_canonical
        # reads them with raw.get(...) which yields None for CHTK (absent),
        # which is the correct canonical value. The None-safe DST fallback
        # (Trap #1) lives in _build_canonical.

        return BirthDataManager._build_canonical(
            raw, chtk_path=chtk_path, source_format='chtk',
            raw_chtk_data=reader_output)

    @staticmethod
    def _build_canonical(raw: Dict, *, chtk_path: Optional[str],
                         source_format: str,
                         raw_chtk_data: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Shared canonicalization: both CHTK and TOML paths produce the same
        output shape (SPEC-IMPORT-001 §3.2, Appendix C).

        Expects FLAT keys in raw: latitude, longitude, utc_offset_hours (BASE,
        standard sign), year, month, day, hour, minute, second,
        time_change_flag, name, gender, city, country. Optional: rodden, tags,
        notes, julian_day, dst_offset_hours, _toml_extra, birth_place.

        Handles:
        - Resolve a pure IANA name left in a CHTK timezone field (CHTK only).
        - Compute the DST-adjusted TOTAL offset [INVARIANT m14] using the float
          dst_offset_hours when present-and-non-None, else time_change_flag.
        - Compute UTC time via local_to_utc_total (CE and BCE safe).
        - Detect the IANA timezone from coordinates.
        - Compute the chtk_timezone string for CHTK write-back compatibility.
        - Propagate rodden/tags/notes/julian_day/dst_offset_hours/_toml_extra.
        - Assemble the canonical dict (raw_chtk_data and chtk_path key names
          kept; 79+ consumers).

        raw_chtk_data: the dict stored under the 'raw_chtk_data' key (Appendix
        C: "original reader output"). Defaults to `raw` itself (correct for the
        TOML path, whose raw IS the reader output). The CHTK path passes the
        PRISTINE reader output here because its `raw` is a normalized copy
        (coordinates flattened, timezone parsed), and consumers expect the
        un-normalized reader shape under this key.
        """
        if raw_chtk_data is None:
            raw_chtk_data = raw
        latitude = raw.get('latitude', 0.0)
        longitude = raw.get('longitude', 0.0)

        # LOCAL time. Read BEFORE timezone resolution: pure-IANA resolution
        # below needs the birth year for historical rules (SPEC-TZ-001 ref_year).
        local_year = raw.get('year', 1970)
        local_month = raw.get('month', 1)
        local_day = raw.get('day', 1)
        local_hour = raw.get('hour', 12)
        local_minute = raw.get('minute', 0)
        local_second = raw.get('second', 0)

        time_change_flag = raw.get('time_change_flag', 0)
        tz_warnings: List[str] = []

        # BASE offset, already standard-sign (CHTK path inverted it,
        # TOML path supplies it directly).
        utc_offset_hours = raw.get('utc_offset_hours', 0.0)

        # The original CHTK timezone string (only present on the CHTK path).
        # TOML has no CHTK string -> None -> chtk_timezone is synthesized below.
        is_chtk = source_format == 'chtk'
        chtk_tz = raw.get('timezone') if is_chtk else None

        # Pure IANA name in a CHTK timezone field (malformed per CHTK spec):
        # _parse_chtk_timezone returns 0.0 for it (no colon after last '/').
        # The == 0.0 guard confirms the parser took that branch; hybrid forms
        # like '+Europe/Lisbon:00:00' keep a colon in the last segment and are
        # excluded. Resolve with the birth year's historical rules. NO sign
        # inversion: an IANA name denotes the zone directly (CHTK inversion
        # applies only to offset strings). SPEC-TZ-001 8a, td-n0ug source (b).
        # TOML never enters this branch (is_chtk is False there).
        if is_chtk:
            _tz_clean = str(chtk_tz).strip() if chtk_tz else ''
            _seg = _tz_clean.rsplit('/', 1)
            if len(_seg) == 2 and ':' not in _seg[1] and utc_offset_hours == 0.0:
                # Date-aware resolution (pm-20260610-106): resolve at the
                # actual birth instant so negative-DST zones (Europe/Dublin)
                # convert correctly in BOTH seasons, not just the Jan probe.
                try:
                    from core.time_utils import resolve_total_offset
                    _std, _ = resolve_total_offset(
                        _tz_clean, local_year if local_year >= 1 else 1,
                        local_month, local_day, local_hour, local_minute,
                        longitude=longitude)
                    utc_offset_hours = _std
                except Exception:
                    # Bad IANA name degrades to the old date-less path (which
                    # returns 0 on failure), keeping the existing warning.
                    from core.time_utils import parse_offset_seconds
                    utc_offset_hours = parse_offset_seconds(
                        _tz_clean, ref_year=local_year if local_year >= 1 else 1) / 3600.0
                tz_warnings.append(
                    f"Timezone: CHTK timezone field contains IANA name "
                    f"'{_tz_clean}' (malformed per CHTK spec); resolved "
                    f"standard offset {_fmt_dec(utc_offset_hours)} using "
                    f"year {local_year} rules")

        # Detect IANA timezone from coordinates. Runs BEFORE the DST
        # application so the -1 auto-flag resolution below can use it.
        # Still exactly ONE TimezoneFinder use per chart (td-5w3c.1).
        iana_timezone = BirthDataManager._detect_timezone(latitude, longitude)

        # Apply DST/War Time as the TOTAL offset [INVARIANT m14]. Use the float
        # dst_offset_hours when present-and-non-None (preserves non-1h DST like
        # Lord Howe Island's 0.5h); fall back to the integer time_change_flag
        # for CHTK charts where dst_offset_hours is None.
        # Trap #1: NEVER use raw.get('dst_offset_hours', float(time_change_flag))
        # (dict.get returns None, not the default, when the key is present with
        # value None). Use an explicit `is None` check.
        # CHTK semantics (preserved byte-for-byte from create_from_raw_data):
        # only flags 1 (DST) and 2 (War Time) add an offset. The reader emits
        # -1 meaning AUTO: resolve DST from IANA rules at load (Kala
        # convention, td-5w3c.1); the integer fallback stays gated on (1, 2).
        dst = raw.get('dst_offset_hours')
        time_change_flag_raw = None
        if dst is None and time_change_flag == -1:
            # Kala AUTO flag: resolve the DST flag from IANA rules at the
            # birth instant, then add float(flag) to the CHTK standard
            # offset. The CHTK std field stays authoritative; the pytz TOTAL
            # is never used outright (SPEC-TZ-001, decompose-from-total is
            # inside resolve_auto_dst_flag's helper). Fail-loud branch (c),
            # no coordinates so no IANA detection, lives here; branches (a)
            # and (b) live in resolve_auto_dst_flag.
            time_change_flag_raw = -1
            if latitude == 0.0 and longitude == 0.0:
                resolved_flag = 0
                tz_warnings.append(
                    "Timezone: DST flag -1 could not be auto-resolved: no "
                    "coordinates to detect an IANA zone (chart may be 1h off)")
            else:
                from core.time_utils import resolve_auto_dst_flag
                resolved_flag, _auto_warns = resolve_auto_dst_flag(
                    iana_timezone, local_year, local_month, local_day,
                    local_hour, local_minute, longitude=longitude)
                tz_warnings.extend(_auto_warns)
            # Normalize outward: consumers (recipes, panels, write-back)
            # must only ever see a real flag (0/1), never the -1 sentinel.
            time_change_flag = resolved_flag
            dst = float(resolved_flag)
        if dst is None:
            dst = float(time_change_flag) if time_change_flag in (1, 2) else 0.0
        # From here on 'utc_offset_hours' is the TOTAL offset (standard + DST).
        # All consumers expect TOTAL: panels subtract the flag for standard-
        # offset display, _compute_chtk_timezone subtracts it for the CHTK
        # field, chart builds take it as display metadata. Never re-add it.
        utc_offset_hours += dst

        # Convert to UTC (delegates to core.time_utils for both CE and BCE)
        from core.time_utils import local_to_utc_total
        utc_year, utc_month, utc_day, utc_hour, utc_minute, utc_second = (
            local_to_utc_total(local_year, local_month, local_day,
                               local_hour, local_minute, local_second,
                               utc_offset_hours))

        # chtk_timezone string for write-back. CHTK keeps its original string
        # verbatim (lossless round-trip, byte-identical with the pre-refactor
        # output). TOML synthesizes a CHTK-convention string from the standard
        # BASE offset (= TOTAL minus the DST just added) with dst_flag=0 so
        # _compute_chtk_timezone does not subtract the flag a second time.
        if is_chtk:
            chtk_timezone = chtk_tz
        else:
            chtk_timezone = BirthDataManager._compute_chtk_timezone(
                utc_offset_hours - dst, 0)

        # city/country and synthesized display place. Prefer an explicit
        # birth_place from raw (TOML synthesizes it), else build "City, Country".
        city = raw.get('city', '')
        country = raw.get('country', '')
        birth_place = raw.get('birth_place')
        if not birth_place:
            if city and country and str(country).lower() not in (
                    'unknown', '', 'na', 'n/a'):
                birth_place = f"{city}, {country}"
            else:
                birth_place = city or ''

        # Build canonical structure (Appendix C)
        birth_data = {
            # Identity
            'name': raw.get('name', 'Unknown'),
            'gender': raw.get('gender', 'Unknown'),
            'birth_place': birth_place,

            # Location
            'city': city,
            'country': country,
            'latitude': latitude,
            'longitude': longitude,

            # LOCAL time (what user sees)
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
            'chtk_timezone': chtk_timezone,  # CHTK-convention string for saving
            'tz_warnings': tz_warnings,  # SPEC-TZ-001 8a creation-path channel

            # Metadata (new, optional; None for CHTK)
            'rodden': raw.get('rodden'),
            'tags': raw.get('tags'),
            'notes': raw.get('notes'),
            'julian_day': raw.get('julian_day'),
            'dst_offset_hours': raw.get('dst_offset_hours'),

            # Round-trip preservation (TOML only, None for CHTK)
            '_toml_extra': raw.get('_toml_extra'),

            # Source tracking (KEY NAMES KEPT for backward compat, 79+ consumers)
            'source_format': source_format,
            'raw_chtk_data': raw_chtk_data,  # original reader output (any format)
            'chtk_path': str(chtk_path) if chtk_path else None,
        }

        # HARD INVARIANT (td-5w3c.1): the raw-flag key is added ONLY when the
        # -1 auto branch fired. Flag 0/1/2 charts keep their EXACT dict shape
        # (byte-identical no-op for the ~6030 non-auto charts).
        if time_change_flag_raw is not None:
            birth_data['time_change_flag_raw'] = time_change_flag_raw

        return birth_data

    @staticmethod
    def create_from_raw_data(raw_data: Dict, chtk_path: str = None) -> Dict[str, Any]:
        """
        Build canonical birth_data from an ALREADY-PARSED CHTK raw dict.

        DEPRECATED as a public entry: prefer create_birth_data_from_chtk(path)
        / create_birth_data_from_file(path). Retained as a thin backward-compat
        shim (SPEC-IMPORT-001 §6.4 item 4: create_from_raw_data is now an
        internal detail of the CHTK path) for callers/tests that hold a raw
        CHTK dict and have not yet been migrated. It performs the same CHTK
        normalization as create_birth_data_from_chtk (flatten nested
        coordinates, parse the inverted-sign timezone string) then delegates to
        _build_canonical with source_format='chtk'.

        Args:
            raw_data: Dict from CHTKReader.read_chtk_file() (nested coordinates,
                      CHTK-convention timezone string)
            chtk_path: Optional path to source file

        Returns:
            Canonical birth_data dict
        """
        raw = dict(raw_data)  # copy: never mutate the caller's dict
        coords = raw.pop('coordinates', {})
        raw['latitude'] = coords.get('latitude', 0.0)
        raw['longitude'] = coords.get('longitude', 0.0)
        chtk_tz = raw.get('timezone', '+00:00:00')
        raw['timezone'] = chtk_tz
        raw['utc_offset_hours'] = BirthDataManager._parse_chtk_timezone(chtk_tz)
        # Preserve the caller's original (un-normalized) dict under
        # raw_chtk_data, matching the pre-refactor contract.
        return BirthDataManager._build_canonical(
            raw, chtk_path=chtk_path, source_format='chtk',
            raw_chtk_data=raw_data)

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
    def _compute_chtk_timezone(utc_offset_hours: float, dst_flag: int = 0,
                               dst_offset_hours: Optional[float] = None) -> str:
        """Compute CHTK-format timezone string (inverted sign, standard offset
        only).

        Subtracts the DST/War Time amount from the supplied offset to recover
        the standard BASE that CHTK stores. Prefer the float dst_offset_hours
        when present-and-non-None (preserves non-1h DST like Lord Howe Island's
        0.5h); fall back to the integer dst_flag otherwise.

        Trap #1: an explicit `is None` check, never .get(..., float(dst_flag)),
        because the caller may pass dst_offset_hours=None deliberately.

        CALL-SITE CONTRACT: _build_canonical already subtracts the DST itself
        and calls this with (BASE, 0) so nothing is subtracted a second time
        (dst_flag=0 -> not in (1, 2) -> dst=0.0). Preserve that: passing the
        TOTAL offset here requires passing the matching DST amount.
        """
        dst = dst_offset_hours
        if dst is None:
            dst = float(dst_flag) if dst_flag in (1, 2) else 0.0
        else:
            dst = float(dst)  # defensive against Decimal/str (tomllib: float)
        base = utc_offset_hours - dst
        chtk = -base
        # BUG-5 (SPEC-IMPORT-002) + td-5mg6: round (not truncate) the sub-hour
        # component so half/quarter-hour historical offsets (e.g. +05:30,
        # +05:45) survive FP error — and round to total SECONDS, not minutes,
        # so LMT-era offsets like +00:09:21 survive too (minute rounding cost
        # the ADB batch 93 charts 6-21 arcminutes of ascendant). Compute total
        # seconds then divmod so a rounded :60 rolls into the minute/hour
        # instead of emitting an invalid ":60".
        total_sec = int(round(abs(chtk) * 3600))
        h, rem = divmod(total_sec, 3600)
        m, s = divmod(rem, 60)
        sign = '+' if chtk >= 0 else '-'
        return f"{sign}{h:02d}:{m:02d}:{s:02d}"

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
        from core.time_utils import (
            local_to_utc_total, utc_to_local_total, parse_offset_seconds)

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

        # Compute the TOTAL UTC offset FIRST, then convert local<->UTC with that
        # one numeric offset in whichever direction the input mode requires.
        # ref_year: IANA names must resolve with the birth year's historical
        # rules (spec Section 1); unused for +HH:MM offset strings.
        try:
            utc_offset_hours = parse_offset_seconds(
                tz_offset, ref_year=local_year if local_year >= 1 else 1) / 3600.0
        except (ValueError, TypeError):
            utc_offset_hours = 0.0
            tz_warnings.append(
                f"Timezone: could not parse timezone '{tz_offset}'; "
                f"chart assumed UTC+0 (SPEC-TZ-001 5f)")

        # INVARIANT (m14): TOTAL offset from here on (see create_from_raw_data).
        # Add the float DST amount when the form carries one
        # (dst_offset_hours, preserves non-1h DST like Lord Howe Island's
        # 0.5h); else fall back to the integer dst_flag, gated on (1, 2).
        # Trap #1: explicit `is None` check, never .get(..., float(dst_flag)).
        # `dst` is reused below so the chtk_timezone string subtracts the SAME
        # amount that was added here (no integer/float mismatch).
        dst = form_data.get('dst_offset_hours')
        if dst is None:
            dst = float(dst_flag) if dst_flag in (1, 2) else 0.0
        else:
            dst = float(dst)  # defensive against Decimal/str (tomllib: float)
        utc_offset_hours += dst

        # Convert with the TOTAL offset (not the offset-string + integer flag).
        # This is what makes a fractional/non-1h DST correct: the old
        # local_to_utc(tz_offset, dst_flag) path could only add whole hours, so
        # a 0.5h DST silently dropped the half hour and jd came out 30 min off.
        # For integer DST this is byte-identical to the old conversion (proven
        # against a Paris/NY/India/war-time/midnight-roll baseline).
        if time_mode == 'UTC':
            # UTC-entered chart ("hardcore geek mode"): the typed fields ARE the
            # authoritative UTC instant. Keep utc_* = typed and DERIVE the true
            # local civil time from it, so the stored local_* is the real local
            # clock rather than a copy of UTC. Without this the [civil]/jd
            # derived from local_* is wrong by the whole offset -- a UTC-mode
            # Paris summer chart saved a jd 2h early (civil "10:00 local +2" ->
            # UTC 08:00 instead of the true UTC 10:00). utc_input_mode stays
            # True: Check A is skipped for UTC-entered charts (SPEC-TZ-001 8a,
            # pre-mortem pm-20260610-005) and the chtk_timezone string is
            # unaffected.
            utc_input_mode = True
            utc_year, utc_month, utc_day = local_year, local_month, local_day
            utc_hour, utc_minute, utc_second = local_hour, local_minute, local_second
            (local_year, local_month, local_day,
             local_hour, local_minute, local_second) = utc_to_local_total(
                utc_year, utc_month, utc_day,
                utc_hour, utc_minute, utc_second, utc_offset_hours)
        else:
            (utc_year, utc_month, utc_day,
             utc_hour, utc_minute, utc_second) = local_to_utc_total(
                local_year, local_month, local_day,
                local_hour, local_minute, local_second, utc_offset_hours)

        if not iana_tz:
            iana_tz = BirthDataManager._detect_timezone(latitude, longitude)

        gender_raw = form_data.get('gender', '')
        if gender_raw and str(gender_raw).lower() in ('male', 'm', '1'):
            gender = 'Male'
        elif gender_raw and str(gender_raw).lower() in ('female', 'f', '2'):
            gender = 'Female'
        else:
            gender = 'Unknown'

        # Synthesize a display birth_place (Appendix C) consistent with the
        # other two canonical producers.
        _city = form_data.get('city', '')
        _country = form_data.get('country', '')
        if _city and _country and str(_country).lower() not in (
                'unknown', '', 'na', 'n/a'):
            birth_place = f"{_city}, {_country}"
        else:
            birth_place = _city or ''

        return {
            'name': form_data.get('name', 'Unknown'),
            'gender': gender,
            'birth_place': birth_place,
            'city': _city,
            'country': _country,
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
            # Pass the same float `dst` that was added above so the standard
            # BASE is recovered exactly (preserves non-1h DST; no int/float
            # mismatch with the += at the TOTAL-offset step).
            'chtk_timezone': BirthDataManager._compute_chtk_timezone(
                utc_offset_hours, dst_flag, dst_offset_hours=dst),
            'tz_warnings': tz_warnings,  # SPEC-TZ-001 8a creation-path channel
            'utc_input_mode': utc_input_mode,  # Check A skip for UTC-entered charts
            # Metadata (SPEC-IMPORT-001 §6.4 item 5): pass through from the form
            # if present (SPEC-IMPORT-002 will add the editing UI), else None,
            # so editing a chart no longer silently drops these fields.
            'rodden': form_data.get('rodden'),
            'tags': form_data.get('tags'),
            'notes': form_data.get('notes'),
            'julian_day': form_data.get('julian_day'),
            'dst_offset_hours': form_data.get('dst_offset_hours'),
            '_toml_extra': form_data.get('_toml_extra'),
            # Edited charts save back to CHTK by default; allow the caller to
            # override when editing a TOML-sourced chart.
            'source_format': form_data.get('source_format', 'chtk'),
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
