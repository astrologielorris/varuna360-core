# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Where a map click BECOMES a location, for every host in the app.

SPEC-MAP-004 section 4.1-4.2.

Five panels put a map in front of the user, and each of them used to decide
for itself what a click meant: whether to move the point to a nearby capital,
where the timezone came from, what to call the place. They disagreed, and the
disagreements were invisible — the two worst bugs this module exists to retire
both looked right on screen:

  * F-1: a click with no capital near enough left the PREVIOUS selection's
    timezone in place, and the place NAME was then derived from that stale
    timezone. Two wrong answers that agreed with each other.
  * Unbounded snapping: a mid-ocean click silently became a chart for a
    capital thousands of km away, that capital's timezone included, and the
    user was never told they had been moved.

So routing lives here, once, as a pure function. When it snaps, the timezone it
returns is the capital's; when it does not, it is the clicked point's own, as
the widget resolved it. **There is no branch that returns a previous
selection's timezone** — F-1 is retired by construction, not by review.

`route_selection` is the only caller of `snap_to_capital` outside tests. The
host panels that used to call it (`pro/panels/lunar_new_year_panel.py`,
`pro/panels/eclipse_panel.py`) no longer import or call it or `resolve_place`,
and an AST sweep gate keeps it that way: test_place_naming_contract.py::
test_no_host_panel_imports_or_calls_snap_or_resolve fails on any host panel
that reaches around the component to snap or name a click itself.

Deliberately Qt-free, and gated as such (T-7): the CLI tools and the tests
call `route_selection` directly (Rule 24), and a `from PySide6 import ...`
anywhere in this file would end that.

WHAT THIS MODULE DOES NOT DO. It never resolves a timezone and never
geocodes. It is handed the facts and decides what they mean. Resolution is the
widget's job (`core.tz_finder`, `core.place_naming`), which is why this stays
pure and instant.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

from core.place_naming import (
    clamp_label,
    clean_place_parts,
    format_place_line,
    resolve_place,
    snap_to_capital,
)

__all__ = [
    "MapSelection",
    "SelectionPolicy",
    "RoutedSelection",
    "route_selection",
]


@dataclass(frozen=True)
class MapSelection:
    """A point the user picked, with everything the widget already knows.

    `tz_name` is Optional and stays that way. None means "not resolved", it is
    reportable, and it is never quietly turned into UTC or into the last
    location's zone (SPEC-MAP-003 INV-3). A host that receives None must
    refuse the dependent action visibly.
    """

    lat: float
    lon: float
    tz_name: Optional[str]
    city: str = ""
    country: str = ""
    is_final: bool = True
    #: WHAT made this selection — "click" | "search" | "parse" | "load". It rides
    #: the routed payload so a host can tell a user action apart from a derived
    #: one WITHOUT a fragile process-local latch (WI-4): a parse-driven pin move
    #: must NOT steal the place chip from the token bar, or a later re-parse
    #: could no longer move the pin. Defaults to "click" so every existing
    #: caller (five map hosts + the CLI) is unchanged.
    origin: str = "click"


@dataclass(frozen=True)
class SelectionPolicy:
    """How one host interprets a click. Declared once, per host.

    `snap_max_km` has NO default distance on purpose (SPEC-MAP-003 INV-5): a
    host either states how far it is willing to move the user, or it does not
    snap at all. None is the default, and None means never.

    `snap_only_when` lets a host gate snapping on its own UI state — Eclipse's
    capitals combo — without this module knowing anything about combos.
    """

    snap_max_km: Optional[float] = None
    snap_only_when: bool = True

    def __post_init__(self):
        """Reject a bound that is not a real distance.

        `snap_to_capital` guards only `max_km <= 0`, so `float('inf')` snapped
        from anywhere, and `float('nan')` did too — `km < best.km` is False
        against NaN, so the comparison that is supposed to reject the capital
        accepts it. Both reinstate exactly the unbounded snapping this type
        exists to make inexpressible: a mid-ocean click became a chart for a
        capital 2000 km away, that capital's timezone included, silently.

        The invariant is worth more than the convenience, so this raises rather
        than clamping: a caller asking to snap from any distance has a bug, and
        a silently-clamped bound would hide it.
        """
        if self.snap_max_km is None:
            return
        import math
        if not math.isfinite(self.snap_max_km) or self.snap_max_km <= 0:
            raise ValueError(
                f"snap_max_km must be a positive finite distance in km, or "
                f"None to never snap; got {self.snap_max_km!r}")


