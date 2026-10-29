# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Stored chart facts for display (SPEC-FIND-005 §3.5, §3.6). Qt-free.

Two readers over what the extractors already stored, never computing
(INV-6: no extractor ``extract``, no libaditya):

- ``chart_facts``: one birth moment's facts as the inspector's sections;
- ``column_values``: the extra result columns (all placements, column groups)
  for many moments.

Values are labelled through ``taxonomy.label`` in the search system's mode and
naming, as every other Find Chart label.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.chart_search import taxonomy
from core.chart_search.extractors import registry
from core.chart_search.extractors.base import Row
from core.chart_search.extractors.subjects import BODIES, CHART, CUSPS, GRAHAS, LAGNA, OUTER
from core.chart_search.stamp import computation_stamp
from core.chart_search.store import ComputationState, MomentId, StoreReader
from core.chart_search.system import SearchSystem
from core.chart_search.taxonomy import Naming

if TYPE_CHECKING:  # typing only
    from core.chart_search.search import Filter

#: The three placements shown by default (the table's Asc, Sun, Moon).
DEFAULT_PLACEMENTS: tuple[str, ...] = (LAGNA, "Sun", "Moon")
#: Every placement PLACEMENTS ALL shows: the Ascendant, the nine grahas, the
#: outer planets (Earth carries only Human Design gates).
ALL_PLACEMENTS: tuple[str, ...] = BODIES
#: The placements ALL adds after Asc, Sun, Moon.
EXTRA_PLACEMENTS: tuple[str, ...] = tuple(b for b in BODIES if b not in DEFAULT_PLACEMENTS)

SHORT_BODY = {
    LAGNA: "Asc",
    "Mercury": "Merc",
    "Jupiter": "Jup",
    "Venus": "Ven",
    "Saturn": "Sat",
    "Uranus": "Ura",
    "Neptune": "Nep",
    "Pluto": "Plu",
}

D1 = "D1"
D9 = "D9"
NOT_STORED = "Not stored"


def short_body(subject: str) -> str:
    return SHORT_BODY.get(subject, subject)


def _label(property_name: str, value, system: SearchSystem, naming: Naming) -> str:
    spec = taxonomy.catalogue()[property_name]
    try:
        return taxonomy.label(spec, value, system.mode, naming)
    except (KeyError, IndexError, ValueError):
        return str(value)


def _state_label(value: str) -> str:
    """Avastha engine codes read as words (``shamed`` -> ``Shamed``)."""
    return value[:1].upper() + value[1:] if value else value


def _cause_text(row: Row) -> str:
    """One Lajjitaadi row in full: "Shamed by Saturn (aspect)"."""
    text = _state_label(str(row.value))
    if row.q1:
        text += f" by {row.q1}"
    if row.q2:
        text += f" ({row.q2})"
    return text


# --------------------------------------------------------------- the reads


def _pid(store: StoreReader, extractor_id: str, system: SearchSystem):
    return store.projection_id(registry.get(extractor_id).projection(system))


def _rows(
    store: StoreReader,
    system: SearchSystem,
    extractor_ids: Iterable[str],
    moment_ids: frozenset[MomentId],
    *,
    position_vargas: tuple[str, ...] | None = None,
) -> tuple[
    dict[str, dict[MomentId, tuple[Row, ...]]],
    dict[str, dict[MomentId, ComputationState]],
]:
    """Per extractor: the stored rows of each moment with an ``ok``
    computation at its current version, and every moment's computation state
    at that version (absent = not computed)."""
    rows: dict[str, dict[MomentId, tuple[Row, ...]]] = {}
    states: dict[str, dict[MomentId, ComputationState]] = {}
    for eid in dict.fromkeys(extractor_ids):
        extractor = registry.get(eid)
        pid = _pid(store, eid, system)
        if pid is None or not moment_ids:
            rows[eid], states[eid] = {}, {}
            continue
        states[eid] = store.states(pid, extractor.version, moment_ids)
        ok = frozenset(mid for mid, st in states[eid].items() if st.ok)
        if not ok:
            rows[eid] = {}
        elif eid == "positions" and position_vargas is not None:
            rows[eid] = store.moment_rows(pid, ok, property_name="sign", q1_values=position_vargas)
        else:
            rows[eid] = store.moment_rows(pid, ok)
    return rows, states


