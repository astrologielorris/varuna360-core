# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Naming a map point, and moving a map point. One implementation, for every map.

SPEC-MAP-003. This module is the ONLY place in the app that turns a latitude
and longitude into a place name (INV-1), and the only place that snaps a click
to a capital (INV-5). Five panels host the same map widget; before this module
they each invented their own answer, which is why one gesture could be named
"Toronto" in Edit Chart, snapped to Ottawa in Lunar New Year, and shown as bare
coordinates in Transit.

Two operations, deliberately separate
-------------------------------------
`resolve_place` NAMES a point and never moves it (INV-2).
`snap_to_capital` MOVES a point and is always bounded (INV-5).

They were tangled before: Lunar New Year "named" a click by relocating it to
the nearest capital at any distance and adopting that capital's timezone, so a
click 2000 km out to sea silently became a chart for somewhere else. Naming and
relocating are different acts with different consequences, and a caller has to
ask for the second one explicitly, with a distance it is willing to move.

Why a name can be refused
-------------------------
The instant placeholder used to be "the nearest world capital", scored with a
flat squared-degree distance and with no ceiling at all. Two consequences, both
user-reported:

  * no cos(latitude) term on the longitude leg, so at 40 N a degree of
    longitude was over-weighted by ~30 %, and the +/-180 meridian did not wrap;
  * more fundamentally, a nearest-capital search over ~230 points ALWAYS has an
    answer, however far away it is. Clicking Fort Wayne, Indiana named the
    point "Toronto, Canada" (700 km); clicking Oklahoma named it "Mexico City"
    (1500 km).

Distance alone did not finish the job. A click can be within 35 km of a city
and still not be in it, because cities sit on borders: Nice is 13 km from
Monaco, Johor Bahru is a bridge from Singapore, and Vatican City is inside
Rome. So a candidate must ALSO agree with the country the point's own timezone
puts it in (INV-4). The timezone polygon is ground truth about the clicked
point; proximity is only a guess about it.

An empty answer is a correct answer. Open ocean, an `Etc/GMT*` offset zone, or
a country we cannot confirm all yield "", and the caller shows coordinates.
Coordinates are honest; a confident wrong city is the bug this module exists to
prevent.
"""

from typing import Dict, NamedTuple, Optional, Tuple

__all__ = [
    "CAPITAL_HIT_KM", "MAX_LABEL_CHARS",
    "PlaceName", "CapitalSnap",
    "haversine_km", "nearest_capital", "country_from_timezone",
    "resolve_place", "snap_to_capital", "clamp_label",
    "instant_place_name",
]

#: A click within this many km of a known city's centre MAY be that city --
#: necessary, not sufficient; the country must agree too (INV-4).
#: Sized to a large metropolitan area (greater London is ~40 km across, greater
#: Tokyo ~60 km) and no larger: beyond it the name is a guess, and a guess is
#: exactly what this module refuses to print.
CAPITAL_HIT_KM = 35.0

#: Hard ceiling on any name that reaches a painting path (INV-8). The map label
#: is rasterised into a QPixmap sized from the string, and geocoder output is
#: external and unbounded: a 1000-character reply measured 10.86 s and a
#: 16710 px pixmap, and longer input fails rasterisation outright. No real place
#: name approaches this, so truncation here only ever fires on bad data.
MAX_LABEL_CHARS = 120


class PlaceName(NamedTuple):
    """What a point is called. `city` may be empty; `country` may be empty."""
    city: str
    country: str

    @property
    def is_empty(self) -> bool:
        return not (self.city or self.country)

    def display(self) -> str:
        """One line, or "" when nothing is known. Never a stray comma."""
        if self.city and self.country:
            return f"{self.city}, {self.country}"
        return self.city or self.country or ""


class CapitalSnap(NamedTuple):
    """A capital a click was moved to. `km` is how far the user was moved."""
    name: str
    country: str
    lat: float
    lon: float
    tz: str
    km: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance. Correct at every latitude and across +/-180."""
    import math
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return 2 * R * math.asin(min(1.0, math.sqrt(a)))


# --- the capital table ------------------------------------------------------
_CAPITALS: Optional[Dict[str, dict]] = None


