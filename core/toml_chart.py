# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Open Astrology Chart format (.toml) reader and writer.

Implements SPEC-IMPORT-001 (open-chart-import-definition.md) Sections 4 and 5,
for the upstream "open-astrology-chart" v1 format authored by Josh (Ninth House
Studios). Julian Day is the canonical instant; civil time is advisory.

Public surface:
    TOMLChartReader().read_toml_file(path, canonicalize=True) -> raw dict (§4.2)
    TOMLChartWriter().write(birth_data, path)                 -> writes .toml (§5)
    TOMLChartWriter().update_toml_birth_data(path, birth_data)-> merge + atomic (§6.7)

Design notes:
- Reader emits the §4.2 *raw* dict (NOT the BDM canonical dict). That raw dict is
  the interface seam consumed by BirthDataManager.create_birth_data_from_toml()
  (a separate bead). Its key set is fixed; see TOMLChartReader.RAW_KEYS.
- JD is canonical when [moment].jd is present (civil time is derived from it).
  When jd is absent we compute it from civil time and (only when canonicalize=True)
  write [moment].jd back to the file atomically (upstream §6 conformance).
- Writer hand-formats TOML (StringIO, Dart reference pattern) — no tomli_w dep.
- repr() precision for jd/lat/lon (shortest round-tripping float; upstream §7).
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import tomllib
from datetime import date as _date_cls
from datetime import datetime as _datetime_cls
from datetime import time as _time_cls
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import swisseph as swe

logger = logging.getLogger(__name__)

# Upstream spec markers (§3, §4.3 Step 1).
SPEC_MARKER = "open-astrology-chart"
SUPPORTED_VERSIONS = {1}

# Calendar flag for Swiss Ephemeris. The upstream format and the Dart reference
# both use the proleptic Gregorian calendar for the jd<->civil conversion.
_GREG = swe.GREG_CAL


# ---------------------------------------------------------------------------
# JD <-> civil helpers
# ---------------------------------------------------------------------------

def _jd_to_civil(jd: float) -> tuple[int, int, int, int, int, int]:
    """Convert a Julian Day (any reference frame) to (y, m, d, h, mi, s) ints.

    Uses ``swe.revjul`` for the date and a datetime normalization for the time
    so that sub-second rounding cannot produce a 60-second / 24-hour overflow
    (it correctly rolls into the next minute/day instead).
    """
    y, mo, d, dec_hours = swe.revjul(float(jd), _GREG)
    y, mo, d = int(y), int(mo), int(d)
    total_seconds = round(dec_hours * 3600.0)
    # Anchor at midnight of the revjul date, then add the rounded seconds so the
    # carry propagates through minute/hour/day boundaries. datetime cannot
    # represent year < 1, so fall back to manual normalization there.
    if y >= 1:
        base = _datetime_cls(y, mo, d, tzinfo=timezone.utc)
        full = base + timedelta(seconds=total_seconds)
        return full.year, full.month, full.day, full.hour, full.minute, full.second
    # BCE / year-0 fallback (datetime cannot represent year < 1). Split the time
    # of day into [0, 86400); when the rounded seconds carry a whole day, re-add
    # it through Swiss Ephemeris so the month/year carry is correct (a plain
    # d + extra_days could overflow the month, e.g. day 31 -> 32).
    extra_days, rem = divmod(total_seconds, 86400)
    h = rem // 3600
    mi = (rem % 3600) // 60
    s = rem % 60
    if extra_days:
        cy, cmo, cd, _ = swe.revjul(
            swe.julday(y, mo, d, 0.0, _GREG) + extra_days, _GREG)
        y, mo, d = int(cy), int(cmo), int(cd)
    return y, mo, d, h, mi, s


def _civil_to_jd(year: int, month: int, day: int,
                 hour: int, minute: int, second: int,
                 total_offset_hours: float) -> float:
    """Compute JD(UT) from a LOCAL civil time and its TOTAL offset.

    local_jd = swe.julday(local civil); jd_ut = local_jd - total_offset/24.
    """
    dec_local = hour + minute / 60.0 + second / 3600.0
    local_jd = swe.julday(int(year), int(month), int(day), dec_local, _GREG)
    return local_jd - total_offset_hours / 24.0


def _format_iso_date(year: int, month: int, day: int) -> str:
    """Format a civil date, supporting BCE (negative) years.

    Positive years use the 4-digit ``YYYY-MM-DD`` form. Negative (BCE) years use
    the ISO 8601 expanded form with a leading sign (``-0044-03-15``), which the
    reader's _parse_date round-trips. (A 4-digit %04d on a negative int yields
    ``-044`` which then re-parses with an empty first field — the round-trip bug
    this avoids.)
    """
    if year < 0:
        return f"-{abs(year):04d}-{month:02d}-{day:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _iso_from_toml_temporal(value: Any) -> Any:
    """Convert TOML datetime/date/time objects to ISO 8601 strings (JSON-safety).

    tomllib returns native datetime/date/time for offset-date-time, local-date,
    local-time, etc. These are not JSON-serializable, and _toml_extra values MUST
    be (spec §2 Principle 7, §4.3 Step 9). Containers are walked recursively.
    """
    if isinstance(value, (_datetime_cls, _date_cls, _time_cls)):
        return value.isoformat()
    if isinstance(value, list):
        return [_iso_from_toml_temporal(v) for v in value]
    if isinstance(value, dict):
        return {k: _iso_from_toml_temporal(v) for k, v in value.items()}
    return value