def _index(rows: Sequence[Row], prop: str, q1: str | None = None) -> dict[str, list[Row]]:
    out: dict[str, list[Row]] = {}
    for row in rows:
        if row.property == prop and (q1 is None or row.q1 == q1):
            out.setdefault(row.subject, []).append(row)
    return out


# --------------------------------------------------------------- inspector


@dataclass(frozen=True)
class FactRow:
    cells: tuple[str, ...]
    retrograde: bool = False
    #: The full stored detail behind a summarised cell (Lajjitaadi causes:
    #: "Shamed by Saturn (aspect)"), for the tooltip and JSON.
    details: tuple[str, ...] = ()


#: Computation states (SPEC-FIND-005 §3.6). An extractor is one of the
#: first four for a moment; a section whose extractors differ is PARTIAL.
COMPUTED, MISSING, FAILED, STALE, PARTIAL = (
    "computed",
    "missing",
    "failed",
    "stale",
    "partial",
)


@dataclass(frozen=True)
class OwnerState:
    """One extractor's computation for the moment: ``state`` is computed,
    missing (nothing at its current version), failed (``error`` is the
    stored failure text) or stale (ok, stamped by another app version)."""

    extractor_id: str
    state: str
    error: str = ""


@dataclass(frozen=True)
class FactSection:
    """One inspector section. ``owners``: each extractor it reads and its
    state; ``state`` summarises them (all equal: that state; mixed:
    ``partial``). Stored rows always show whatever the state; the panel
    offers COMPUTE for missing owners, RETRY for failed, RECOMPUTE for stale."""

    key: str
    title: str
    subtitle: str
    owners: tuple[OwnerState, ...]
    columns: tuple[str, ...]
    rows: tuple[FactRow, ...]

    @property
    def extractors(self) -> tuple[str, ...]:
        return tuple(o.extractor_id for o in self.owners)

    @property
    def state(self) -> str:
        states = {o.state for o in self.owners}
        return states.pop() if len(states) == 1 else PARTIAL

    @property
    def computed(self) -> bool:
        """Every owner has rows stored (possibly by another app version)."""
        return all(o.state in (COMPUTED, STALE) for o in self.owners)

    def owners_in(self, state: str) -> tuple[str, ...]:
        return tuple(o.extractor_id for o in self.owners if o.state == state)


@dataclass(frozen=True)
class ChartFacts:
    sections: tuple[FactSection, ...]
    #: D1 sign labels of Ascendant, Sun, Moon ("" when not computed).
    cards: tuple[tuple[str, str], ...]
    #: The Glance Chart (SPEC-FIND-007 §6): ``(body, sign_index, retrograde)``
    #: per body with a stored D1 sign, in ``BODIES`` order; ``sign_index`` =
    #: stored value - 1 (0..11, never re-mapped by mode). The Ascendant is
    #: included (drawn as the marker); its retrograde is always False.
    glance: tuple[tuple[str, int, bool], ...] = ()
    #: The 12 sign labels in the search naming (index 0 = ordinal 1).
    sign_labels: tuple[str, ...] = ()
    #: The rows already read for the sections, per extractor (the centre
    #: resolver reads them; no new store query, SPEC-FIND-007 INV-1).
    stored: Mapping[str, tuple[Row, ...]] = field(default_factory=dict)
    #: Each extractor's computation state for the moment.
    owner_states: Mapping[str, OwnerState] = field(default_factory=dict)

    def section(self, key: str) -> FactSection:
        return next(s for s in self.sections if s.key == key)


SECTION_ORDER = (
    "placements",
    "navamsa",
    "nakshatras",
    "dignity",
    "avasthas",
    "shayanadi",
    "retinue",
    "cards_of_truth",
    "human_design",
)