def _capitals() -> Dict[str, dict]:
    """The UNION of both capital tables, built once.

    Two tables exist and NEITHER is a superset (SPEC-MAP-003 RC-10):
    `core.world_capitals` has 231 entries, `tools.capitals_data` has 134, and
    six well-known cities live only in the smaller one -- Dubai, Los Angeles,
    Mumbai, New York, Sydney, Toronto. Preferring the larger table and falling
    back only on ImportError, as this module first did, made those six
    unreachable: a click on New York was answered "United States".

    Union, with the larger table winning on a name collision, because its
    coordinates are the curated ones. Neither table is authoritative on its own
    and the merge is the only form that loses nothing.
    """
    global _CAPITALS
    if _CAPITALS is not None:
        return _CAPITALS
    merged: Dict[str, dict] = {}
    for module, attr in (("tools.capitals_data", "WORLD_CAPITALS"),
                         ("core.world_capitals", "WORLD_CAPITALS")):
        try:
            table = getattr(__import__(module, fromlist=[attr]), attr)
        except Exception:
            continue
        for name, data in table.items():
            merged[name] = data          # later module wins: core over tools
    _CAPITALS = merged
    return merged


def capital_table() -> Dict[str, dict]:
    """The one city table, for callers going the OTHER way: name -> coordinates.

    Search, autocomplete and capital dropdowns are not naming a point, so
    INV-1 does not govern them -- but they were reading a single table with an
    ImportError fallback, which is the same omission that made six cities
    unreachable for naming. Typing "New York" missed the local tier and fell
    through to the network, and offline it found nothing at all. One table, both
    directions.
    """
    return _capitals()


def nearest_capital(lat: float, lon: float) -> Tuple[str, str, float]:
    """(name, country, distance_km) of the closest known city, or ("", "", inf).

    Naming callers must NOT use this directly -- it is unbounded by nature and
    always has an answer. Use `resolve_place`. It is public because
    `snap_to_capital` and its tests need it.
    """
    best_name, best_country, best_km = "", "", float("inf")
    for name, data in _capitals().items():
        km = haversine_km(lat, lon, data.get("lat", 0.0), data.get("lon", 0.0))
        if km < best_km:
            best_km, best_name = km, name
            best_country = data.get("country", "")
    return best_name, best_country, best_km


# --- country from the already-resolved IANA timezone ------------------------
_TZ_COUNTRY: Optional[Dict[str, str]] = None


def _tz_country_map() -> Dict[str, str]:
    """{IANA zone -> country display name}. Built once, ~420 entries.

    pytz ships the zone.tab country mapping, so this is a local table lookup,
    not a geography computation. Measured: 20.6 ms to build, 0.83 ms per call
    afterwards, and zero zones in the shipped data map to more than one country.
    """
    global _TZ_COUNTRY
    if _TZ_COUNTRY is not None:
        return _TZ_COUNTRY
    table: Dict[str, str] = {}
    try:
        import pytz
        for code, zones in pytz.country_timezones.items():
            display = pytz.country_names.get(code, code)
            for zone in zones:
                table[zone] = display
    except Exception:
        pass
    _TZ_COUNTRY = table
    return table


#: pytz's `country_names` are drawn from zone.tab and a few read as data rather
#: than as prose. These land in a birth-data form and in a chart's location
#: line, so the handful a user actually hits are given their ordinary name. Only
#: SPELLING changes here; the country is the same country, and matching happens
#: on the normalised key (`_normalise_country`), never on these strings.
#: The other awkward entries pytz ships -- "Congo (Dem. Rep.)", "Virgin Islands
#: (UK)" -- are left alone: they are unambiguous and rewriting them would be
#: invention rather than tidying.
_TZ_COUNTRY_DISPLAY = {
    "Britain (UK)": "United Kingdom",
    "Korea (South)": "South Korea",
    "Korea (North)": "North Korea",
    "Myanmar (Burma)": "Myanmar",
    "Eswatini (Swaziland)": "Eswatini",
    "Samoa (western)": "Samoa",
    "US minor outlying islands": "United States Minor Outlying Islands",
}


