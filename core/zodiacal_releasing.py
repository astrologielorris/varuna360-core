# -*- coding: utf-8 -*-
# Portions Copyright (c) Max Lange (Aries, https://github.com/primum-mobile/aries),
# used under the GNU AGPL-3.0-or-later.
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Zodiacal Releasing engine (Vettius Valens, Anthology IV) — pure, no Qt.

Ported from Aries `zodiacalreleasing.py` (Max Lange, AGPL-3.0-or-later, built
on Morinus; https://github.com/primum-mobile/aries); credited in NOTICE. Not imported from aries — reimplemented on JD floats and made
position-bound per SPEC-ZR-001.

INVARIANT (INV-1, the whole point): `build()` and `drill()` take sign POSITIONS
(0..11), never longitudes. A longitude reaches a position only through
`resolve_releaser`, which calls the mode-aware `get_sign_index_*` helpers. A
position is a division number under SPEC-ZOD-001, so the same chart releases
differently in Aditya Circle than in Tropical Classic — that is a feature.

Everything is in Julian Day floats. Level base durations (days):
  L1 = 360 * weight    L2 = 30 * weight    L3 = 2.5 * weight    L4 = (5/24) * weight
Intervals are half-open: a JD equal to `end_jd` belongs to the next row.

Reference: SPEC-ZR-001 §3.1 (walk, peaks), §3.3 (resolver), §3.4 (anchor),
§3.5 (display entry schema).
"""
import math

from core.aditya_mode import (
    get_sign_index_aditya,
    get_sign_index_sidereal,
    get_sign_index_tropical,
)
from core.lots import is_day_chart, lot_of_fortune, lot_of_spirit

__all__ = [
    "WEIGHTS", "RULERS", "VALID_RIGHT_MODES", "DEFAULT_ANCHOR",
    "build", "drill", "find_current", "resolve_releaser", "anchor_jd",
    "format_level", "zr_tooltip", "RULER_ABBREV",
]

# By POSITION 0..11 (division number - 1). WEIGHTS are the classical Valens
# "greater years"-independent minor-year weights; RULERS the domicile lords.
WEIGHTS = (15, 8, 20, 25, 19, 20, 8, 15, 12, 27, 30, 12)
RULERS = ("Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury",
          "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter")

_L1_DAYS = 360.0
_L2_DAYS = 30.0
_L3_DAYS = 2.5
_L4_DAYS = 5.0 / 24.0

# Half-open comparison tolerance in JD (~0.09 ms) to keep float round-off from
# spawning a spurious zero-width final row.
_EPS = 1e-9

# D-2 (OPEN): the settings default anchor. "birth" agrees with Vimshottari's
# age 0 in the same panel; "midnight" matches aries/Morinus published tables.
# TODO(D-2): confirm with Lorris before wiring the settings default.
DEFAULT_ANCHOR = "birth"

VALID_RIGHT_MODES = ("vimshottari", "nisarga", "zr")
_VALID_ZODIAC_MODES = ("aditya", "tropical_classic", "sidereal")


# ─────────────────────────────── durations & flags ───────────────────────────────

def _dur(level, pos):
    w = WEIGHTS[pos]
    if level == 1:
        return w * _L1_DAYS
    if level == 2:
        return w * _L2_DAYS
    if level == 3:
        return w * _L3_DAYS
    return w * _L4_DAYS


def _peak_kind(pos, fortune_pos):
    """Peak rank keyed to natal Fortune (SPEC-ZR-001 §3.1.2, D-4).

    Offset (pos - fortune_pos) % 12: 0 or 9 -> 'major' (9 is also the
    culmination / 10th-from-Fortune), 6 -> 'moderate', 3 -> 'minor', else None.
    """
    off = (pos - fortune_pos) % 12
    if off in (0, 9):
        return "major"
    if off == 6:
        return "moderate"
    if off == 3:
        return "minor"
    return None


def _period(level, pos, start_jd, end_jd, fortune_pos, parent_pos,
            is_lob, is_completion):
    off = (pos - fortune_pos) % 12
    kind = _peak_kind(pos, fortune_pos)
    return {
        "level": level,
        "pos": pos,
        "start_jd": start_jd,
        "end_jd": end_jd,
        "ruler": RULERS[pos],
        "parent_pos": parent_pos,
        "is_lob": bool(is_lob),
        "is_completion": bool(is_completion),
        "peak_kind": kind,
        "is_culmination": off == 9,
    }


# ─────────────────────────────── the walk (§3.1.1) ───────────────────────────────

def _walk(parent_start, parent_end, parent_pos, level, fortune_pos):
    """Emit one sublevel inside [parent_start, parent_end).

    Begin at the parent's position and advance in zodiacal order. The ONE time
    the next position would re-enter the parent's start position, jump instead
    to its opposite (parent_pos + 6) % 12 (that landing row carries is_lob=True)
    and continue in order. The post-jump return to the parent's own position is
    is_completion=True and runs its full duration unless the parent ends first.
    Rows are truncated at parent_end. One jump per chain.
    """
    rows = []
    t = parent_start
    pos = parent_pos
    lob_done = False
    next_is_lob = False  # the row about to be emitted IS the LoB landing
    while t < parent_end - _EPS:
        e = t + _dur(level, pos)
        if e > parent_end:
            e = parent_end
        is_completion = lob_done and pos == parent_pos
        rows.append(_period(level, pos, t, e, fortune_pos, parent_pos,
                            next_is_lob, is_completion))
        next_is_lob = False
        t = e
        nxt = (pos + 1) % 12
        if (not lob_done) and nxt == parent_pos:
            pos = (parent_pos + 6) % 12
            lob_done = True
            next_is_lob = True
        else:
            pos = nxt
        if t >= parent_end - _EPS:
            break
    return rows


def build(releaser_pos, fortune_pos, start_jd, horizon_years=150):
    """L1 + L2, interleaved (each L1 row followed by its L2 children).

    Positions only (INV-1). L1 has no parent and no LoB.
    """
    if not (0 <= releaser_pos <= 11):
        raise ValueError(f"releaser_pos out of range: {releaser_pos!r}")
    if not (0 <= fortune_pos <= 11):
        raise ValueError(f"fortune_pos out of range: {fortune_pos!r}")
    out = []
    t = float(start_jd)
    pos = releaser_pos
    acc_years = 0.0
    while acc_years < horizon_years:
        e = t + _dur(1, pos)
        out.append(_period(1, pos, t, e, fortune_pos, None, False, False))
        out.extend(_walk(t, e, pos, 2, fortune_pos))
        t = e
        acc_years += WEIGHTS[pos]
        pos = (pos + 1) % 12
    return out


def drill(period, fortune_pos):
    """L3 + L4 of one L2 period, interleaved (each L3 row followed by its L4).

    `period` is an L2 row dict from `build()`.
    """
    s = period["start_jd"]
    e = period["end_jd"]
    pos = period["pos"]
    out = []
    for l3 in _walk(s, e, pos, 3, fortune_pos):
        out.append(l3)
        out.extend(_walk(l3["start_jd"], l3["end_jd"], l3["pos"], 4, fortune_pos))
    return out


def find_current(rows, jd, level=None):
    """Index of the row whose half-open [start_jd, end_jd) contains jd.

    Optionally restricted to `level`. Returns -1 if none (jd None or no match).
    A jd exactly on a boundary belongs to the next row (half-open).
    """
    if jd is None or not rows:
        return -1
    for i, r in enumerate(rows):
        if level is not None and r["level"] != level:
            continue
        if r["start_jd"] <= jd < r["end_jd"]:
            return i
    return -1


# ─────────────────────────────── releaser resolution (§3.3) ───────────────────────────────

def resolve_releaser(inp):
    """Map lot longitudes to sign positions in the active mode.

    inp keys (SPEC-ZR-001 §3.3):
      asc_lon, sun_lon, moon_lon : float, tropical ecliptic degrees (required)
      mode      : "aditya" | "tropical_classic" | "sidereal" (required)
      ayanamsa_offset : float degrees, REQUIRED when mode == "sidereal"
      releaser  : "spirit" | "fortune" | "sign:<0..11>" | "lot:<name>" (required;
                  names in core.lots.LOT_REGISTRY, SPEC-ZR-001 v1.1)
      spirit_shift : bool, default True
      planet_lons : dict body -> tropical lon (mercury venus mars jupiter
                  saturn), REQUIRED for "lot:" releasers that use them
      gender    : "Male" | "Female" | None, for the gendered lots

    Returns {releaser_pos, fortune_pos, releaser_lon|None, label_token} with
    label_token in {"spirit", "spirit_shifted", "fortune", "sign", "lot"};
    for "lot" the dict also carries lot_name and lot_label.

    Missing required input raises ValueError — never a silent default to
    position 0.
    """
    for key in ("asc_lon", "sun_lon", "moon_lon", "mode", "releaser"):
        if inp.get(key) is None:  # `is None`, so 0.0 longitude stays valid
            raise ValueError(f"resolve_releaser: missing required input {key!r}")

    mode = inp["mode"]
    if mode not in _VALID_ZODIAC_MODES:
        raise ValueError(f"resolve_releaser: invalid mode {mode!r}")
    ayan = inp.get("ayanamsa_offset")
    if mode == "sidereal" and ayan is None:
        raise ValueError("resolve_releaser: sidereal mode requires ayanamsa_offset")

    asc = float(inp["asc_lon"])
    sun = float(inp["sun_lon"])
    moon = float(inp["moon_lon"])

    def _pos(lon):
        if mode == "tropical_classic":
            return get_sign_index_tropical(lon)
        if mode == "aditya":
            return get_sign_index_aditya(lon)
        return get_sign_index_sidereal(lon, ayan)

    day = is_day_chart(sun, asc)
    fortune_lon = lot_of_fortune(asc, sun, moon, day)
    fortune_pos = _pos(fortune_lon)

    releaser = inp["releaser"]
    spirit_shift = inp.get("spirit_shift", True)

    if releaser == "spirit":
        spirit_lon = lot_of_spirit(asc, sun, moon, day)
        releaser_pos = _pos(spirit_lon)
        label = "spirit"
        if spirit_shift and releaser_pos == fortune_pos:
            releaser_pos = (releaser_pos + 1) % 12
            label = "spirit_shifted"
        return {"releaser_pos": releaser_pos, "fortune_pos": fortune_pos,
                "releaser_lon": spirit_lon, "label_token": label}

    if releaser == "fortune":
        return {"releaser_pos": fortune_pos, "fortune_pos": fortune_pos,
                "releaser_lon": fortune_lon, "label_token": "fortune"}

    if isinstance(releaser, str) and releaser.startswith("sign:"):
        try:
            n = int(releaser.split(":", 1)[1])
        except (ValueError, IndexError):
            raise ValueError(f"resolve_releaser: bad sign releaser {releaser!r}")
        if not (0 <= n <= 11):
            raise ValueError(f"resolve_releaser: sign out of range {n!r}")
        # Manual sign is verbatim in the active mode's numbering; no shift.
        return {"releaser_pos": n, "fortune_pos": fortune_pos,
                "releaser_lon": None, "label_token": "sign"}

    if isinstance(releaser, str) and releaser.startswith("lot:"):
        from core.lots import LOT_REGISTRY, lot_longitude
        name = releaser.split(":", 1)[1]
        if name not in LOT_REGISTRY:
            raise ValueError(f"resolve_releaser: unknown lot {name!r}")
        lons = {"asc": asc, "sun": sun, "moon": moon}
        lons.update({k.lower(): float(v)
                     for k, v in (inp.get("planet_lons") or {}).items()})
        try:
            lot_lon = lot_longitude(name, lons, day, inp.get("gender"))
        except KeyError as e:
            raise ValueError(f"resolve_releaser: lot {name!r} needs {e.args[0]}")
        # A lot releaser is used verbatim (no Spirit-style shift), as in aries.
        return {"releaser_pos": _pos(lot_lon), "fortune_pos": fortune_pos,
                "releaser_lon": lot_lon, "label_token": "lot",
                "lot_name": name, "lot_label": LOT_REGISTRY[name]["label"]}

    raise ValueError(f"resolve_releaser: unknown releaser {releaser!r}")


# ─────────────────────────────── start anchor (§3.4) ───────────────────────────────

def anchor_jd(birth_jd_utc, tz_offset_hours, anchor=DEFAULT_ANCHOR):
    """Start JD for the releasing.

    "birth"    -> the UTC birth instant (age 0 shared with Vimshottari).
    "midnight" -> local civil midnight (00:00) of the birth date
                  (aries/Morinus convention). Computed in JD: JD fraction .5 is
                  local midnight, so the day's start is floor(local - 0.5) + 0.5,
                  converted back to UTC.
    """
    if anchor == "birth":
        return float(birth_jd_utc)
    if anchor == "midnight":
        local = float(birth_jd_utc) + float(tz_offset_hours) / 24.0
        local_midnight = math.floor(local - 0.5) + 0.5
        return local_midnight - float(tz_offset_hours) / 24.0
    raise ValueError(f"anchor_jd: unknown anchor {anchor!r}")


# ─────────────────────────────── display formatting (§3.5) ───────────────────────────────

# Row-format constants — DESIGN DECISION 1 / 5 (companion doc). Glyphs are
# restricted to the bundled Inter cmap; ⤳ ▾ ▸ ◂ ▴ ▵ are ABSENT and must never
# appear. RULER_ABBREV mirrors DashaManager.PLANET_TO_ABBREV / nisarga
# PLANET_ABBREV (Su Mo Ma Me Ju Ve Sa).
RULER_ABBREV = {
    "Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me",
    "Jupiter": "Ju", "Venus": "Ve", "Saturn": "Sa",
}
_MARK_CURRENT = "▶"           # ▶
_PEAK_MARK = {"major": "▲", "moderate": "△", "minor": "·"}  # ▲ △ ·
_MARK_LOB = "↪"               # ↪
_MARK_COMPLETION = "↺"        # ↺
_UNIT_LETTER = {1: "y", 2: "m", 3: "d", 4: "h"}
_UNIT_WORD = {1: "ZR years", 2: "ZR months", 3: "days", 4: "hours"}
_ZODIAC_DISPLAY = {"aditya": "Aditya Circle",
                   "tropical_classic": "Tropical Classic",
                   "sidereal": "Sidereal"}
_OFFSET_PHRASE = {0: "sign of Fortune", 9: "10th from Fortune",
                  6: "7th from Fortune", 3: "4th from Fortune"}


def _date_display(jd, date_format=None, convention=None):
    """JD -> the user's numeric date string (td-okit decision 7).

    Field order comes from display.date_format (default MM/DD/YYYY) unless an
    explicit date_format is passed (CLI path); the calendar convention is
    honoured through display_revjul inside format_display_date (None reads
    display.calendar_convention, an explicit `convention` never touches settings
    — the CLI path, td-okit c0-5).
    """
    from core.time_utils import format_display_date
    return format_display_date(jd, date_format, convention)


def _datetime_local(jd, with_time, date_format=None, convention=None):
    """JD -> the user's numeric date, optionally with ' HH:MM' (jd already local).

    Date field order follows display.date_format (or an explicit date_format for
    CLIs); the calendar convention is honoured via the display helper (None reads
    the setting, an explicit `convention` is CLI-safe — td-okit c0-5).
    """
    from core.time_utils import format_display_date
    if not with_time:
        return format_display_date(jd, date_format, convention)
    # Snap to the nearest minute BEFORE the date conversion so a boundary like
    # 23:59:40 rolls to next-day 00:00, never renders as an invalid "24:00"
    # (W6 review MINOR 9). The display helper then handles the day rollover.
    from core.time_utils import display_revjul
    jd = round(jd * 1440.0) / 1440.0
    _y, _m, _d, h = display_revjul(jd, convention)
    total_min = int(round(h * 60.0)) % 1440
    hh, mm = divmod(total_min, 60)
    return "%s %02d:%02d" % (format_display_date(jd, date_format, convention), hh, mm)


def _value_in_unit(level, start_jd, end_jd):
    days = end_jd - start_jd
    if level == 1:
        return days / 360.0
    if level == 2:
        return days / 30.0
    if level == 3:
        return days
    return days * 24.0


def _age_ym(birth_jd_local, start_jd_local):
    """'Ny Mm' native age at a period start, calendar-month arithmetic identical
    to DashaManager._age_str (Vedanga/Vimshottari rows) for equivalent inputs.
    (_age_str additionally supports a 120-year cycle offset via years_offset; ZR
    has no such cycle, so _age_ym omits it — the month formulas match exactly at
    years_offset == 0.)

    td-okit c0-7 (sol delta P2): an AGE is a DURATION between two fixed instants,
    so it must NOT change when the display calendar toggles. Both endpoints are
    rendered in the FIXED astronomical calendar (NOT the threaded display
    convention — that governs the row's displayed date/time text, not this month
    count). This is what makes the two age implementations truly equivalent; c0-5
    threaded the display convention here, which made the age setting-dependent and
    disagree with _age_str for a pre-1582 chart under proleptic_gregorian. The
    pre-1582 boundary case is logged as a Kala cross-check on td-fwj1. ZR periods
    start at birth or later, so the pre-birth branch is effectively unreachable
    here; it is corrected only to keep parity with _age_str."""
    from core.time_utils import display_revjul
    by, bm, bd, _ = display_revjul(birth_jd_local, "astronomical")
    y, m, d, _ = display_revjul(start_jd_local, "astronomical")
    by, bm, bd = int(by), int(bm), int(bd)
    y, m, d = int(y), int(m), int(d)
    if (y, m, d) >= (by, bm, bd):
        total = (y - by) * 12 + (m - bm)
        if d < bd:
            total -= 1
        return "%dy %dm" % (total // 12, total % 12)
    total = (by - y) * 12 + (bm - m)
    if bd < d:
        total -= 1
    if total == 0:
        return "0y 0m"          # zero completed months carries no sign
    month_part = "-%dm" % (total % 12) if total % 12 else "0m"
    return "-%dy %s" % (total // 12, month_part)


def _length_token(level, start_jd, end_jd):
    """DESIGN DECISION 1: value + unit letter; %.0f at >= 10, else %.1f with
    a trailing .0 stripped (30y, 8m, 68d, 9.5d, 150h, 7.5h)."""
    value = _value_in_unit(level, start_jd, end_jd)
    if value >= 10:
        s = "%.0f" % value
    else:
        s = ("%.1f" % value).rstrip("0").rstrip(".")
    return s + _UNIT_LETTER[level]


def format_level(rows, level, chain=None, now_jd=None, mode="aditya",
                 use_western=False, show_age=False, birth_jd=None,
                 tz_offset_hours=0.0, date_format=None, convention=None):
    """Format ONE level's rows to the §3.5 display-entry schema + DESIGN
    DECISION 1 (rev 2026-08-25) row text
    `{cur}{mark} {sign:<pad} {ru} {dd/mm/yyyy HH:MM}  {age}` where `age` is the
    native age at the period START as `Ny Mm` (calendar months, like the
    Vedanga/Vimshottari rows). The period LENGTH is not on the row (tooltip
    only): Lorris 2026-08-25, "the third column is the age when it starts,
    not how long it lasts".

    Only one level is listed at a time (the breadcrumb strip shows the parents),
    so the text carries NO indentation; `indent` stays the int `level - 1` for
    the remote consumer. `jd`/`start_jd`/`end_jd` are ABSOLUTE (UTC) so
    "Open in Transit" hits the right instant; `date` is the LOCAL civil start
    date (`start_jd + tz/24`) in display.date_format order (default MM/DD/YYYY,
    or an explicit date_format for CLIs); the remote layer derives ISO from `jd`,
    never from this text. The row text carries the local clock time too so
    transits can be timed.
    """
    from core.aditya_mode import displayed_sign_name

    tz_days = float(tz_offset_hours) / 24.0
    pad = 11 if use_western else 8
    level_rows = [r for r in rows if r["level"] == level]
    cur = find_current(level_rows, now_jd, level) if now_jd is not None else -1

    entries = []
    for i, r in enumerate(level_rows):
        pos = r["pos"]
        sign_label = displayed_sign_name(pos, mode, use_western)
        lord = r["ruler"]
        ru = RULER_ABBREV.get(lord, lord[:2])
        date = _date_display(r["start_jd"] + tz_days, date_format, convention)
        date_time = _datetime_local(r["start_jd"] + tz_days, True, date_format,
                                    convention)
        length = _length_token(level, r["start_jd"], r["end_jd"])

        cur_ch = _MARK_CURRENT if i == cur else " "
        if r["is_lob"]:
            mark = _MARK_LOB
        elif r["is_completion"]:
            mark = _MARK_COMPLETION
        elif r["peak_kind"]:
            mark = _PEAK_MARK[r["peak_kind"]]
        else:
            mark = " "

        age_years = None
        if birth_jd is not None:
            age_years = (r["start_jd"] - float(birth_jd)) / 365.2425
        # Age column is always shown (show_age kept for signature compat).
        # Age is a duration -> astronomical, independent of `convention` (which
        # governs the displayed date/time text above). See _age_ym (c0-7).
        age_tok = _age_ym(float(birth_jd) + tz_days, r["start_jd"] + tz_days) \
            if birth_jd is not None else ""

        text = "%s%s %-*s %s %s  %s" % (
            cur_ch, mark, pad, sign_label, ru, date_time, age_tok,
        )
        entries.append({
            "text": text,
            "date": date,
            "jd": r["start_jd"],
            "start_jd": r["start_jd"],
            "end_jd": r["end_jd"],
            "lord": lord,
            "indent": level - 1,
            "level": level,
            "is_current": i == cur,
            # ZR-only
            "pos": pos,
            "parent_pos": r["parent_pos"],
            "sign_label": sign_label,
            "is_peak": r["peak_kind"] is not None,
            "peak_kind": r["peak_kind"],
            "is_lob": r["is_lob"],
            "is_completion": r["is_completion"],
            "age_years": age_years,
        })
    return entries


def zr_tooltip(entry, meta):
    """DESIGN DECISION 5 tooltip for one ZR row (plain text, one fact per line;
    optional lines only when they apply). `meta` carries the releaser context:
        mode, use_western, tz_offset_hours, birth_jd,
        releaser_token, releaser_pos, releaser_sign_label,
        fortune_pos, fortune_sign_label
    """
    from core.aditya_mode import displayed_sign_name

    tz_days = float(meta.get("tz_offset_hours", 0.0)) / 24.0
    mode = meta.get("mode", "aditya")
    use_western = meta.get("use_western", False)
    level = entry["level"]
    with_time = level in (3, 4)

    lines = []
    lines.append("%s · %s · level %d" % (entry["sign_label"], entry["lord"], level))
    start = _datetime_local(entry["start_jd"] + tz_days, with_time)
    end = _datetime_local(entry["end_jd"] + tz_days, with_time)
    lines.append("%s → %s" % (start, end))

    value = _value_in_unit(level, entry["start_jd"], entry["end_jd"])
    unit_word = _UNIT_WORD[level]
    if level in (1, 2):
        days = entry["end_jd"] - entry["start_jd"]
        lines.append("Length: %s %s (%d days)"
                     % (("%.0f" % value if value >= 10 else ("%.1f" % value).rstrip("0").rstrip(".")),
                        unit_word, int(round(days))))
    else:
        lines.append("Length: %s %s"
                     % (("%.0f" % value if value >= 10 else ("%.1f" % value).rstrip("0").rstrip(".")),
                        unit_word))

    birth_jd = meta.get("birth_jd")
    if birth_jd is not None:
        a1 = (entry["start_jd"] - float(birth_jd)) / 365.2425
        a2 = (entry["end_jd"] - float(birth_jd)) / 365.2425
        lines.append("Age %.1f → %.1f" % (a1, a2))

    if entry["peak_kind"]:
        offset = (entry["pos"] - meta["fortune_pos"]) % 12
        lines.append("Peak: %s (%s)" % (entry["peak_kind"],
                                        _OFFSET_PHRASE.get(offset, "from Fortune")))
    if entry["is_lob"]:
        lines.append("Loosing of the bond: the walk jumped to the opposite sign")
    if entry["is_completion"] and entry.get("parent_pos") is not None:
        parent_sign = displayed_sign_name(entry["parent_pos"], mode, use_western)
        lines.append("Completion: the walk returned to %s" % parent_sign)

    tok = meta.get("releaser_token", "spirit")
    who = ("Spirit" if tok in ("spirit", "spirit_shifted")
           else "Fortune" if tok == "fortune"
           else ("Lot of %s" % meta["lot_label"]) if tok == "lot" and meta.get("lot_label")
           else "manual sign")
    rel_line = "Releaser: %s in %s (division %d)" % (
        who, meta.get("releaser_sign_label", ""), int(meta.get("releaser_pos", 0)) + 1)
    if tok == "spirit_shifted":
        rel_line += ", shifted out of Fortune's sign"
    lines.append(rel_line)
    lines.append("Peaks measured from natal Fortune in %s"
                 % meta.get("fortune_sign_label", ""))
    lines.append("Zodiac: %s" % _ZODIAC_DISPLAY.get(mode, mode))
    return "\n".join(lines)