_SECTION_EXTRACTORS: Mapping[str, tuple[str, ...]] = {
    "placements": ("positions", "whole_sign"),
    "navamsa": ("positions",),
    "nakshatras": ("nakshatras",),
    "dignity": ("dignity",),
    "avasthas": ("avasthas",),
    "shayanadi": ("shayanadi",),
    "retinue": ("retinue",),
    "cards_of_truth": ("cards_of_truth",),
    "human_design": ("human_design",),
}


def chart_facts(
    store: StoreReader, system: SearchSystem, naming: Naming, moment_id: MomentId
) -> ChartFacts:
    """One moment's stored facts in ``system``, as the inspector's sections."""
    ids = frozenset({moment_id})
    every = {eid for eids in _SECTION_EXTRACTORS.values() for eid in eids}
    rows, states = _rows(store, system, every, ids)
    running = computation_stamp()

    def got(eid: str) -> tuple[Row, ...]:
        return rows[eid].get(moment_id, ())

    def owner(eid: str) -> OwnerState:
        st = states[eid].get(moment_id)
        if st is None:
            return OwnerState(eid, MISSING)
        if not st.ok:
            return OwnerState(eid, FAILED, st.error or "")
        return OwnerState(eid, STALE if st.app_version != running else COMPUTED)

    def done(*eids: str) -> bool:
        return all(owner(eid).state in (COMPUTED, STALE) for eid in eids)

    def lab(prop, value):
        return _label(prop, value, system, naming)

    pos = got("positions")
    signs = _index(pos, "sign", D1)
    navamsa = _index(pos, "sign", D9)
    retro = {s: bool(int(r[0].value)) for s, r in _index(pos, "retrograde").items()}
    houses = _index(got("whole_sign"), "whole_sign_house")

    def sign_of(index, subject):
        r = index.get(subject)
        return lab("sign", r[0].value) if r else ""

    placements = tuple(
        FactRow(
            (
                short_body(b),
                sign_of(signs, b) or NOT_STORED,
                str(houses[b][0].value) if b in houses else "·",
            ),
            retro.get(b, False) and b != LAGNA,
        )
        # Every body with a stored sign or house shows (D-15): a valid Whole
        # Sign row stays visible while Positions is missing, and the reverse.
        for b in ALL_PLACEMENTS
        if b in signs or b in houses or done("positions")
    )
    nav = tuple(
        FactRow((short_body(b), sign_of(navamsa, b)), retro.get(b, False) and b != LAGNA)
        for b in ALL_PLACEMENTS
        if b in navamsa
    )
    naks = _index(got("nakshatras"), "nakshatra")
    nak_rows = tuple(
        FactRow((short_body(b), lab("nakshatra", naks[b][0].value), naks[b][0].q1 or ""))
        for b in ALL_PLACEMENTS
        if b in naks
    )
    dig = _index(got("dignity"), "dignity")
    dig_rows = tuple(
        FactRow((short_body(b), lab("dignity", dig[b][0].value)))
        for b in GRAHAS
        if b in dig
    )
    ava = got("avasthas")
    bal, jag, dee = (_index(ava, p) for p in ("baladi", "jagradadi", "deeptadi"))
    laj = _index(ava, "lajjitaadi")
    ava_rows = []
    for b in GRAHAS:
        if b not in bal and b not in laj:
            continue
        causes = ", ".join(dict.fromkeys(_state_label(str(r.value)) for r in laj.get(b, ())))
        details = tuple(_cause_text(r) for r in laj.get(b, ()))
        ava_rows.append(
            FactRow(
                (
                    short_body(b),
                    str(bal[b][0].value) if b in bal else "",
                    str(jag[b][0].value) if b in jag else "",
                    str(dee[b][0].value) if b in dee else "",
                    causes,
                ),
                details=details,
            )
        )
    shay = _index(got("shayanadi"), "shayanadi")
    shay_rows = tuple(FactRow((short_body(b), str(shay[b][0].value))) for b in GRAHAS if b in shay)
    ret = got("retinue")
    trim, hora = _index(ret, "trimsamsa_being"), _index(ret, "hora_being")
    ret_rows = tuple(
        FactRow(
            (
                short_body(b),
                str(trim[b][0].value) if b in trim else "",
                str(hora[b][0].value) if b in hora else "",
            )
        )
        for b in ALL_PLACEMENTS
        if b in trim or b in hora
    )
    cot = got("cards_of_truth")
    birth = _index(cot, "birth_card").get(CHART)
    cards = _index(cot, "card")
    cot_rows = []
    if birth:
        cot_rows.append(FactRow(("Birth card", lab("birth_card", birth[0].value))))
    for position, found in cards.items():
        cot_rows.append(FactRow((f"{position} card", lab("card", found[0].value))))
    hd = got("human_design")
    hd_chart = {r.property: r for r in hd if r.subject == CHART and r.q1 is None}
    hd_rows = [
        FactRow((title, lab(prop, hd_chart[prop].value)))
        for prop, title in (
            ("hd_type", "Type"),
            ("authority", "Authority"),
            ("definition", "Definition"),
            ("profile", "Profile"),
            ("incarnation_cross", "Incarnation cross"),
        )
        if prop in hd_chart
    ]
    channels = sorted(
        str(r.value) for r in hd if r.property == "channel" and r.q1 == "both"
    )
    if channels:
        hd_rows.append(FactRow(("Channels", ", ".join(channels))))
    defined = sorted(
        str(r.value)
        for r in hd
        if r.property == "center" and r.q1 == "both" and r.q2 == "defined"
    )
    if defined:
        hd_rows.append(FactRow(("Defined centers", ", ".join(defined))))

    def section(key, title, subtitle, columns, body_rows):
        owners = tuple(owner(eid) for eid in _SECTION_EXTRACTORS[key])
        return FactSection(key, title, subtitle, owners, columns, tuple(body_rows))

    sections = (
        section("placements", "Placements", "D1 · Whole sign", ("Body", "D1 sign", "House"), placements),
        section("navamsa", "Navamsa", "D9", ("Body", "D9 sign"), nav),
        section("nakshatras", "Nakshatras", "Pada", ("Body", "Nakshatra", "Pada"), nak_rows),
        section("dignity", "Dignity", f"{len(dig_rows)} bodies", ("Body", "Dignity"), dig_rows),
        section(
            "avasthas",
            "Avasthas",
            "4 families",
            ("Body", "Baladi", "Jagradadi", "Deeptadi", "Lajjitaadi"),
            ava_rows,
        ),
        section("shayanadi", "Shayanadi", "", ("Body", "Shayanadi"), shay_rows),
        section(
            "retinue",
            "Retinue beings",
            "Trimsamsa · Hora",
            ("Body", "Trimsamsa", "Hora"),
            ret_rows,
        ),
        section("cards_of_truth", "Cards of Truth", "", ("Position", "Card"), cot_rows),
        section("human_design", "Human Design", "", ("Fact", "Value"), hd_rows),
    )
    return ChartFacts(
        sections,
        tuple((b, sign_of(signs, b)) for b in DEFAULT_PLACEMENTS),
        glance_bodies(signs, retro),
        sign_labels(system, naming),
        {eid: got(eid) for eid in every},
        {eid: owner(eid) for eid in every},
    )


