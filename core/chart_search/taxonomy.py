# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Subjects, properties, values and labels (design.md §4.4, §4.7, D7).

The one translator between what users type or see (labels) and what the store
holds (values). Values are the engine's identifiers, never display text.

**Sign ordinals.** A ``sign`` value is the division ordinal 1-12 from the start
of the system's circle: libaditya's ``sign()`` on the chart built in the
system's mode. Division 1 is Dhata = Aries in every mode (SPEC-ZOD-001 §4.2);
only where division 1 starts differs, and that is already in the value. So the
label codec is mode-independent: ``core.aditya_mode.displayed_sign_name(value -
1, mode, use_western_names, sign_language)``. Parsing accepts both label sets
in any naming (``Aries`` and ``Dhata`` both mean 1), plus the ordinal.

**Parsing is lenient, display is not.** A filter value may be the stored value
(``5``, ``"shamed"``, ``"20-34"``) or any label of it; display uses the
current ``Naming`` only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache

from core.aditya_mode import LOCALIZED_SIGN_NAMES, displayed_sign_name
from core.chart_search.errors import BadFilterError, InvariantError
from core.chart_search.extractors.subjects import CUSPS, LAGNA, SUBJECT_GROUPS
from core.chart_search.system import Mode
from core.frame_names import native_western_names

Value = int | str


class ValueKind(StrEnum):
    ORDINAL = "ordinal"  # int in a closed range (sign 1-12, gate 1-64)
    CODE = "code"  # str from a closed set (dignity "EX", channel "20-34")


class Codec(StrEnum):
    """How a value is labelled. Each codec delegates to the code the screens use."""

    SIGN = "sign"  # core.aditya_mode.displayed_sign_name
    NUMBER = "number"  # house, gate, line: the number itself
    BOOLEAN = "boolean"  # retrograde 0/1 -> "direct"/"retrograde"
    NAKSHATRA = "nakshatra"  # the F2 wheel's nakshatra names
    ENGINE = "engine"  # engine string shown as is (avastha states, beings)
    DIGNITY = "dignity"  # "EX" -> "Exalted" (the panels' dignity labels)
    CARD = "card"  # cards_of_truth_data.card_descriptor(code)["name"]
    HD = "hd"  # hd_model vocabulary (center keys, types, authorities)
    CROSS = "cross"  # incarnation cross label as is; its short form parses too


@dataclass(frozen=True)
class Qualifier:
    """One of a property's at most two qualifiers (``q1``, ``q2`` in order).
    ``values`` is the closed set; ``None`` means the store's distinct values
    at the projection (cascading dropdowns read ``SELECT DISTINCT``).
    ``default`` is what an absent qualifier means; ``None`` means any. It is
    set where "any" would mislead: a sign means the rashi (``D1``) unless a
    varga is named, and an HD centre ``undefined`` on some side is not an
    undefined centre, so the centre's side defaults to ``both``.
    ``allows_any``: the qualifier given as ``ANY`` (``varga=*``) means any,
    overriding the default; ``False`` rejects it where "any" would mislead
    (that centre's side)."""

    name: str
    values: tuple[str, ...] | None
    default: str | None = None
    allows_any: bool = True


@dataclass(frozen=True)
class PropertySpec:
    """A property name is unique across the whole registry (tested), so
    ``(subject, property)`` names exactly one extractor."""

    name: str
    subjects: tuple[str, ...]
    kind: ValueKind
    values: tuple[int, ...] | tuple[str, ...]  # the full value domain
    codec: Codec
    qualifiers: tuple[Qualifier, ...] = ()  # len <= 2 (InvariantError at registration)
    multi: bool = False  # several rows per subject (causes, channels)
    #: Parse-only labels, value -> other names it may be typed as (the
    #: lajjitaadi states' Sanskrit names); never displayed.
    aliases: tuple[tuple[Value, tuple[str, ...]], ...] = ()


@dataclass(frozen=True)
class Naming:
    """Display choices, never part of the system (SPEC-FIND-001)."""

    use_western_names: bool
    sign_language: str = "en"


class SignNames(StrEnum):
    """Which sign names Find Chart shows (varuna/47)."""

    BY_SYSTEM = "system"  # the search system's own: Aditya in the Aditya Circle
    ADITYA = "aditya"
    ZODIAC = "zodiac"


