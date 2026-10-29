# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The calculation input every capability takes (AIC plan 2, W4).

A chart on screen is often not a file: "Now", edited, time-adjusted and
AI-made charts have no path (``core/chart_factory.py:98-110``), and the
selected varga or an ascendant override change what the panels show. So a
capability never takes "a path"; it takes a ``CalculationInput``: the chart's
authoritative moment and place, the frame (preferences), and the view state.

- **Frame** values are preferences. Resolution: explicit argument, then the
  user's saved settings (``SettingsView``), then the factory default. Each
  value's source is recorded (Lorris, 2026-10-01: tools follow the Settings tab).
- **View** values are what is on screen now (varga, ascendant override, Human
  Design, reference instant). They are never read from the saved settings: the
  caller passes them (plan 3's capture fills them from the live app); the
  ``--tool`` command line takes the varga and the Human Design mode from the
  running app's live frame when no flag is given (``resolve_view``, shared by
  ``--tool``, the AI Tools tab and the CLIs).
- **Human Design** (``view.human_design``): the app's active chart is then the
  -88 Design chart (``build_chart``, ``design_mode``, ``chart_display``).

``from_file`` reads a chart file read-only (``canonicalize=False``, td-tw7hq).
``build_chart`` builds through ``core.chart_factory.build_chart_from_params``,
the same call ``ChartManager.load_chart`` makes, so tool and GUI build one way.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple

from core.capabilities.settings_view import (
    SOURCE_ARGUMENT,
    SOURCE_FACTORY,
    SOURCE_LIVE,
    SettingsView,
)

VALID_MODES = ("aditya", "tropical_classic", "sidereal")
NAKSHATRA_COORDS = ("neither", "equatorial")  # ui/settings_tab.py:2027-2028

# Frame key -> (settings key, factory default). The default is the settings
# registry's (SPEC-SET-003): one declaration per key.
from core.settings_registry import default as _registry_default
from core.settings_registry import valid as _registry_valid

# The frame keys: the six frame settings plus the Human Design level (a
# fallback-only registry entry, absent from DEFAULT_SETTINGS, that gates the
# Design chart's mode). The one list: FRAME_SETTINGS, the catalog's
# COMMON_INPUT_SCHEMA frame entries and its COMMON_SETTING_ARGS derive from it.
FRAME_KEYS = (
    ("mode", "zodiac.mode"),
    ("ayanamsa_id", "zodiac.ayanamsa_id"),
    ("house_system", "zodiac.house_system"),
    ("nakshatra_coords", "zodiac.nakshatra_coords"),
    ("show_outer_planets", "chart.show_outer_planets"),
    ("use_western_names", "zodiac.use_western_names"),
    ("hd_experience_level", "ui.hd_experience_level"),
)
FRAME_PREFERENCES = {name: (key, _registry_default(key)) for name, key in FRAME_KEYS}
FRAME_EXTRA_SETTINGS = {"hd_experience_level": FRAME_PREFERENCES["hd_experience_level"]}
FRAME_SETTINGS = {
    name: value
    for name, value in FRAME_PREFERENCES.items()
    if name not in FRAME_EXTRA_SETTINGS
}
HD_LEVELS = ("beginner", "advanced")


class InputError(ValueError):
    """A calculation input that cannot describe a chart (bad value, bad file)."""


def _unix_to_jd(seconds: float) -> float:
    return seconds / 86400.0 + 2440587.5


def _factory(name: str):
    """The factory value of a frame option: the settings registry's (V-13,
    SPEC-SET-003: one declaration per key, never a copied literal)."""
    return FRAME_PREFERENCES[name][1]