# ------------------------------------------------------------ glance chart


def sign_labels(system: SearchSystem, naming: Naming) -> tuple[str, ...]:
    """The 12 sign labels (ordinals 1..12) in the search naming: available
    without any chart facts, so the grid labels draw while loading."""
    return tuple(_label("sign", v, system, naming) for v in range(1, 13))


def glance_bodies(
    signs: Mapping[str, list[Row]], retro: Mapping[str, bool]
) -> tuple[tuple[str, int, bool], ...]:
    """``(body, sign_index, retrograde)`` from the D1 sign rows; a value out
    of 1..12 is not drawn (never invented, INV-5)."""
    out = []
    for b in BODIES:
        found = signs.get(b)
        if not found:
            continue
        try:
            index = int(found[0].value) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < 12:
            out.append((b, index, bool(retro.get(b, False)) and b != LAGNA))
    return tuple(out)


#: The centre's categories (SPEC-FIND-007 §2.1), one design each.
SIGN, HOUSE, CUSP, MOTION, NAKSHATRA, DIGNITY, AVASTHA, SHAYANADI, RETINUE, HUMAN_DESIGN, CARDS = (
    "sign", "house", "cusp", "motion", "nakshatra", "dignity", "avastha",
    "shayanadi", "retinue", "human_design", "cards_of_truth",
)
CATEGORIES = (SIGN, HOUSE, CUSP, MOTION, NAKSHATRA, DIGNITY, AVASTHA, SHAYANADI,
              RETINUE, HUMAN_DESIGN, CARDS)
