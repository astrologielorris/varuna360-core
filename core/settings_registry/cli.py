# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings for a command-line tool (SPEC-SET-003 §4.5, D-9, D-12, D-20).

A CLI names the settings it uses; it never defines or overrides them::

    from core.settings_registry.cli import use_settings, resolve_settings, echo
    USES = ("zodiac.mode", "zodiac.ayanamsa_id", "dasha.year_length.nakshatra")
    use_settings(parser, USES, capabilities=("get_dasha",))
    args = parser.parse_args()
    cfg = resolve_settings(args)          # cfg["zodiac.mode"], cfg.source("zodiac.mode")
    print(json.dumps(echo(payload, cfg)))  # adds "settings": {key: {value, source}}

- ``use_settings`` adds ``--factory-defaults`` and the repeatable
  ``--set key=value`` and records the command's TRANSITIVE uses: its own keys
  plus the settings of every capability it calls (the frame keys and the
  capability's ``SETTING_ARGS`` keys).
- ``resolve_settings`` resolves through the effective-settings API: the
  terminal context (``--set`` > ``cli_settings.json`` > live > saved >
  factory) for a process started from a terminal, the app context for a child
  process the running app started with its trusted app block (INV-4b).
- ``--set`` is refused (exit 2) while advanced mode is off (D-15), for a key
  the command does not use (D-20), an unknown, protected (D-17),
  non-calculation (D-16) or other-edition key, and a bad value. A damaged or
  newer tools' settings file stops the command with exit 2 naming the file,
  ``--factory-defaults`` included (§4.5a).
- ``--factory-defaults`` means factory only (INV-4): with ``--set`` it is
  refused (``set.factory``, exit 2).

Messages follow the D-21 text gate (``cli_text``): approved wording verbatim,
everything pending in its structured form. Qt-free.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Sequence, Tuple

from core.settings_registry import cli_text, effective

SET_FLAG = "--set"
FACTORY_FLAG = "--factory-defaults"
SET_DEST = "settings_set"
USES_ATTR = "settings_uses"
EXIT_USAGE = 2


# ------------------------------------------------------------------ USES

def capability_uses(capability_id: str) -> Tuple[str, ...]:
    """Every setting a capability reads: the frame keys plus its
    ``SETTING_ARGS`` keys (both sides of a side mapping)."""
    from core.capabilities import catalog, registry  # noqa: F401  (registers)
    from core.capabilities.inputs import FRAME_KEYS
    from core.capabilities.setting_args import used_keys
    cap = catalog.get(capability_id)
    from core.custom_ayanamsa_settings import dependencies
    return dependencies({key for _n, key in FRAME_KEYS} | set(used_keys(cap.setting_args)))


def transitive_uses(keys: Iterable[str] = (), capabilities: Iterable[str] = ()) -> Tuple[str, ...]:
    """A command's own keys plus the keys of the capabilities it calls."""
    out = set(keys or ())
    for cap in capabilities or ():
        out.update(capability_uses(cap))
    from core.custom_ayanamsa_settings import dependencies
    return dependencies(out)


def use_settings(parser, keys: Iterable[str] = (), *,
                 capabilities: Iterable[str] = ()) -> Tuple[str, ...]:
    """Add ``--factory-defaults`` and ``--set key=value`` (repeatable) to
    ``parser`` and record the command's transitive uses. Idempotent. Returns
    the uses."""
    uses = transitive_uses(keys, capabilities)
    have = getattr(parser, "_option_string_actions", {})
    if FACTORY_FLAG not in have:
        from core.capabilities.cli_settings import add_settings_flag
        add_settings_flag(parser)
    if SET_FLAG not in have:
        # help: pending wording (D-21); argparse shows the flag without one.
        parser.add_argument(SET_FLAG, dest=SET_DEST, action="append", default=None,
                            metavar="KEY=VALUE")
    parser.set_defaults(**{USES_ATTR: uses})
    return uses


# --------------------------------------------------------------- --set

def _choices_text(key: Optional[str]) -> Optional[list]:
    """The ``choices`` field of a ``set.bad_value`` refusal (shown
    comma-joined by the approved text)."""
    from core.settings_registry import cli_store
    return cli_store.allowed_values(key)


def parse_set(items: Sequence[str], uses: Iterable[str],
              edition: Optional[str] = None) -> Dict[str, Any]:
    """The ``--set`` values, each checked; the first bad one raises
    ``effective.CommandRefused`` (its code is the message key)."""
    from core.settings_registry import cli_store
    uses = set(uses or ())
    out: Dict[str, Any] = {}
    for item in items or ():
        key, sep, text = str(item).partition("=")
        key = key.strip()
        if not sep or not key:
            # A malformed item (no ``=``, or no key before it) has its own
            # message key, pending until its draft is approved (W6d fix F2).
            raise effective.CommandRefused("set.malformed_item", item=str(item))
        reason = cli_store.check_key(key, edition)
        if reason in (cli_store.UNKNOWN_KEY, cli_store.OTHER_EDITION):
            raise effective.CommandRefused("set.unknown_key", key=key)
        if reason == cli_store.PROTECTED:
            raise effective.CommandRefused("set.protected", key=key)
        if reason == cli_store.NOT_CALCULATION:
            raise effective.CommandRefused("set.not_calculation", key=key)
        if key not in uses:
            raise effective.CommandRefused("set.unused_key", key=key)
        # W6d fix F2: a key without a fixed list of values has its own
        # (pending) message; the approved set.bad_value names the choices.
        choices = _choices_text(key)
        fields = dict(key=key, value=text, choices=choices) if choices else dict(key=key, value=text)
        try:
            value = cli_store.parse_value(key, text)
        except (ValueError, TypeError):
            raise effective.CommandRefused(cli_text.bad_value_key(choices), **fields) from None
        if cli_store.check(key, value, edition) is not None:
            raise effective.CommandRefused(cli_text.bad_value_key(choices), **fields)
        out[key] = value
    return out


# ------------------------------------------------------------- context

def _factory(args) -> bool:
    if isinstance(args, bool):
        return args
    return bool(getattr(args, "factory_defaults", False))


def context_for(args, keys: Optional[Iterable[str]] = None, *,
                edition: Optional[str] = None):
    """The settings context of this command run: the app context when the
    running app started this process (its trusted app block), else the
    terminal context. Raises ``effective.CommandRefused`` and the store
    errors (``cli_store.StoreError``); ``report`` prints them."""
    sets = [] if isinstance(args, bool) or args is None else list(
        getattr(args, SET_DEST, None) or [])
    try:
        app = effective.app_context_from_env()
    except effective.AppBlockError as exc:
        raise effective.CommandRefused("settings.bad_app_block",
                                       env=effective.APP_SETTINGS_ENV, reason=str(exc)) from None
    if app is not None:
        if sets:
            # A child of the app answers in the app's settings (INV-4b).
            raise effective.CommandRefused("set.app_context", flag=SET_FLAG)
        return effective.app_context(live=app.live, factory_only=_factory(args))
    # The tools' settings file is loaded and validated on EVERY terminal run
    # (a damaged or newer file stops the command, --factory-defaults
    # included, §4.5a).
    from core.settings_registry import cli_store
    store = cli_store.load(edition=edition)
    if not sets:
        return effective.terminal_context(store=store, factory_only=_factory(args))
    # The lock first (D-15): nothing about the keys is checked while
    # advanced mode is off.
    if not store.advanced_on:
        raise effective.CommandRefused("set.advanced_off")
    # INV-4: --factory-defaults means factory only; a command value would
    # silently replace it (W6 review F4).
    if _factory(args):
        raise effective.CommandRefused("set.factory", flag=FACTORY_FLAG)
    # D-20 against the command's transitive uses (recorded by use_settings),
    # whatever subset this call resolves.
    uses = getattr(args, USES_ATTR, None)
    if uses is None:
        uses = keys or ()
    return effective.terminal_context(parse_set(sets, uses, edition), store=store,
                                      factory_only=_factory(args))


def report(err: BaseException, stream=None) -> None:
    """One line on stderr for a refusal or a store error (the D-21 gate:
    approved wording, else the structured form)."""
    from core.settings_registry import cli_store
    stream = stream or sys.stderr
    if isinstance(err, effective.CommandRefused):
        line = cli_text.message(err.code, **err.fields)
    elif isinstance(err, cli_store.NewerStore):
        line = cli_text.message("store.newer_version", path=str(err.path),
                                fix="settings.py reset --discard-newer")
    elif isinstance(err, cli_store.StoreBusy):
        line = cli_text.message("store.busy", path=str(err.path))
    elif isinstance(err, cli_store.StoreWriteFailed):
        line = cli_text.message("store.write_failed", path=str(err.path),
                                errno=err.errno_name, reason=err.reason)
    elif isinstance(err, cli_store.StoreError):
        line = cli_text.message("store.bad_file", path=str(err.path), fix="settings.py reset")
    else:
        line = cli_text.structured("settings.error", detail=str(err))
    stream.write(line + "\n")
    stream.flush()


def _or_exit(fn, *a, **k):
    from core.settings_registry import cli_store
    try:
        return fn(*a, **k)
    except (effective.CommandRefused, cli_store.StoreError) as err:
        report(err)
        raise SystemExit(EXIT_USAGE)


def view_for(args=None, keys: Optional[Iterable[str]] = None):
    """The settings object (``SettingsView``'s interface) a command reads:
    capabilities, ``ChartFrame.resolve``, ``DashaState.from_settings`` and a
    renderer's read-only manager all take it. Exits 2 on a refusal or a
    damaged store."""
    return effective.view(_or_exit(context_for, args, keys))


# ------------------------------------------------------------- resolve

class ResolvedSettings(Mapping):
    """``{key: value}`` with ``.source(key)``; ``.view`` is the settings
    object the same context gives a capability or a renderer.
    ``raw_keys``: keys the command's own code reads as stored and normalizes
    itself (``resolve_settings``' ``as_stored``; extract_reading_date's
    engine keys): ``use_read_only_settings`` leaves them as stored."""

    def __init__(self, resolved: Dict[str, Tuple[Any, str]], context, settings_view,
                 raw_keys: Iterable[str] = ()):
        self._resolved = resolved
        self.context = context
        self.view = settings_view
        self.raw_keys = frozenset(raw_keys)

    def __getitem__(self, key: str) -> Any:
        return self._resolved[key][0]

    def __iter__(self) -> Iterator[str]:
        return iter(self._resolved)

    def __len__(self) -> int:
        return len(self._resolved)

    def source(self, key: str) -> str:
        return self._resolved[key][1]

    @property
    def ignored(self) -> Dict[str, str]:
        """Stored tools' values that are not used, with the reason code."""
        store = getattr(self.context, "store", None)
        if store is None or getattr(self.context, "factory_only", False):
            return {}       # a factory run uses no stored value at all
        return dict(sorted(store.ignored.items()))

    def echo(self) -> Dict[str, Dict[str, Any]]:
        return {key: {"value": value, "source": source}
                for key, (value, source) in sorted(self._resolved.items())}


def _used_values(resolved: Dict[str, Tuple[Any, str]], ctx, settings_view,
                 as_stored: Iterable[str] = ()) -> Dict[str, Tuple[Any, str]]:
    """``resolved`` turned into the values a calculation uses, with the layer
    that decided each one (W7 review F3: the echo describes what was used,
    never a raw stored value the calculation replaced).

    - The chart frame keys (``FRAME_KEYS``): the values ``ChartFrame.resolve``
      calculates with, each with the source ``ChartFrame.resolve_entries``
      reports for it (W9 fix4 R4-1). An unknown or wrong-type mode, house
      system, nakshatra reference or HD level, a container where a boolean
      is stored, and a saved ayanamsa outside the registry's integer choices
      (98.5, "98", -1; W9 fix2 N2) fall back to the factory value: source
      ``default`` (``factory`` in the app context). A western-names choice
      the clamp to the resolved mode changed takes the mode's source.
    - Every other key: a value the registry does not accept falls back to the
      factory value, as the GUI's readers do (``DashaState.from_settings``,
      the capabilities' ``resolve_options``, the panels' readers).
    - ``as_stored``: keys the command's calculation reads as stored, without
      that check (the dasha panels' ayanamsa ids, ``DashaState``; the chart
      ayanamsa a Kala-reference command hands its engine as is, Kala's saved 99)."""
    from core import settings_registry as registry
    from core.capabilities.settings_view import SOURCE_FACTORY
    terminal = isinstance(ctx, effective.TerminalContext)
    factory = effective.SOURCE_DEFAULT if terminal else SOURCE_FACTORY

    def layer(source):
        return effective.SOURCE_DEFAULT if terminal and source == SOURCE_FACTORY else source

    out = dict(resolved)
    as_stored = set(as_stored)
    from core.capabilities.inputs import FRAME_KEYS, ChartFrame, InputError
    frame_keys = {key: name for name, key in FRAME_KEYS}
    if any(key in out for key in frame_keys):
        try:
            _frame, entries = ChartFrame.resolve_entries(settings_view)
        except (InputError, TypeError, ValueError):
            entries = None  # the calculation stops on it too; echo as resolved
        if entries is not None:
            for key, name in frame_keys.items():
                if key not in out or key in as_stored:
                    continue
                value, source = out[key]
                used, decided = entries[name]
                if used == value and type(used) is type(value):
                    continue
                # the layer the resolver reports for this entry (W9 fix4
                # R4-1): a fallback is the factory value's own, a clamped
                # label set the mode's, never another entry's by guess
                out[key] = (used, layer(decided))
    for key, (value, source) in list(out.items()):
        if key in frame_keys or key in as_stored:
            continue
        try:
            accepted = registry.valid(key, value)
        except KeyError:
            continue        # not a registry key: nothing to check it against
        if not accepted:
            out[key] = (registry.default(key), factory)
    return out


def resolve_settings(args=None, keys: Optional[Iterable[str]] = None, *,
                     as_stored: Iterable[str] = ()) -> ResolvedSettings:
    """The values and sources of ``keys`` (default: the uses recorded by
    ``use_settings``) for this command run, as its calculation uses them
    (``_used_values``; ``as_stored``: keys read without the registry check).
    Exits 2 on a refused ``--set`` or a damaged / newer tools' settings
    file."""
    keys = tuple(keys if keys is not None else getattr(args, USES_ATTR, ()) or ())
    ctx = _or_exit(context_for, args, keys)
    settings_view = effective.view(ctx)
    resolved = _used_values(effective.resolve(keys, ctx), ctx, settings_view, as_stored)
    from core.custom_ayanamsa_settings import AYANAMSA_KEYS, KEYS, install_from
    if any(resolved.get(key, (None,))[0] == 255 for key in AYANAMSA_KEYS):
        resolved.update(_used_values(effective.resolve(KEYS, ctx), ctx, settings_view))
    # Ayanamsa 255 is the user's own definition: compute it as this context defines it.
    install_from({key: value for key, (value, _source) in resolved.items()}
                 if all(key in resolved for key in KEYS) else settings_view)
    return ResolvedSettings(resolved, ctx, settings_view, raw_keys=as_stored)


def check_listing_route(args) -> None:
    """A listing route (``--list-ayanamsas`` and the like) uses no setting:
    the shared checker runs with empty USES before anything is printed (W7
    review N2, as the W6 metadata routes). ``--set`` is refused as on every terminal route (D-15 while
    advanced mode is off, D-20 ``set.unused_key`` while on), a damaged or
    newer tools' settings file stops the command (§4.5a). Exits 2."""
    import argparse
    meta = argparse.Namespace(**vars(args))
    setattr(meta, USES_ATTR, ())
    _or_exit(context_for, meta, ())


def echo(payload: Dict[str, Any], resolved: ResolvedSettings) -> Dict[str, Any]:
    """``payload`` (a JSON object output) with ``settings``: ``{key: {value,
    source}}``, and ``settings_ignored`` (``{key: reason}``) when the tools'
    settings file holds values that are not used (never as a source)."""
    out = dict(payload)
    out["settings"] = resolved.echo()
    if resolved.ignored:
        out["settings_ignored"] = resolved.ignored
    return out


def use_read_only_settings(resolved: ResolvedSettings):
    """For a command that runs app widget code reading ``get_settings()`` (the
    chart renderers): install the process-wide SettingsManager as an in-memory
    copy of this run's resolved settings (``resolve_settings``'s context)
    whose saves do nothing, so the drawing reads exactly the layers the
    calculation read and nothing is written to the user data folder (INV-3,
    INV-4b; SPEC-SET-003 W8). The registry counterpart of
    ``core.capabilities.cli_settings.use_read_only_settings`` (same name, so
    the T-10 census sees the read-only setup). Call it before any widget is
    built. Returns the installed manager.

    SET-003 W11-R2-3: the manager holds the values the echo discloses. A
    registry key of ``resolved`` whose stored value the resolution replaced
    (a wrong type or unknown choice at its factory value, a chart frame
    entry as ``ChartFrame.resolve`` uses it) is installed as resolved, so
    the drawing reads ``appearance.deep_dark`` = False, never the stored
    text ``'false'`` (``bool('false')`` is True). Keys the command reads as
    stored and normalizes itself (``resolved.raw_keys``: the AI engine's
    provider and effort keys) stay as stored, and a key the layers do not
    hold is not added, so the widgets' own defaults are unchanged."""
    return effective.install_read_only(resolved.context, normalized_overrides(resolved))


def normalized_overrides(resolved: ResolvedSettings) -> Dict[str, Any]:
    """``{key: value}``: the registry keys of ``resolved`` whose resolved
    value is not the value the layers hold (``use_read_only_settings``)."""
    from core import settings_registry as registry
    out = {}
    for key in resolved:
        if key in resolved.raw_keys:
            continue
        try:
            registry.default(key)
        except KeyError:
            continue            # not a registry key
        try:
            stored = resolved.view.get(key, effective._MISSING)
        except effective.MissingSetting:
            continue            # a frozen packet without it: nothing to replace
        if stored is effective._MISSING:
            continue            # the layers do not hold it: the reader's default
        value = resolved[key]
        if stored == value and type(stored) is type(value):
            continue
        out[key] = value
    return out


# ------------------------------------------------------------- fixed frame
#
# The ONE table of commands that keep a fixed chart frame on purpose (W12,
# orchestrator decision on the W11 questions). They generate reference data
# for sibling repos (golden fixtures, parity reports): their output must be
# reproducible whatever the user's Settings tab or the tools' settings file
# hold, so they never follow the settings. Each takes ``use_settings(parser,
# ())`` and ``resolve_settings``: every ``--set`` key is refused (D-20, the
# key is not used) and ``--factory-defaults`` changes nothing. Each echoes
# ``fixed_frame_echo()`` in its output. No other command may keep a fixed
# frame (test_settings_registry_w12_guards.py). This module ships in Lite, so
# it lists the Core commands only; the Pro tree lists its own in its
# fixed_frame_commands module (Core never names a Pro path, release Gate 3).

FIXED_FRAME = {"zodiac.mode": "aditya", "zodiac.ayanamsa_id": 1,
               "zodiac.house_system": "campanus"}

FIXED_FRAME_COMMANDS = {
    "AI_tools/analysis/export_avastha_reference.py":
        "writes the avastha golden parity fixture "
        "(SPEC-AVW-001) that the website and the mobile app test against",
}


def fixed_frame_echo() -> Dict[str, Dict[str, Any]]:
    """The settings echo of a fixed-frame command: ``{key: {value, source:
    "fixed"}}`` (§4.5's shape, source ``fixed``)."""
    return {key: {"value": value, "source": "fixed"} for key, value in FIXED_FRAME.items()}