@dataclass
class ChartFrame:
    mode: str = _factory("mode")
    ayanamsa_id: int = _factory("ayanamsa_id")
    house_system: str = _factory("house_system")  # human key, as settings store it
    nakshatra_coords: str = _factory("nakshatra_coords")
    show_outer_planets: bool = _factory("show_outer_planets")
    use_western_names: bool = _factory("use_western_names")
    hd_experience_level: str = _factory(
        "hd_experience_level"
    )  # gates the -88 Design chart's mode
    sources: Dict[str, str] = field(default_factory=dict)

    @property
    def house_system_code(self) -> str:
        from core.house_systems import get_house_system_code

        return get_house_system_code(self.house_system)

    @classmethod
    def resolve(cls, settings: SettingsView, **explicit) -> "ChartFrame":
        """Argument > saved setting > factory, with the GUI's own validation:
        an unknown mode or house system falls back as the GUI does
        (``apps/core_gui_qt.py:465-481``), and the western-names choice is
        the one the app shows for the resolved mode (see the label set note
        below: the boot clamp ``:507-512`` and ``ZodiacSettingsManager.set_mode``)."""
        return cls.resolve_entries(settings, **explicit)[0]

    @classmethod
    def resolve_entries(
        cls, settings: SettingsView, **explicit
    ) -> Tuple["ChartFrame", Dict[str, Tuple[Any, str]]]:
        """``resolve``, plus ``{name: (value, source)}`` for each frame entry:
        the value the frame holds and the layer that decided it (SPEC-SET-003
        W9 fix4 R4-1; the settings echo takes it as is, ``_used_values``).

        - A value ``resolve`` replaced by its fallback (a wrong-type or
          unknown choice, a container where a boolean is stored, an HD level
          the app reads as Beginner) carries ``factory``, whatever layer held
          the discarded value and whatever the mode's source is.
        - A western-names value the label-set clamp changed carries the
          source of the mode that decided it (also after a fallback).
        - Any other value carries the layer it came from (a scalar boolean
          read by its truth value included: that layer's value decided)."""
        from core.house_systems import HOUSE_SYSTEM_CODES

        unknown = set(explicit) - set(FRAME_PREFERENCES)
        if unknown:
            raise InputError(f"unknown frame option(s): {sorted(unknown)}")
        values, sources = {}, {}
        for name, (key, fallback) in FRAME_PREFERENCES.items():
            values[name], sources[name] = settings.resolve(
                key, explicit.get(name), fallback
            )

        # A saved or live value of the wrong TYPE (a list, a dict, a number
        # where a name is stored) is invalid like an unknown name: it falls
        # back to the factory value, never reaches a membership test it
        # cannot take (a list in the house-system dict raised TypeError in
        # every frame CLI) and is never echoed as used (SPEC-SET-003 W9 fix3
        # I1, the ayanamsa rule of fix2 N2 for every frame key).
        def _choice(name, allowed):
            return isinstance(values[name], str) and values[name] in allowed

        for name in ("show_outer_planets", "use_western_names"):
            # booleans: the app reads a scalar by its truth value ("yes" ->
            # true, as SettingsManager.get hands it over); a container is no
            # choice at all
            if sources[name] != SOURCE_ARGUMENT and isinstance(
                values[name], (list, tuple, dict, set)
            ):
                values[name], sources[name] = _factory(name), SOURCE_FACTORY

        if not _choice("mode", VALID_MODES):
            if sources["mode"] == SOURCE_ARGUMENT:
                raise InputError(f"mode must be one of {VALID_MODES}")
            values["mode"], sources["mode"] = _factory("mode"), SOURCE_FACTORY
        if not _choice("house_system", HOUSE_SYSTEM_CODES):
            if sources["house_system"] == SOURCE_ARGUMENT:
                raise InputError(
                    f"house_system must be one of {sorted(HOUSE_SYSTEM_CODES)}"
                )
            values["house_system"], sources["house_system"] = (
                _factory("house_system"),
                SOURCE_FACTORY,
            )
        if sources["ayanamsa_id"] == SOURCE_ARGUMENT:
            try:
                values["ayanamsa_id"] = int(values["ayanamsa_id"])
            except (TypeError, ValueError):
                raise InputError(
                    f"ayanamsa_id must be an integer, got {values['ayanamsa_id']!r}"
                )
        elif not _registry_valid("zodiac.ayanamsa_id", values["ayanamsa_id"]):
            # A saved (or live) ayanamsa that is not an integer of the
            # registry's choices (98.5, "98", -1, a non-number) falls back
            # like an invalid mode: no truncation, no string coercion
            # (SPEC-SET-003 W9 fix2 N2: the echo names the value used).
            values["ayanamsa_id"], sources["ayanamsa_id"] = (
                _factory("ayanamsa_id"),
                SOURCE_FACTORY,
            )
        if not _choice("nakshatra_coords", NAKSHATRA_COORDS):
            if sources["nakshatra_coords"] == SOURCE_ARGUMENT:
                raise InputError(f"nakshatra_coords must be one of {NAKSHATRA_COORDS}")
            values["nakshatra_coords"], sources["nakshatra_coords"] = (
                _factory("nakshatra_coords"),
                SOURCE_FACTORY,
            )
        values["show_outer_planets"] = bool(values["show_outer_planets"])
        hd_fallback = False  # a string level the app reads as Beginner
        if not _choice("hd_experience_level", HD_LEVELS):
            if sources["hd_experience_level"] == SOURCE_ARGUMENT:
                raise InputError(f"hd_experience_level must be one of {HD_LEVELS}")
            if not isinstance(values["hd_experience_level"], str):
                sources["hd_experience_level"] = SOURCE_FACTORY
            elif values["hd_experience_level"] != "beginner":
                hd_fallback = True
            # the app reads anything but "advanced" as Beginner (hd_manager)
            values["hd_experience_level"] = "beginner"
        # The label set (SPEC-MODE-001). A western-names value belongs to the
        # mode it was recorded with: the running app's mode for a live value,
        # the mode the app boots with (saved, else factory) for a saved or
        # factory value. With that mode it applies as the app shows it (Beginner
        # still clamps it, as the boot clamp does). With another mode the GUI
        # would first have to switch modes, and every mode switch the user can
        # make (toolbar, menus, Alt+S, the sidereal toggle, the panels' mode
        # buttons: ZodiacSettingsManager.set_mode) sets the new mode's own
        # names at EVERY experience level; Beginner additionally clamps any
        # other mode change (_clamp_western_names_on_mode_change). So the value
        # becomes the resolved mode's own names. An argument always wins, and
        # so does a value the terminal user chose for the tools on purpose
        # (``--set``: ``command``; ``settings.py set``: ``cli``; SPEC-SET-003
        # W6): like an argument, it is never the app's recorded state.
        clamped = False  # the label-set clamp changed the western names
        if sources["use_western_names"] not in (SOURCE_ARGUMENT, "command", "cli"):
            native = values["mode"] != "aditya"
            factory_mode = _factory("mode")
            if sources["use_western_names"] == SOURCE_LIVE:
                recorded = settings.live_value(
                    "zodiac.mode", settings.stored_value("zodiac.mode", factory_mode)
                )
            else:
                recorded = settings.stored_value("zodiac.mode", factory_mode)
            if recorded not in VALID_MODES:
                recorded = factory_mode  # the GUI's boot fallback
            if (
                recorded != values["mode"]
                or settings.get(
                    "ui.experience_level", _registry_default("ui.experience_level")
                )
                != "advanced"
            ):
                if bool(values["use_western_names"]) != native:
                    clamped = True
                values["use_western_names"] = native
        values["use_western_names"] = bool(values["use_western_names"])
        decided = dict(sources)
        if hd_fallback:
            # the frame keeps the saved layer (fix3 decision); the value used
            # is the factory one
            decided["hd_experience_level"] = SOURCE_FACTORY
        if clamped:
            decided["use_western_names"] = sources["mode"]
        frame = cls(**values, sources=sources)
        return frame, {name: (values[name], decided[name]) for name in values}