#: Centre states: the stored value is shown, the owner has nothing for this
#: moment, its computation failed, or it is computed but holds no such row.
OK, NOT_COMPUTED, CENTRE_FAILED, NOT_FOUND = "ok", "not_computed", "failed", "not_stored"

_CATEGORY_OF = {
    "whole_sign_house": HOUSE,
    "cusp_house": HOUSE,
    "cusp_conjunction": HOUSE,
    "retrograde": MOTION,
    "nakshatra": NAKSHATRA,
    "dignity": DIGNITY,
    "baladi": AVASTHA,
    "jagradadi": AVASTHA,
    "deeptadi": AVASTHA,
    "lajjitaadi": AVASTHA,
    "shayanadi": SHAYANADI,
    "trimsamsa_being": RETINUE,
    "hora_being": RETINUE,
    "birth_card": CARDS,
    "card": CARDS,
    "in_card": CARDS,
}
_HD_PROPS = ("gate", "channel", "center", "hd_type", "authority", "definition",
             "profile", "incarnation_cross")
_FIXED_DETAIL = {
    "whole_sign_house": "Whole-sign house",
    "cusp_house": "Cusp house",
    "cusp_conjunction": "Cusp conjunction",
    "baladi": "Baladi",
    "jagradadi": "Jagradadi",
    "deeptadi": "Deeptadi",
    "lajjitaadi": "Lajjitaadi",
    "trimsamsa_being": "Trimsamsa being",
    "hora_being": "Hora being",
    "birth_card": "Birth card",
    "channel": "Channel",
    "hd_type": "Type",
    "authority": "Authority",
    "definition": "Definition",
    "profile": "Profile",
    "incarnation_cross": "Incarnation cross",
}
#: HD side in the funnel's wording (commit 78a5b8ce0): Conscious first.
HD_SIDE = {"personality": "Conscious", "design": "Unconscious", "both": "Conscious and unconscious"}
_SUITS = {"H": "\u2665", "D": "\u2666", "C": "\u2663", "S": "\u2660"}


@dataclass(frozen=True)
class Centre:
    """What the Glance Chart's centre shows for the first funnel filter.

    ``body``: the matched subject (an "any" filter names the one that
    matched, ``matched_any``); ``None`` for chart-level facts. ``value``:
    the stored value's label in the search naming (the hero). ``detail``:
    the small line (pada, scheme, side, varga). ``card``: ``(rank, suit
    symbol)`` for a playing card. ``state``: ok / not_computed / failed /
    not_stored."""

    category: str
    body: str | None
    value: str
    detail: str = ""
    state: str = OK
    matched_any: bool = False
    card: tuple[str, str] | None = None
    #: The cusp's name ("Ascendant") for the cusp category's small line.
    cusp: str = ""


def card_parts(code: str) -> tuple[str, str] | None:
    """``"3S"`` -> ``("3", "\u2660")``; ``None`` for a code that is no suit
    card (the joker)."""
    code = str(code)
    if len(code) < 2 or code[-1] not in _SUITS:
        return None
    return code[:-1].replace("T", "10"), _SUITS[code[-1]]


def centre_category(property_name: str, subjects: tuple[str, ...] | None) -> str:
    if property_name == "sign":
        cusps = subjects is not None and all(s in CUSPS for s in subjects)
        return CUSP if cusps else SIGN
    if property_name in _HD_PROPS:
        return HUMAN_DESIGN
    return _CATEGORY_OF.get(property_name, SIGN)


