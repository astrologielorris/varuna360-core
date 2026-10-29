# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The effective-settings API (SPEC-SET-003 INV-4b): one resolver, an explicit
context chosen by the caller, never guessed.

- ``app``: a calculation started by the running app or its AI (task tools on
  the live app, the Pro AI Tools tab, in-process capabilities and the child
  processes they spawn). Layers: the app's live values > the saved app file >
  factory. ``cli_settings.json`` and ``--set`` are never read.
- ``frozen``: replay of a capture. Layers: the capture's frozen settings (per
  region, SPEC-SET-003 §4.6a) > the versioned defaults of the packet's
  version (source ``assumed``), then STOP: a key in neither is an explicit
  ``MissingSetting`` (code ``missing``), never today's factory tree (a later
  factory change must not move an old capture's replay). No live, saved or
  CLI layer: the saved file is never opened, the running app is never asked.
- ``terminal``: a CLI or ``varuna360 --tool`` started by a person or an
  outside AI (W6). Layers: ``--set`` on the command (only while the tools'
  settings file says advanced mode is on, D-15) > the tools' settings file
  ``cli_settings.json`` (``cli_store``) > live > saved > factory. Sources
  ``command``, ``cli``, ``live``, ``settings``, ``default``.
  ``factory_only`` (``--factory-defaults``) means factory only (INV-4):
  ``--set`` with it is refused (``set.factory``), and the tools' settings
  file is still loaded and validated, so a damaged or newer file stops the
  run (§4.5a: ``reset`` / ``reset --discard-newer`` are the only escapes).

A child process the running app starts is NOT a terminal process: the app
hands it a complete trusted app block in its environment
(``VARUNA360_APP_SETTINGS``, ``app_block_env``), and the child resolves in the
app context from it (``app_context_from_env``). A process without that block
is a terminal process. A process that serves the app only (the task MCP
server) declares it (``declare_app_process``): a terminal context is then
refused, so it can never read the tools' settings file.

``resolve(keys, context)`` returns ``{key: (value, source)}``. ``view(context)``
is the settings object the capability catalog reads (``SettingsView``'s
interface), so a capability resolves its options and frame through exactly the
context its caller named; ``install_read_only(context)`` gives widget-backed
renderers a read-only manager holding the SAME resolved values (a calculation
and its drawing never read different layers).

Qt-free, never writes.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

# Stdlib-only module (no import side effects): the view every context's
# settings object follows.
from core.capabilities.settings_view import SOURCE_FACTORY, SOURCE_LIVE, SettingsView

CONTEXT_APP = "app"
CONTEXT_FROZEN = "frozen"
CONTEXT_TERMINAL = "terminal"

SOURCE_FROZEN = "frozen"        # the capture's own frozen value
SOURCE_ASSUMED = "assumed"      # not recorded: the packet version's default (D-19)
# Terminal context (SPEC-SET-003 §4.5): where each value came from.
SOURCE_COMMAND = "command"      # --set on this command (advanced mode)
SOURCE_CLI = "cli"              # the tools' settings file (settings.py set)
SOURCE_DEFAULT = "default"      # the factory value (the view says "factory")

# The trusted app block a child process of the running app gets (INV-4b).
APP_SETTINGS_ENV = "VARUNA360_APP_SETTINGS"
APP_BLOCK_VERSION = 1

_MISSING = object()


class CommandRefused(Exception):
    """A terminal command's settings request that cannot be honoured
    (``--set`` while advanced mode is off, an unused or invalid key...).
    ``code`` names the case (the key of its message), ``fields`` the facts."""

    def __init__(self, code: str, **fields: Any):
        super().__init__(code + "".join(f" {k}={v}" for k, v in fields.items()))
        self.code = code
        self.fields = fields


class AppBlockError(ValueError):
    """``VARUNA360_APP_SETTINGS`` is present but not a complete app block: a
    child of the app must never silently become a terminal process."""

    code = "bad_app_block"


class MissingSetting(LookupError):
    """A frozen replay needs a setting that is neither frozen in the capture
    nor pinned in its packet version's defaults: an explicit error, never a
    silent fallback to the factory tree (INV-4b, W4 review F1)."""

    code = "missing"

    def __init__(self, key: str, version: int):
        super().__init__(f"setting {key!r} is not recorded by this capture and not "
                         f"pinned for packet version {version}")
        self.key = key
        self.version = version