def _normalize_gender(raw_gender: Any) -> tuple[str, Optional[str]]:
    """Normalize a gender value (§4.3 Step 6).

    Returns (normalized, original_if_changed). ``original_if_changed`` is the raw
    string when normalization altered it (so the writer can restore byte-identity
    per §4.3 round-trip note), else None.

    - "male"/"m"  -> "Male"
    - "female"/"f"-> "Female"
    - "unknown"   -> "Unknown"
    - absent      -> "Unknown" (original_if_changed=None; nothing to restore)
    - other       -> preserved as-is (free strings: "nonbinary", "event", ...)
    """
    if raw_gender is None:
        return "Unknown", None
    original = str(raw_gender)
    low = original.strip().lower()
    if low in ("male", "m"):
        norm = "Male"
    elif low in ("female", "f"):
        norm = "Female"
    elif low == "unknown":
        norm = "Unknown"
    else:
        # Free string preserved verbatim; never treated as "changed".
        return original, None
    return norm, (original if original != norm else None)


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

class TOMLChartReader:
    """Read an Open Astrology Chart .toml file into the §4.2 raw dict."""

    # The exact key set emitted by read_toml_file(). This is the interface seam
    # consumed by BirthDataManager.create_birth_data_from_toml(). Do not change
    # without coordinating with that bead.
    RAW_KEYS = (
        "name", "gender",
        "year", "month", "day", "hour", "minute", "second",
        "latitude", "longitude",
        "city", "country", "birth_place",
        "utc_offset_hours", "time_change_flag",
        "rodden", "tags", "notes",
        "julian_day", "dst_offset_hours",
        "source_format",
        "_toml_extra",
    )

    # Keys recognized inside each table (everything else -> _toml_extra by table).
    _KNOWN_TOP = {"spec", "spec_version", "name", "gender", "rodden", "tags",
                  "notes", "moment", "location", "civil"}
    _KNOWN_MOMENT = {"jd"}
    _KNOWN_LOCATION = {"lat", "lon", "placename", "country"}
    _KNOWN_CIVIL = {"date", "time", "utc_offset", "dst_offset"}

    def read_toml_file(self, path, canonicalize: bool = True) -> dict:
        """Read a .toml file and return the §4.2 raw dict.

        Args:
            path: path to the .toml file (UTF-8, no BOM).
            canonicalize: when True (interactive default) and the file has no
                [moment].jd, compute it and write it back atomically. When False
                (batch / indexer), compute JD in memory only and NEVER touch the
                file (GATE: indexing must not mutate user files).

        Raises:
            ValueError: spec marker / version mismatch, or malformed instant.
            tomllib.TOMLDecodeError: invalid TOML syntax (propagated).
            OSError: file cannot be read.
        """
        path = Path(path)
        with open(path, "rb") as f:
            doc = tomllib.load(f)

        # --- Step 1: validate spec marker + version (§4.3 Step 1, §9.1) ---
        if doc.get("spec") != SPEC_MARKER:
            raise ValueError(
                f"Not an Open Astrology Chart file (spec={doc.get('spec')!r}): {path}"
            )
        version = doc.get("spec_version")
        # Must be a true int. `version in {1}` would also accept 1.0 and True
        # (Python compares by ==); spec versions are integers by definition.
        if type(version) is not int or version not in SUPPORTED_VERSIONS:
            raise ValueError(
                f"Unsupported spec_version {version!r} "
                f"(supported: {sorted(SUPPORTED_VERSIONS)}): {path}"
            )

        moment = doc.get("moment") or {}
        location = doc.get("location") or {}
        civil = doc.get("civil") or {}
        has_civil_table = "civil" in doc

        # --- Location (§4.3 Step 7); lat/lon required (§9.1) ---
        if "lat" not in location or "lon" not in location:
            raise ValueError(f"Missing location.lat/location.lon: {path}")
        latitude = float(location["lat"])
        longitude = float(location["lon"])
        city = str(location.get("placename", "") or "")
        country = str(location.get("country", "") or "")
        if city and country:
            birth_place = f"{city}, {country}"
        else:
            birth_place = city

        # --- Civil offsets (BASE) + DST (§4.3 Step 5) ---
        jd_present = moment.get("jd") is not None
        utc_offset_present = "utc_offset" in civil
        utc_offset = float(civil.get("utc_offset", 0.0))
        # dst_offset is stored verbatim for round-trip of non-1h DST.
        dst_present = "dst_offset" in civil
        dst_offset = float(civil.get("dst_offset", 0.0)) if dst_present else None
        dst_for_total = dst_offset if dst_offset is not None else 0.0
        # BUG-9 (SPEC-IMPORT-002): any non-zero DST (positive OR negative) means
        # DST was in effect; only exactly 0.0 sets flag=0. Negative historical DST
        # previously set flag=0, hiding DST from downstream flag consumers. JD is
        # unaffected (total_offset already folds in dst_for_total). War Time (flag=2)
        # remains round-trip lossy to flag=1 on TOML re-import (documented §7).
        time_change_flag = 0 if dst_for_total == 0 else 1

        # --- Resolve the instant (§4.3 Steps 2-4, partial-civil §4.3 Step 3) ---
        julian_day: Optional[float]
        derived_civil_only = False  # True when we synthesized civil from coords

        if jd_present:
            julian_day = float(moment["jd"])
            if not has_civil_table:
                # §4.3 Step 3 + §9.1: no [civil] at all -> derive offset from
                # coordinates (IANA), then civil time from JD at that offset.
                utc_offset, time_change_flag, dst_offset = self._offset_from_coords(
                    latitude, longitude, julian_day, path)
                dst_for_total = dst_offset if dst_offset is not None else 0.0
                derived_civil_only = True
            elif not utc_offset_present:
                # [civil] exists but no utc_offset -> default 0.0 (Dart parity).
                logger.warning(
                    "No utc_offset in [civil], defaulting to UTC: %s", path)
            total_offset = utc_offset + dst_for_total
            y, mo, d, h, mi, s = _jd_to_civil(julian_day + total_offset / 24.0)
            if has_civil_table and not derived_civil_only:
                self._warn_civil_disagreement(civil, total_offset, julian_day, path)
        else:
            # No jd: must have civil date + time (§4.3 Step 2 / §9.1).
            c_date = civil.get("date")
            c_time = civil.get("time")
            if not c_date or not c_time:
                raise ValueError(
                    f"Malformed: no [moment].jd and no [civil].date+time: {path}")
            y, mo, d = self._parse_date(c_date, path)
            h, mi, s = self._parse_time(c_time, path)
            if not utc_offset_present:
                logger.warning(
                    "No utc_offset in [civil], defaulting to UTC: %s", path)
            total_offset = utc_offset + dst_for_total
            julian_day = _civil_to_jd(y, mo, d, h, mi, s, total_offset)
            # Auto-canonicalize: write [moment].jd back (§4.3 Step 2, §6.13).
            if canonicalize:
                self._canonicalize_write_back(path, julian_day)
            else:
                logger.info(
                    "Computed JD in memory (batch mode, no write-back): %s", path)

        # --- Gender (§4.3 Step 6) ---
        gender, original_gender = _normalize_gender(doc.get("gender"))

        # --- Metadata (§4.3 Step 8) ---
        rodden = doc.get("rodden")
        if rodden is not None:
            rodden = str(rodden)
        tags = self._parse_tags(doc.get("tags"))
        notes = doc.get("notes")
        if notes is not None:
            notes = str(notes)

        # --- Unknown keys + tracked optional extras (§4.3 Step 9) ---
        toml_extra = self._collect_extra(
            doc, moment, location, civil,
            dst_present=dst_present, dst_offset=dst_offset,
            original_gender=original_gender,
        )

        return {
            "name": str(doc.get("name", "") or ""),
            "gender": gender,
            "year": int(y), "month": int(mo), "day": int(d),
            "hour": int(h), "minute": int(mi), "second": int(s),
            "latitude": latitude,
            "longitude": longitude,
            "city": city,
            "country": country,
            "birth_place": birth_place,
            "utc_offset_hours": utc_offset,   # BASE, standard sign
            "time_change_flag": time_change_flag,
            "rodden": rodden,
            "tags": tags,
            "notes": notes,
            "julian_day": julian_day,
            "dst_offset_hours": dst_offset,   # float or None (None == absent)
            "source_format": "toml",
            "_toml_extra": toml_extra,
        }

    # -- parsing helpers -----------------------------------------------------

    @staticmethod
    def _parse_date(value, path) -> tuple[int, int, int]:
        """Parse civil.date. tomllib may give a str OR a datetime.date."""
        if isinstance(value, _date_cls) and not isinstance(value, _datetime_cls):
            return value.year, value.month, value.day
        if isinstance(value, _datetime_cls):
            return value.year, value.month, value.day
        try:
            s = str(value)
            # ISO expanded years can be negative (BCE): "-0044-03-15".
            neg = s.startswith("-")
            if neg:
                s = s[1:]
            parts = s.split("-")
            year = int(parts[0]) * (-1 if neg else 1)
            return year, int(parts[1]), int(parts[2])
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Invalid civil.date {value!r}: {path}") from exc

    @staticmethod
    def _parse_time(value, path) -> tuple[int, int, int]:
        """Parse civil.time. tomllib may give a str OR a datetime.time.

        A trailing leap-second-style ``second == 60`` (or any second/minute
        overflow in a hand-authored file) is normalized by carry so the raw dict
        upholds its "0-59" guarantee.
        """
        if isinstance(value, _time_cls):
            return value.hour, value.minute, value.second
        if isinstance(value, _datetime_cls):
            return value.hour, value.minute, value.second
        try:
            parts = str(value).split(":")
            h = int(parts[0])
            mi = int(parts[1]) if len(parts) > 1 else 0
            s = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError) as exc:
            raise ValueError(f"Invalid civil.time {value!r}: {path}") from exc
        # Normalize overflow (e.g. 23:59:60 -> 24:00:00 -> carried into the day).
        mi += s // 60
        s %= 60
        h += mi // 60
        mi %= 60
        return h, mi, s

    @staticmethod
    def _parse_tags(raw_tags) -> Optional[list]:
        """Tags: list[str], deduplicated preserving first-occurrence order."""
        if raw_tags is None:
            return None
        if not isinstance(raw_tags, (list, tuple)):
            return None
        seen = set()
        out = []
        for item in raw_tags:
            s = str(item)
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out

    def _collect_extra(self, doc, moment, location, civil, *,
                       dst_present, dst_offset, original_gender) -> dict:
        """Collect unknown keys nested by table, using ORIGINAL key names (§4.3 Step 9).

        Also records two round-trip markers in '_top':
          - _original_gender: restore the as-authored gender string (§4.3 note).
          - (dst_offset==0.0 re-emit is handled via civil['dst_offset'], §6.14.)
        All values are ISO-stringified for JSON-safety.
        """
        extra: dict[str, dict] = {}

        top = {k: _iso_from_toml_temporal(v)
               for k, v in doc.items() if k not in self._KNOWN_TOP}
        if original_gender is not None:
            top["_original_gender"] = original_gender
        if top:
            extra["_top"] = top

        m_extra = {k: _iso_from_toml_temporal(v)
                   for k, v in moment.items() if k not in self._KNOWN_MOMENT}
        if m_extra:
            extra["moment"] = m_extra

        loc_extra = {k: _iso_from_toml_temporal(v)
                     for k, v in location.items()
                     if k not in self._KNOWN_LOCATION}
        if loc_extra:
            extra["location"] = loc_extra

        civ_extra = {k: _iso_from_toml_temporal(v)
                     for k, v in civil.items() if k not in self._KNOWN_CIVIL}
        # §6.14: re-emit dst_offset = 0.0 on round-trip when it was present as 0.0.
        # (Non-zero dst is carried by dst_offset_hours and re-emitted by the
        # writer anyway; we only need to track the explicit-zero case here.)
        if dst_present and dst_offset == 0.0:
            civ_extra["dst_offset"] = 0.0
        if civ_extra:
            extra["civil"] = civ_extra

        return extra

    # -- timezone-from-coordinates (partial/missing civil) -------------------

    @staticmethod
    def _offset_from_coords(latitude, longitude, jd, path):
        """Resolve a numeric offset from coordinates at the JD's date (§4.3 Step 3).

        Returns (utc_offset_base, time_change_flag, dst_offset). pytz returns the
        TOTAL offset at that instant; we cannot decompose standard vs DST, so we
        emit the whole thing as BASE with flag=0 and dst_offset=0.0. The final
        UTC time is still correct (the imprecision is only in the BASE/DST split).
        """
        offset = 0.0
        try:
            from timezonefinder import TimezoneFinder
            tf = TimezoneFinder()
            iana = tf.timezone_at(lat=latitude, lng=longitude)
            if iana:
                import pytz
                # Approximate civil date from the UTC instant to pick the rule.
                uy, um, ud, uh, umi, _us = _jd_to_civil(jd)
                if uy < 1:
                    # BUG-10 (SPEC-IMPORT-002): datetime()/pytz cannot localize
                    # year < 1 (BCE) dates (raises ValueError, previously swallowed
                    # by the broad except below -> silent UTC fallback). Make the
                    # limitation explicit instead of looking like a generic failure.
                    logger.warning(
                        "BCE/year<1 date (year=%s) in %s: pytz cannot resolve a "
                        "historical timezone from coordinates; using UTC (offset 0.0)",
                        uy, path)
                    return 0.0, 0, 0.0
                tz = pytz.timezone(iana)
                naive = _datetime_cls(uy, um, ud, uh, umi)
                aware = pytz.utc.localize(naive).astimezone(tz)
                offset = aware.utcoffset().total_seconds() / 3600.0
        except Exception as exc:  # noqa: BLE001 - resilience over precision
            logger.warning(
                "Timezone-from-coords failed (%s), using UTC: %s", exc, path)
            offset = 0.0
        logger.warning(
            "No [civil] section in %s, derived timezone from coordinates "
            "(offset=%s)", path, offset)
        return offset, 0, 0.0

    @staticmethod
    def _warn_civil_disagreement(civil, total_offset, jd, path):
        """Log a warning when stored civil time disagrees with JD by > 1 min (§9.1)."""
        c_date = civil.get("date")
        c_time = civil.get("time")
        if not c_date or not c_time:
            return
        try:
            cy, cmo, cd = TOMLChartReader._parse_date(c_date, path)
            ch, cmi, cs = TOMLChartReader._parse_time(c_time, path)
        except ValueError:
            return
        stated_jd = _civil_to_jd(cy, cmo, cd, ch, cmi, cs, total_offset)
        if abs(stated_jd - jd) * 86400.0 > 60.0:
            logger.warning(
                "civil time disagrees with [moment].jd by >1min (trusting jd): %s",
                path)

    # -- auto-canonicalize write-back ----------------------------------------

    @staticmethod
    def _canonicalize_write_back(path, julian_day):
        """Insert [moment].jd into an existing file atomically (§4.3 Step 2, §6.13).

        Reads the raw bytes, injects (or replaces) the jd line under [moment]
        (creating the table if needed), and writes via temp-file + os.replace.
        On any failure (read-only fs, permissions) logs a warning and continues
        with the in-memory JD (upstream uses SHOULD, so this is conformant).
        """
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8")
            new_text = _inject_moment_jd(text, julian_day)
            if new_text == text:
                return
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), suffix=".toml.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new_text)
                os.replace(tmp_path, str(path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            logger.info("Canonicalized %s: computed JD from civil time.", path)
        except Exception as exc:  # noqa: BLE001 - graceful degradation
            logger.warning(
                "Could not write-back [moment].jd to %s (%s); "
                "using computed JD in memory.", path, exc)


def _inject_moment_jd(text: str, julian_day: float) -> str:
    """Return ``text`` with ``jd = <repr>`` placed under a [moment] table.

    - If a [moment] table exists, insert/replace its jd line.
    - Otherwise create a [moment] table just before [location] (or at end).
    Preserves the rest of the file verbatim (line endings normalized to \\n).
    """
    jd_line = f"jd = {repr(float(julian_day))}"
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    def _is_table_header(line: str, name: str) -> bool:
        return line.strip() == f"[{name}]"

    moment_idx = next(
        (i for i, ln in enumerate(lines) if _is_table_header(ln, "moment")), None)

    if moment_idx is not None:
        # Find end of the [moment] table block (next table header or EOF).
        end = len(lines)
        for j in range(moment_idx + 1, len(lines)):
            if lines[j].lstrip().startswith("["):
                end = j
                break
        # Replace an existing jd line, else insert right after the header.
        for j in range(moment_idx + 1, end):
            if lines[j].split("=", 1)[0].strip() == "jd":
                lines[j] = jd_line
                return "\n".join(lines)
        lines.insert(moment_idx + 1, jd_line)
        return "\n".join(lines)

    # No [moment] table: build one and insert before [location] if possible.
    block = ["[moment]", jd_line, ""]
    loc_idx = next(
        (i for i, ln in enumerate(lines) if _is_table_header(ln, "location")), None)
    if loc_idx is not None:
        lines[loc_idx:loc_idx] = block
        return "\n".join(lines)
    # Append at end (ensure a separating blank line).
    if lines and lines[-1].strip() != "":
        lines.append("")
    lines.extend(["[moment]", jd_line, ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

class TOMLChartWriter:
    """Write canonical birth_data to an Open Astrology Chart .toml file."""

    def write(self, birth_data: dict, path) -> bool:
        """Write ``birth_data`` to ``path`` as a spec-conformant .toml file.

        UTF-8, no BOM, \\n line endings, atomic (temp + os.replace).
        """
        content = self.encode(birth_data)
        path = Path(path)
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".toml.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
            os.replace(tmp_path, str(path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return True

    def encode(self, birth_data: dict) -> str:
        """Render ``birth_data`` to a spec-conformant TOML string (§5)."""
        extra = birth_data.get("_toml_extra") or {}
        top_extra = dict(extra.get("_top", {}))
        moment_extra = dict(extra.get("moment", {}))
        location_extra = dict(extra.get("location", {}))
        civil_extra = dict(extra.get("civil", {}))

        buf = io.StringIO()
        buf.write(f'spec = "{SPEC_MARKER}"\n')
        buf.write("spec_version = 1\n")

        # --- Top-level metadata (§5.3 omission rules) ---
        name = birth_data.get("name") or ""
        gender = self._gender_for_write(birth_data, top_extra)
        rodden = birth_data.get("rodden")
        # An unrated Rodden is the empty string (the form reports '' exactly like
        # gender), and a whitespace-only value is equally empty. §5.3 omits
        # empty optional metadata: never emit rodden = "" (a spec violation that
        # also round-trips back as a bogus empty rating).
        rodden = rodden.strip() if isinstance(rodden, str) else rodden
        tags = birth_data.get("tags")
        notes = birth_data.get("notes")

        has_meta = bool(name) or gender is not None or bool(rodden) \
            or (tags) or (notes) or self._has_real_extra(top_extra)
        if has_meta:
            buf.write("\n")
        if name:
            buf.write(f"name = {_toml_str(name)}\n")
        if gender is not None:
            buf.write(f"gender = {_toml_str(gender)}\n")
        if rodden:
            buf.write(f"rodden = {_toml_str(str(rodden))}\n")
        if tags:
            # De-duplicate while preserving first-seen order: a chart re-saved
            # after a metadata edit could otherwise accumulate the same tag
            # twice ("astro", "astro"), which §5.3 does not sanction.
            seen = set()
            uniq = []
            for t in tags:
                key = str(t)
                if key not in seen:
                    seen.add(key)
                    uniq.append(key)
            rendered = ", ".join(_toml_str(t) for t in uniq)
            buf.write(f"tags = [{rendered}]\n")
        if notes:
            buf.write(self._render_notes(notes))
        # Unknown top-level extras (skip the private restore marker).
        for key, value in top_extra.items():
            if key == "_original_gender":
                continue
            buf.write(f"{_render_key(key)} = {_render_scalar(value)}\n")

        # --- [moment] (§5.5 full precision) ---
        jd = self._resolve_jd(birth_data)
        buf.write("\n[moment]\n")
        buf.write(f"jd = {repr(float(jd))}\n")
        for key, value in moment_extra.items():
            buf.write(f"{_render_key(key)} = {_render_scalar(value)}\n")

        # --- [location] ---
        # None-safe: a present-but-None coordinate must not crash float().
        lat = birth_data.get("latitude")
        lon = birth_data.get("longitude")
        lat = 0.0 if lat is None else float(lat)
        lon = 0.0 if lon is None else float(lon)
        buf.write("\n[location]\n")
        buf.write(f"lat = {repr(lat)}\n")
        buf.write(f"lon = {repr(lon)}\n")
        for key, value in location_extra.items():
            buf.write(f"{_render_key(key)} = {_render_scalar(value)}\n")
        city = birth_data.get("city") or ""
        country = birth_data.get("country") or ""
        if city:
            buf.write(f"placename = {_toml_str(city)}\n")
        if country:
            buf.write(f"country = {_toml_str(country)}\n")

        # --- [civil] (derived; numeric fields only, never display strings) ---
        base_offset, dst_hours = self._recover_offsets(birth_data)
        ly, lm, ld, lh, lmi, ls = self._local_fields(birth_data)
        # Calendar convention (SPEC-CAL-001): the stored local_* date is always
        # ASTRONOMICAL (Julian pre-1582). Render the human-readable [civil].date
        # under display.calendar_convention so it matches how the app shows the
        # date. DISPLAY-ONLY: jd above stays authoritative and untouched, and the
        # renamed date is NEVER fed back into a civil->JD path. Default
        # ('astronomical') returns the fields unchanged, so post-1582 charts and
        # the default setting are byte-identical; only a 'proleptic_gregorian'
        # user with a pre-1582 chart sees the Gregorian name (which is what the
        # format's own proleptic jd<->civil expects, i.e. more conformant).
        #
        # ONLY shift when an authoritative julian_day is present. Without one,
        # _resolve_jd DERIVED the jd above from these very civil fields (as
        # proleptic Gregorian); shifting the date then would make [civil] and
        # [moment].jd describe instants ~10 days apart for a pre-1582 chart. With
        # an authoritative jd the civil block is advisory, so a proleptic rename
        # is not only safe but agrees with that Julian-based jd.
        from core.time_utils import display_civil_date
        if birth_data.get("julian_day") is not None:
            cy, cm, cd = display_civil_date(ly, lm, ld)
        else:
            cy, cm, cd = ly, lm, ld
        buf.write("\n[civil]\n")
        buf.write(f'date = "{_format_iso_date(cy, cm, cd)}"\n')
        buf.write(f'time = "{lh:02d}:{lmi:02d}:{ls:02d}"\n')
        buf.write(f"utc_offset = {repr(float(base_offset))}\n")
        # dst_offset: emit whenever non-zero (positive OR negative; a negative
        # historical DST such as Irish Standard Time dst=-0.5 must round-trip,
        # else the total offset is silently corrupted). The originally-explicit
        # 0.0 case (§6.14) is still re-emitted via the civil_extra branch below.
        if dst_hours is not None and dst_hours != 0.0:
            buf.write(f"dst_offset = {repr(float(dst_hours))}\n")
        elif "dst_offset" in civil_extra:
            buf.write(f"dst_offset = {_render_scalar(civil_extra['dst_offset'])}\n")
        for key, value in civil_extra.items():
            if key == "dst_offset":
                continue
            buf.write(f"{_render_key(key)} = {_render_scalar(value)}\n")

        return buf.getvalue()

    # -- writer helpers ------------------------------------------------------

    @staticmethod
    def _has_real_extra(top_extra: dict) -> bool:
        return any(k != "_original_gender" for k in top_extra)

    @staticmethod
    def _gender_for_write(birth_data: dict, top_extra: dict) -> Optional[str]:
        """Decide the gender value to emit (§5.3 omission, §4.3 round-trip note).

        - If the original authored string was tracked, re-emit it verbatim
          (byte-identity).
        - Else omit "Unknown"/empty, write everything else as-is (free strings).
        """
        original = top_extra.get("_original_gender")
        if original is not None:
            return original
        gender = birth_data.get("gender")
        if gender is None:
            return None
        if str(gender).strip().lower() in ("unknown", ""):
            return None
        return str(gender)

    @staticmethod
    def _render_notes(notes: str) -> str:
        """Render the notes field (§5.4).

        Multi-line basic string ('''...''') only when the content has newlines,
        contains no '\"\"\"' sequence, does not end with '\"' (which would close
        the delimiter), has no backslash (a multi-line basic string still
        processes '\\' as an escape, so e.g. a Windows path like C:\\Users would
        produce a file tomllib rejects), and has no control characters other than
        \\t / \\n (a multi-line basic string still forbids raw control chars).
        Otherwise use an escaped single-line basic string (which correctly
        escapes both '\\' and newlines).
        """
        if (
            "\n" in notes
            and '"""' not in notes
            and "\\" not in notes
            and not notes.endswith('"')
            and not any(ord(c) < 0x20 and c not in ("\t", "\n") for c in notes)
        ):
            # The newline immediately after the opening delimiter is trimmed by
            # TOML, so the content round-trips exactly as written. Do NOT force a
            # trailing newline before the closing delimiter: a note without one
            # (\"line1\\nline2\") would otherwise gain a \\n on every save and
            # drift. A note that already ends in \\n keeps it because the closing
            # \"\"\" then sits on its own line.
            out = 'notes = """\n'
            out += notes
            out += '"""\n'
            return out
        return f"notes = {_toml_str(notes)}\n"

    @staticmethod
    def _resolve_jd(birth_data: dict) -> float:
        """JD source priority (§5.3): stored julian_day -> compute from civil."""
        jd = birth_data.get("julian_day")
        if jd is not None:
            return float(jd)
        ly, lm, ld, lh, lmi, ls = TOMLChartWriter._local_fields(birth_data)
        base_offset, dst_hours = TOMLChartWriter._recover_offsets(birth_data)
        total = base_offset + (dst_hours or 0.0)
        return _civil_to_jd(ly, lm, ld, lh, lmi, ls, total)

    @staticmethod
    def _recover_offsets(birth_data: dict) -> tuple[float, float]:
        """Recover (BASE offset, dst hours) for the [civil] block (§5.3, None-safe).

        Two input shapes are supported (the writer's spec input is the canonical
        BDM dict, but round-trip and update_toml_birth_data feed the §4.2 raw
        reader dict):
          - CANONICAL dict (has local_*): utc_offset_hours is the TOTAL offset, so
            BASE = TOTAL - dst.
          - RAW reader dict (has year/hour, no local_*): utc_offset_hours is
            ALREADY the BASE offset, so do not subtract.
        dst is the float dst_offset_hours when present, else the integer
        time_change_flag (None-safe per §5.3 / round 4 B1).
        """
        # Defensive dual-key read (§6.2.1). dict.get with a default returns None
        # when the key is PRESENT with value None, so check explicitly and fall
        # through to the legacy `utcoffset` key before defaulting to 0.0.
        offset = birth_data.get("utc_offset_hours")
        if offset is None:
            offset = birth_data.get("utcoffset")
        if offset is None:
            offset = 0.0
        offset = float(offset)
        dst = birth_data.get("dst_offset_hours")
        if dst is None:
            # Fall back to the integer time_change_flag as a DST *duration* (1h/2h).
            # A NEGATIVE flag is the CHTK/Kala "auto" SENTINEL ("re-resolve from the
            # zone"), NOT an hours quantity — the .toml format has no auto field
            # (§4.3), so it must never become a negative dst_offset. Treat it as
            # unresolved (0). A genuine fractional negative DST (e.g. Irish Standard
            # Time -0.5h) arrives as an explicit float dst_offset_hours, not via the
            # flag, so this cannot swallow a real value.
            flag = birth_data.get("time_change_flag", 0) or 0
            dst = float(flag) if flag > 0 else 0.0
        dst = float(dst)
        is_canonical = "local_year" in birth_data
        base = offset - dst if is_canonical else offset
        return base, dst

    @staticmethod
    def _local_fields(birth_data: dict) -> tuple[int, int, int, int, int, int]:
        """Read LOCAL civil fields, supporting both canonical and raw key names.

        Canonical dict uses local_*; the reader's raw dict uses year/hour/etc.
        """
        def pick(canon, raw, default):
            if canon in birth_data:
                return int(birth_data[canon])
            if raw in birth_data:
                return int(birth_data[raw])
            return default
        return (
            pick("local_year", "year", 1970),
            pick("local_month", "month", 1),
            pick("local_day", "day", 1),
            pick("local_hour", "hour", 12),
            pick("local_minute", "minute", 0),
            pick("local_second", "second", 0),
        )

    # -- partial update (§6.7) ----------------------------------------------

    def update_toml_birth_data(self, path, birth_data: dict) -> bool:
        """Merge ``birth_data`` into an existing .toml, preserving extras (§6.7).

        Reads the existing file for its _toml_extra (unknown keys + round-trip
        markers), merges those under the incoming birth_data (incoming canonical
        fields win), and writes back atomically. If the file does not exist or
        cannot be read, falls back to a plain write.
        """
        path = Path(path)
        merged = dict(birth_data)
        try:
            existing = TOMLChartReader().read_toml_file(path, canonicalize=False)
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            existing = None

        if existing is not None:
            existing_extra = existing.get("_toml_extra") or {}
            incoming_extra = birth_data.get("_toml_extra") or {}
            merged["_toml_extra"] = _merge_extra(existing_extra, incoming_extra)
            # Preserve a stored JD only when civil time did not change. If the
            # incoming data carries no JD but keeps the same civil time, reuse
            # the existing JD; if civil changed, recompute from the new civil.
            if merged.get("julian_day") is None:
                if self._same_civil(existing, birth_data):
                    merged["julian_day"] = existing.get("julian_day")

        return self.write(merged, path)

    @staticmethod
    def _same_civil(existing: dict, incoming: dict) -> bool:
        """True when the incoming civil instant matches the existing one.

        The instant is the local wall-clock time AND its offset: the same
        wall-clock at a different UTC offset is a different JD. Comparing only
        the local fields would preserve a stale JD when the user corrects the
        timezone (§6.7: recompute JD when civil time changed).
        """
        if TOMLChartWriter._local_fields(existing) != \
                TOMLChartWriter._local_fields(incoming):
            return False
        ex_base, ex_dst = TOMLChartWriter._recover_offsets(existing)
        inc_base, inc_dst = TOMLChartWriter._recover_offsets(incoming)
        return (ex_base, ex_dst) == (inc_base, inc_dst)


def _merge_extra(existing: dict, incoming: dict) -> dict:
    """Deep-merge two _toml_extra dicts (nested one level by table)."""
    out = {table: dict(keys) for table, keys in existing.items()}
    for table, keys in incoming.items():
        out.setdefault(table, {})
        out[table].update(keys)
    return out


# ---------------------------------------------------------------------------
# TOML string / scalar rendering (§5.4)
# ---------------------------------------------------------------------------

_ESCAPES = {
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0C: "\\f",
    0x0D: "\\r",
    0x22: '\\"',
    0x5C: "\\\\",
}


def _toml_str(s: str) -> str:
    """Encode a Python string as a TOML basic (quoted) string (§5.4 / Dart _tomlStr)."""
    out = ['"']
    for ch in str(s):
        code = ord(ch)
        if code in _ESCAPES:
            out.append(_ESCAPES[code])
        elif code < 0x20 or code == 0x7F:
            # BUG-12 (SPEC-IMPORT-002): DEL (U+007F) is a control char strict TOML
            # parsers reject in basic strings; escape it like the C0 controls.
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


_BARE_KEY_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


def _render_key(key: str) -> str:
    """Render a TOML key: bare when safe, otherwise a quoted basic string."""
    key = str(key)
    if key and all(c in _BARE_KEY_CHARS for c in key):
        return key
    return _toml_str(key)


def _render_scalar(value: Any) -> str:
    """Render a preserved _toml_extra value back to TOML.

    Used for unknown keys round-tripped from the source file. Strings are quoted
    and escaped; bools/ints/floats are emitted natively (float via repr for
    precision); lists are rendered element-wise; dicts (TOML tables / inline
    tables from the source) become inline tables, which tomllib re-reads to the
    same mapping (data preserved even though the byte form may differ from a
    standalone [table] in the source).
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_render_scalar(v) for v in value) + "]"
    if isinstance(value, dict):
        items = ", ".join(
            f"{_render_key(k)} = {_render_scalar(v)}" for k, v in value.items())
        return "{" + items + "}"
    return _toml_str(str(value))
