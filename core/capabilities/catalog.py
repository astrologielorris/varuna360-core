# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The capability catalog (SPEC-AIC-001 §4.4, AIC plan 2 W6).

A ``Capability`` is one shared calculation with its schemas. ``invoke`` is the
only way to run one: it resolves the capability's options (argument > saved
settings > factory, like the chart frame), validates them, runs the shared
function and wraps the answer in the result envelope. The GUI panel, the
``--tool`` CLI and (plan 4) the MCP tool all end up calling the same ``run``.

Static registry, no dynamic import: ``core/capabilities/registry.py`` imports
every capability module explicitly, so frozen builds find them without hidden
imports and the Lite manifest gate sees them.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple, Union

from core.capabilities import result as _result
from core.capabilities.inputs import (
    FRAME_PREFERENCES,
    VIEW_DEFAULTS,
    CalculationInput,
    InputError,
    LibraryInput,
)
from core.capabilities.settings_view import (
    SOURCE_ARGUMENT, SOURCE_FACTORY, SettingsView)

EDITION_CORE = "core"
EDITION_PRO = "pro"

# What a capability runs against (design find-chart §4.8, D1): one chart (a
# CalculationInput) or the chart library (a LibraryInput, no chart). Library
# capabilities stay out of the default listings, so the task MCP (SPEC-AIC-001
# D-13: every task has a chart; --blind) and the AI Tools adapter never see them.
SCOPE_CHART = "chart"
SCOPE_LIBRARY = "library"
Scope = Literal["chart", "library"]


class OptionError(ValueError):
    """A capability option that fails its schema. ``error_type``, when given,
    is the code it is reported with. Without one the attribute is ABSENT, not
    defaulted: each reader picks its own fallback with
    ``getattr(exc, "error_type", ...)`` (``invoke``'s run errors: ``bad_input``;
    the Pro tool adapter's option refusals: ``bad_option``), and a class
    default would silently override every one of them."""

    def __init__(self, message: str, error_type: Optional[str] = None) -> None:
        super().__init__(message)
        if error_type is not None:
            self.error_type = error_type


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    description: str
    run: Callable[..., Dict[str, Any]]  # (inp, values[, sources]) -> data
    # JSON Schema (object) for the capability's own options. Each property may
    # carry "x-settings-key": the saved setting it follows when not given.
    options_schema: Dict[str, Any] = field(default_factory=lambda: {
        "type": "object", "properties": {}, "additionalProperties": False})
    output_schema: Dict[str, Any] = field(default_factory=lambda: {"type": "object"})
    schema_version: int = 1
    edition: str = EDITION_CORE
    sources: Tuple[Tuple[str, str], ...] = ()   # (file, symbol) the data comes from
    # True: ``run(inp, values, sources)`` also receives each option's source
    # (a capability that needs to know whether an option was an argument).
    run_with_sources: bool = False
    # SPEC-SET-003 §4.4: every option classified (core/capabilities/setting_args.py):
    # a per-call input, a setting, a dict member of one or a side mapping.
    setting_args: Dict[str, Tuple] = field(default_factory=dict)
    # key -> the properties naming it, winner first (two properties, one key).
    setting_precedence: Dict[str, Tuple[str, ...]] = field(default_factory=dict)
    # "chart": ``run`` takes a CalculationInput; "library": a LibraryInput.
    scope: Scope = SCOPE_CHART
    # How the model should use the tool (model-facing only, never shown to the
    # user: the tool chooser's tooltip is ``description``). Appended to the
    # AI task tool's and the MCP tool's description.
    guidance: str = ""


_REGISTRY: Dict[str, Capability] = {}


def register(cap: Capability) -> Capability:
    if cap.id in _REGISTRY and _REGISTRY[cap.id] is not cap:
        raise ValueError(f"capability {cap.id!r} registered twice")
    if cap.edition not in (EDITION_CORE, EDITION_PRO):
        raise ValueError(f"capability {cap.id!r}: bad edition {cap.edition!r}")
    if cap.scope not in (SCOPE_CHART, SCOPE_LIBRARY):
        raise ValueError(f"capability {cap.id!r}: bad scope {cap.scope!r}")
    _REGISTRY[cap.id] = cap
    return cap


def capabilities(
    edition: Optional[str] = None, scope: Optional[Scope] = SCOPE_CHART
) -> List[Capability]:
    """Registered capabilities in deterministic (id) order. ``edition='lite'``
    hides Pro capabilities; ``scope`` keeps one scope (``None``: every scope).
    The default lists chart scope only, as before library scope existed."""
    from core.capabilities import registry  # noqa: F401  (populates _REGISTRY)
    caps = sorted(_REGISTRY.values(), key=lambda c: c.id)
    if edition == "lite":
        caps = [c for c in caps if c.edition == EDITION_CORE]
    if scope is not None:
        caps = [c for c in caps if c.scope == scope]
    return caps


