# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Heal Chart Memory recipes stored at latitude 0, longitude 0.

Before 2026-10-02 (commit 1869d1022) the CHTK reader returned 0,0 for Kala's
short lower-case coordinates (``16n13`` / ``81e12``). Every recipe writer
copied that faithfully, the IANA lookup at 0,0 gave ``Etc/GMT``, and the
entry was saved to session.json. Reopening such an entry from Chart Memory
rebuilds the chart at 0°/0° even though the file now reads correctly.

The heal is deliberately narrow (SPEC-MEM-002 heal-on-match is the model):
it runs only when the stored recipe is at exactly 0,0, its source chart
file exists and now reads non-zero coordinates, AND the file describes the
same birth (name, date, local time within 0.002 h, the
``ChartMemoryPanel._is_same_chart`` rule). Then the file is authoritative
and the recipe is rebuilt from it, keeping the stored house system. A
recipe whose time was edited in memory (no identity match) is left alone,
as is any file that still reads 0,0. The chart file is only READ
(``canonicalize=False``): user files are never written here.

Dry-run report: test/scan_zero_coord_recipes.py lists the affected
entries across profiles/ (read only).
"""
from pathlib import Path

# File-level failures only: a recipe mismatch must not suppress another birth.
# Bound the negative cache; file identity/change stamps invalidate replacements.
_NO_HEAL_LIMIT = 128
_NO_HEAL = {}


def _is_zero(recipe):
    return recipe.get('lat') == 0 and recipe.get('lon') == 0


def same_birth(a, b):
    """The ChartMemoryPanel._is_same_chart identity on two recipes."""
    return (str(a.get('name', '')).lower() == str(b.get('name', '')).lower()
            and (a.get('year'), a.get('month'), a.get('day'))
            == (b.get('year'), b.get('month'), b.get('day'))
            and abs(float(a.get('timedec', 0.0)) - float(b.get('timedec', 0.0))) < 0.002)


def recipe_from_file(path, house_system='campanus'):
    """A fresh recipe from a .chtk/.toml file, built the way the Chart
    Memory folder load builds it (BirthDataManager, canonicalize=False)."""
    from managers.birth_data_manager import BirthDataManager
    from core.chart_factory import make_recipe
    bd = BirthDataManager.create_birth_data_from_file(str(path), canonicalize=False)
    timedec = (bd.get('local_hour', 0) + bd.get('local_minute', 0) / 60.0
               + bd.get('local_second', 0) / 3600.0)
    return make_recipe(
        name=bd.get('name', 'Unknown'),
        year=bd['local_year'], month=bd['local_month'], day=bd['local_day'],
        timedec=timedec,
        utcoffset=bd.get('utc_offset_hours', 0.0),
        timezone=bd.get('iana_timezone', 'UTC'),
        lat=bd.get('latitude', 0.0), lon=bd.get('longitude', 0.0),
        city=bd.get('city', ''), country=bd.get('country', ''),
        gender=bd.get('gender', 'Unknown'),
        time_change_flag=bd.get('time_change_flag', 0),
        house_system=house_system,
        rodden=bd.get('rodden'), tags=bd.get('tags'), notes=bd.get('notes'),
        julian_day=bd.get('julian_day'),
        dst_offset_hours=bd.get('dst_offset_hours'),
    )


def diagnose(recipe, chart_path):
    """(status, fresh_recipe_or_None) for a stored recipe. Status is one of
    'ok' (not at 0,0), 'no_file', 'file_zero', 'unreadable', 'mismatch'
    (file is a different birth, e.g. time edited in memory), 'healable'."""
    if not recipe or not _is_zero(recipe):
        return 'ok', None
    if not chart_path or not Path(str(chart_path)).is_file():
        return 'no_file', None
    try:
        fresh = recipe_from_file(chart_path, recipe.get('house_system', 'campanus'))
    except Exception:  # noqa: BLE001 - a bad file never blocks a restore
        return 'unreadable', None
    if _is_zero(fresh):
        return 'file_zero', fresh
    if not same_birth(recipe, fresh):
        return 'mismatch', fresh
    return 'healable', fresh


def heal_zero_coordinate_recipe(entry):
    """Replace entry['recipe'] in place when diagnose() says 'healable'.
    Returns True when it healed. Never raises."""
    recipe = entry.get('recipe') or {}
    path = entry.get('chtk_path')
    if not _is_zero(recipe) or not path:
        return False
    try:
        source = Path(str(path))
        stat = source.stat()
        key = (str(source.resolve()), stat.st_dev, stat.st_ino, stat.st_size,
               stat.st_mtime_ns, stat.st_ctime_ns, repr(recipe.get('house_system', 'campanus')))
    except OSError:
        return False
    if key in _NO_HEAL:
        return False
    try:
        status, fresh = diagnose(recipe, path)
    except Exception:  # noqa: BLE001 - malformed stored recipe: leave it
        return False                    # never cache recipe-dependent errors
    if status != 'healable':
        if status in ('file_zero', 'unreadable'):
            if len(_NO_HEAL) >= _NO_HEAL_LIMIT:
                _NO_HEAL.pop(next(iter(_NO_HEAL)))
            _NO_HEAL[key] = None
        return False
    entry['recipe'] = fresh
    print(f"[SESSION] Healed 0,0 recipe for {fresh['name']!r} from {path} "
          f"({fresh['lat']:.4f}, {fresh['lon']:.4f}, {fresh['timezone']})")
    return True