def _match(row: Row, resolved) -> bool:
    if row.property != resolved.spec.name:
        return False
    if resolved.subjects is not None and row.subject not in resolved.subjects:
        return False
    if resolved.value is not None and str(row.value) != str(resolved.value):
        return False
    if resolved.q1 is not None and str(row.q1) != str(resolved.q1):
        return False
    return resolved.q2 is None or str(row.q2) == str(resolved.q2)


def _order(subject: str) -> int:
    return BODIES.index(subject) if subject in BODIES else len(BODIES)


def resolve_centre(
    chart: ChartFacts | None,
    flt: Filter | None,
    system: SearchSystem,
    naming: Naming,
) -> Centre | None:
    """The centre for ``flt`` (the first funnel filter) on ``chart``, from
    the rows already loaded; ``None`` without a filter (empty centre) or for
    a filter that does not resolve. ``chart is None`` (facts loading): the
    category with an empty value and state ok, so the design shows at once."""
    if flt is None:
        return None
    from core.chart_search import search  # local: search imports this module's peers

    try:
        resolved = search.resolve(flt)
    except Exception:  # noqa: BLE001 - an invalid filter draws no centre
        return None
    spec = resolved.spec
    category = centre_category(spec.name, resolved.subjects)
    one = resolved.subjects[0] if resolved.subjects and len(resolved.subjects) == 1 else None
    if chart is None:
        return Centre(category, one if one != CHART else None, "", state=OK)
    eid = resolved.extractor.id
    owner = chart.owner_states.get(eid)
    rows = tuple(chart.stored.get(eid, ()))
    matched = sorted((r for r in rows if _match(r, resolved)), key=lambda r: _order(r.subject))
    row = matched[0] if matched else None
    if row is None:
        # Not matched (OR'd tokens, a stale result): the chart's own stored
        # value for that subject and property, never a paraphrase.
        loose = sorted(
            (r for r in rows if r.property == spec.name
             and (resolved.subjects is None or r.subject in resolved.subjects)
             and (spec.name != "sign" or r.q1 == resolved.q1)),
            key=lambda r: _order(r.subject),
        )
        row = loose[0] if loose and one is not None else None
    if row is None:
        state = NOT_FOUND
        if owner is None or owner.state == MISSING:
            state = NOT_COMPUTED
        elif owner.state == FAILED:
            state = CENTRE_FAILED
        body = one if one not in (None, CHART) and spec.name != "card" else None
        return Centre(category, body, "", "", state, cusp=one if category == CUSP else "")
    any_body = resolved.subjects is None or len(resolved.subjects) > 1
    value = _label(spec.name, row.value, system, naming)
    detail = _FIXED_DETAIL.get(spec.name, "")
    body: str | None = row.subject if row.subject != CHART else None
    card = None
    cusp = ""
    if spec.name == "sign":
        if row.q1 and row.q1 != D1:
            detail = str(row.q1)
        if category == CUSP:
            cusp, body = row.subject, None
    elif spec.name == "nakshatra":
        detail = f"pada {row.q1}" if row.q1 else ""
    elif spec.name == "gate":
        value = f"{row.value}.{row.q2}" if row.q2 else str(row.value)
        detail = f"Gate · {HD_SIDE.get(str(row.q1), str(row.q1 or ''))}".rstrip(" ·")
    elif spec.name == "channel":
        detail = " · ".join(p for p in ("Channel", HD_SIDE.get(str(row.q1), "")) if p)
    elif spec.name == "center":
        state_word = str(row.q2 or "").capitalize()
        side = HD_SIDE.get(str(row.q1), "")
        detail = " · ".join(p for p in ("Center", state_word, side) if p)
    elif spec.name == "lajjitaadi":
        value = _state_label(str(row.value))
        cause = " ".join(p for p in (f"by {row.q1}" if row.q1 else "",
                                      f"({row.q2})" if row.q2 else "") if p)
        detail = f"Lajjitaadi · {cause}" if cause else "Lajjitaadi"
    elif spec.name in ("card", "in_card", "birth_card"):
        card = card_parts(str(row.value))
        if spec.name == "card":
            detail, body = f"{row.subject} card", None
        elif spec.name == "in_card":
            detail = f"In card · {row.q1}" if row.q1 else "In card"
    return Centre(category, body, value, detail, OK, any_body and body is not None, card, cusp)


