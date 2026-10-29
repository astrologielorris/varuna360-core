# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Planet glyph sizes and sign shadows as single settings (AI setting
redesign, td-bztjj, item 2). Qt-free, data only.

The four typed display sections (``chart_display``, ``south_indian_display``,
``wheel_display``, ``north_indian_display``) are registered whole (their
getters merge and normalise them, ``display.py``). Their leaves had no entry,
so neither the AI nor a Settings row could name one. Here:

- one leaf per planet and section, ``<section>.planet_sizes.<Planet>`` (int,
  pixels): the section's factory size, bounds from half the section's
  smallest default size to twice its largest;
- one convenience key per section, ``<section>.planet_scale`` (int, percent
  of the factory sizes, 100 = standard), so "make the planets bigger" is one
  change. It is NOT stored: its value is read from the section's sizes
  (``current``) and a write scales every planet of the section together,
  keeping their proportions (``expand``: one write of
  ``<section>.planet_sizes``, through the same request transaction);
- the two ``chart_display.element_shadows`` leaves the Settings tab's
  "Advanced appearance" rows already write.

The factory sizes are the sections' own (``managers/settings_manager.py``
``DEFAULT_*_DISPLAY["planet_sizes"]``), repeated here because the registry
never imports the settings manager; ``test_ai_settings_planet_sizes`` pins
them equal.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from core.settings_registry.rules import APP_AI
from core.settings_registry.schema import Setting

PLANETS = ("Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn",
           "Rahu", "Ketu", "Uranus", "Neptune", "Pluto")

# Factory sizes per section (pixels), in PLANETS order.
FACTORY: Dict[str, Dict[str, int]] = {
    "chart_display": dict(zip(PLANETS, (213, 214, 160, 173, 160, 136, 162, 136, 126,
                                        187, 157, 173))),
    "wheel_display": dict(zip(PLANETS, (130, 151, 139, 138, 137, 127, 146, 124, 121,
                                        99, 91, 97))),
    "north_indian_display": dict(zip(PLANETS, (149, 186, 152, 142, 140, 120, 143, 130,
                                               120, 128, 120, 110))),
    "south_indian_display": dict(zip(PLANETS, (149, 186, 152, 142, 140, 120, 143, 130,
                                               120, 128, 120, 110))),
}
# How a label names the view a section draws (written labels: no caption).
VIEW_NAMES = {
    "chart_display": "South Indian artistic",
    "south_indian_display": "South Indian",
    "wheel_display": "wheel",
    "north_indian_display": "North Indian",
}
SCALE_BOUNDS = (50, 200)
SCALE_SUFFIX = "planet_scale"
SIZES_SUFFIX = "planet_sizes"


def _bounds(section: str) -> Tuple[int, int]:
    sizes = FACTORY[section].values()
    return min(sizes) // 2, max(sizes) * 2


def _section_settings(section: str):
    view = VIEW_NAMES[section]
    yield Setting(f"{section}.{SCALE_SUFFIX}", int, 100, label=f"Planet size ({view})",
                  help=f"How big the planets are drawn on the {view} chart, in percent of "
                       f"the standard size. All planets change together.",
                  bounds=SCALE_BOUNDS, persisted=False, rules=APP_AI)
    low, high = _bounds(section)
    for planet in PLANETS:
        yield Setting(f"{section}.{SIZES_SUFFIX}.{planet}", int, FACTORY[section][planet],
                      label=f"{planet} size ({view})", bounds=(low, high),
                      persisted=False, rules=APP_AI)


SETTINGS = (
    *(s for section in FACTORY for s in _section_settings(section)),
    # The Chart Display page's "Advanced appearance" rows (ui/settings_tab.py).
    Setting("chart_display.element_shadows.enabled", bool, True,
            label="Sign glyph/icon shadows:", persisted=False, rules=APP_AI,
            help="Add element-coloured shadows to Josh glyphs and zodiac icons in every "
                 "supported chart view. Planet shadows are controlled separately."),
    Setting("chart_display.element_shadows.blur_radius", int, 6, label="Sign shadow size:",
            bounds=(0, 12), persisted=False, rules=APP_AI,
            help="Increase or decrease the glyph and zodiac-icon shadow footprint."),
)

SCALE_KEYS = {f"{section}.{SCALE_SUFFIX}": section for section in FACTORY}


def is_scale_key(key: Any) -> bool:
    return isinstance(key, str) and key in SCALE_KEYS


def _sizes(section: str, get: Callable[..., Any]) -> Dict[str, int]:
    """The section's planet sizes as drawn: the stored ones over the factory."""
    stored = get(f"{section}.{SIZES_SUFFIX}", None)
    sizes = dict(FACTORY[section])
    if isinstance(stored, dict):
        for planet, size in stored.items():
            if isinstance(size, (int, float)) and not isinstance(size, bool):
                sizes[planet] = size
    return sizes


def _leaf_locked(section: str, planet: str,
                 locked: Optional[Callable[[str], bool]]) -> bool:
    """True when the user locked ``planet``'s size: its leaf, the section's
    sizes or the whole section (a lock on a parent covers its leaves)."""
    if locked is None:
        return False
    return any(locked(k) for k in (f"{section}.{SIZES_SUFFIX}.{planet}",
                                   f"{section}.{SIZES_SUFFIX}", section))


def kept_planets(key: str, locked: Optional[Callable[[str], bool]]) -> List[str]:
    """The planets a scale ``key`` leaves as they are: the locked ones
    (AI setting redesign fix RD-7: a scale never overrides the user's lock
    on one planet; it scales the others)."""
    section = SCALE_KEYS.get(key) if isinstance(key, str) else None
    if section is None:
        return []
    return [p for p in PLANETS if _leaf_locked(section, p, locked)]


