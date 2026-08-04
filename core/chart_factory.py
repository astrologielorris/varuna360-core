# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Chart-Everywhere migration helper (Issue 2).

Builds mode-appropriate libaditya Chart objects directly from EphContext,
without going through the deprecated dict pipeline. Also produces
`source_params` dicts that ChartState stores for Issue 2b (mode-switch rebuild)
and Issue 10 (session restore).
"""

from libaditya.objects.context import EphContext, Circle
from libaditya.objects.julian_day import JulianDay
from libaditya.objects.location import Location
from libaditya.charts.chart import Chart
from libaditya import constants as const
from libaditya import swe
from core.house_systems import HOUSE_SYSTEM_CODES, get_house_system_code


def mode_to_circle_sysflg(mode):
    """Map ChartState aditya_mode → (Circle, sysflg, sign_names) tuple.

    Mode is baked at construction so downstream consumers do not branch.
    Public (td-tagx.7): core.chart_helpers.ascendant_probe reuses this so the
    fast Cusps probe shares the exact Circle/sysflg basis the factory bakes,
    keeping the single source of truth for the mode→Circle mapping.
    """
    if mode == "aditya":
        return Circle.ADITYA, const.TROP, "adityas"
    if mode == "tropical_classic":
        return Circle.ZODIAC, const.TROP, "zodiac"
    if mode == "sidereal":
        return Circle.ZODIAC, const.SID, "zodiac"
    raise ValueError(f"Unknown aditya_mode: {mode!r}")


def build_chart_from_params(*, jd, lat, lon, mode, name="", utcoffset=0.0,
                            ayanamsa, hsys="C"):
    """Build a Chart with mode-baked Circle/sysflg.

    Args:
        jd: Julian Day (float)
        lat: latitude (positive = north)
        lon: longitude (positive = east)
        mode: "aditya" | "tropical_classic" | "sidereal"
        name: chart name (optional, stored on context)
        utcoffset: UTC offset in hours
        ayanamsa: ayanamsa id (required, no default)
        hsys: house system code (default "C" — Campanian; matches existing)

    Returns:
        Chart with context.circle/sysflg matching `mode`.
    """
    circle, sysflg, sign_names = mode_to_circle_sysflg(mode)
    timeJD = JulianDay(jd, utcoffset=utcoffset)
    location = Location(lat=lat, long=lon, alt=0, placename=name, utcoffset=utcoffset)
    ctx = EphContext(
        name=name,
        timeJD=timeJD,
        location=location,
        sysflg=sysflg,
        amsha=1,
        ayanamsa=ayanamsa,
        hsys=hsys,
        circle=circle,
        signize=True,
        toround=(True, 3),
        names_type="mixed",
        sign_names=sign_names,
    )
    return Chart(ctx)


def build_chart_from_planets_data(planets_data, mode, name="", ayanamsa=98):
    """Build a mode-aware Chart from a planets_data dict's stored jd/lat/lon.

    Transitional helper — replaces build_chart_from_dict() during migration.
    The dict only supplies jd/lat/lon; the mode controls Circle/sysflg.
    Removed alongside the dict pipeline in Issue 11.
    """
    import warnings
    warnings.warn(
        "build_chart_from_planets_data is deprecated — use build_chart_from_params directly",
        DeprecationWarning, stacklevel=2,
    )
    return build_chart_from_params(
        jd=planets_data["julian_day"],
        lat=planets_data["latitude"],
        lon=planets_data["longitude"],
        mode=mode,
        name=name,
        utcoffset=planets_data.get("utcoffset", 0.0),
        ayanamsa=ayanamsa,
    )


def make_source_params(*, chtk_path, birth_data, mode, ayanamsa,
                       house_system="campanus", is_human_design=False,
                       origin_memory_id=None):
    """Build the dict ChartState stores for chart reconstruction.

    Consumers:
        - Issue 2b: SetZodiacMode handler reads to rebuild with new mode
        - Issue 10: session_manager serializes for cross-restart restore
        - Issue 8:  memory recall uses to rebuild from saved entry

    `birth_data` is always populated. `chtk_path` may be None for "Now"
    charts, AI-generated charts, edited charts, and time-adjusted charts
    — that is the majority case (audit B6).

    `origin_memory_id` (SPEC-ECL-002 section 6, td-n3h3.8 7d): the memory
    entry UUID the active chart was dispatched FROM. Single writer: ONLY
    the chart_memory_panel dispatch passes it; every other build path (new
    chart, edit, Now, AI) constructs fresh params without the key, so its
    presence is a reliable identity short-circuit for the Personal Eclipse
    pinned natal row. The key is ABSENT (not None) when not provided.

    The stored `birth_data` is isolated from the caller's dict so later
    mutation of `tags`/`_toml_extra`/`tz_warnings` on either side does not
    leak across (SPEC-IMPORT-001 §6.6, §L4-R4). Only those mutable nested
    keys are deep-copied; flat values (and large blobs like `raw_chtk_data`)
    stay shallow so folder-load of 500+ charts is not penalized.
    """
    import copy

    if birth_data:
        sp_bd = dict(birth_data)  # shallow base
        for k in ("tags", "_toml_extra", "tz_warnings"):
            if birth_data.get(k) is not None:
                sp_bd[k] = copy.deepcopy(birth_data[k])
    else:
        sp_bd = {}

    params = {
        "chtk_path": chtk_path,
        "birth_data": sp_bd,
        "mode": mode,
        "ayanamsa": ayanamsa,
        "house_system": house_system,
        "is_human_design": bool(is_human_design),
    }
    if origin_memory_id is not None:
        params["origin_memory_id"] = origin_memory_id
    return params


def rebuild_chart(chart, **overrides):
    """Create a new Chart by modifying specific EphContext fields.

    Convenience translations:
      jd=float        -> timeJD=JulianDay(jd, utcoffset=...)
      mode="aditya"   -> circle=..., sysflg=..., sign_names=...
    """
    from dataclasses import replace as dc_replace

    if "jd" in overrides:
        jd_val = overrides.pop("jd")
        utcoffset = overrides.pop("utcoffset", chart.context.timeJD.utcoffset)
        overrides["timeJD"] = JulianDay(jd_val, utcoffset=utcoffset)

    if "mode" in overrides:
        mode = overrides.pop("mode")
        circle, sysflg, sign_names = mode_to_circle_sysflg(mode)
        overrides.setdefault("circle", circle)
        overrides.setdefault("sysflg", sysflg)
        overrides.setdefault("sign_names", sign_names)

    new_ctx = dc_replace(chart.context, **overrides)
    return Chart(new_ctx)


def chart_to_dict(chart):
    """Transitional: project Chart to legacy dict for dict-only consumers.

    Replaces chart_to_renderer_dict. Consumers should migrate to Chart API
    via chart_data_adapter functions. Deleted when all consumers migrate.
    """
    import warnings
    warnings.warn(
        "chart_to_dict is deprecated, use Chart API directly",
        DeprecationWarning, stacklevel=2,
    )
    from core.planets_data_compat import chart_to_planets_data
    ctx = chart.context
    jd = ctx.timeJD
    loc = ctx.location
    year, month, day = jd.usryear(), jd.usrmonth(), jd.usrday()
    hour_float = jd.usrhour()
    hour_int = int(hour_float)
    frac = hour_float - hour_int
    minute = int(frac * 60)
    second = int(round((frac * 60 - minute) * 60))
    if second == 60:
        second, minute = 0, minute + 1
    if minute == 60:
        minute, hour_int = 0, hour_int + 1
    result = chart_to_planets_data(
        chart, year=year, month=month, day=day,
        hour=hour_int, minute=minute,
        lat=loc.lat, lon=loc.long,
        timezone_str="UTC", second=second,
    )
    result["utcoffset"] = ctx.timeJD.utcoffset if hasattr(ctx.timeJD, 'utcoffset') else 0.0
    return result


def birth_data_from_planets_data(planets_data, name=""):
    """Best-effort extraction of `birth_data` shape from a legacy planets_data dict.

    Used at sites where only the dict is in scope (e.g., AI-dialog callback).
    The dict carries enough to rebuild EphContext at restore time. If a field
    is missing, it falls back to a sensible default.

    Issue H1 Bug 4: `chart_to_planets_data()` writes hour/minute/second as
    integers but never writes a `timedec` key. Reconstruct it from h/m/s.
    """
    hour = planets_data.get("hour", 0) or 0
    minute = planets_data.get("minute", 0) or 0
    second = planets_data.get("second", 0) or 0
    timedec = hour + minute / 60.0 + second / 3600.0
    return {
        "name": planets_data.get("name", name),
        "year": planets_data.get("year"),
        "month": planets_data.get("month"),
        "day": planets_data.get("day"),
        "timedec": timedec,
        "lat": planets_data.get("latitude"),
        "lon": planets_data.get("longitude"),
        "utcoffset": planets_data.get("utcoffset", 0.0),
    }


# ── SPEC-MEM-002 Recipe Infrastructure ──────────────────────────────────


def timedec_to_hms(timedec):
    """Decompose a decimal-hour value into (hour, minute, second) integers."""
    hour = int(timedec)
    frac = timedec % 1
    minute = int(frac * 60)
    second = int(round((frac * 60 - minute) * 60))
    if second >= 60:
        second, minute = 0, minute + 1
    if minute >= 60:
        minute, hour = 0, hour + 1
    if hour >= 24:
        hour = 0
    return hour, minute, second


def metadata_from_recipe(recipe):
    """Build backward-compat birth_metadata and birth_data shims from a recipe."""
    hour, minute, second = timedec_to_hms(recipe['timedec'])
    birth_data = birth_data_from_recipe(recipe)
    birth_metadata = {
        'name': recipe['name'],
        'year': recipe['year'], 'month': recipe['month'], 'day': recipe['day'],
        'hour': hour, 'minute': minute, 'second': second,
        'timezone': recipe['timezone'],
        'iana_timezone': recipe['timezone'],
        'latitude': recipe['lat'], 'longitude': recipe['lon'],
        'city': recipe['city'], 'country': recipe['country'],
        'coordinates': {'latitude': recipe['lat'], 'longitude': recipe['lon']},
        'location': {'city': recipe['city'], 'country': recipe['country']},
        # SPEC-IMPORT-001 §6.3: additive TOML metadata (None for CHTK charts).
        'rodden': recipe.get('rodden'),
        'tags': recipe.get('tags'),
        'notes': recipe.get('notes'),
        'julian_day': recipe.get('julian_day'),
        'dst_offset_hours': recipe.get('dst_offset_hours'),
    }
    return birth_data, birth_metadata


def chart_data_from_recipe(recipe):
    """Build a standardized current_chart_data dict from a recipe.

    Provides both flat and nested keys so all consumers work regardless
    of which access pattern they use (F4 fix).
    """
    hour, minute, second = timedec_to_hms(recipe['timedec'])
    return {
        'name': recipe['name'],
        'year': recipe['year'], 'month': recipe['month'],
        'day': recipe['day'], 'hour': hour, 'minute': minute,
        'second': second, 'timezone': recipe['timezone'],
        'utcoffset': recipe.get('utcoffset'),
        'time_change_flag': recipe.get('time_change_flag', 0),
        'gender': recipe.get('gender', 'Unknown'),
        'city': recipe['city'], 'country': recipe['country'],
        'latitude': recipe['lat'], 'longitude': recipe['lon'],
        'location': {'city': recipe['city'], 'country': recipe['country']},
        'coordinates': {'latitude': recipe['lat'], 'longitude': recipe['lon']},
        # SPEC-IMPORT-001 §6.3: additive TOML metadata (None for CHTK charts).
        'rodden': recipe.get('rodden'),
        'tags': recipe.get('tags'),
        'notes': recipe.get('notes'),
        'julian_day': recipe.get('julian_day'),
        'dst_offset_hours': recipe.get('dst_offset_hours'),
    }


def birth_data_from_recipe(recipe):
    """Build a standardized current_birth_data dict from a recipe (F5 fix)."""
    return {
        'name': recipe['name'],
        'year': recipe['year'], 'month': recipe['month'],
        'day': recipe['day'], 'timedec': recipe['timedec'],
        'utcoffset': recipe['utcoffset'],
        'iana_timezone': recipe['timezone'],
        'lat': recipe['lat'], 'lon': recipe['lon'],
        'city': recipe['city'], 'country': recipe['country'],
        'gender': recipe.get('gender', 'Unknown'),
        # SPEC-IMPORT-001 §6.3: additive TOML metadata (None for CHTK charts).
        'rodden': recipe.get('rodden'),
        'tags': recipe.get('tags'),
        'notes': recipe.get('notes'),
        'julian_day': recipe.get('julian_day'),
        'dst_offset_hours': recipe.get('dst_offset_hours'),
    }


def make_recipe(*, name, year, month, day, timedec, utcoffset,
                timezone='UTC', lat, lon, city='', country='',
                gender='Unknown', time_change_flag=0,
                house_system='campanus',
                rodden=None, tags=None, notes=None,
                julian_day=None, dst_offset_hours=None):
    """Build a validated recipe dict (SPEC-MEM-002 S2.1, SPEC-HSY-001 §7.3).

    house_system is stored as a human key (e.g. 'campanus'), never an SE code.

    SPEC-IMPORT-001 §6.3: rodden/tags/notes/julian_day/dst_offset_hours are
    optional TOML-native metadata. They default to None so CHTK-origin charts
    (which never carry them) round-trip unchanged. Per §6.3 ("include in output
    dict if not None") each of the 5 fields is emitted CONDITIONALLY: a field
    is added to the recipe ONLY when its value is not None. This keeps a CHTK
    recipe byte-identical to its pre-T1 shape (no 5 spurious None keys) and
    preserves the `if mapped in recipe` presence check used by the memory
    panel. The *_from_recipe consumers all use recipe.get(...), so an absent
    key reads back as None and stays robust.

    None-safe casting (SPEC-IMPORT-001 §6.3 hardening, Trap #1):
      - julian_day / dst_offset_hours: float(x) only when not None
        (float(None) raises TypeError).
      - tags: list(tags) when not None (preserves an explicit empty list as a
        distinct value from absent), never a shared mutable default.
      - rodden / notes: passed through verbatim.
    """
    recipe = {
        'name': str(name),
        'year': int(year),
        'month': int(month),
        'day': int(day),
        'timedec': float(timedec),
        'utcoffset': float(utcoffset),
        'timezone': str(timezone),
        'lat': float(lat),
        'lon': float(lon),
        'city': str(city),
        'country': str(country),
        'gender': str(gender),
        'time_change_flag': int(time_change_flag),
        'house_system': str(house_system),
    }
    # Conditional additive metadata (omit when None; §6.3).
    if rodden is not None:
        recipe['rodden'] = rodden
    if tags is not None:
        recipe['tags'] = list(tags)
    if notes is not None:
        recipe['notes'] = notes
    if julian_day is not None:
        recipe['julian_day'] = float(julian_day)
    if dst_offset_hours is not None:
        recipe['dst_offset_hours'] = float(dst_offset_hours)
    return recipe


def resolve_recipe_dst_flag(recipe):
    """Guard for legacy recipes carrying time_change_flag == -1 (td-5w3c.1).

    Recipes written after the CHTK auto-flag fix always carry a resolved
    flag (canonical birth_data normalizes -1 at load), but sessions saved
    BEFORE the fix can still hold the Kala -1 AUTO sentinel. Applying -1
    as-is corrupts the UTC offset (treated as no-DST, chart loads 1h early).

    Returns (flag, warnings):
    - flag != -1: passed through unchanged, no warnings.
    - flag == -1 with an IANA name in recipe['timezone'] (contains '/'):
      resolved via core.time_utils.resolve_auto_dst_flag at the recipe's
      local birth instant.
    - flag == -1 without an IANA name: degrades to 0 with a fail-loud
      warning (SPEC-TZ-001 5f), via the same helper's falsy-IANA branch.
    """
    flag = recipe.get('time_change_flag', 0)
    if flag != -1:
        return flag, []
    from core.time_utils import resolve_auto_dst_flag
    tz = str(recipe.get('timezone') or '')
    iana = tz if '/' in tz else None
    hour, minute, _second = timedec_to_hms(recipe.get('timedec', 12.0))
    return resolve_auto_dst_flag(
        iana, recipe.get('year', 2000), recipe.get('month', 1),
        recipe.get('day', 1), hour, minute, longitude=recipe.get('lon'))


def recipe_from_chart(chart, *, name='', timezone='UTC', city='', country='',
                      gender='Unknown', time_change_flag=0,
                      rodden=None, tags=None, notes=None,
                      julian_day=None, dst_offset_hours=None):
    """Extract a recipe from a libaditya Chart object (SPEC-MEM-002 S4.3).

    usrhour(), usryear(), usrmonth(), usrday() all return LOCAL time
    (JulianDay.usrdt() computes swe.revjul(jd + utcoffset/24)).
    No offset conversion needed.

    SPEC-IMPORT-001 §6.3: rodden/tags/notes/julian_day/dst_offset_hours are
    forwarded verbatim to make_recipe (which applies None-safe casting). The
    Chart object does not carry this metadata, so callers supply it from the
    source birth_data; absent values stay None.
    """
    ctx = chart.context
    jd = ctx.timeJD
    loc = ctx.location
    utcoffset = jd.utcoffset if hasattr(jd, 'utcoffset') else 0.0
    # SPEC-HSY-001: reverse-map the chart's SE code back to a human key.
    hsys_human = {v: k for k, v in HOUSE_SYSTEM_CODES.items()}.get(
        getattr(ctx, 'hsys', 'C'), 'campanus'
    )
    return make_recipe(
        name=name or ctx.name,
        year=jd.usryear(), month=jd.usrmonth(), day=jd.usrday(),
        timedec=jd.usrhour(),
        utcoffset=utcoffset,
        timezone=timezone,
        lat=loc.lat, lon=loc.long,
        city=city, country=country,
        gender=gender, time_change_flag=time_change_flag,
        house_system=hsys_human,
        rodden=rodden, tags=tags, notes=notes,
        julian_day=julian_day, dst_offset_hours=dst_offset_hours,
    )


def recipe_from_chtk_meta(meta, house_system="campanus"):
    """Extract a recipe from a CHTK meta dict (SPEC-MEM-002 S4.4).

    # DEAD: no callers as of 2026-06-21 (grep -rn 'recipe_from_chtk_meta'
    # finds only this definition). Kept (not trashed) to avoid breaking any
    # import; revive if a caller is added. SPEC-IMPORT-001 §6.3 requires the
    # 5 additive metadata fields (rodden/tags/notes/julian_day/
    # dst_offset_hours) be FORWARDED here even though CHTK meta dicts never
    # carry them: meta.get(...) yields None when absent, make_recipe emits
    # those conditionally (omits None), so a CHTK recipe stays byte-identical
    # while a future meta that DID carry them would round-trip correctly.
    """
    hour = meta.get('hour', 0) or 0
    minute = meta.get('minute', 0) or 0
    second = meta.get('second', 0) or 0
    timedec = hour + minute / 60.0 + second / 3600.0
    _raw_utcoff = meta.get('utcoffset')
    _utcoffset = float(_raw_utcoff) if _raw_utcoff is not None else 0.0
    return make_recipe(
        name=meta.get('name', ''),
        year=meta.get('year', 0),
        month=meta.get('month', 0),
        day=meta.get('day', 0),
        timedec=timedec,
        utcoffset=_utcoffset,
        timezone=meta.get('timezone', 'UTC') or 'UTC',
        lat=meta.get('latitude', 0.0),
        lon=meta.get('longitude', 0.0),
        city=meta.get('city', ''),
        country=meta.get('country', ''),
        gender=meta.get('gender', 'Unknown'),
        time_change_flag=meta.get('time_change_flag', 0),
        house_system=house_system,
        rodden=meta.get('rodden'),
        tags=meta.get('tags'),
        notes=meta.get('notes'),
        julian_day=meta.get('julian_day'),
        dst_offset_hours=meta.get('dst_offset_hours'),
    )


#: The recipe fields that determine the instant. Anything that edits one of
#: these invalidates a stored julian_day (td-nbl8).
RECIPE_INSTANT_FIELDS = ('year', 'month', 'day', 'timedec', 'utcoffset')


def jd_from_recipe_civil(recipe):
    """Julian Day from the recipe's CIVIL time, ignoring any stored julian_day.

    The one place this formula lives. build_chart_from_recipe falls back to it,
    and chart_memory_panel.update_current_chart re-derives a stale JD with it
    after a time edit. Two copies of this expression would drift, and a drift
    here moves the chart.
    """
    return swe.julday(
        recipe['year'], recipe['month'], recipe['day'],
        recipe['timedec'] - recipe['utcoffset']
    )


def build_chart_from_recipe(recipe, mode, ayanamsa):
    """Build a Chart from a recipe dict. Single reconstruction path (SPEC-MEM-002 S3.1).

    SPEC-IMPORT-001 §6.3 (JD forwarding): when the recipe carries a non-None
    julian_day (TOML-origin charts), use it directly to preserve the file's
    sub-second precision across session restart. CHTK-origin recipes have
    julian_day=None, so JD is recomputed from civil time as before.

    The stored JD WINS over civil time, so whoever edits the civil fields owns
    keeping it honest — see td-nbl8, where a saved time adjustment reverted on
    the next rebuild because only timedec had been updated.
    """
    _recipe_jd = recipe.get('julian_day')
    if _recipe_jd is not None:
        jd = float(_recipe_jd)
    else:
        jd = jd_from_recipe_civil(recipe)
    # SPEC-HSY-001: recipe stores a human key; convert to SE code at consumption.
    hsys = get_house_system_code(recipe.get('house_system', 'campanus'))
    return build_chart_from_params(
        jd=jd,
        lat=recipe['lat'],
        lon=recipe['lon'],
        mode=mode,
        name=recipe['name'],
        ayanamsa=ayanamsa,
        utcoffset=recipe['utcoffset'],
        hsys=hsys,
    )


def get_or_build_chart(entry, current_mode, current_ayanamsa, current_hsys="campanus"):
    """Return cached Chart or rebuild if mode/ayanamsa/hsys changed (SPEC-MEM-002 S3.2).

    SPEC-HSY-001 §7.4: current_hsys is a human key ("campanus", "placidus", etc.)
    and is part of the cache key so switching house systems invalidates cached
    Chart objects. Default "campanus" keeps backward compatibility.
    """
    cached = entry.get('_chart')
    if cached is not None:
        if (entry.get('_built_mode') == current_mode and
                entry.get('_built_ayanamsa') == current_ayanamsa and
                entry.get('_built_hsys') == current_hsys):
            return cached
    entry['recipe']['house_system'] = current_hsys
    chart = build_chart_from_recipe(entry['recipe'], current_mode, current_ayanamsa)
    entry['_chart'] = chart
    entry['_built_mode'] = current_mode
    entry['_built_ayanamsa'] = current_ayanamsa
    entry['_built_hsys'] = current_hsys
    return chart
