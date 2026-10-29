# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings tab rows built from the settings registry (SPEC-SET-003 §4.3).

A row's values, their labels, its default and its Reset membership come from
the key's registry entry, so the Settings tab never re-types them. The tab
keeps its own layout, signals and custom rules (the zodiac combo's Beginner
clamp, the Chara switch box): this module only builds and fills widgets and
resets a section by its registry keys. Writes go through SettingsManager.set
only (Rule 4b: nothing is written on ChartGUI).
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

from PySide6.QtWidgets import QComboBox

from core import settings_registry as registry


def _edition() -> str:
    from core.edition import current_edition
    from core.edition_features import PRO_UP          # Personal owns Pro's keys
    return "pro" if current_edition() in PRO_UP else "core"


def owned_keys(section: str, edition: Optional[str] = None) -> frozenset:
    """The keys a Settings tab section owns: Apply writes only these and Reset
    restores exactly these. The registry's explicit owner set for the running
    edition (SPEC-SET-003 INV-5), never the listing group."""
    return registry.owner_set(section, edition or _edition())


def label(key: str) -> str:
    """The row title of ``key`` (the form label text)."""
    return registry.get(key).label


def help_text(key: str) -> str:
    """The row's description / tooltip text of ``key`` ("" when it has none)."""
    return registry.get(key).help


def radio_options(key: str) -> list:
    """(label, value) pairs for ``_locked_radio_group`` (label first)."""
    return [(lab, value) for value, lab in choices(key)]


def choices(key: str) -> Tuple[Tuple[Any, str], ...]:
    """(value, label) pairs of a key; a missing label shows the value."""
    entry = registry.get(key)
    items = (entry.choices.resolve() if hasattr(entry.choices, "resolve")
             else (entry.choices or ()))
    return tuple((c.value, c.label or str(c.value)) for c in items)


def calculation_tooltip(widget, key: str, note: Optional[str] = None) -> None:
    """A calculation setting's row tooltip: its registry help, the same field
    ``settings.py show`` prints (SPEC-SET-003 D-21, the approved per-key
    help), followed by the control's own existing ``note`` when it has one
    (a blank line between). App settings keep their own description rows."""
    entry = registry.get(key)
    parts = []
    if entry.help and entry.rules is not None and entry.rules.cli == "calculation":
        parts.append(entry.help)
    if note:
        parts.append(note)
    if parts:
        widget.setToolTip("\n\n".join(parts))


def registry_combo(key: str, *, max_width: Optional[int] = 220) -> QComboBox:
    """A combo filled with the key's values (item data) and labels (text)."""
    combo = QComboBox()
    for value, label in choices(key):
        combo.addItem(label, value)
    calculation_tooltip(combo, key)
    if max_width:
        combo.setMaximumWidth(max_width)
    return combo


def select_data(combo: QComboBox, value: Any) -> bool:
    """Select the item whose data is ``value``; False (selection kept) if absent."""
    idx = combo.findData(value)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    return idx >= 0


def saved(settings, key: str) -> Any:
    """The stored value of ``key``, else its registry factory value."""
    return settings.get(key, registry.default(key))


def reset_section(settings, section: str, edition: Optional[str] = None) -> None:
    """One ``settings.set(key, factory default)`` per leaf the section owns, in
    key order. A typed section key (``chart_display``) is restored by its own
    getter, never here."""
    for key in sorted(owned_keys(section, edition)):
        if registry.get(key).kind == "leaf":
            settings.set(key, registry.default(key))
