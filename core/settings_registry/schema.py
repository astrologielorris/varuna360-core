# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The shape of one settings registry entry (SPEC-SET-003 §3.1).

Qt-free, import-side-effect free: plain data only. Engine tables (house
systems, year lengths...) are referenced by ``ChoicesRef`` and
resolved on first use, so importing the registry never imports an engine.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Optional, Tuple, Union

from core.settings_registry.rules import KIND_LEAF, KIND_SECTION, Rules, kind_of  # noqa: F401

NoneType = type(None)
# Settings tab sections (logical ids; Core and Pro lay them out differently).
SECTIONS = ("zodiac_calculation", "chart_display", "appearance", "folders",
            "display_scale", "fonts")


@dataclass(frozen=True)
class Choice:
    value: Any
    label: str = ""


@dataclass(frozen=True)
class ChoicesRef:
    """``"module.path:NAME"``: a dict whose keys are the values (and whose string
    values are labels), or a tuple/list of values, of ``(value, label, ...)``
    tuples (AYANAMSA_OPTIONS), or of objects with ``key`` and ``label`` (dasha MODES)."""
    target: str

    def resolve(self) -> Tuple[Choice, ...]:
        # Loaded by the package (load_table): no dynamic import here (SI guard).
        from core.settings_registry import load_table
        table = load_table(self.target)
        if isinstance(table, dict):
            # str values are labels; objects may carry a ``title``
            return tuple(Choice(k, v if isinstance(v, str)
                                else str(getattr(v, "title", "") or ""))
                         for k, v in table.items())
        out = []
        for v in table:
            if isinstance(v, tuple):
                out.append(Choice(v[0], str(v[1])))
            elif hasattr(v, "key"):
                out.append(Choice(v.key, str(getattr(v, "label", "") or "")))
            else:
                out.append(Choice(v))
        return tuple(out)

Choices = Union[None, Tuple[Choice, ...], ChoicesRef]

@dataclass(frozen=True)
class Setting:
    key: str
    type: Union[type, Tuple[type, ...]]
    default: Any
    label: str = ""
    help: str = ""
    choices: Choices = None
    bounds: Optional[Tuple[float, float]] = None   # (minimum, maximum), inclusive
    widget: str = "none"            # combo | check | radio | spin | text | path | custom | none
    section: Optional[str] = None   # owning Settings tab section; None = no row
    lockable: bool = True
    persisted: bool = True          # False: fallback only, never in DEFAULT_SETTINGS
    live: bool = False
    live_reader: Optional[str] = None
    watch: Optional[str] = None
    edition: str = "core"           # core | pro
    rules: Optional[Rules] = None   # v0.7: replaces the kind field (rules.py)

    def factory(self) -> Any:
        """The default, deep-copied (a list or dict default is never shared)."""
        return copy.deepcopy(self.default)

    @property
    def kind(self) -> str:
        return kind_of(self.rules)


def choice_values(entry: Setting) -> Optional[Tuple[Any, ...]]:
    if entry.choices is None:
        return None
    items = (entry.choices.resolve() if isinstance(entry.choices, ChoicesRef)
             else entry.choices)
    return tuple(c.value for c in items)