def search_naming(
    mode: Mode, names: SignNames = SignNames.BY_SYSTEM, sign_language: str = "en"
) -> Naming:
    """The label set for a search in ``mode``. ``BY_SYSTEM`` is the mode's own
    names: the Aditya names in the Aditya Circle, the zodiac names in Tropical
    Classic and Sidereal. Never the app's ``use_western_names``: that follows
    the app's frame, and the search system may be pinned to another one."""
    if names is SignNames.BY_SYSTEM:
        return Naming(native_western_names(mode.value), sign_language)
    return Naming(names is SignNames.ZODIAC, sign_language)


# ------------------------------------------------------------------ catalogue


#: Property names that were split, -> the names that replace them. Not
#: aliases: the old name was ambiguous, so a filter naming it fails
#: (houses.md D23).
RETIRED: Mapping[str, tuple[str, ...]] = {
    "house": ("whole_sign_house", "cusp_house"),
}


def catalogue() -> Mapping[str, PropertySpec]:
    """Property name -> spec, over ``extractors.registry.EXTRACTORS``."""
    return {name: spec for name, (spec, _owner) in _registered().items()}


def owner(property_name: str) -> str:
    """The id of the extractor that declares ``property_name``. Raises
    ``BadFilterError`` listing the known properties."""
    registered = _registered()
    if property_name in RETIRED:
        replacements = RETIRED[property_name]
        raise BadFilterError(
            f"{property_name!r} is no longer a property: it meant one of "
            f"{' or '.join(replacements)}; name the one you mean",
            replacements,
        )
    if property_name not in registered:
        raise BadFilterError(
            f"unknown property {property_name!r}", tuple(sorted(registered))
        )
    return registered[property_name][1]


@cache
def _registered() -> Mapping[str, tuple[PropertySpec, str]]:
    """Property name -> (spec, extractor id), checking the registration rules."""
    # Imported here: the extractor modules import this one.
    from core.chart_search.extractors.registry import EXTRACTORS

    out: dict[str, tuple[PropertySpec, str]] = {}
    for extractor in EXTRACTORS:
        for spec in extractor.properties:
            if spec.name in out:
                raise InvariantError(
                    f"invariant: property {spec.name!r} is declared once "
                    f"({out[spec.name][1]!r} and {extractor.id!r} both declare it)"
                )
            if len(spec.qualifiers) > 2:
                raise InvariantError(
                    f"invariant: property {spec.name!r} has at most two qualifiers"
                )
            out[spec.name] = (spec, extractor.id)
    return out


# --------------------------------------------------------------------- codecs


#: The naming error messages list labels in.
ENGLISH_WESTERN = Naming(use_western_names=True)
#: Every label set a value may be typed in (parsing is lenient).
ALL_NAMINGS: tuple[Naming, ...] = (
    Naming(use_western_names=False),
    ENGLISH_WESTERN,
    *(Naming(True, language) for language in LOCALIZED_SIGN_NAMES),
)
#: Subject aliases, case-folded -> the identity name (``subjects.LAGNA``,
#: ``subjects.CUSPS``): ``cusp7`` for "Cusp 7", which ``--where`` cannot quote
#: before its dot.
SUBJECT_ALIASES: Mapping[str, str] = {
    "asc": LAGNA,
    "lagna": LAGNA,
    **{f"cusp{n}": cusp for n, cusp in enumerate(CUSPS, start=1)},
}
RETROGRADE_LABELS: Mapping[int, str] = {0: "direct", 1: "retrograde"}
#: What a filter's subject or value is when left open ("any").
ANY = "*"
#: The label of the empty ``by`` qualifier (a lajjitaadi cause without a planet).
NO_PLANET_LABEL = "none"
#: HD ``side`` labels: conscious/unconscious lead (the core HD idea, Lorris
#: 2026-10-24); Personality/Design kept since both names are in use (varuna/45).
SIDE_LABELS: Mapping[str, str] = {
    "both": "Conscious or unconscious",
    "personality": "Conscious only (Personality, black)",
    "design": "Unconscious only (Design, red)",
}


def parse_value(spec: PropertySpec, raw: Value) -> Value:
    """A stored value or any of its labels -> the stored value. Raises
    ``BadFilterError`` listing the domain's labels in English Western naming."""
    if not isinstance(raw, bool) and raw in spec.values:
        return raw
    if isinstance(raw, str):
        typed = raw.strip().casefold()
        for value in spec.values:
            if typed == str(value).casefold() or typed in _labels(spec, value):
                return value
    raise BadFilterError(
        f"{raw!r} is not a value of {spec.name}",
        tuple(
            label(spec, value, Mode.ADITYA, ENGLISH_WESTERN) for value in spec.values
        ),
    )