def get(capability_id: str) -> Capability:
    from core.capabilities import registry  # noqa: F401
    try:
        return _REGISTRY[capability_id]
    except KeyError:
        raise OptionError(
            f"unknown capability {capability_id!r}; "
            f"known: {[c.id for c in capabilities(scope=None)]}"
        ) from None


# ---------------------------------------------------------------- options

_TYPES = {"string": str, "integer": int, "number": (int, float),
          "boolean": bool, "array": list, "object": dict}


def _check(name: str, value: Any, prop: Dict[str, Any]) -> Any:
    kind = prop.get("type")
    if kind == "integer" and isinstance(value, str) and value.lstrip("-").isdigit():
        value = int(value)
    if kind == "number" and isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            pass
    if kind == "boolean" and isinstance(value, str) and value.lower() in (
            "true", "false", "1", "0", "yes", "no"):
        value = value.lower() in ("true", "1", "yes")
    expected = _TYPES.get(kind)
    if expected is not None and (not isinstance(value, expected)
                                 or (kind in ("integer", "number")
                                     and isinstance(value, bool))):
        raise OptionError(f"option {name!r} must be {kind}, got {value!r}")
    if "enum" in prop and value not in prop["enum"]:
        raise OptionError(f"option {name!r} must be one of {prop['enum']}, "
                          f"got {value!r}")
    for bound, test in (("minimum", lambda v, b: v >= b),
                        ("maximum", lambda v, b: v <= b)):
        if bound in prop and not test(value, prop[bound]):
            raise OptionError(f"option {name!r} {bound} is {prop[bound]}")
    return value


def _valid_siblings(unknown, props) -> str:
    """For an unknown dotted option (``search_system.hd_experience_level``),
    the valid options under the same prefix, so a renamed one names its
    successor; empty when there are none."""
    prefixes = {name.rpartition(".")[0] + "." for name in unknown if "." in name}
    valid = sorted(n for n in props if any(n.startswith(p) for p in prefixes))
    return f"; valid: {valid}" if valid else ""