# ------------------------------------------------------------ result columns


@dataclass(frozen=True)
class ColumnGroup:
    key: str
    label: str
    extractors: tuple[str, ...]
    #: Short header suffix ("NAK"); chart-level groups name their own columns.
    suffix: str = ""
    #: Bodies the group's extractor stores, in display order.
    bodies: tuple[str, ...] = ALL_PLACEMENTS
    #: Chart-level columns: (key, header).
    chart_columns: tuple[tuple[str, str], ...] = ()


COLUMN_GROUPS: tuple[ColumnGroup, ...] = (
    ColumnGroup("nakshatras", "Nakshatras", ("nakshatras",), "NAK"),
    ColumnGroup("d9", "D9", ("positions",), "D9"),
    ColumnGroup("houses", "Houses", ("whole_sign",), "H", (*GRAHAS, *OUTER)),
    ColumnGroup("dignity", "Dignity", ("dignity",), "DIG", GRAHAS),
    ColumnGroup("avasthas", "Avasthas", ("avasthas",), "AVA", GRAHAS[:7]),
    ColumnGroup("shayanadi", "Shayanadi", ("shayanadi",), "SHAY", GRAHAS[:7]),
    ColumnGroup("retinue", "Retinue", ("retinue",), "RET"),
    ColumnGroup(
        "cards",
        "Cards",
        ("cards_of_truth",),
        "CARD",
        (*GRAHAS, *OUTER),
        (("birth_card", "Birth card"),),
    ),
    ColumnGroup(
        "human_design",
        "Human Design",
        ("human_design",),
        bodies=(),
        chart_columns=(
            ("hd_type", "Type"),
            ("authority", "Authority"),
            ("definition", "Definition"),
            ("profile", "Profile"),
            ("incarnation_cross", "Cross"),
        ),
    ),
)
GROUPS_BY_KEY: Mapping[str, ColumnGroup] = {g.key: g for g in COLUMN_GROUPS}
PLACEMENTS_KEY = "placements"


@dataclass(frozen=True)
class Column:
    key: str  # "<group>:<subject or chart key>"
    header: str
    group: str


def columns(groups: Sequence[str], all_placements: bool) -> tuple[Column, ...]:
    """The extra columns, in display order: the placements ALL adds, then
    each group's columns over the placements in view."""
    view = ALL_PLACEMENTS if all_placements else DEFAULT_PLACEMENTS
    out: list[Column] = []
    if all_placements:
        out += [
            Column(f"{PLACEMENTS_KEY}:{b}", short_body(b).upper(), PLACEMENTS_KEY)
            for b in EXTRA_PLACEMENTS
        ]
    for key in groups:
        group = GROUPS_BY_KEY.get(key)
        if group is None:
            continue
        out += [
            Column(f"{key}:{c}", header.upper(), key) for c, header in group.chart_columns
        ]
        out += [
            Column(f"{key}:{b}", f"{short_body(b)} {group.suffix}".upper(), key)
            for b in view
            if b in group.bodies
        ]
    return tuple(out)


def needed_extractors(groups: Sequence[str], all_placements: bool) -> tuple[str, ...]:
    eids: list[str] = ["positions"] if all_placements else []
    for key in groups:
        group = GROUPS_BY_KEY.get(key)
        if group is not None:
            eids += group.extractors
    return tuple(dict.fromkeys(eids))


