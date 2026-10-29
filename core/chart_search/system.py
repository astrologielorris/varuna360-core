# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The search system and its projections (design.md §4.3, D2, D6).

A ``SearchSystem`` is every option that can change a stored value. It is
independent of the app's settings; the app's resolved frame is only its default
(SPEC-SET-003 exception, SPEC-FIND-004).

Each extractor stores its rows under a ``Projection``: the canonical encoding of
only the fields its code reads, after normalisation. Two systems with the same
projection share rows.

**Canonical key encoding.** ``Projection.key`` is compact JSON with sorted keys
and no whitespace, values as JSON scalars: ``{"ayanamsa_id":27,"mode":"sidereal"}``.
Field names are ``Field`` values, plus the derived ``custom_ayanamsa``. Floats are written as ``round(x, 6)``.
The key is stable across releases: changing a field name or encoding is a
store schema change (``store.SCHEMA_VERSION``).

**Custom ayanamsa (id 255).** Its definition lives in three settings
(``zodiac.custom_ayanamsa_*``) and the engine reads it from global state
(``libaditya.custom_ayanamsa``). It is not a search-system input: the system
always carries the definition the engine has installed (taken from settings,
like the app), so the compute worker never re-installs it under the app's
feet. It joins every projection that keeps ``ayanamsa_id == 255``, so rows
computed before the user edits the definition are not served after.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TypeVar

from core import custom_ayanamsa_settings
from core.ayanamsa_data import AYANAMSA_OPTIONS
from core.ayanamsa_data import CUSTOM_AYANAMSA_ID as _ENGINE_CUSTOM_ID
from core.capabilities.inputs import ChartFrame
from core.capabilities.settings_view import SettingsView
from core.chart_search.errors import BadSystemError, InvariantError
from core.hd_model import hd_frame_for
from core.house_systems import HOUSE_SYSTEM_CODES
from core.settings_registry import default as registry_default

Scalar = int | float | str


# A plain TypeVar, not PEP 695 syntax: the module must parse on Python 3.11.
E = TypeVar("E", bound=StrEnum)


class Field(StrEnum):
    """The search-system fields. Each defaults from its settings key (FIELD_SETTINGS)."""

    MODE = "mode"
    AYANAMSA_ID = "ayanamsa_id"
    HOUSE_SYSTEM = "house_system"
    COT_PLANET_ORDER = "cot_planet_order"
    HD_FRAME = "hd_frame"


#: field -> settings registry key it defaults from (house rule 2: declared once there).
#: ``hd_frame`` has no setting of its own: its default is
#: ``hd_frame_for(zodiac.mode, ui.hd_experience_level)``, the HD page's frame.
FIELD_SETTINGS: Mapping[Field, str] = {
    Field.MODE: "zodiac.mode",
    Field.AYANAMSA_ID: "zodiac.ayanamsa_id",
    Field.HOUSE_SYSTEM: "zodiac.house_system",
    Field.COT_PLANET_ORDER: "cot.planet_order",
    Field.HD_FRAME: "ui.hd_experience_level",
}
#: Shown on the system bar always; the domain fields only when a filter uses their domain.
CORE_FIELDS: tuple[Field, ...] = (
    Field.MODE,
    Field.AYANAMSA_ID,
    Field.HOUSE_SYSTEM,
)
DOMAIN_FIELDS: tuple[Field, ...] = (Field.COT_PLANET_ORDER, Field.HD_FRAME)

#: Nakshatra divisions as ayanamsa ids (design.md §4.4, D2): each id names one
#: division, so the search system has no separate nakshatra-coordinates field.
#: Equal division of the equator; a planet's nakshatra is that of its right ascension.
EQUATORIAL_DHRUVA_ID = 98  # SgrA*'s right ascension at 6°40' Mula
EQUATORIAL_VEDANGA_ID = 100  # Dhanishta begins at the winter solstice
EQUATORIAL_NAKSHATRA_IDS = frozenset({EQUATORIAL_DHRUVA_ID, EQUATORIAL_VEDANGA_ID})
#: Equal division of the ecliptic.
ECLIPTIC_VEDANGA_ID = 99
#: SgrA*'s ecliptic longitude at 6°40' Mula (Kala's "GC mid-Mula"). Not Swiss
#: #36, which places its own galactic centre 7-12' away. Find Chart's own id:
#: libaditya has none, so the engine is handed ``ENGINE_AYANAMSA_IDS[id]``.
ECLIPTIC_GC_MID_MULA_ID = 102
#: The app's ayanamsa read with ``zodiac.nakshatra_coords = neither``, as one id.
ECLIPTIC_IDS_OF_APP: Mapping[int, int] = {
    EQUATORIAL_DHRUVA_ID: ECLIPTIC_GC_MID_MULA_ID,
    EQUATORIAL_VEDANGA_ID: ECLIPTIC_VEDANGA_ID,
}
#: Find Chart id -> the id ``build_chart_from_params`` takes, where they differ.
#: 98's signs are Swiss #36 in libaditya, the app's signs at 98 + ecliptic.
ENGINE_AYANAMSA_IDS: Mapping[int, int] = {ECLIPTIC_GC_MID_MULA_ID: EQUATORIAL_DHRUVA_ID}
#: Refused until the libaditya reconciliation lands (Q7, libaditya-divergence.md).
REFUSED_AYANAMSA_IDS = frozenset({97})
CUSTOM_AYANAMSA_ID: int = _ENGINE_CUSTOM_ID  # 255
#: The projection field the Human Design rows are stored under (``Field.HD_FRAME``).
HD_FRAME = Field.HD_FRAME.value