@dataclass
class ChartMoment:
    jd_ut: float
    latitude: float
    longitude: float
    utc_offset_hours: float = 0.0
    title: str = ""
    kind: str = "chart"
    source_path: Optional[str] = None  # informational; never re-read


@dataclass
class ViewState:
    varga: int = 1
    ascendant_override: Optional[int] = None  # sign index 0-11
    human_design: bool = False
    reference_jd: Optional[float] = None  # "now" for current rows


# View values the running app publishes (live_state, LiveFrameManager): a tool
# given no value shows what the screen shows. Never from the saved file (a view
# value is not a preference); a factory-only SettingsView has no live values.
VIEW_DEFAULTS = {
    "varga": 1,
    "ascendant_override": None,
    "human_design": False,
    "reference_jd": None,
}
LIVE_VIEW_KEYS = {"varga": "view.varga", "human_design": "view.human_design"}


def view_value(name: str, settings: SettingsView, explicit: Any = None) -> Any:
    """One view value: ``explicit`` if given (not None), else the running
    app's live value (``view.varga``, ``view.human_design``) when it has the
    right type, else the factory value. The one rule for every entry point:
    ``--tool``, the AI Tools tab's in-process capabilities and the CLIs."""
    if name not in VIEW_DEFAULTS:
        raise InputError(f"unknown view option {name!r}")
    if explicit is not None:
        return explicit
    key = LIVE_VIEW_KEYS.get(name)
    if key is not None:
        value = settings.live_value(key)
        if name == "varga" and isinstance(value, int) and not isinstance(value, bool):
            return value
        if name == "human_design" and isinstance(value, bool):
            return value
    return VIEW_DEFAULTS[name]


