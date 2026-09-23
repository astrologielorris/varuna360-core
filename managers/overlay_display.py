"""SPEC-BAR-001 Feature 2 — the overlaid chart's own birth-identity payload.

D-23(b): when a second chart is overlaid, the title-well chip shows the whole
of its birth info: ``◇ <Name> · <DD/MM/YYYY> <HH:MM> · <City, Country>``.

This module owns the ONE pure formatter that produces that text. It is
deliberately NOT the window-title formatter (``managers/chart_manager.py``,
which is ``MM/DD/YYYY`` with seconds, SPEC-UI-001): two surfaces, two
audiences — do not unify them.

The payload is populated at the overlay call site (from a memory recipe or a
file's birth_data), passed into ``TransitOverlayManager.overlay_chart``, stored
alongside the overlay metadata, and cleared when the overlay clears. It is an
immutable value object of already-formatted strings so the widget never derives
anything itself.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverlayBirthDisplay:
    """Preformatted display strings for the overlay chip (D-23(b))."""
    name: str
    date_str: str          # DD/MM/YYYY  (empty when unknown)
    time_str: str          # HH:MM       (empty when unknown)
    place: str             # "City, Country" (empty when unknown)

    @property
    def info(self) -> str:
        """The ``.ovl-info`` span text: ``· DD/MM/YYYY HH:MM · City, Country``.

        Each present segment is introduced by ` · ` exactly as the mockup's
        info span reads. A segment with no content is dropped (no stub), so a
        placeless or dateless chart still renders cleanly.
        """
        bits = []
        dt = " ".join(x for x in (self.date_str, self.time_str) if x)
        if dt:
            bits.append(dt)
        if self.place:
            bits.append(self.place)
        return "".join(f" · {b}" for b in bits)


def _clean_place(city, country) -> str:
    """City, Country with the same defensive cleanup the window title uses
    (trailing commas, the ", 0" artifact, city == country collapse)."""
    city = (city or "").strip().rstrip(",")
    country = (country or "").strip().rstrip(",")
    if city.endswith(", 0"):
        city = city[:-3].strip()
    if city and country and city.lower() == country.lower():
        return city
    if city and country:
        return f"{city}, {country}"
    return city or country or ""


def _fmt_date(year, month, day) -> str:
    try:
        return f"{int(day):02d}/{int(month):02d}/{int(year):04d}"
    except (TypeError, ValueError):
        return ""


def _fmt_time(hour, minute) -> str:
    try:
        return f"{int(hour):02d}:{int(minute):02d}"
    except (TypeError, ValueError):
        return ""


def overlay_display_from_fields(*, name, year, month, day, hour, minute,
                                city, country) -> OverlayBirthDisplay:
    """The pure DD/MM/YYYY HH:MM formatter (D-23(b))."""
    return OverlayBirthDisplay(
        name=(name or "chart"),
        date_str=_fmt_date(year, month, day),
        time_str=_fmt_time(hour, minute),
        place=_clean_place(city, country),
    )


def _first(d, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return default


def overlay_display_from_recipe(recipe) -> OverlayBirthDisplay:
    """Build the payload from a memory-entry recipe (its ``timedec`` holds the
    local clock time; year/month/day are the local civil date)."""
    from core.chart_factory import timedec_to_hms
    hour, minute, _ = timedec_to_hms(recipe.get("timedec", 0) or 0)
    return overlay_display_from_fields(
        name=recipe.get("name") or "chart",
        year=recipe.get("year"), month=recipe.get("month"),
        day=recipe.get("day"), hour=hour, minute=minute,
        city=recipe.get("city", ""), country=recipe.get("country", ""))


def overlay_display_from_birth_data(bd) -> OverlayBirthDisplay:
    """Build the payload from a file's birth_data dict. Prefers the local_*
    civil fields (the birth clock the person keeps), falling back to the plain
    keys, exactly like the window title's local-first preference."""
    return overlay_display_from_fields(
        name=bd.get("name") or "chart",
        year=_first(bd, "local_year", "year"),
        month=_first(bd, "local_month", "month"),
        day=_first(bd, "local_day", "day"),
        hour=_first(bd, "local_hour", "hour", default=0),
        minute=_first(bd, "local_minute", "minute", default=0),
        city=bd.get("city", ""), country=bd.get("country", ""))