def country_from_timezone(tz_name: Optional[str]) -> str:
    """Country display name for an IANA zone, or "" when it names no country.

    `Etc/GMT+10` and friends are pure offset zones -- a click on open water gets
    one, and it must NOT be dressed up as a place.

    Only CANONICAL zone names map, which is all that is needed: the name comes
    from `timezonefinder`, which emits canonical zones. A deprecated alias
    (`US/Eastern`, `Asia/Calcutta`) yields "" -- vague on purpose, because the
    alternative here is guessing.

    Known limit: pytz's zone.tab gives one country per zone, so a zone shared by
    more than one territory reports the dominant one (`Europe/Belgrade` covers
    Kosovo and reports Serbia). That is a data limit, not a logic error, and it
    is a country-level imprecision rather than the cross-continent naming error
    this module was written to stop.
    """
    if not tz_name:
        return ""
    raw = _tz_country_map().get(tz_name, "")
    return _TZ_COUNTRY_DISPLAY.get(raw, raw)


# --- country-name reconciliation (INV-4) ------------------------------------
#: The capital tables and pytz spell the same country differently. Comparing
#: raw strings would reject every legitimate hit, so both sides are normalised
#: through this table first. It is DATA and it is tested.
#:
#: An unrecognised spelling normalises to itself, so an unknown pair simply
#: fails to match -- which fails the INV-4 check, which drops the city and
#: keeps the country. Failing closed is the whole point: a name we cannot
#: confirm is a name we do not print.
_COUNTRY_ALIASES = {
    "usa": "united states",
    "u.s.a.": "united states",
    "us": "united states",
    "united states of america": "united states",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "britain (uk)": "united kingdom",
    "great britain": "united kingdom",
    "england": "united kingdom",
    "uae": "united arab emirates",
    "russia": "russian federation",
    "south korea": "korea (south)",
    "north korea": "korea (north)",
    "vatican": "holy see (vatican city state)",
    "vatican city": "holy see (vatican city state)",
    "czech republic": "czechia",
    "burma": "myanmar",
    "ivory coast": "cote d'ivoire",
    "cape verde": "cabo verde",
    "swaziland": "eswatini",
    "macedonia": "north macedonia",
    "holland": "netherlands",
    "east timor": "timor-leste",
    "congo (drc)": "congo (the democratic republic of the)",
    "dr congo": "congo (the democratic republic of the)",
    "tanzania": "tanzania, united republic of",
    "bolivia": "bolivia (plurinational state of)",
    "venezuela": "venezuela (bolivarian republic of)",
    "iran": "iran (islamic republic of)",
    "syria": "syrian arab republic",
    "laos": "lao people's democratic republic",
    "moldova": "moldova, republic of",
    "brunei": "brunei darussalam",
    "palestine": "palestine, state of",
    "taiwan": "taiwan, province of china",
}


def _normalise_country(name: str) -> str:
    key = (name or "").strip().lower()
    return _COUNTRY_ALIASES.get(key, key)


def _same_country(a: str, b: str) -> bool:
    """True only when both name the same country. Empty on either side is False.

    Deliberately strict. `_normalise_country` maps an unknown spelling to
    itself, so a pair this table does not cover returns False, the city is
    dropped and the country survives -- the safe direction.
    """
    if not a or not b:
        return False
    return _normalise_country(a) == _normalise_country(b)


def clamp_label(text: str) -> str:
    """Truncate any externally-sourced name before it can size a pixmap (INV-8)."""
    text = (text or "").strip()
    if len(text) <= MAX_LABEL_CHARS:
        return text
    return text[:MAX_LABEL_CHARS - 1].rstrip() + "…"