#: What an extractor passes the engine for a field its projection dropped, or
#: does not read but the engine requires (``build_chart_from_params`` needs an
#: ayanamsa even in tropical modes, ``Charts.chart`` a house system).
#: Fixed, so memoised charts are shared across systems.
NEUTRAL: Mapping[Field, int | str] = {
    Field.AYANAMSA_ID: 98,
    Field.HOUSE_SYSTEM: "campanus",
}


class Mode(StrEnum):
    ADITYA = "aditya"
    TROPICAL_CLASSIC = "tropical_classic"
    SIDEREAL = "sidereal"


class CotPlanetOrder(StrEnum):
    SOLAR_SYSTEM = "solar_system"
    VEDIC = "vedic"  # "Week Day" in the UI


class HdFrame(StrEnum):
    """Human Design's gate-1 frame (``core.hd_model.VALID_FRAMES``), independent
    of the search mode (system-bar.md D17)."""

    STANDARD = "standard"
    ADITYA = "aditya"
    SIDEREAL = "sidereal"


@dataclass(frozen=True)
class CustomAyanamsa:
    """The id-255 definition (``core.custom_ayanamsa_settings.read``)."""

    value_deg: float
    year: int


@dataclass(frozen=True)
class SearchSystem:
    """Invariant (checked in ``__post_init__``): ``custom_ayanamsa`` is set
    exactly when ``ayanamsa_id == 255``."""

    mode: Mode
    ayanamsa_id: int
    house_system: str  # human key, as settings store it ("campanus")
    cot_planet_order: CotPlanetOrder
    hd_frame: HdFrame
    custom_ayanamsa: CustomAyanamsa | None = None

    def __post_init__(self) -> None:
        if (self.ayanamsa_id == CUSTOM_AYANAMSA_ID) != (
            self.custom_ayanamsa is not None
        ):
            raise InvariantError(
                "invariant: custom_ayanamsa is set exactly when ayanamsa_id is "
                f"{CUSTOM_AYANAMSA_ID} (ayanamsa_id={self.ayanamsa_id}, "
                f"custom_ayanamsa={self.custom_ayanamsa})"
            )

    @classmethod
    def from_frame(cls, frame: ChartFrame, settings: SettingsView) -> SearchSystem:
        """The default system: the resolved frame (mode, ayanamsa with its
        nakshatra coords as one id, house system), the HD page's frame
        (``hd_frame_for(mode, HD level)``, D18), ``cot.planet_order`` and the
        custom ayanamsa from ``settings``. Never raises: the frame is
        already validated."""
        order_key = FIELD_SETTINGS[Field.COT_PLANET_ORDER]
        order = settings.get(order_key, registry_default(order_key))
        if order not in _values(CotPlanetOrder):
            order = registry_default(order_key)
        custom = None
        if frame.ayanamsa_id == CUSTOM_AYANAMSA_ID:
            _name, value_deg, year = custom_ayanamsa_settings.read(settings)
            custom = CustomAyanamsa(value_deg, year)
        return cls(
            mode=Mode(frame.mode),
            ayanamsa_id=search_ayanamsa_id(frame.ayanamsa_id, frame.nakshatra_coords),
            house_system=frame.house_system,
            cot_planet_order=CotPlanetOrder(order),
            hd_frame=HdFrame(hd_frame_for(frame.mode, frame.hd_experience_level)),
            custom_ayanamsa=custom,
        )

    def with_values(self, given: Mapping[Field, object]) -> SearchSystem:
        """This system with ``given`` fields replaced (a query's ``search_system.*``
        options, the panel's pinned fields). Validated like ``ChartFrame.resolve``
        validates an argument; raises ``BadSystemError`` naming the valid values
        (ayanamsa: ``AYANAMSA_OPTIONS`` ids minus ``REFUSED_AYANAMSA_IDS``).

        Switching to id 255 takes the definition the engine has installed
        (``libaditya.custom_ayanamsa``): no settings are at hand here, and the
        app and every CLI install the settings' definition before computing."""
        given_by_field: dict[Field, object] = {}
        for name, raw in given.items():
            try:
                given_by_field[Field(name)] = raw
            except ValueError:
                raise BadSystemError(str(name), raw, _values(Field)) from None

        def pick(field: Field, enum: type[E], current: E) -> E:
            return (
                _member(field, enum, given_by_field[field])
                if field in given_by_field
                else current
            )

        ayanamsa_id = (
            _ayanamsa_id(given_by_field[Field.AYANAMSA_ID])
            if Field.AYANAMSA_ID in given_by_field
            else self.ayanamsa_id
        )
        custom = self.custom_ayanamsa
        if ayanamsa_id != CUSTOM_AYANAMSA_ID:
            custom = None
        elif custom is None:
            from libaditya.custom_ayanamsa import get_custom_ayanamsa

            _name, value_deg, year = get_custom_ayanamsa()
            custom = CustomAyanamsa(float(value_deg), int(year))
        return replace(
            self,
            mode=pick(Field.MODE, Mode, self.mode),
            ayanamsa_id=ayanamsa_id,
            house_system=(
                _house_system(given_by_field[Field.HOUSE_SYSTEM])
                if Field.HOUSE_SYSTEM in given_by_field
                else self.house_system
            ),
            cot_planet_order=pick(
                Field.COT_PLANET_ORDER, CotPlanetOrder, self.cot_planet_order
            ),
            hd_frame=pick(Field.HD_FRAME, HdFrame, self.hd_frame),
            custom_ayanamsa=custom,
        )

    def describe(self, sources: Mapping[Field, str]) -> dict[str, dict[str, object]]:
        """``{field: {"value", "source"}}`` for the capability echo; source is
        ``query`` or ``default``."""
        return {
            field.value: {
                "value": _scalar(getattr(self, field.value)),
                "source": sources.get(field, "default"),
            }
            for field in Field
        }