def _labels(spec: PropertySpec, value: Value) -> frozenset[str]:
    """Every label of ``value``, case-folded. The sign codec ignores the mode
    (module docstring), so one mode gives all of them. A cross also parses
    from its short label ("RAX of the Sphinx"); any value from its
    ``PropertySpec.aliases``."""
    labels = frozenset(
        label(spec, value, Mode.ADITYA, naming).casefold() for naming in ALL_NAMINGS
    ) | frozenset(
        alias.casefold()
        for aliased, names in spec.aliases
        if aliased == value
        for alias in names
    )
    short = _cross_short_labels().get(str(value)) if spec.codec is Codec.CROSS else None
    return labels if short is None else labels | {short.casefold()}


@cache
def _cross_short_labels() -> Mapping[str, str]:
    from core.hd_model import incarnation_cross_short_labels

    return incarnation_cross_short_labels()


def parse_subject(spec: PropertySpec, raw: str) -> str:
    """Case-insensitive subject, with aliases (``Asc``, ``Lagna`` -> ``Ascendant``,
    ``cusp7`` -> ``Cusp 7``)."""
    typed = raw.strip().casefold()
    typed = SUBJECT_ALIASES.get(typed, typed).casefold()
    for subject in spec.subjects:
        if subject.casefold() == typed:
            return subject
    raise BadFilterError(f"{raw!r} is not a subject of {spec.name}", spec.subjects)


def parse_subjects(spec: PropertySpec, raw: str | None) -> tuple[str, ...] | None:
    """A filter's subject slot as the subjects it matches: ``None`` (any) for
    ``None`` or ``ANY``; a group name (``SUBJECT_GROUPS``, case-insensitive) as
    its members that ``spec`` declares, in ``spec`` order; else one subject
    (``parse_subject``). Raises ``BadFilterError`` listing the subjects and the
    groups that apply to ``spec``."""
    if raw is None or raw.strip() == ANY:
        return None
    group = SUBJECT_GROUPS.get(raw.strip().casefold())
    if group is not None:
        members = tuple(s for s in spec.subjects if s in group)
        if members:
            return members
        raise BadFilterError(
            f"group {raw!r} has no subject of {spec.name}", _subject_choices(spec)
        )
    try:
        return (parse_subject(spec, raw),)
    except BadFilterError as exc:
        raise BadFilterError(exc.message, _subject_choices(spec)) from exc


def _subject_choices(spec: PropertySpec) -> tuple[str, ...]:
    """What a filter on ``spec`` may name as its subject."""
    groups = tuple(
        name
        for name, members in SUBJECT_GROUPS.items()
        if any(s in members for s in spec.subjects)
    )
    return (*spec.subjects, *groups, ANY)


def parse_value_or_any(spec: PropertySpec, raw: Value | None) -> Value | None:
    """``parse_value``, with ``None`` (any) for ``None`` or ``ANY``."""
    if raw is None or raw == ANY:
        return None
    return parse_value(spec, raw)


def label(spec: PropertySpec, value: Value, mode: Mode, naming: Naming) -> str:
    """The display label of a stored value."""
    codec = spec.codec
    if codec is Codec.SIGN:
        return str(
            displayed_sign_name(
                int(value) - 1,
                mode.value,
                naming.use_western_names,
                naming.sign_language,
            )
        )
    if codec is Codec.BOOLEAN:
        return RETROGRADE_LABELS[int(value)]
    if codec is Codec.NAKSHATRA:
        from AI_tools.AI_main_function.dasha import NAKSHATRA_NAMES_27

        return str(NAKSHATRA_NAMES_27[int(value) - 1])
    if codec is Codec.DIGNITY:
        from core.dignity_names import DIGNITY_FULL_NAMES

        return DIGNITY_FULL_NAMES[str(value)]
    if codec is Codec.CARD:
        from core.cards_of_truth_data import card_descriptor

        return str(card_descriptor(str(value))["name"])
    # NUMBER, ENGINE, HD and CROSS (hd_model's vocabulary is already display text;
    # centre keys stay keys until the HD extractor task pins their names).
    return str(value)


def qualifier_label(
    spec: PropertySpec, qualifier: str, value: str, naming: Naming
) -> str:
    """Qualifier values are engine keys shown as is (``D9``, ``Saturn``),
    except the empty ``by`` and the HD ``side`` (``SIDE_LABELS``).
    ``BadFilterError`` for a qualifier ``spec`` does not declare."""
    names = tuple(q.name for q in spec.qualifiers)
    if qualifier not in names:
        raise BadFilterError(f"{spec.name} has no qualifier {qualifier!r}", names)
    if qualifier == "side":
        return SIDE_LABELS[value]
    return value if value else NO_PLANET_LABEL