@dataclass(frozen=True)
class RoutedSelection:
    """What the click MEANS: the answer the host, the component's own display
    and every add-on all read. One object, so they cannot diverge.

    `snap_from` carries the pre-snap click point as structured data rather
    than as prose inside `note`, because bounded snapping is the move most
    likely to silently relocate someone's chart, and a gate needs to assert on
    it, not parse a sentence.
    """

    lat: float
    lon: float
    tz_name: Optional[str]
    city: str
    country: str
    snapped: bool
    snap_km: Optional[float]
    snap_from: Optional[Tuple[float, float]]
    is_final: bool
    sel_gen: int
    note: str
    display: str
    #: carried through from the MapSelection (WI-4) so _on_selection_routed can
    #: tell a user pick (click/search) from a derived one (parse/load). Default
    #: keeps directly-constructed test fixtures valid.
    origin: str = "click"


def route_selection(sel: MapSelection, policy: SelectionPolicy,
                    sel_gen: int = 0) -> RoutedSelection:
    """Decide what a selection means under a host's policy. Pure.

    Snapping, when the policy allows it and a capital is within the bound:
    the point, the name, the country AND the timezone all move together to
    that capital. Moving four of the five and leaving the timezone behind is
    precisely the class of bug this replaces.

    Not snapping: the point stays exactly where the user put it, and the
    timezone is `sel.tz_name` — the clicked point's own. If that is None it
    stays None all the way to the host, which is the honest outcome and the
    only one that lets the host refuse visibly.

    `note` is always populated when a policy could have snapped, including
    when it declined. The refusal is the half users never used to be told
    about: it rides on the location label, not on stdout.
    """
    may_snap = policy.snap_max_km is not None and policy.snap_only_when
    snap = None
    if may_snap:
        snap = snap_to_capital(sel.lat, sel.lon, policy.snap_max_km)

    if snap is not None:
        note = (f"Snapped to {snap.name}, {snap.country} "
                f"({snap.km:.0f} km from your click)")
        return RoutedSelection(
            lat=snap.lat,
            lon=snap.lon,
            tz_name=snap.tz,
            city=clamp_label(snap.name),
            country=clamp_label(snap.country),
            snapped=True,
            snap_km=snap.km,
            snap_from=(sel.lat, sel.lon),
            is_final=sel.is_final,
            sel_gen=sel_gen,
            note=note,
            display=format_place_line(snap.name, snap.country,
                                      snap.lat, snap.lon),
            origin=sel.origin,
        )

    city, country = sel.city, sel.country
    if not (city or country):
        # The clicked point's OWN timezone supplies the country. Offline and
        # instant; deliberately vague when it has to be, because a confidently
        # wrong "Toronto, Canada" over Indiana is worse than no city at all.
        place = resolve_place(sel.lat, sel.lon, sel.tz_name)
        city, country = place.city, place.country

    # Sanitise at the source (before clamping), so RoutedSelection.city /
    # .country / .display are all clean and no host has to re-clean. The
    # geocoder-sourced fields are where 'Ermont,' comes from; resolve_place's
    # output is already clean, so this is idempotent on that path. The snap
    # path uses the curated WORLD_CAPITALS spelling and needs no cleaning.
    city = clean_place_parts(city or "")
    country = clean_place_parts(country or "")

    note = ""
    if may_snap:
        note = (f"No capital within {policy.snap_max_km:.0f} km — "
                f"using the point you clicked")
        if sel.tz_name is None:
            note += " (timezone unresolved)"
    elif sel.tz_name is None:
        note = "Timezone unresolved for this point"

    return RoutedSelection(
        lat=sel.lat,
        lon=sel.lon,
        tz_name=sel.tz_name,
        city=clamp_label(city or ""),
        country=clamp_label(country or ""),
        snapped=False,
        snap_km=None,
        snap_from=None,
        is_final=sel.is_final,
        sel_gen=sel_gen,
        note=note,
        display=format_place_line(city, country, sel.lat, sel.lon),
        origin=sel.origin,
    )