@dataclass(frozen=True)
class AppContext:
    """Live > saved > factory. ``live`` None: the trusted app block of this
    process (``VARUNA360_LIVE_SETTINGS`` for a child) or the running app's
    live file, as ``SettingsView.load`` reads it; ``{}``: no live layer."""
    live: Optional[Dict[str, Any]] = None
    settings_dir: Optional[Path] = None
    name: str = CONTEXT_APP
    # ``--factory-defaults`` given to a child process of the app (a builder
    # passing it on): factory only, as for any CLI; still never the CLI store.
    factory_only: bool = False


@dataclass(frozen=True)
class FrozenContext:
    """A capture's frozen settings (flat dot keys; per region, merged by the
    replay loader) over the versioned defaults of its packet version."""
    frozen: Dict[str, Any]
    defaults: Dict[str, Any]
    version: int
    name: str = CONTEXT_FROZEN
    meta: Dict[str, Any] = field(default_factory=dict)


def app_context(live: Optional[Dict[str, Any]] = None,
                settings_dir: Optional[Path] = None,
                factory_only: bool = False) -> AppContext:
    return AppContext(live=None if live is None else dict(live), settings_dir=settings_dir,
                      factory_only=bool(factory_only))


def frozen_context(frozen: Mapping[str, Any], defaults: Mapping[str, Any],
                   version: int, meta: Optional[Dict[str, Any]] = None) -> FrozenContext:
    return FrozenContext(frozen=copy.deepcopy(dict(frozen or {})),
                         defaults=copy.deepcopy(dict(defaults or {})),
                         version=int(version), meta=dict(meta or {}))


@dataclass(frozen=True)
class TerminalContext:
    """``--set`` overrides (already checked) > the tools' settings file
    (``store``: the validated ``cli_store.Store``, loaded on every terminal
    run; its values are not used with ``factory_only``) > live > saved >
    factory. ``factory_only`` never carries overrides."""
    overrides: Dict[str, Any]
    store: Any = None
    factory_only: bool = False
    live: Optional[Dict[str, Any]] = None
    settings_dir: Optional[Path] = None
    name: str = CONTEXT_TERMINAL


_APP_PROCESS = False


def declare_app_process() -> None:
    """This process serves the running app only (the task MCP server): a
    terminal context is refused from now on (INV-4b)."""
    global _APP_PROCESS
    _APP_PROCESS = True


def terminal_context(args_overrides: Optional[Mapping[str, Any]] = None, store=None, *,
                     factory_only: bool = False, live: Optional[Dict[str, Any]] = None,
                     settings_dir: Optional[Path] = None) -> TerminalContext:
    """The terminal context of a CLI run. ``store`` None loads the tools'
    settings file of ``settings_dir`` (default: the user-data folder), on
    EVERY terminal run, ``--factory-defaults`` included: ``cli_store.BadStore``
    / ``NewerStore`` propagate (the caller exits 2, §4.5a).
    ``--factory-defaults`` (``factory_only``) means factory only (INV-4): the
    file's values are not used. ``args_overrides`` (the ``--set`` values) are
    refused unless advanced mode is on (``CommandRefused("set.advanced_off")``,
    checked first, D-15), then refused with ``factory_only``
    (``CommandRefused("set.factory")``, W6 review F4)."""
    if _APP_PROCESS:
        raise RuntimeError("terminal settings context refused: this process serves the app")
    from core.settings_registry import cli_store
    overrides = copy.deepcopy(dict(args_overrides or {}))
    if store is None:
        store = cli_store.load(settings_dir)
    if overrides and not store.advanced_on:
        raise CommandRefused("set.advanced_off", keys=",".join(sorted(overrides)))
    if overrides and factory_only:
        raise CommandRefused("set.factory", flag="--factory-defaults")
    return TerminalContext(overrides=overrides,
                           store=store,
                           factory_only=bool(factory_only),
                           live=None if live is None else dict(live),
                           settings_dir=settings_dir)


