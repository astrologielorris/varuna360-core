# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The settings registry: each setting declared once (SPEC-SET-003).

One entry per key (``schema.Setting``): type, factory default, choices,
label, owning Settings tab section, whether the running app publishes it, the
edition. The factory table, the Settings tab, the capability schemas, every
CLI and the live publisher read these entries instead of re-typing them.

Static registration (no dynamic discovery) so frozen builds and the Lite
manifest gate see every module. Qt-free and import-side-effect free. Both
editions live in one table (``edition="pro"`` entries are plain data; Core
imports nothing from ``pro``); Lite filters at consumption. The one exception
is the settings of a Pro-only feature that Core must not name at all: the Pro
package declares them in its own tree and adds them with ``register_module``
when it is imported (td-txv5v), before the window or any CLI reads a setting.

App state that is not a preference (``APP_STATE_KEYS``) stays a literal in
``DEFAULT_SETTINGS`` and is not registered.
"""
from __future__ import annotations

import copy
import importlib
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.settings_registry import (
    ai, appearance, chart, compat, cot, dasha, display, partner, paths, planet_sizes,
    recorder, zodiac)
from core.settings_registry import labels as _labels
from core.settings_registry import validators  # noqa: F401  (rules.validate targets:
#   imported statically so frozen builds bundle the module; engine imports stay lazy)
from core.settings_registry.owners import OWNER_SETS
from core.settings_registry.schema import KIND_LEAF, KIND_SECTION, Setting
from core.settings_registry.schema import choice_values as _values_of

def load_table(target: str):
    """The table a ``ChoicesRef`` names (``"module.path:NAME"``)."""
    module, _, name = target.partition(":")
    return getattr(importlib.import_module(module), name)


_MODULES = (zodiac, dasha, chart, display, appearance, compat, cot, paths, ai, recorder,
            planet_sizes, partner)

# DEFAULT_SETTINGS keys that are app state, not preferences: never registered.
APP_STATE_KEYS = (
    "version", "locks",
    "windows.main.width", "windows.main.height",
    "windows.last_position.x", "windows.last_position.y",
    "ui.last_active_tab", "ui.action_bar_v2_default_migrated",
    "ui.exchange_chain_on_default_migrated",
    "defaults.aditya_mode", "chart.aspect_split_fraction",
    # SPEC-LAYOUT-001 remembered Chart-tab layout
    "ui.layout.dasha_right_position", "ui.layout.dasha_right_user_rail",
    "ui.layout.info_panels_auto", "ui.layout.info_panels_folded",
    "ui.layout.info_stack_fractions", "ui.layout.info_magazine_fractions",
)

# Keys the app writes at run time that are state, not preferences, and are
# absent from DEFAULT_SETTINGS (W3e census of dynamic set() writers): never
# registered, never offered to settings.py or the AI.
RUNTIME_STATE_KEYS = (
    "paths.last_chart_write_error",       # managers/persist_health.py HEALTH_KEY
    "appearance.applied_theme_overrides", # theme palette overrides, written on Apply
)


def _labelled(entry: Setting) -> Setting:
    from dataclasses import replace
    if not entry.label and _labels.label_for(entry.key):
        # Every entry has a label (AI setting redesign, td-bztjj): the
        # Settings caption, or a written one (labels.py).
        entry = replace(entry, label=_labels.label_for(entry.key))
    return entry


def _build() -> Dict[str, Setting]:
    table: Dict[str, Setting] = {}
    for module in _MODULES:
        for entry in module.SETTINGS:
            if entry.key in table:
                raise ValueError(f"settings registry: {entry.key!r} declared twice")
            table[entry.key] = _labelled(entry)
    return table


_TABLE: Dict[str, Setting] = _build()

# Settings modules an edition package added at its import (register_module).
_REGISTERED: List[Any] = []


def register_module(module: Any) -> None:
    """Add an edition's settings group (a module, or any object, with a
    ``SETTINGS`` tuple of ``Setting``) to the table (td-txv5v).

    Core's own groups are static (``_MODULES``). A Pro-only feature that Core
    must not name declares its settings in the Pro tree, and the Pro package
    registers them when it is imported (``pro/__init__.py``), which the
    launcher does before anything reads a setting. Registering the same module
    again does nothing; a key already declared raises, as at import.

    The persisted factory values are merged ADDITIVELY (missing keys only)
    into ``DEFAULT_SETTINGS`` and into the settings manager already built, so
    the factory table is the same whatever the import order and no stored
    value is touched. A settings file holding these keys stays intact in an
    edition that never registers them: the manager keeps keys it does not
    know, on load and on save."""
    if any(m is module for m in _REGISTERED):
        return
    added: Dict[str, Setting] = {}
    for entry in module.SETTINGS:
        if entry.key in _TABLE or entry.key in added:
            raise ValueError(f"settings registry: {entry.key!r} declared twice")
        added[entry.key] = _labelled(entry)
    _TABLE.update(added)
    _REGISTERED.append(module)
    tree: Dict[str, Any] = {}
    for e in added.values():
        if e.persisted and e.kind == KIND_LEAF:
            node = tree
            parts = e.key.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = e.factory()
    if tree:
        _merge_into_live_defaults(tree)


def _merge_missing(base: Dict[str, Any], extra: Dict[str, Any]) -> None:
    for name, value in extra.items():
        if name not in base:
            base[name] = copy.deepcopy(value)
        elif isinstance(base[name], dict) and isinstance(value, dict):
            _merge_missing(base[name], value)


def _merge_into_live_defaults(tree: Dict[str, Any]) -> None:
    """The factory table, and the manager's in-memory settings, built before
    a ``register_module`` call gain the new keys (missing keys only). Nothing
    is written to disk; a module not imported yet will build them itself."""
    import sys
    manager = sys.modules.get("managers.settings_manager")
    if manager is None:
        return
    defaults = getattr(manager, "DEFAULT_SETTINGS", None)
    if isinstance(defaults, dict):
        _merge_missing(defaults, tree)
    instance = getattr(manager, "_instance", None)
    stored = getattr(instance, "_settings", None)
    if isinstance(stored, dict):
        _merge_missing(stored, tree)


def get(key: str) -> Setting:
    try:
        return _TABLE[key]
    except KeyError:
        raise KeyError(f"{key!r} is not a registered setting") from None


def has(key: str) -> bool:
    return key in _TABLE


def entries(*, section: Optional[str] = None, live: Optional[bool] = None,
            edition: Optional[str] = None, persisted: Optional[bool] = None,
            kind: Optional[str] = None, cli: Optional[str] = None) -> List[Setting]:
    """Registered entries in key order. ``edition="lite"`` drops Pro entries;
    ``cli`` filters on the family (``rules.cli``, D-16)."""
    wanted = {"section": section, "live": live, "persisted": persisted, "kind": kind}
    out = []
    for key in sorted(_TABLE):
        e = _TABLE[key]
        if edition == "lite" and e.edition == "pro":
            continue
        if any(v is not None and getattr(e, name) != v for name, v in wanted.items()):
            continue
        if cli is not None and (e.rules is None or e.rules.cli != cli):
            continue
        out.append(e)
    return out


def keys(**filters) -> Tuple[str, ...]:
    return tuple(e.key for e in entries(**filters))


def default(key: str) -> Any:
    """The factory value (deep copy): persisted or fallback-only alike."""
    return get(key).factory()


def choice_values(key: str):
    return _values_of(get(key))


def owner_set(section: str, edition: str) -> frozenset:
    """The keys a Settings section's Apply writes and its Reset restores, per
    edition (INV-5, INV-15). ``lite`` is Core. KeyError for a section that the
    edition does not build."""
    edition = "core" if edition == "lite" else edition
    try:
        return OWNER_SETS[(section, edition)]
    except KeyError:
        raise KeyError(f"no {edition} Settings section {section!r}") from None


def valid(key: str, value: Any) -> bool:
    """True when ``value`` may be stored under ``key``: its type, its choices,
    its bounds and its ``rules.validate`` check (spec §3.1, T-1)."""
    e = get(key)
    types = e.type if isinstance(e.type, tuple) else (e.type,)
    if isinstance(value, bool) and bool not in types:
        return False                      # True is an int to Python, not here
    if not isinstance(value, types) and not (float in types and type(value) is int):
        return False
    allowed = _values_of(e)
    if allowed is not None and value not in allowed:
        return False
    if e.bounds is not None and not e.bounds[0] <= value <= e.bounds[1]:
        return False
    check = e.rules.validate if e.rules is not None else None
    return check is None or bool(load_table(check)(value))


# JSON Schema type of a registry type (option_schema).
_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean",
               list: "array", dict: "object"}
OMIT = object()     # option_schema: leave this field out of the property


def option_schema(key: str, name: Optional[str] = None, *, description: Any = None,
                  enum: Any = None, default: Any = None,
                  applies_when: Any = None, **extra: Any) -> Dict[str, Any]:
    """The JSON Schema property of a capability option that follows ``key``
    (SPEC-SET-003 §4.4): ``type``, ``enum`` (the entry's choices), ``default``
    (the factory value), ``x-settings-key`` and ``x-applies-when``
    (``rules.applies_when``, or the capability's own ``applies_when``).
    ``description`` stays the capability's own (None: none). ``enum`` or
    ``default`` given replace the entry's; ``OMIT`` leaves the field out.
    ``extra`` adds schema fields (``items``, ``minimum``...) or annotations.
    ``name`` is the option's name, for error messages only."""
    e = get(key)
    kinds = e.type if isinstance(e.type, tuple) else (e.type,)
    types = [_JSON_TYPES[t] for t in kinds if t in _JSON_TYPES]
    if len(types) != 1:
        raise ValueError(f"option {name or key!r}: {key} has no single JSON type")
    prop: Dict[str, Any] = {"type": types[0]}
    values = choice_values(key) if enum is None else enum
    if values is not None and values is not OMIT:
        prop["enum"] = list(values)
    if default is not OMIT:
        prop["default"] = e.factory() if default is None else copy.deepcopy(default)
    if description is not None:
        prop["description"] = description
    prop["x-settings-key"] = key
    when = applies_when if applies_when is not None else (
        e.rules.applies_when if e.rules is not None else None)
    if when is not None:
        prop["x-applies-when"] = copy.deepcopy(when)
    prop.update(copy.deepcopy(extra))
    return prop


def live_keys() -> Tuple[str, ...]:
    """Leaf keys the running app publishes (typed sections listed apart)."""
    return keys(live=True, kind=KIND_LEAF)


def section_keys() -> Tuple[str, ...]:
    return keys(kind=KIND_SECTION)


def factory_tree(edition: Optional[str] = None) -> Dict[str, Any]:
    """The nested factory dict of every PERSISTED leaf (what DEFAULT_SETTINGS
    holds for registered keys). Fallback-only entries are never in it."""
    tree: Dict[str, Any] = {}
    for e in entries(edition=edition, persisted=True, kind=KIND_LEAF):
        node = tree
        parts = e.key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = e.factory()
    return tree


def iter_leaf_paths(tree: Dict[str, Any], prefix: str = "",
                    whole: Iterable[str] = ()) -> Iterable[Tuple[str, Any]]:
    """(dot key, value) for every leaf of a nested settings dict; a key in
    ``whole`` (a dict used as one value) is not descended into."""
    whole = set(whole)
    for name, value in tree.items():
        key = prefix + name
        if isinstance(value, dict) and value and key not in whole:
            yield from iter_leaf_paths(value, key + ".", whole)
        else:
            yield key, copy.deepcopy(value)
