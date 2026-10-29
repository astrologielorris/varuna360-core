# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Capability-scoped ``SETTING_ARGS`` rows (SPEC-SET-003 §4.4, W4a).

Every property of every capability is classified, the tagged ones and the
untagged aliases alike. A row is one of:

- ``INPUT``: a per-call input (``cycle``, ``levels``, ``drill``, ``side``...);
- ``setting(key)``: the property IS the setting ``key``;
- ``setting(key, member)``: a dict-member projection (``dasha.chara.overrides``
  member ``count``: a Chara switch);
- ``side_setting(template, selector)``: a conditional side mapping
  (``dasha_ayanamsa_id`` -> ``dasha.<side>.ayanamsa_id``, the side named by
  the ``selector`` option; absent or null = follow the side's own setting);
- ``META``: a switch about settings themselves (``factory_defaults``).

These are capability data, not registry data: they drive the schema export,
the ``--tool`` parser, the refusal at each external entry point and the packet
v2 conversion. Two properties of one capability that map to one key need a
stated precedence (``SETTING_PRECEDENCE`` of the module, winner first).
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, Optional, Tuple

INPUT = ("input",)
META = ("meta",)
SIDES = ("left", "right")


def setting(key: str, member: Optional[str] = None) -> Tuple:
    return ("setting", key) if member is None else ("setting", key, member)


def side_setting(template: str, selector: str = "side") -> Tuple:
    return ("side", template, selector)


def is_setting(row: Tuple) -> bool:
    return row[0] in ("setting", "side")


def base_keys(row: Tuple) -> Tuple[str, ...]:
    """Every settings key a row can name (a side mapping: both sides)."""
    if row[0] == "setting":
        return (row[1],)
    if row[0] == "side":
        return tuple(row[1].format(side=s) for s in SIDES)
    return ()


def member_of(row: Tuple) -> Optional[str]:
    return row[2] if row[0] == "setting" and len(row) == 3 else None


def concrete_key(row: Tuple, options: Mapping[str, Any],
                 defaults: Mapping[str, Any] = None) -> Optional[str]:
    """The one key a setting row names for these options (a side mapping
    reads its selector, falling back to the selector's schema default)."""
    if row[0] == "setting":
        return row[1]
    if row[0] == "side":
        side = options.get(row[2])
        if side is None:
            side = (defaults or {}).get(row[2])
        return row[1].format(side=side) if side in SIDES else None
    return None


def settings_rows(table: Mapping[str, Tuple]) -> Dict[str, Tuple]:
    return {name: row for name, row in table.items() if is_setting(row)}


def split_options(table: Mapping[str, Tuple], options: Mapping[str, Any],
                  defaults: Mapping[str, Any] = None,
                  base: Mapping[str, Any] = None,
                  precedence: Mapping[str, Tuple[str, ...]] = None
                  ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """``(per_call, frozen)``: the per-call options, and the settings the
    setting-named options stand for as flat keys (packet v2 conversion).

    ``base`` holds the frozen values already known (the capture's live
    values): a member projection merges into a copy of the base dict, so
    the overrides the panel did not name keep their frozen value. A null
    side mapping means "follow the side": nothing is frozen for it. An
    unknown option name is kept per-call (the catalog refuses it later).

    ``precedence`` (the capability's ``setting_precedence``, winner first):
    when two scalar properties name one key, the winner is the first of the
    declared order that was given, whatever the JSON property order (W4
    review F4); a member projection still wins over its whole-dict property,
    as the declared Chara order says."""
    per_call: Dict[str, Any] = {}
    frozen: Dict[str, Any] = {}
    given: Dict[str, Dict[str, Any]] = {}          # key -> {property: value}
    members: List[Tuple[str, str, Any]] = []
    for name, value in options.items():
        row = table.get(name, INPUT)
        if not is_setting(row):
            per_call[name] = value
            continue
        if value is None:
            continue
        key = concrete_key(row, options, defaults)
        if key is None:
            continue
        member = member_of(row)
        if member is None:
            given.setdefault(key, {})[name] = value
        else:
            members.append((key, member, value))
    for key, named in given.items():
        order = [n for n in (precedence or {}).get(key, ()) if n in named]
        # A declared winner; else (one property, or an undeclared pair the
        # guard test forbids) the last one given, as before.
        winner = order[0] if order else list(named)[-1]
        frozen[key] = copy.deepcopy(named[winner])
    for key, member, value in members:
        if key not in frozen:
            start = (base or {}).get(key)
            frozen[key] = copy.deepcopy(start) if isinstance(start, dict) else {}
        frozen[key][member] = copy.deepcopy(value)
    return per_call, frozen


def collisions(table: Mapping[str, Tuple]) -> Dict[str, Tuple[str, ...]]:
    """key -> the properties mapping to it, for every key named by two or
    more properties (members of a dict key count as that key)."""
    named: Dict[str, List[str]] = {}
    for name, row in table.items():
        for key in base_keys(row):
            named.setdefault(key, []).append(name)
    return {k: tuple(sorted(v)) for k, v in named.items() if len(v) > 1}


def used_keys(table: Mapping[str, Tuple]) -> Tuple[str, ...]:
    """Every settings key the table's setting rows can name, sorted."""
    out = set()
    for row in table.values():
        out.update(base_keys(row))
    return tuple(sorted(out))


def count(table: Mapping[str, Tuple]) -> Dict[str, int]:
    rows = list(table.values())
    return {"properties": len(rows),
            "setting": sum(1 for r in rows if r[0] == "setting" and len(r) == 2),
            "member": sum(1 for r in rows if member_of(r) is not None),
            "side": sum(1 for r in rows if r[0] == "side"),
            "input": sum(1 for r in rows if r == INPUT),
            "meta": sum(1 for r in rows if r == META)}