def clean_place_parts(*parts: object) -> str:
    """Join location parts into one label, robust to ANY stray-comma mess.

    Splits every part on commas, strips each token, drops the empties, rejoins
    with ', '. A geocoder that hands back 'Ermont,' or 'City, ,' or a doubled
    'City, , Country' is cleaned to 'City, Country'; a legitimate multi-part
    name ('Washington, D.C.') is preserved, because the rejoin is idempotent on
    it. Non-string parts (None, a dict-shaped birth_data['location']) are
    ignored, yielding '' so a caller shows coordinates instead of a literal
    object.

    This is the SINGLE home for stray-comma sanitisation. It used to live only
    in `transit_utils.format_place`, so only Eclipse (which called it) cleaned
    its selection while Lunar and Birth Finder assigned the raw field — the
    exact host-local divergence SPEC-MAP-004 INV-5 exists to retire.
    `route_selection` now calls this per field, so RoutedSelection.city /
    .country / .display are clean at the source and no host re-sanitises;
    `transit_utils.format_place` delegates here (td-4po7, F4).
    """
    tokens = []
    for part in parts:
        if isinstance(part, str):
            for piece in part.split(','):
                piece = piece.strip()
                if piece:
                    tokens.append(piece)
    return ", ".join(tokens)


def resolve_place(lat: float, lon: float,
                  tz_name: Optional[str] = None) -> PlaceName:
    """What this point is called, offline and instantly. Never moves the point.

    Precedence:
      1. a known city within CAPITAL_HIT_KM WHOSE COUNTRY AGREES with the
         country of the point's own timezone -- the click really is on it;
      2. the country of the point's IANA timezone (exact, offline);
      3. nothing, and the caller shows coordinates.

    Step 1's country test is not belt-and-braces, it is load-bearing. Without
    it, measured: Nice becomes "Monaco, Monaco", Johor Bahru becomes
    "Singapore, Singapore" and Vatican City becomes "Rome, Italy" -- the same
    class of confident lie as naming Indiana "Toronto", just at a smaller
    radius.

    When the timezone is unknown the country cannot be confirmed, so no city is
    claimed. That is the honest outcome: without a timezone there is nothing
    here that knows which side of a border the point is on.
    """
    tz_country = country_from_timezone(tz_name)
    name, capital_country, km = nearest_capital(lat, lon)
    if name and km <= CAPITAL_HIT_KM and _same_country(capital_country, tz_country):
        # The tz country is the one displayed: it is derived from the clicked
        # point, where the table's spelling is a property of the table.
        return PlaceName(clamp_label(name), clamp_label(tz_country))
    return PlaceName("", clamp_label(tz_country))


def snap_to_capital(lat: float, lon: float,
                    max_km: float) -> Optional[CapitalSnap]:
    """Move a click to the nearest capital, or refuse (INV-5).

    Returns None when nothing is within `max_km`. There is no unbounded form
    and `max_km` has no default: a caller states how far it is willing to move
    the user, or it does not snap at all. The unbounded version of this is what
    let a mid-ocean click in Lunar New Year silently become a chart for a
    capital thousands of km away, timezone included.
    """
    if max_km <= 0:
        return None
    best: Optional[CapitalSnap] = None
    for name, data in _capitals().items():
        km = haversine_km(lat, lon, data.get("lat", 0.0), data.get("lon", 0.0))
        if best is None or km < best.km:
            best = CapitalSnap(name, data.get("country", ""),
                               data.get("lat", 0.0), data.get("lon", 0.0),
                               data.get("tz", "") or data.get("timezone", ""),
                               km)
    if best is None or best.km > max_km:
        return None
    return best


def format_place_line(city: str, country: str,
                      lat: Optional[float] = None,
                      lon: Optional[float] = None) -> str:
    """One display line for a named point, with coordinates as the LAST resort.

    Exists because three separate consumers had independently written

        f"{city}, {country}" if city else f"({lat:.2f}, {lon:.2f})"

    which throws the country away whenever the city is unknown. That was
    harmless while the naming layer always invented a city; once naming started
    correctly returning country-only for a click outside any city centre, every
    one of those sites began showing raw coordinates for ordinary clicks.

    Order: "City, Country", else "Country", else "City", else coordinates,
    else "". Never a stray comma, never coordinates when a country is known.
    """
    line = PlaceName(clamp_label(city or ""), clamp_label(country or "")).display()
    if line:
        return line
    if lat is None or lon is None:
        return ""
    return f"({lat:.2f}, {lon:.2f})"


def instant_place_name(lat: float, lon: float,
                       tz_name: Optional[str] = None) -> Tuple[str, str]:
    """Back-compatible tuple form of `resolve_place`. Prefer `resolve_place`."""
    return tuple(resolve_place(lat, lon, tz_name))  # type: ignore[return-value]