def column_values(
    store: StoreReader,
    system: SearchSystem,
    naming: Naming,
    moment_ids: frozenset[MomentId],
    groups: Sequence[str],
    all_placements: bool,
) -> dict[MomentId, dict[str, str]]:
    """``{moment: {column key: label}}`` from stored rows only; a moment or
    a cell with nothing stored is absent (the table leaves it empty)."""
    wanted = columns(groups, all_placements)
    if not wanted or not moment_ids:
        return {}
    # Positions contains every stored varga (signs, retrograde, cusp
    # houses; no longitude). Result cells need only signs in D1 and/or D9;
    # loading the entire projection can materialize millions of unused Row
    # objects on a mode switch.
    vargas = ((D1,) if all_placements else ()) + ((D9,) if "d9" in groups else ())
    rows, _states = _rows(store, system, needed_extractors(groups, all_placements),
                         moment_ids, position_vargas=vargas)
    out: dict[MomentId, dict[str, str]] = {}
    for mid in moment_ids:
        cells: dict[str, str] = {}

        def got(eid: str) -> tuple[Row, ...]:
            return rows.get(eid, {}).get(mid, ())

        for column in wanted:
            group, _, subject = column.key.partition(":")
            text = _cell(group, subject, got, system, naming)
            if text:
                cells[column.key] = text
        if cells:
            out[mid] = cells
    return out


def _first(rows: Sequence[Row], prop: str, subject: str, q1: str | None = None) -> Row | None:
    for row in rows:
        if row.property == prop and row.subject == subject and (q1 is None or row.q1 == q1):
            return row
    return None


def _cell(group, subject, got, system, naming) -> str:
    def lab(prop, value):
        return _label(prop, value, system, naming)

    if group == PLACEMENTS_KEY:
        row = _first(got("positions"), "sign", subject, D1)
        return lab("sign", row.value) if row else ""
    if group == "d9":
        row = _first(got("positions"), "sign", subject, D9)
        return lab("sign", row.value) if row else ""
    if group == "nakshatras":
        row = _first(got("nakshatras"), "nakshatra", subject)
        return f"{lab('nakshatra', row.value)} {row.q1}".strip() if row else ""
    if group == "houses":
        row = _first(got("whole_sign"), "whole_sign_house", subject)
        return str(row.value) if row else ""
    if group == "dignity":
        row = _first(got("dignity"), "dignity", subject)
        return lab("dignity", row.value) if row else ""
    if group == "avasthas":
        parts = [_first(got("avasthas"), p, subject) for p in ("baladi", "jagradadi", "deeptadi")]
        return " · ".join(str(p.value) for p in parts if p)
    if group == "shayanadi":
        row = _first(got("shayanadi"), "shayanadi", subject)
        return str(row.value) if row else ""
    if group == "retinue":
        rows = got("retinue")
        parts = [_first(rows, p, subject) for p in ("trimsamsa_being", "hora_being")]
        return " / ".join(str(p.value) for p in parts if p)
    if group == "cards":
        rows = got("cards_of_truth")
        if subject == "birth_card":
            row = _first(rows, "birth_card", CHART)
            return lab("birth_card", row.value) if row else ""
        row = _first(rows, "card", subject)
        return lab("card", row.value) if row else ""
    if group == "human_design":
        row = next(
            (r for r in got("human_design") if r.property == subject and r.subject == CHART),
            None,
        )
        return lab(subject, row.value) if row else ""
    return ""


def group_missing_moments(
    store: StoreReader,
    system: SearchSystem,
    moment_ids: frozenset[MomentId],
    groups: Iterable[str] = tuple(g.key for g in COLUMN_GROUPS),
) -> dict[str, frozenset[MomentId]]:
    """Per group: the moments of ``moment_ids`` some extractor of the group
    has no ``ok`` computation for in ``system``. The panel counts the result
    entries on those moments for the chip's tooltip. Read only."""
    out: dict[str, frozenset[MomentId]] = {}
    for key in groups:
        missing: set[MomentId] = set()
        for eid in GROUPS_BY_KEY[key].extractors:
            pid = _pid(store, eid, system)
            ok = (
                frozenset()
                if pid is None
                else store.computed(pid, registry.get(eid).version, moment_ids)
            )
            missing |= moment_ids - ok
        out[key] = frozenset(missing)
    return out


def group_missing(
    store: StoreReader,
    system: SearchSystem,
    moment_ids: frozenset[MomentId],
    groups: Iterable[str] = tuple(g.key for g in COLUMN_GROUPS),
) -> dict[str, int]:
    """Per group: how many of ``moment_ids`` are missing (moments)."""
    return {
        k: len(v)
        for k, v in group_missing_moments(store, system, moment_ids, groups).items()
    }