def resolve_options(
    cap: Capability, given: Optional[Dict[str, Any]], settings: SettingsView
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Argument > live value > saved setting (``x-settings-key``) > schema default. A saved
    setting that fails the schema falls back to the default, as the GUI's own
    readers do (e.g. ``DashaState.from_settings``); a bad argument is refused."""
    props = cap.options_schema.get("properties", {})
    given = dict(given or {})
    unknown = set(given) - set(props)
    if unknown:
        raise OptionError(
            f"unknown option(s) for {cap.id}: {sorted(unknown)}"
            + _valid_siblings(unknown, props)
        )
    values, sources = {}, {}
    # An option may apply only when other options hold given values
    # ("x-applies-when": {"dasa": [...]}, SPEC-JRD-001 §3.6). Those resolve after
    # the rest; an inapplicable one is not resolved, its setting not read and it
    # is not echoed, and asking for it as an argument is refused. A schema without
    # the key resolves exactly as before, in the same order.
    order = ([n for n, p in props.items() if "x-applies-when" not in p]
             + [n for n, p in props.items() if "x-applies-when" in p])
    for name in order:
        prop = props[name]
        # Presence, not value: an explicit null is still an argument.
        if prop.get("x-setting-only") and name in given:
            # SPEC-SET-003 D-9: settings are changed in the app, which every tool follows.
            raise OptionError(f"option {name!r} is a setting ({prop['x-settings-key']}): "
                              "change it in Settings, the tools follow it")
        when = prop.get("x-applies-when")
        if when and not all(values.get(k) in allowed for k, allowed in when.items()):
            if name in given:
                raise OptionError("option {!r} does not apply when {}".format(
                    name, ", ".join(f"{k} = {values.get(k)!r}" for k in when)))
            continue
        if given.get(name) is not None:
            values[name], sources[name] = _check(name, given[name], prop), SOURCE_ARGUMENT
            continue
        key = prop.get("x-settings-key")
        if key:
            raw, src = settings.resolve(key, None, prop.get("default"))
            try:
                values[name], sources[name] = _check(name, raw, prop), src
                continue
            except OptionError:
                pass
        if "default" in prop:
            values[name], sources[name] = copy.deepcopy(prop["default"]), SOURCE_FACTORY
        elif name in cap.options_schema.get("required", ()):
            raise OptionError(f"option {name!r} is required for {cap.id}")
        else:
            values[name], sources[name] = None, SOURCE_FACTORY
    return values, sources


# ----------------------------------------------------------------- invoke


def invoke(
    capability_id: str,
    inp: Union[CalculationInput, LibraryInput, None],
    options: Optional[Dict[str, Any]] = None,
    settings: Optional[SettingsView] = None,
) -> Dict[str, Any]:
    """Run one capability. Never raises: failures come back as an error
    envelope (``status: error``) naming the problem. ``inp=None`` is for a
    library-scope capability (invoke builds ``LibraryInput.resolve(settings)``);
    a chart-scope capability refuses it (``bad_input``)."""
    try:
        cap = get(capability_id)
    except OptionError as exc:
        return _result.error(capability_id, 0, inp, options, "unknown_capability", str(exc))
    settings = settings or SettingsView.load()
    if inp is None:
        if cap.scope != SCOPE_LIBRARY:
            return _result.error(
                cap.id,
                cap.schema_version,
                None,
                options,
                "bad_input",
                f"{cap.id} runs on a chart: give a calculation input",
            )
        try:
            inp = LibraryInput.resolve(settings)
        except InputError as exc:
            return _result.error(
                cap.id, cap.schema_version, None, options, "bad_input", str(exc)
            )
    try:
        values, sources = resolve_options(cap, options, settings)
    except OptionError as exc:
        return _result.error(cap.id, cap.schema_version, inp, options,
                             "bad_option", str(exc))
    echoed = {k: {"value": v, "source": sources[k]} for k, v in values.items()}
    try:
        from core.custom_ayanamsa_settings import KEYS, calculation_context
        ayanamsas = [inp.frame.ayanamsa_id] + [
            value for key, value in values.items() if "ayanamsa" in key]
        with calculation_context(settings, ayanamsas):
            if 255 in ayanamsas:
                from dataclasses import replace
                inp = replace(inp, settings=dict(inp.settings, custom_ayanamsa={
                    key: {"value": settings.get(key), "source": settings.source(key)}
                    for key in KEYS}))
            data = (cap.run(inp, values, sources) if cap.run_with_sources
                    else cap.run(inp, values))
    except (InputError, OptionError) as exc:
        # An option error may name its own type (e.g. invalid_combination).
        return _result.error(cap.id, cap.schema_version, inp, echoed,
                             getattr(exc, "error_type", "bad_input"), str(exc))
    except Exception as exc:  # a calculation failure is reported, never raised
        return _result.error(cap.id, cap.schema_version, inp, echoed,
                             "calculation_error", f"{type(exc).__name__}: {exc}")
    # A capability that resolves some options itself (for example
    # from a profile) reports their final value and source here.
    if isinstance(data, dict) and isinstance(data.get("resolved_options"), dict):
        echoed.update(data.pop("resolved_options"))
    envelope = _result.ok(cap.id, cap.schema_version, inp, echoed, data)
    return _result.compact_envelope(envelope) if values.get("compact") is True else envelope


# ------------------------------------------------------------ MCP export

# Chart, frame and view arguments every tool accepts (plan 4 turns these into
# MCP input schemas; plan 2 keeps them stable and tested). The frame entries
# come from the settings registry (SPEC-SET-003 §4.4): the six frame keys plus
# the Human Design level (inputs.FRAME_KEYS); their defaults stay out (a frame
# value follows the app), their descriptions are the catalog's own.
_FRAME_DESCRIPTIONS = {
    "mode": "Zodiac system. Default: the user's saved setting.",
    "ayanamsa_id": "Chart ayanamsa id for sidereal. Default: saved setting.",
    "house_system": "House system. Default: saved setting.",
    "use_western_names": ("Western sign names (Aries...) instead of the mode's own "
                          "label set. Default: what the app shows for the mode."),
    "hd_experience_level": ("Human Design level: the Design chart's mode. "
                            "Default: saved setting."),
}


def _frame_entry(name: str, key: str) -> Dict[str, Any]:
    from core.settings_registry import OMIT, option_schema
    # The chart ayanamsa is any id the engine knows: no enum (as before).
    return option_schema(key, name, default=OMIT,
                         enum=OMIT if name == "ayanamsa_id" else None,
                         description=_FRAME_DESCRIPTIONS.get(name))


COMMON_INPUT_SCHEMA: Dict[str, Any] = {
    "chart": {"type": "string",
              "description": "Path of a .chtk or .toml chart file (read only)."},
    **{name: _frame_entry(name, key) for name, (key, _d) in FRAME_PREFERENCES.items()},
    "varga": {"type": "integer", "minimum": 1,
              "description": "Divisional chart shown (1 = rashi)."},
    "ascendant_override": {"type": "integer", "minimum": 0, "maximum": 11},
    "human_design": {"type": "boolean"},
    "reference_jd": {"type": "number",
                     "description": "UT Julian Day used as 'now'. Default: current time."},
    "factory_defaults": {"type": "boolean",
                         "description": "Ignore the running app and the saved "
                                        "settings: factory defaults (arguments "
                                        "still win)."},
}
# The argument groups of the contract, from their one source: every frame
# preference (``FRAME_PREFERENCES``), every view value (``VIEW_DEFAULTS``) and
# the settings switch. ``varuna360 --tool`` (cli.py) and the AI Tools tab's
# in-process adapter (``run_capability_tool``) both read these, and
# COMMON_INPUT_SCHEMA must describe each (test_capability_catalog).
FRAME_ARGS = tuple(FRAME_PREFERENCES)
VIEW_ARGS = tuple(VIEW_DEFAULTS)
SETTINGS_ARGS = ("factory_defaults",)

# The common arguments classified like a capability's options (SPEC-SET-003
# §4.4): the frame entries are settings, the chart and view values inputs,
# factory_defaults a switch about settings (terminal only, W4c).
from core.capabilities.setting_args import INPUT as _INPUT, META as _META  # noqa: E402
from core.capabilities.setting_args import setting as _setting_row  # noqa: E402

COMMON_SETTING_ARGS: Dict[str, Tuple] = {
    "chart": _INPUT,
    **{name: _setting_row(key) for name, (key, _d) in FRAME_PREFERENCES.items()},
    **{name: _INPUT for name in VIEW_ARGS},
    "factory_defaults": _META,
}


# ------------------------------------------------- the external boundary
# SPEC-SET-003 D-9 (W4c): settings are not tool arguments. Every external
# entry point (``varuna360 --tool``, the AI task tools of both engines, the Pro
# AI Tools adapter) calls ``external_options`` before ``invoke``; the internal
# schema keeps its settings properties for the app's own callers (a panel's
# on-screen state, a capture replaying its frozen state).

def setting_properties(cap: Capability) -> Tuple[str, ...]:
    """The capability's properties that are settings (SETTING_ARGS rows)."""
    from core.capabilities.setting_args import is_setting
    props = cap.options_schema.get("properties", {})
    return tuple(n for n in props
                 if is_setting(cap.setting_args.get(n, ("input",)))
                 or "x-settings-key" in props[n])


def external_properties(cap: Capability) -> Dict[str, Any]:
    """The capability's own options an external caller may give (per-call
    inputs only), with their internal annotations."""
    settings = set(setting_properties(cap))
    return {n: p for n, p in cap.options_schema.get("properties", {}).items()
            if n not in settings}


def external_options(cap: Capability, given: Optional[Dict[str, Any]],
                     factory_defaults: bool = False) -> Dict[str, Any]:
    """``given`` checked at an external entry point: a setting property or a
    frame entry is refused (``bad_option``, argparse-style "not an option"),
    as is ``factory_defaults`` where the context has no factory route (the
    in-app AI and the Pro adapter answer in the app's or the capture's
    settings, INV-4b). Returns a copy."""
    given = dict(given or {})
    refused = set(setting_properties(cap)) | set(FRAME_ARGS)
    if not factory_defaults:
        refused |= set(SETTINGS_ARGS)
    bad = sorted(n for n in given if n in refused)
    if bad:
        raise OptionError(
            "not an option of {}: {} (settings follow the app; change "
            "them in Settings)".format(cap.id, ", ".join(bad)),
            "bad_option",
        )
    return given


def tool_schemas(
    edition: Optional[str] = None,
    factory_defaults: bool = True,
    scope: Optional[Scope] = SCOPE_CHART,
) -> List[Dict[str, Any]]:
    """One entry per capability of ``scope`` (default chart, ``None`` every
    scope): name, description and a JSON Schema input (the chart, the view
    values, the capability's per-call options, and ``factory_defaults`` for a
    terminal caller). A library capability takes no chart and no view value.
    No setting property and no frame entry (SPEC-SET-003 D-9): the frame and
    every setting follow the app."""
    out = []
    for cap in capabilities(edition, scope):
        library = cap.scope == SCOPE_LIBRARY
        common = [
            n
            for n in COMMON_INPUT_SCHEMA
            if n not in FRAME_ARGS
            and (factory_defaults or n not in SETTINGS_ARGS)
            and not (library and n not in SETTINGS_ARGS)
        ]
        props = {
            name: {
                k: v
                for k, v in copy.deepcopy(COMMON_INPUT_SCHEMA[name]).items()
                if not k.startswith("x-")
            }
            for name in common
        }
        for name, prop in external_properties(cap).items():
            props[name] = {k: v for k, v in prop.items() if not k.startswith("x-")}
        out.append(
            {
                "name": cap.id,
                "title": cap.title,
                "description": " ".join(filter(None, (cap.description, cap.guidance))),
                "inputSchema": {
                    "type": "object",
                    "properties": props,
                    "required": [] if library else ["chart"],
                    "additionalProperties": False,
                },
                "outputSchema": cap.output_schema,
                "edition": cap.edition,
            }
        )
    return out