def _values(enum: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum)


def _scalar(value: object) -> Scalar:
    """A field value as a plain JSON scalar (a ``StrEnum`` member as its str)."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (int, float, str)):
        return value
    raise InvariantError(f"invariant: search-system values are scalars, got {value!r}")


def valid_ayanamsa_ids() -> tuple[int, ...]:
    """The ids a search system may take: the app's list, minus the refused ones,
    each equatorial id preceded by its ecliptic counterpart."""
    return tuple(
        aid
        for app_id, _name, _cat, _tip in AYANAMSA_OPTIONS
        if app_id not in REFUSED_AYANAMSA_IDS
        for aid in (
            (ECLIPTIC_IDS_OF_APP[app_id], app_id)
            if app_id in ECLIPTIC_IDS_OF_APP
            else (app_id,)
        )
    )


def search_ayanamsa_id(app_ayanamsa_id: int, nakshatra_coords: str) -> int:
    """The app's ``zodiac.ayanamsa_id`` and ``zodiac.nakshatra_coords`` as one id:
    ecliptic coords turn an equatorial id into its ecliptic counterpart."""
    if nakshatra_coords == "equatorial":
        return app_ayanamsa_id
    return ECLIPTIC_IDS_OF_APP.get(app_ayanamsa_id, app_ayanamsa_id)


def engine_ayanamsa_id(ayanamsa_id: int) -> int:
    """The id the engine is handed for a search-system id (``ENGINE_AYANAMSA_IDS``)."""
    return ENGINE_AYANAMSA_IDS.get(ayanamsa_id, ayanamsa_id)


# Validation like ``ChartFrame.resolve`` on an argument: an integer string is
# an ayanamsa id, nothing else is coerced; a failure names the valid values.


def _ayanamsa_id(raw: object) -> int:
    valid_ids = valid_ayanamsa_ids()
    aid: int | None = None
    if isinstance(raw, int) and not isinstance(raw, bool):
        aid = raw
    elif isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        aid = int(raw)
    if aid is None or aid not in valid_ids:
        raise BadSystemError(Field.AYANAMSA_ID.value, raw, valid_ids)
    return aid


def _house_system(raw: object) -> str:
    if not isinstance(raw, str) or raw not in HOUSE_SYSTEM_CODES:
        raise BadSystemError(
            Field.HOUSE_SYSTEM.value, raw, tuple(sorted(HOUSE_SYSTEM_CODES))
        )
    return raw


def _member(field: Field, enum: type[E], raw: object) -> E:
    if not isinstance(raw, str) or raw not in _values(enum):
        raise BadSystemError(field.value, raw, _values(enum))
    return enum(raw)


# --------------------------------------------------------------- projections

#: A normaliser maps the read fields of a system to the projection's fields:
#: it may drop fields (a value they cannot change) or collapse several into a
#: derived one (``custom_ayanamsa`` is added by ``project`` itself). Pure; depends only on the extractor's ``reads``.
Normaliser = Callable[[SearchSystem, Mapping[str, Scalar]], Mapping[str, Scalar]]


@dataclass(frozen=True)
class Projection:
    """An extractor's slice of a system. ``fields`` is sorted by name."""

    extractor_id: str
    fields: tuple[tuple[str, Scalar], ...]

    @property
    def key(self) -> str:
        """The canonical JSON encoding (module docstring)."""
        return json.dumps(
            {
                name: round(value, 6) if isinstance(value, float) else value
                for name, value in self.fields
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def value(self, name: str) -> Scalar:
        """A field the projection holds. ``InvariantError`` if absent: the
        extractor reads a field it did not declare."""
        for field_name, value in self.fields:
            if field_name == name:
                return value
        raise InvariantError(
            f"invariant: extractor {self.extractor_id!r} reads {name!r}, "
            f"which its projection does not hold ({self.key})"
        )

    def value_or_neutral(self, name: Field) -> Scalar:
        """The field, or ``NEUTRAL[name]`` when a normaliser dropped it or the
        extractor does not read it. In the invariance harness the projection
        holds every field, so an unread field the engine is handed this way is
        checked inert like a dropped one."""
        for field_name, value in self.fields:
            if field_name == name.value:
                return value
        if name not in NEUTRAL:
            raise InvariantError(
                f"invariant: extractor {self.extractor_id!r} reads {name.value!r}, "
                f"which has no NEUTRAL value and its projection does not hold"
            )
        return NEUTRAL[name]


def project(
    system: SearchSystem,
    extractor_id: str,
    reads: frozenset[Field],
    normalisers: tuple[Normaliser, ...],
) -> Projection:
    """Take ``reads`` from ``system``, apply ``normalisers`` in order, then add
    ``custom_ayanamsa`` when ``ayanamsa_id`` survived and is 255."""
    fields: Mapping[str, Scalar] = {
        field.value: _scalar(getattr(system, field.value)) for field in reads
    }
    for normalise in normalisers:
        fields = normalise(system, fields)
    out = dict(fields)
    if out.get(Field.AYANAMSA_ID.value) == CUSTOM_AYANAMSA_ID:
        custom = system.custom_ayanamsa
        if custom is None:
            raise InvariantError(
                "invariant: a system with ayanamsa 255 carries its definition"
            )
        out["custom_ayanamsa"] = encode_custom_ayanamsa(custom)
    return Projection(extractor_id, tuple(sorted(out.items())))


def encode_custom_ayanamsa(custom: CustomAyanamsa) -> str:
    """``"<value_deg>@<year>"``, the value rounded like every projection float."""
    return f"{round(custom.value_deg, 6)!r}@{custom.year}"


def _read(fields: Mapping[str, Scalar], field: Field, normaliser: str) -> Scalar:
    """A field a normaliser decides on. It must be among the extractor's reads,
    or the normaliser would depend on more than the reads."""
    if field.value not in fields:
        raise InvariantError(
            f"invariant: {normaliser} decides on {field.value!r}, "
            "so the extractor using it must read it"
        )
    return fields[field.value]


def _without(fields: Mapping[str, Scalar], *names: str) -> dict[str, Scalar]:
    return {name: value for name, value in fields.items() if name not in names}


# The stock normalisers. Each names the code fact it rests on; the invariance
# test (test/test_chart_search_invariance.py) checks it.


def drop_ayanamsa_unless_sidereal(
    system: SearchSystem, fields: Mapping[str, Scalar]
) -> Mapping[str, Scalar]:
    """Signs, houses, dignity, retinue, CoT placement: ``build_chart_from_params``
    bakes the ayanamsa in only through ``sysflg=SID`` (``mode_to_circle_sysflg``)."""
    if (
        _read(fields, Field.MODE, "drop_ayanamsa_unless_sidereal")
        == Mode.SIDEREAL.value
    ):
        return fields
    return _without(fields, Field.AYANAMSA_ID.value)


def collapse_hd_frame(
    system: SearchSystem, fields: Mapping[str, Scalar]
) -> Mapping[str, Scalar]:
    """Human Design: ``ayanamsa_id`` is kept only when ``hd_frame`` is
    ``sidereal`` (``build_hd_model`` reads it for that frame alone). The key is
    the one the old ``(mode, hd_experience_level)`` collapse wrote, so rows
    stored before ``hd_frame`` became a field stay valid."""
    if _read(fields, Field.HD_FRAME, "collapse_hd_frame") == HdFrame.SIDEREAL.value:
        return fields
    return _without(fields, Field.AYANAMSA_ID.value)