def _free(section: str, sizes: Dict[str, Any], skip) -> List[str]:
    """The planets a scale reads and moves: not kept, not at a bound (a
    size pinned to its bound says nothing about the scale, RD-8)."""
    low, high = _bounds(section)
    return [p for p in PLANETS if p not in skip and low < sizes[p] < high]


def _mean_ratio(section: str, sizes: Dict[str, Any], planets) -> float:
    ratios = [sizes[p] / FACTORY[section][p] for p in planets]
    return sum(ratios) / len(ratios)


def current(key: str, get: Callable[..., Any], default: Any = None,
            locked: Optional[Callable[[str], bool]] = None) -> Any:
    """``key``'s value as the app uses it: a scale key's percent, read from
    its section's sizes (their mean ratio to the factory sizes, over the
    planets a scale moves: not locked, not at a bound; all of them when none
    is free); any other key ``get(key, default)``."""
    section = SCALE_KEYS.get(key) if isinstance(key, str) else None
    if section is None:
        return get(key, default)
    sizes = _sizes(section, get)
    planets = _free(section, sizes, kept_planets(key, locked)) or list(PLANETS)
    return int(round(100.0 * _mean_ratio(section, sizes, planets)))


def _factor(section: str, sizes, movable, target: float) -> float:
    """The factor that brings the planets left inside the bounds to
    ``target`` (their mean ratio to the factory sizes): the planets a bound
    stops leave the mean, recomputed until that set is stable."""
    low, high = _bounds(section)
    inside, factor = list(movable), 1.0
    for _ in range(2 * len(PLANETS)):
        if not inside:
            break
        factor = target / _mean_ratio(section, sizes, inside)
        now_inside = [p for p in movable if low < sizes[p] * factor < high]
        if now_inside == inside:
            break
        inside = now_inside
    return factor


def _nudge(section: str, sizes: Dict[str, Any], movable, value: int) -> None:
    """Move free planets one pixel at a time (round robin, never onto a
    bound) until the sizes read back exactly ``value`` (rounding, R2-6)."""
    low, high = _bounds(section)
    for _ in range(40 * len(PLANETS)):
        free = _free(section, sizes, set(PLANETS) - set(movable))
        if not free:
            return
        now = int(round(100.0 * _mean_ratio(section, sizes, free)))
        if now == value:
            return
        step = 1 if now < value else -1
        moved = False
        for planet in sorted(free, key=lambda p: FACTORY[section][p], reverse=True):
            if low < sizes[planet] + step < high:
                sizes[planet] += step
                moved = True
                break
        if not moved:
            return


def _scale_once(section: str, sizes: Dict[str, Any], keep, value: int) -> Dict[str, Any]:
    """One scaling of ``sizes`` (every planet) to ``value`` percent."""
    low, high = _bounds(section)
    movable = [p for p in PLANETS if p not in keep]
    factor = _factor(section, sizes, movable, float(value) / 100.0)
    out = dict(sizes)
    for planet in movable:
        out[planet] = max(low, min(high, int(round(sizes[planet] * factor))))
    _nudge(section, out, movable, int(value))
    return out


def _settled(section: str, sizes: Dict[str, Any], keep, value: int) -> bool:
    """True when ``sizes`` already reads ``value`` (no change to make)."""
    free = _free(section, sizes, keep) or list(PLANETS)
    return int(round(100.0 * _mean_ratio(section, sizes, free))) == int(value)


def expand(key: str, value: Any, get: Callable[..., Any],
           locked: Optional[Callable[[str], bool]] = None) -> Tuple[str, Any]:
    """The write a request for ``key`` = ``value`` makes: ``(key, value)``
    itself, except a scale key, whose percent scales the planets of its
    section together from their current sizes (proportions kept), each size
    kept within its bounds: ``("<section>.planet_sizes", {planet: size})``.

    - Locked planets (``locked``: the user's lock on a key) keep their size
      (RD-7); ``kept_planets`` names them.
    - Idempotent for every percent (RD-8, R2-6): the result is a fixed
      point, the map a repeat of the same request leaves as it is. Scaling
      is repeated on its own result (one pixel nudges fix the rounding) until
      the sizes read back ``value`` or a further scaling changes nothing;
      a percent the sizes already read is no change at all."""
    section = SCALE_KEYS.get(key) if isinstance(key, str) else None
    if section is None:
        return key, value
    sizes = _sizes(section, get)
    stored = get(f"{section}.{SIZES_SUFFIX}", None)
    out: Dict[str, Any] = dict(stored) if isinstance(stored, dict) else {}
    keep = set(kept_planets(key, locked))
    if _settled(section, sizes, keep, int(value)):
        return f"{section}.{SIZES_SUFFIX}", out
    for _ in range(8):
        nxt = _scale_once(section, sizes, keep, int(value))
        done = nxt == sizes or _settled(section, nxt, keep, int(value))
        sizes = nxt
        if done:
            break
    for planet in PLANETS:
        if planet in keep:
            out.setdefault(planet, sizes[planet])
        else:
            out[planet] = sizes[planet]
    return f"{section}.{SIZES_SUFFIX}", out


def write_path(key: Any) -> Any:
    """The key a request for ``key`` writes: a scale key's section sizes,
    else the key itself."""
    section = SCALE_KEYS.get(key) if isinstance(key, str) else None
    return key if section is None else f"{section}.{SIZES_SUFFIX}"


def section_of(key: Any) -> Optional[str]:
    """The typed section a planet size, scale or shadow key belongs to."""
    if not isinstance(key, str):
        return None
    head = key.split(".", 1)[0]
    return head if head in FACTORY and "." in key else None