def app_block(live: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The complete trusted app block a child process gets: the context name
    and the app's live layer (``{}`` when the app published none)."""
    return {"v": APP_BLOCK_VERSION, "context": CONTEXT_APP,
            "live": copy.deepcopy(dict(live or {}))}


def app_block_env(live: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """Environment entries that make a child process resolve in the app
    context (never the tools' settings file)."""
    return {APP_SETTINGS_ENV: json.dumps(app_block(live), sort_keys=True)}


def app_context_from_env(environ: Optional[Mapping[str, str]] = None) -> Optional[AppContext]:
    """The app context a child process was handed, or None (a terminal
    process). A present but incomplete block raises ``AppBlockError``."""
    env = os.environ if environ is None else environ
    raw = env.get(APP_SETTINGS_ENV)
    if raw is None:
        return None
    try:
        block = json.loads(raw)
    except ValueError:
        raise AppBlockError(f"{APP_SETTINGS_ENV} is not JSON") from None
    if (not isinstance(block, dict) or set(block) != {"v", "context", "live"}
            or block["v"] != APP_BLOCK_VERSION or block["context"] != CONTEXT_APP
            or not isinstance(block["live"], dict)
            or not all(isinstance(k, str) for k in block["live"])):
        raise AppBlockError(f"{APP_SETTINGS_ENV} is not a complete app block")
    return app_context(live=block["live"])


def _factory_tree() -> Dict[str, Any]:
    from managers.settings_manager import DEFAULT_SETTINGS
    return copy.deepcopy(DEFAULT_SETTINGS)


def _set_path(tree: Dict[str, Any], key: str, value: Any) -> None:
    node = tree
    parts = key.split(".")
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = node[part] = {}
        node = child
    node[parts[-1]] = copy.deepcopy(value)


def _fallback(key: str) -> Any:
    """App context only: a key the app's layers lack (an app-state or display
    key): the registry's factory value, else the factory tree, else None.
    Never used by the frozen route (MissingSetting)."""
    from core.capabilities.setting_defaults import setting_default
    try:
        return setting_default(key)
    except KeyError:
        return None


class FrozenView:
    """``SettingsView``'s read interface over a FrozenContext: every value is
    ``frozen`` or ``assumed``; nothing else is ever read."""

    factory_only = False
    path = None
    status = "frozen"

    def __init__(self, ctx: FrozenContext):
        self.ctx = ctx
        self._live = dict(ctx.frozen)        # flat overlay (read-only manager)
        self._saved: Dict[str, Any] = {}

    @property
    def _merged(self) -> Dict[str, Any]:
        """The tree a widget-backed renderer's read-only manager holds
        (``install_read_only``): the version's pinned defaults over the
        factory tree, the frozen values laid on top by the builder. Only
        drawing keys no capability reads (colours, fonts) come from the
        factory tree here; every key a calculation reads is frozen or
        pinned, and the calculation route (``get``) never reads this tree."""
        merged = _factory_tree()
        for key, value in self.ctx.defaults.items():
            _set_path(merged, key, value)
        return merged

    def _lookup(self, key: str):
        if key in self.ctx.frozen:
            return self.ctx.frozen[key], SOURCE_FROZEN
        if key in self.ctx.defaults:
            return self.ctx.defaults[key], SOURCE_ASSUMED
        raise MissingSetting(key, self.ctx.version)

    def get(self, key: str, default: Any = None) -> Any:
        """The frozen value, else the version's pinned default; a key in
        neither raises ``MissingSetting`` (``default`` is never used: the
        frozen route has no fallback layer)."""
        value, _src = self._lookup(key)
        return copy.deepcopy(value)

    def source(self, key: str) -> str:
        return self._lookup(key)[1]

    def resolve(self, key: str, explicit: Any = None,
                default: Any = None) -> Tuple[Any, str]:
        from core.capabilities.settings_view import SOURCE_ARGUMENT
        if explicit is not None:
            return explicit, SOURCE_ARGUMENT
        return self.get(key, default), self.source(key)

    # One layer: the capture's frozen state stands where the running app and
    # the saved file stand for the other contexts.
    def live_value(self, key: str, default: Any = None) -> Any:
        return copy.deepcopy(self.ctx.frozen[key]) if key in self.ctx.frozen else default

    def stored_value(self, key: str, default: Any = None) -> Any:
        return self.get(key, default)

    def describe(self) -> Dict[str, Any]:
        return {"status": self.status, "path": None,
                "packet_version": self.ctx.version,
                "live_keys": sorted(self.ctx.frozen)}


class TerminalView(SettingsView):
    """``SettingsView``'s interface with the two terminal layers above the
    running app: ``--set`` (``command``) and the tools' settings file
    (``cli``). ``_live`` holds every layer above the saved file, so a
    renderer's read-only manager (``install_read_only``) draws what the
    calculation reads; ``live_value`` stays the running app's own value.
    ``source`` keeps the capability vocabulary (``factory``); ``resolve``
    names it ``default`` for the terminal echo."""

    @classmethod
    def build(cls, ctx: TerminalContext) -> "TerminalView":
        base = SettingsView.load(factory_only=ctx.factory_only,
                                 settings_dir=ctx.settings_dir,
                                 live=None if ctx.live is None else dict(ctx.live))
        out = cls.__new__(cls)
        out.__dict__.update(base.__dict__)
        out.context = ctx
        out._app_live = dict(base._live)
        out._cli = ({} if ctx.factory_only or ctx.store is None
                    else copy.deepcopy(dict(ctx.store.values)))
        out._command = copy.deepcopy(dict(ctx.overrides))
        out._live = {**out._app_live, **out._cli, **out._command}
        return out

    def source(self, key: str) -> str:
        if key in self._command:
            return SOURCE_COMMAND
        if key in self._cli:
            return SOURCE_CLI
        if key in self._app_live:
            return SOURCE_LIVE
        return super().source(key)

    def live_value(self, key: str, default: Any = None) -> Any:
        return copy.deepcopy(self._app_live[key]) if key in self._app_live else default

    def describe(self) -> Dict[str, Any]:
        """``SettingsView.describe`` unchanged (a CLI's output stays byte
        identical while no terminal layer holds a value, INV-13), plus the
        terminal layers when they hold anything: the tools' settings file
        (its path, the keys it gave, the values it ignored) and the
        ``--set`` keys."""
        out = dict(super().describe(), live_keys=sorted(self._app_live))
        store = self.context.store
        # A factory run reads no stored value: its output never depends on
        # the file's content (the file was still validated).
        if store is not None and not self.context.factory_only and (self._cli or store.ignored):
            out["cli_settings"] = {
                "path": str(store.path) if store.path else None,
                "keys": sorted(self._cli),
                "ignored": dict(sorted(store.ignored.items()))}
        if self._command:
            out["command_keys"] = sorted(self._command)
        return out


def view(context):
    """The settings object a capability reads under ``context``."""
    if isinstance(context, FrozenContext):
        return FrozenView(context)
    if isinstance(context, TerminalContext):
        return TerminalView.build(context)
    if isinstance(context, AppContext):
        # SettingsView never opens cli_settings.json: the app context has no
        # CLI layer by construction.
        return SettingsView.load(factory_only=context.factory_only,
                                 settings_dir=context.settings_dir,
                                 live=None if context.live is None else dict(context.live))
    raise TypeError(f"not a settings context: {context!r}")


def resolve(keys: Iterable[str], context) -> Dict[str, Tuple[Any, str]]:
    """``{key: (value, source)}`` for each key, in ``context``'s layers."""
    if not isinstance(context, (AppContext, FrozenContext, TerminalContext)):
        raise TypeError(f"not a settings context: {context!r}")
    settings = view(context)
    out = {}
    for key in keys:
        if isinstance(context, FrozenContext):
            # frozen > pinned, then STOP (MissingSetting): no factory layer.
            out[key] = (settings.get(key), settings.source(key))
            continue
        value = settings.get(key, _MISSING)
        if value is _MISSING:
            value = _fallback(key)
        source = settings.source(key)
        if isinstance(context, TerminalContext) and source == SOURCE_FACTORY:
            source = SOURCE_DEFAULT     # the terminal echo's name (spec §4.5)
        out[key] = (value, source)
    return out


def install_read_only(context, overrides=None):
    """Install the process-wide SettingsManager as a read-only copy of the
    values ``context`` resolves (``use_read_only_settings`` for a route that
    has a context): the widgets draw from the same layers the calculation
    used. ``overrides`` (``{key: value}``): the normalized values laid on top
    (SET-003 W11-R2-3). Returns the manager."""
    import managers.settings_manager as sm
    from core.capabilities.read_only_settings import build_read_only_settings
    mgr = build_read_only_settings(view(context), overrides)
    sm._instance = mgr
    return mgr
