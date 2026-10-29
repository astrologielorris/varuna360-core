# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Faceted filter rows: a path of (facet, pick) steps <-> one ``search.Filter``
(filter-redesign.md §1-§4). Qt-free.

A row fills the slots of one ``Filter(subject, property, value, q1, q2)``; a
slot left unfilled is "any". ``FACETS`` is the only hand-written navigation
data: each facet says which slot its picks fill and of which properties.
What a row offers next is generated from the taxonomy (``next_facets``):

- **Compatible.** A facet is offered when one of its picks leaves at least
  one property whose subjects, value and qualifiers can all hold what the
  row has filled (Earth: only the HD gate; the Ascendant: no avastha).
- **One property per row.** Once the property is fixed, only its value (if
  still open), subject narrowing and its qualifiers are offered.
- **Qualifiers follow their property**, except a facet marked ``starts_row``
  (HD "Line" alone: any gate, line fixed).
- **Unambiguous.** Every pick names exactly one property once applied, so a
  complete row compiles to exactly one ``Filter``.

``path_of`` is the inverse on the canonical path: subject step first, then
the menu, the property's value step, then qualifier steps in declaration
order; an absent qualifier, or one at its ``Qualifier.default``, has no step
(a defaulted qualifier left any is the facet's open pick: "Any varga").
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from core.chart_search import hd_names, search, taxonomy
from core.chart_search.errors import InvariantError
from core.chart_search.extractors import human_design
from core.chart_search.extractors.cards_of_truth import POSITIONS as CARD_POSITIONS
from core.chart_search.extractors.subjects import CHART, CUSPS, LAGNA, SUBJECT_GROUPS
from core.chart_search.search import Filter
from core.chart_search.system import Mode, SearchSystem
from core.chart_search.taxonomy import Naming, PropertySpec, Qualifier, Value
from core.hd_model import STRATEGY
from core.house_systems import house_system_label


class Section(StrEnum):
    """The top-level dropdown's headers (§2)."""

    BODIES = "Bodies"
    PLACES = "Places"
    STATES = "States"
    SYSTEMS = "Systems"


class Slot(StrEnum):
    """What a facet's pick fills."""

    SUBJECT = "subject"  # a subject, or the facet's group (open pick)
    VALUE = "value"  # the property's value; also fixes the property
    QUALIFIER = "qualifier"  # one named qualifier of the fixed property
    MENU = "menu"  # opens its children (Cards of Truth, Human Design); fills nothing


class Entry(StrEnum):
    """When a facet may be offered relative to the subject slot. Two facets
    filling the same slot of one property differ only here and in label:
    Occupied (no subject yet) and Card (after a body) both fill in_card's
    value."""

    ANY = "any"
    NO_SUBJECT = "no_subject"
    WITH_SUBJECT = "with_subject"


@dataclass(frozen=True)
class Facet:
    """One row of the facet table.

    ``properties`` is the closed set this facet's slot belongs to (empty for
    a menu, and for Planets/Cusps, which narrow whatever property comes).
    ``subjects`` is a SUBJECT facet's domain, in display order; ``group`` the
    ``SUBJECT_GROUPS`` key its open pick compiles to (``None``: the open pick
    leaves the subject any). ``open_label`` labels the open pick ("Any
    planet", "Both"). A VALUE facet always has one ("Any" when unlabelled);
    a SUBJECT or QUALIFIER facet has one only when labelled. ``relabel``
    replaces the value labels (Strategy over the type values); ``name`` adds
    a short name after the value ("21 (Control)"), the value still canonical.
    ``tooltip``
    is the facet item's hover text; ``names_house_system`` appends the
    search's house system to the label (``facet_label``)."""

    key: str
    label: str
    slot: Slot
    section: Section | None = None  # None: a follow-up, or a menu child
    menu: str | None = None  # key of the menu facet this one sits under
    properties: tuple[str, ...] = ()
    qualifier: str | None = None  # QUALIFIER: the qualifier's name
    subjects: tuple[str, ...] = ()
    group: str | None = None
    entry: Entry = Entry.ANY
    starts_row: bool = False  # QUALIFIER offered before its property is fixed
    open_label: str | None = None
    relabel: Callable[[Value], str] | None = None
    name: Callable[[Value], str | None] | None = None
    tooltip: str | None = None
    names_house_system: bool = False


@dataclass(frozen=True)
class Pick:
    """What one choice fills, label-free. ``value`` ``None`` is the facet's
    open pick. ``property`` is set when the facet spans several properties
    and the value belongs to one (Avasthas: ``baladi``); else ``None``."""

    value: Value | None
    property: str | None = None


@dataclass(frozen=True)
class Choice:
    """One item of a facet's value combo."""

    pick: Pick
    label: str
    section: str | None = None  # value-combo header (Avasthas: "Baladi")


@dataclass(frozen=True)
class Step:
    """``pick`` is ``None`` for a menu, and for the last step while its value
    is not chosen yet."""

    facet: Facet
    pick: Pick | None


Path = tuple[Step, ...]


class Narrow(Protocol):
    """The store's distinct values (``StoreReader.distinct``) of ``column``
    (``subject``, ``value``, ``q1``, ``q2``) for ``property_name`` with the
    other columns fixed; ``None`` when the projection was never computed.
    ``panels.find_chart.choices.FilterChoices`` provides it."""

    def __call__(
        self, property_name: str, column: str, fixed: Mapping[str, Value]
    ) -> tuple[Value, ...] | None: ...


# ---------------------------------------------------------------- the table

#: Every facet. The only hand-written navigation data (tested: every property
#: has exactly one canonical VALUE facet, every declared qualifier one
#: QUALIFIER facet).
FACETS: tuple[Facet, ...] = (
    # Bodies: subject narrowing, offered at any point while the subject is open.
    Facet(
        "planets",
        "Planets",
        Slot.SUBJECT,
        Section.BODIES,
        subjects=SUBJECT_GROUPS["planets"],
        group="planets",
        open_label="Any planet",
    ),
    Facet(
        "cusps",
        "Cusps",
        Slot.SUBJECT,
        Section.BODIES,
        subjects=CUSPS,
        group="cusps",
        open_label="Any cusp",
    ),
    # Places
    Facet(
        "signs",
        "Signs",
        Slot.VALUE,
        Section.PLACES,
        properties=("sign",),
        open_label="Any sign",
    ),
    # Three kinds of house, labelled by what is computed (houses.md D24).
    Facet("houses", "Houses", Slot.MENU, Section.PLACES),
    Facet(
        "whole_sign_house",
        "Whole-sign house",
        Slot.VALUE,
        menu="houses",
        properties=("whole_sign_house",),
        open_label="Any house",
        tooltip="The sign counted from the Ascendant's sign",
    ),
    Facet(
        "cusp_house",
        "House between cusps",
        Slot.VALUE,
        menu="houses",
        properties=("cusp_house",),
        open_label="Any house",
        tooltip="From cusp n to cusp n+1, under the search's house system",
        names_house_system=True,
    ),
    Facet(
        "cusp_conjunction",
        "Cusps in the same sign",
        Slot.VALUE,
        menu="houses",
        properties=("cusp_conjunction",),
        open_label="Any cusp",
        tooltip=(
            "Ernst Wilhelm: cusps as points; a planet is conjunct each cusp in its sign"
        ),
    ),
    Facet(
        "nakshatras",
        "Nakshatras",
        Slot.VALUE,
        Section.PLACES,
        properties=("nakshatra",),
        open_label="Any nakshatra",
    ),
    # States
    Facet("dignity", "Dignity", Slot.VALUE, Section.STATES, properties=("dignity",)),
    Facet(
        "avasthas",
        "Avasthas",
        Slot.VALUE,
        Section.STATES,
        properties=("baladi", "jagradadi", "deeptadi", "lajjitaadi", "shayanadi"),
    ),
    Facet("motion", "Motion", Slot.VALUE, Section.STATES, properties=("retrograde",)),
    # Systems
    Facet(
        "retinue",
        "Retinue Beings",
        Slot.VALUE,
        Section.SYSTEMS,
        properties=("trimsamsa_being", "hora_being"),
    ),
    Facet("cot", "Cards of Truth", Slot.MENU, Section.SYSTEMS),
    Facet(
        "birth_card", "Birth card", Slot.VALUE, menu="cot", properties=("birth_card",)
    ),
    Facet(
        "spread",
        "Spread",
        Slot.SUBJECT,
        menu="cot",
        properties=("card",),
        subjects=CARD_POSITIONS,
        entry=Entry.NO_SUBJECT,
        open_label="Any position",
    ),
    Facet(
        "occupied",
        "Occupied",
        Slot.VALUE,
        menu="cot",
        properties=("in_card",),
        entry=Entry.NO_SUBJECT,
        open_label="Any card",
    ),
    Facet(
        "cot_card",
        "Card",
        Slot.VALUE,
        menu="cot",
        properties=("card", "in_card"),
        entry=Entry.WITH_SUBJECT,
        open_label="Any card",
    ),
    Facet(
        "position",
        "Position",
        Slot.QUALIFIER,
        menu="cot",
        properties=("in_card",),
        qualifier="position",
        starts_row=True,
    ),
    Facet("hd", "Human Design", Slot.MENU, Section.SYSTEMS),
    Facet(
        "gate",
        "Gate",
        Slot.VALUE,
        menu="hd",
        properties=("gate",),
        open_label="Any gate",
        name=hd_names.gate_name,
    ),
    Facet(
        "line",
        "Line",
        Slot.QUALIFIER,
        menu="hd",
        properties=("gate",),
        qualifier="line",
        starts_row=True,
    ),
    Facet(
        "side",
        "Conscious / unconscious",
        Slot.QUALIFIER,
        menu="hd",
        properties=("gate", "channel", "center"),
        qualifier="side",
        open_label=taxonomy.SIDE_LABELS["both"],
    ),
    Facet(
        "channel",
        "Channel",
        Slot.VALUE,
        menu="hd",
        properties=("channel",),
        open_label="Any channel",
        name=hd_names.channel_name,
    ),
    Facet("center", "Center", Slot.VALUE, menu="hd", properties=("center",)),
    Facet(
        "center_state",
        "Defined / undefined",
        Slot.QUALIFIER,
        menu="hd",
        properties=("center",),
        qualifier="state",
    ),
    Facet("hd_type", "Type", Slot.VALUE, menu="hd", properties=("hd_type",)),
    Facet(
        "strategy",
        "Strategy",
        Slot.VALUE,
        menu="hd",
        properties=("hd_type",),
        relabel=lambda value: STRATEGY[str(value)],
    ),
    Facet("authority", "Authority", Slot.VALUE, menu="hd", properties=("authority",)),
    Facet(
        "definition", "Definition", Slot.VALUE, menu="hd", properties=("definition",)
    ),
    Facet("profile", "Profile", Slot.VALUE, menu="hd", properties=("profile",)),
    Facet(
        "cross",
        "Incarnation cross",
        Slot.VALUE,
        menu="hd",
        properties=("incarnation_cross",),
    ),
    # Follow-ups: qualifiers of Places/States properties.
    Facet(
        "varga",
        "Varga",
        Slot.QUALIFIER,
        properties=("sign",),
        qualifier="varga",
        open_label="Any varga",
    ),
    Facet("pada", "Pada", Slot.QUALIFIER, properties=("nakshatra",), qualifier="pada"),
    Facet(
        "by",
        "Caused by",
        Slot.QUALIFIER,
        properties=("lajjitaadi",),
        qualifier="by",
    ),
    Facet(
        "via",
        "Via",
        Slot.QUALIFIER,
        properties=("lajjitaadi",),
        qualifier="via",
    ),
)
#: The open value pick's label when the facet names none.
ANY_VALUE = "Any"
#: Subject labels where the identity name is not the display (§2).
_CUSP_LABELS: Mapping[str, str] = {
    cusp: (f"{n} (Ascendant)" if cusp == LAGNA else str(n))
    for n, cusp in enumerate(CUSPS, start=1)
}
_HD_SUBJECT_LABELS: Mapping[str, str] = {"Rahu": "North Node", "Ketu": "South Node"}
_HD_PROPERTIES = frozenset(spec.name for spec in human_design.PROPERTIES)
_BY_KEY: Mapping[str, Facet] = {f.key: f for f in FACETS}
#: Properties whose subjects only their own subject facet names: a CoT
#: position is called "Mars" but is not the body Mars, so Planets -> Mars
#: never leads to ``card``.
_CLAIMED: frozenset[str] = frozenset(
    p for f in FACETS if f.slot is Slot.SUBJECT for p in f.properties
)


def facet(key: str) -> Facet:
    """``FACETS`` by key. ``InvariantError`` for an unknown key."""
    found = _BY_KEY.get(key)
    if found is None:
        raise InvariantError(f"invariant: {key!r} is a key of FACETS")
    return found


# ---------------------------------------------------------------- row state


@dataclass(frozen=True)
class _Row:
    """The slots a path has filled. ``subject`` is as compiled (a subject, a
    group key, or ``None``); ``subjects`` what it matches (``None``: any)."""

    subject: str | None = None
    subjects: tuple[str, ...] | None = None
    subject_done: bool = False
    property: str | None = None
    value: Value | None = None
    value_done: bool = False
    qualifiers: tuple[tuple[str, str | None], ...] = ()  # None: the open pick

    def has_qualifier(self, name: str) -> bool:
        return any(given == name for given, _value in self.qualifiers)


def facet_label(f: Facet, system: SearchSystem) -> str:
    """``f``'s label in ``system``: "House between cusps (Campanus)", so the
    dependence on the bar's house system is visible (houses.md D26)."""
    if f.names_house_system:
        return f"{f.label} ({house_system_label(system.house_system)})"
    return f.label


def _spec(property_name: str) -> PropertySpec:
    return taxonomy.catalogue()[property_name]


def _candidates(row: _Row) -> tuple[str, ...]:
    """The properties the row can still become, in registry order. A subject
    picked before the property came from Planets or Cusps (a facet with
    properties fixes its property), so claimed properties are out."""
    if row.property is not None:
        return (row.property,)
    claimed = _CLAIMED if row.subject_done else frozenset()
    return tuple(
        name
        for name, spec in taxonomy.catalogue().items()
        if name not in claimed
        and (row.subjects is None or any(s in spec.subjects for s in row.subjects))
    )


def _entry_allows(facet: Facet, row: _Row) -> bool:
    if facet.entry is Entry.NO_SUBJECT:
        return not row.subject_done
    if facet.entry is Entry.WITH_SUBJECT:
        return row.subject_done
    return True


def _qualifier_spec(property_name: str, name: str) -> Qualifier:
    for qualifier in _spec(property_name).qualifiers:
        if qualifier.name == name:
            return qualifier
    raise InvariantError(f"invariant: {property_name!r} declares qualifier {name!r}")


def _qualifier_property(facet: Facet, row: _Row) -> str | None:
    """The property a QUALIFIER facet qualifies after ``row``, or ``None``."""
    if row.property is not None:
        return row.property if row.property in facet.properties else None
    if not facet.starts_row:
        return None
    fits = [p for p in facet.properties if p in _candidates(row)]
    return fits[0] if len(fits) == 1 else None


def _picks(row: _Row, facet: Facet) -> tuple[tuple[Pick, str], ...]:
    """Every pick ``facet`` may make after ``row``, label-free, with the
    property it belongs to. Empty: the facet is not offered."""
    if not _entry_allows(facet, row):
        return ()
    if facet.slot is Slot.SUBJECT:
        return _subject_picks(row, facet)
    if facet.slot is Slot.VALUE:
        return _value_picks(row, facet)
    if facet.slot is Slot.QUALIFIER:
        return _qualifier_picks(row, facet)
    return ()


def _subject_picks(row: _Row, facet: Facet) -> tuple[tuple[Pick, str], ...]:
    """A subject facet's owner is its one property (Spread: ``card``), else
    ``""``: Planets and Cusps narrow whatever property comes."""
    if row.subject_done:
        return ()
    props = _candidates(row)
    if facet.properties:
        props = tuple(p for p in props if p in facet.properties)
        if len(props) != 1:
            return ()
    else:
        props = tuple(p for p in props if p not in _CLAIMED)
    fitting = tuple(
        s for s in facet.subjects if any(s in _spec(p).subjects for p in props)
    )
    if not fitting:
        return ()
    owner = props[0] if facet.properties else ""
    opened = ((Pick(None), owner),) if facet.open_label is not None else ()
    return opened + tuple((Pick(s), owner) for s in fitting)


def _value_picks(row: _Row, facet: Facet) -> tuple[tuple[Pick, str], ...]:
    """Per property: its open pick, then its domain. A facet over several
    properties tags each pick with its property (Avasthas)."""
    if row.value_done:
        return ()
    multi = len(facet.properties) > 1
    out: list[tuple[Pick, str]] = []
    for p in (p for p in facet.properties if p in _candidates(row)):
        tag = p if multi else None
        out.append((Pick(None, tag), p))
        out.extend((Pick(v, tag), p) for v in _spec(p).values)
    return tuple(out)


def _open_means_default(qualifier: Qualifier) -> bool:
    """A QUALIFIER facet's open pick is "any" where the qualifier allows it
    (gate "Both": either side; "Any varga"), else its default (channel
    "Both": the whole chart)."""
    return qualifier.default is not None and not qualifier.allows_any


def _qualifier_picks(row: _Row, facet: Facet) -> tuple[tuple[Pick, str], ...]:
    """The open pick (when the facet labels one) first; a default it stands
    for is not offered twice."""
    p = _qualifier_property(facet, row)
    if p is None or facet.qualifier is None or row.has_qualifier(facet.qualifier):
        return ()
    if facet.qualifier not in (q.name for q in _spec(p).qualifiers):
        return ()
    qualifier = _qualifier_spec(p, facet.qualifier)
    values = qualifier.values or ()
    if facet.open_label is None:
        return tuple((Pick(v), p) for v in values)
    skip = qualifier.default if _open_means_default(qualifier) else None
    return ((Pick(None), p),) + tuple((Pick(v), p) for v in values if v != skip)


def _offered(facet: Facet, row: _Row) -> bool:
    if facet.slot is not Slot.MENU:
        return bool(_picks(row, facet))
    return any(
        _offered(child, row)
        for child in FACETS
        if child.menu == facet.key
        and (child.slot is not Slot.QUALIFIER or row.property is None)
    )


@dataclass(frozen=True)
class _State:
    """Where a path leaves a row: its slots, the menu its last step opened
    (unpicked), the menu its last picked step sits under, and whether every
    step is picked."""

    row: _Row = _Row()
    opened: Facet | None = None
    within: str | None = None
    complete: bool = True


def _next(state: _State) -> tuple[Facet, ...]:
    """After an opened menu: its offered children. Otherwise, in table order:
    top-level facets and menus, the fixed property's qualifier facets wherever
    they sit (offered flat), and the siblings of the last step under its menu
    (Spread -> Card, Line -> Gate)."""
    row = state.row
    if state.opened is not None:
        return tuple(
            f for f in FACETS if f.menu == state.opened.key and _offered(f, row)
        )
    return tuple(
        f
        for f in FACETS
        if (
            f.menu is None
            or f.menu == state.within
            or (f.slot is Slot.QUALIFIER and row.property is not None)
        )
        and _offered(f, row)
    )


def _apply(row: _Row, facet: Facet, pick: Pick, owner: str) -> _Row:
    if facet.slot is Slot.SUBJECT:
        if pick.value is None:
            subject = facet.group
            subjects = None if facet.group is None else SUBJECT_GROUPS[facet.group]
        else:
            subject = str(pick.value)
            subjects = (subject,)
        return replace(
            row,
            subject=subject,
            subjects=subjects,
            subject_done=True,
            property=owner or row.property,
        )
    if facet.slot is Slot.VALUE:
        return replace(row, property=owner, value=pick.value, value_done=True)
    if facet.qualifier is None:
        raise InvariantError(f"invariant: QUALIFIER facet {facet.key!r} names one")
    value = None if pick.value is None else str(pick.value)
    return replace(
        row, property=owner, qualifiers=(*row.qualifiers, (facet.qualifier, value))
    )


def _replay(path: Path) -> _State:
    """The state ``path`` leaves. ``InvariantError`` for a step
    ``next_facets``/``choices`` did not offer, or an unpicked step before
    the last."""
    state = _State()
    for index, step in enumerate(path):
        if step.facet not in _next(state):
            raise InvariantError(
                f"invariant: step {index} ({step.facet.key!r}) is offered after "
                f"{tuple(s.facet.key for s in path[:index])}"
            )
        if step.facet.slot is Slot.MENU:
            if step.pick is not None:
                raise InvariantError(f"invariant: menu step {index} has no pick")
            state = replace(state, opened=step.facet, within=None)
            continue
        if step.pick is None:
            if index != len(path) - 1:
                raise InvariantError(
                    f"invariant: only the last step is unpicked (step {index})"
                )
            return replace(state, opened=None, complete=False)
        owners = [o for p, o in _picks(state.row, step.facet) if p == step.pick]
        if not owners:
            raise InvariantError(
                f"invariant: {step.pick!r} is a pick of {step.facet.key!r} "
                f"at step {index}"
            )
        row = _apply(state.row, step.facet, step.pick, owners[0])
        state = _State(row, None, step.facet.menu, True)
    return state


# --------------------------------------------------------------- navigation


def next_facets(path: Path) -> tuple[Facet, ...]:
    """The facets a row may add after ``path``, in table order (the panel
    sections them by ``Facet.section``). After an unpicked menu step: that
    menu's offered children. Otherwise: the offered top-level facets, menus
    with an offered child, and the fixed property's qualifier facets. Empty
    while the last step is unpicked. ``InvariantError`` if ``path`` is not one
    ``next_facets`` produces."""
    state = _replay(path)
    return _next(state) if state.complete else ()


def choices(
    path: Path,
    facet: Facet,
    mode: Mode,
    naming: Naming,
    narrow: Narrow | None = None,
) -> tuple[Choice, ...]:
    """The picks ``facet`` offers after ``path``: the open pick first (when
    the facet has one), then the domain in taxonomy order, kept to the picks
    compatible with ``path``, then to ``narrow``'s stored values when it
    answers. Labels in ``mode`` and ``naming`` (Ascendant "1 (Ascendant)",
    Rahu/Ketu "North/South Node" when the row's property is HD, positions
    "Sun card"). ``InvariantError`` if ``facet`` is not offered after
    ``path``."""
    state = _replay(path)
    row = state.row
    if not state.complete or facet.slot is Slot.MENU or facet not in _next(state):
        raise InvariantError(
            f"invariant: {facet.key!r} is offered after "
            f"{tuple(s.facet.key for s in path)} and has picks"
        )
    picks = _picks(row, facet)
    stored = _narrowed(row, facet, picks, narrow)
    multi = len({owner for _pick, owner in picks}) > 1
    out: list[Choice] = []
    for pick, owner in picks:
        if (
            pick.value is not None
            and stored is not None
            and pick.value not in stored.get(owner, frozenset())
        ):
            continue
        section = _property_label(owner) if multi else None
        out.append(
            Choice(pick, _pick_label(row, facet, pick, owner, mode, naming), section)
        )
    return tuple(out)


def absent_pick(path: Path, facet: Facet) -> Pick | None:
    """The pick of QUALIFIER ``facet`` after ``path`` that searches what
    leaving the qualifier out searches: its default (varga ``D1``), or the
    open pick where that stands for the default or for "any" (channel side
    "Both", gate side "Both"). ``None`` when no pick does (pada: absent is
    any pada, and there is no "Any pada" pick). ``InvariantError`` if
    ``facet`` is not a QUALIFIER facet offered after ``path``."""
    state = _replay(path)
    p = None if facet.qualifier is None else _qualifier_property(facet, state.row)
    if p is None or not state.complete or facet not in _next(state):
        raise InvariantError(
            f"invariant: QUALIFIER {facet.key!r} is offered after "
            f"{tuple(s.facet.key for s in path)}"
        )
    qualifier = _qualifier_spec(p, str(facet.qualifier))
    if qualifier.default is not None and not _open_means_default(qualifier):
        return Pick(qualifier.default)
    return Pick(None) if facet.open_label is not None else None


def _narrowed(
    row: _Row,
    facet: Facet,
    picks: tuple[tuple[Pick, str], ...],
    narrow: Narrow | None,
) -> Mapping[str, frozenset[Value]] | None:
    """Owner property -> stored values of the facet's column, or ``None``
    when ``narrow`` is absent or any owner's projection was never computed."""
    if narrow is None:
        return None
    out: dict[str, frozenset[Value]] = {}
    for owner in dict.fromkeys(o for _p, o in picks):
        if not owner:
            return None  # Planets/Cusps before the property: nothing to ask
        column, fixed = _column(row, facet, owner)
        stored = narrow(owner, column, fixed)
        if stored is None:
            return None
        out[owner] = frozenset(stored)
    return out


def _column(row: _Row, facet: Facet, owner: str) -> tuple[str, Mapping[str, Value]]:
    """The store column a facet's pick fills, and the columns ``row`` fixes."""
    spec = _spec(owner)
    fixed: dict[str, Value] = {}
    if row.subjects is not None and len(row.subjects) == 1:
        fixed["subject"] = row.subjects[0]
    if row.value is not None:
        fixed["value"] = row.value
    names = [q.name for q in spec.qualifiers]
    for name, value in row.qualifiers:
        if value is not None:
            fixed[f"q{names.index(name) + 1}"] = value
    if facet.slot is Slot.SUBJECT:
        return "subject", fixed
    if facet.slot is Slot.VALUE:
        return "value", fixed
    return f"q{names.index(str(facet.qualifier)) + 1}", fixed


def _property_label(property_name: str) -> str:
    return property_name.replace("_", " ").capitalize()


def _pick_label(
    row: _Row, facet: Facet, pick: Pick, owner: str, mode: Mode, naming: Naming
) -> str:
    if pick.value is None:
        if facet.open_label is not None:
            return facet.open_label
        if len(facet.properties) > 1:
            return f"{ANY_VALUE} {_property_label(owner).casefold()}"
        return ANY_VALUE
    if facet.slot is Slot.SUBJECT:
        return subject_label(str(pick.value), owner or row.property)
    if facet.slot is Slot.VALUE:
        if facet.relabel is not None:
            return facet.relabel(pick.value)
        label = taxonomy.label(_spec(owner), pick.value, mode, naming)
        name = facet.name(pick.value) if facet.name is not None else None
        return f"{label} ({name})" if name else label
    if facet.qualifier == "position":
        return f"{pick.value} card"
    label = taxonomy.qualifier_label(
        _spec(owner), str(facet.qualifier), str(pick.value), naming
    )
    # A default the open pick does not stand for is what an absent qualifier
    # searches: say so ("D1 (default)" beside "Any varga").
    if pick.value == _qualifier_spec(owner, str(facet.qualifier)).default:
        return f"{label} (default)"
    return label


def subject_label(subject: str, property_name: str | None) -> str:
    """A subject's display label in a row on ``property_name`` (``None``: not
    fixed yet): cusps by number ("1 (Ascendant)"), Rahu and Ketu as North and
    South Node under Human Design, CoT positions as "Sun card"."""
    if subject in _CUSP_LABELS:
        return _CUSP_LABELS[subject]
    if property_name in _HD_PROPERTIES and subject in _HD_SUBJECT_LABELS:
        return _HD_SUBJECT_LABELS[subject]
    if property_name == "card":
        return f"{subject} card"
    return subject


# ------------------------------------------------------------- path <-> filter


def compile(path: Path) -> Filter | None:
    """The row's filter in stored values, or ``None`` while incomplete (no
    property fixed, or the last step unpicked). An open QUALIFIER pick
    compiles to "any": no qualifier (gate "Both" -> either side), or
    ``taxonomy.ANY`` over a default ("Any varga" -> ``varga=*``); where the
    qualifier disallows any, to its default (channel/center "Both" ->
    ``side=both``). ``InvariantError`` for a path ``next_facets``/``choices`` could not
    have produced."""
    state = _replay(path)
    row = state.row
    if not state.complete or row.property is None:
        return None
    given = dict(row.qualifiers)
    qualifiers: list[tuple[str, str]] = []
    for qualifier in _spec(row.property).qualifiers:
        if qualifier.name not in given:
            continue
        value = given[qualifier.name]
        if value is None:
            if _open_means_default(qualifier):
                value = qualifier.default
            elif qualifier.default is not None:
                value = taxonomy.ANY
        if value is not None:
            qualifiers.append((qualifier.name, value))
    # A chart-level property's only subject is the chart (the CLI's ``chart.``).
    subject = CHART if _spec(row.property).subjects == (CHART,) else row.subject
    return Filter(subject, row.property, row.value, tuple(qualifiers))


def path_of(f: Filter) -> Path:
    """The canonical path of ``f`` (module docstring), every step picked.
    ``f`` may carry labels: it is resolved first, so ``BadFilterError`` for a
    filter ``search.resolve`` rejects. ``compile(path_of(f))`` resolves to
    the same ``ResolvedFilter`` as ``f``."""
    resolved = search.resolve(f)
    spec = resolved.spec
    p = spec.name
    builder = _PathBuilder()
    subjects = resolved.subjects
    if subjects is not None and subjects != (CHART,):
        builder.add(*_subject_step(spec, subjects))
    columns = (resolved.q1, resolved.q2)
    # A defaulted qualifier resolved to any was asked for: the open pick.
    set_qualifiers = [
        (q.name, value)
        for q, value in zip(spec.qualifiers, columns, strict=False)
        if value != q.default
    ]
    if builder.row.property is None and resolved.value is None:
        for name, value in set_qualifiers:
            starter = _qualifier_facet(p, name)
            if starter.starts_row and _picks(builder.row, starter):
                builder.add(starter, Pick(value))
                break
    if builder.row.property is None:
        opener = _value_facet(p, builder.row)
        if opener is None:
            # Spread: the property's subject facet fixes it, subject any.
            builder.add(_subject_facet(p), Pick(None))
    if not builder.row.value_done and (
        resolved.value is not None or builder.row.property is None
    ):
        value_facet = _value_facet(p, builder.row)
        if value_facet is None:
            raise InvariantError(f"invariant: FACETS has a value facet for {p!r}")
        tag = p if len(value_facet.properties) > 1 else None
        builder.add(value_facet, Pick(resolved.value, tag))
    for name, value in set_qualifiers:
        if not builder.row.has_qualifier(name):
            builder.add(_qualifier_facet(p, name), Pick(value))
    return builder.path


class _PathBuilder:
    """Appends steps, opening a step's menu first when it is not offered flat."""

    def __init__(self) -> None:
        self.path: Path = ()
        self.state = _State()

    @property
    def row(self) -> _Row:
        return self.state.row

    def add(self, facet: Facet, pick: Pick) -> None:
        if facet.menu is not None and facet not in _next(self.state):
            self.path += (Step(_BY_KEY[facet.menu], None),)
        self.path += (Step(facet, pick),)
        self.state = _replay(self.path)


def _subject_step(spec: PropertySpec, subjects: tuple[str, ...]) -> tuple[Facet, Pick]:
    candidates = [
        f
        for f in FACETS
        if f.slot is Slot.SUBJECT
        and (spec.name in f.properties if spec.name in _CLAIMED else not f.properties)
    ]
    if len(subjects) == 1:
        for f in candidates:
            if subjects[0] in f.subjects:
                return f, Pick(subjects[0])
    for f in candidates:
        if f.group is not None:
            members = tuple(s for s in SUBJECT_GROUPS[f.group] if s in spec.subjects)
            if set(members) == set(subjects):
                return f, Pick(None)
    raise InvariantError(
        f"invariant: a subject facet reaches {subjects!r} of {spec.name!r}"
    )


def _subject_facet(property_name: str) -> Facet:
    for f in FACETS:
        if f.slot is Slot.SUBJECT and property_name in f.properties:
            return f
    raise InvariantError(f"invariant: a facet fixes {property_name!r}")


def _value_facet(property_name: str, row: _Row) -> Facet | None:
    """The canonical value facet after ``row``: the first offered one in
    table order, never a relabelling one (Strategy)."""
    for f in FACETS:
        if (
            f.slot is Slot.VALUE
            and property_name in f.properties
            and f.relabel is None
            and _entry_allows(f, row)
        ):
            return f
    return None


def _qualifier_facet(property_name: str, name: str) -> Facet:
    for f in FACETS:
        if (
            f.slot is Slot.QUALIFIER
            and f.qualifier == name
            and property_name in f.properties
        ):
            return f
    raise InvariantError(
        f"invariant: a facet fills qualifier {name!r} of {property_name!r}"
    )