def resolve_view(settings: SettingsView, **explicit) -> "ViewState":
    """The ViewState: argument > live app > factory, per value (``view_value``)."""
    unknown = set(explicit) - set(VIEW_DEFAULTS)
    if unknown:
        raise InputError(f"unknown view option(s): {sorted(unknown)}")
    return ViewState(
        **{
            name: view_value(name, settings, explicit.get(name))
            for name in VIEW_DEFAULTS
        }
    )


@dataclass
class CalculationInput:
    chart: ChartMoment
    frame: ChartFrame
    view: ViewState = field(default_factory=ViewState)
    settings: Dict[str, Any] = field(default_factory=dict)  # SettingsView.describe()

    def __post_init__(self):
        if self.view.reference_jd is None:
            self.view.reference_jd = _unix_to_jd(time.time())

    # ------------------------------------------------------------ adapters

    @classmethod
    def from_file(
        cls,
        path: str,
        settings: Optional[SettingsView] = None,
        view: Optional[ViewState] = None,
        **frame,
    ) -> "CalculationInput":
        """Read a .chtk or .toml read-only and resolve the frame."""
        from core.chart_loading import load_birth_data_and_jd

        settings = settings or SettingsView.load()
        try:
            # THE app loading path (ChartManager.load_chart): same JD.
            birth, jd = load_birth_data_and_jd(str(path), canonicalize=False)
        except Exception as exc:
            raise InputError(f"cannot read chart {path}: {exc}") from exc
        moment = ChartMoment(
            jd_ut=float(jd),
            latitude=float(birth.get("latitude", 0.0)),
            longitude=float(birth.get("longitude", 0.0)),
            # Both key spellings exist in the codebase; an explicit 0.0 is valid.
            utc_offset_hours=float(
                birth["utc_offset_hours"]
                if birth.get("utc_offset_hours") is not None
                else (birth.get("utcoffset") or 0.0)
            ),
            title=str(birth.get("name", "") or ""),
            source_path=str(path),
        )
        return cls(
            chart=moment,
            frame=ChartFrame.resolve(settings, **frame),
            view=view or ViewState(),
            settings=settings.describe(),
        )

    @classmethod
    def from_chart_state(
        cls,
        *,
        jd_ut,
        latitude,
        longitude,
        utc_offset_hours,
        title="",
        source_path=None,
        mode,
        ayanamsa_id,
        house_system,
        nakshatra_coords=_factory("nakshatra_coords"),
        show_outer_planets=_factory("show_outer_planets"),
        use_western_names=_factory("use_western_names"),
        hd_experience_level=_factory("hd_experience_level"),
        varga=1,
        ascendant_override=None,
        human_design=False,
        reference_jd=None,
    ) -> "CalculationInput":
        """The live app's values, every one explicit (plan 3's capture)."""
        frame = ChartFrame.resolve(
            SettingsView.load(factory_only=True),
            mode=mode,
            ayanamsa_id=ayanamsa_id,
            house_system=house_system,
            nakshatra_coords=nakshatra_coords,
            show_outer_planets=show_outer_planets,
            use_western_names=use_western_names,
            hd_experience_level=hd_experience_level,
        )
        return cls(
            chart=ChartMoment(
                jd_ut=float(jd_ut),
                latitude=float(latitude),
                longitude=float(longitude),
                utc_offset_hours=float(utc_offset_hours or 0.0),
                title=title,
                source_path=source_path,
            ),
            frame=frame,
            view=ViewState(
                varga=int(varga or 1),
                ascendant_override=ascendant_override,
                human_design=bool(human_design),
                reference_jd=reference_jd,
            ),
            settings={"status": "live", "path": None},
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CalculationInput":
        try:
            frame = dict(data["frame"])
            sources = frame.pop("sources", {})
            return cls(
                chart=ChartMoment(**data["chart"]),
                frame=ChartFrame(**frame, sources=sources),
                view=ViewState(**data.get("view", {})),
                settings=dict(data.get("settings", {})),
            )
        except (KeyError, TypeError) as exc:
            raise InputError(f"malformed calculation input: {exc}") from exc

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    # --------------------------------------------------------------- charts

    def design_mode(self) -> str:
        """The mode of the -88 Design chart (``HDManager.design_chart_mode``):
        Beginner Human Design level gives tropical_classic, Advanced the
        frame's mode (``core.hd_model.design_chart_mode_for``)."""
        from core.hd_model import design_chart_mode_for

        return design_chart_mode_for(self.frame.mode, self.frame.hd_experience_level)

    def chart_display(self):
        """``(mode, use_western_names)`` the chart drawings label with. In
        Human Design mode the app draws the Design chart in its own mode and
        that mode's own names (``ChartGUI``'s display override); otherwise the
        frame's mode and label set. The side panels (avastha, karakas...) keep
        the frame's mode, as the app's panels read ``state.aditya_mode``."""
        from core.hd_model import chart_display_for

        return chart_display_for(
            self.frame.mode,
            self.frame.use_western_names,
            self.design_mode() if self.view.human_design else None,
        )

    def build_chart(self, mode: Optional[str] = None, natal: bool = False):
        """The Chart the GUI would build for this input (same factory call as
        ``ChartManager.load_chart``). ``mode`` overrides the frame's mode for
        panels that rebuild in another frame (avastha, strength).

        With ``view.human_design`` the app's active chart is the -88 Design
        chart (``ChartGUI._recalculate_chart`` -> ``build_design_chart``): the
        Design instant, built in ``design_mode()`` (``mode`` still overrides),
        the chart ayanamsa and the house system. Every panel reading the
        active chart reads it. ``natal=True`` gives the birth chart whatever
        the view: the dasha side, Zodiacal Releasing and planetary ages read
        the chart's birth data (``ChartGUI.current_chart_data``), never the
        Design chart (the HD dasha seeds its Moon from the Design date
        itself, ``get_dasha_params``)."""
        if self.view.human_design and not natal:
            from core.sun_degree_shift import build_design_chart

            return build_design_chart(
                self.chart.jd_ut,
                self.chart.latitude,
                self.chart.longitude,
                mode=mode or self.design_mode(),
                utcoffset=self.chart.utc_offset_hours,
                ayanamsa=self.frame.ayanamsa_id,
                name=self.chart.title,
                hsys=self.frame.house_system_code,
            )
        from core.chart_factory import build_chart_from_params

        return build_chart_from_params(
            jd=self.chart.jd_ut,
            lat=self.chart.latitude,
            lon=self.chart.longitude,
            mode=mode or self.frame.mode,
            name=self.chart.title,
            utcoffset=self.chart.utc_offset_hours,
            ayanamsa=self.frame.ayanamsa_id,
            hsys=self.frame.house_system_code,
        )

    def birth_data(self) -> Dict[str, Any]:
        """The minimal canonical birth_data dict the dasha and retinue helpers
        read (jd, place, offset, name), built from the input, never a file."""
        return {
            "julian_day": self.chart.jd_ut,
            "latitude": self.chart.latitude,
            "longitude": self.chart.longitude,
            "utc_offset_hours": self.chart.utc_offset_hours,
            "name": self.chart.title,
        }


@dataclass(frozen=True)
class LibraryInput:
    """What a library-scope capability runs against (``Capability.scope ==
    "library"``, design find-chart §4.8 D1): no chart and no view, only the
    resolved frame (e.g. ``search_charts``' default search system) and the
    settings it came from. ``catalog.invoke(id, None)`` builds it."""

    frame: ChartFrame
    settings: SettingsView

    @classmethod
    def resolve(cls, settings: SettingsView) -> "LibraryInput":
        """The frame resolved like a chart's (saved/live > factory, no argument)."""
        return cls(frame=ChartFrame.resolve(settings), settings=settings)

    def to_dict(self) -> Dict[str, Any]:
        """The envelope's ``input``, shaped like ``CalculationInput.to_dict``:
        ``{"chart": None, "frame": {...}, "settings": {...}}``."""
        return {
            "chart": None,
            "frame": asdict(self.frame),
            "settings": self.settings.describe(),
        }
