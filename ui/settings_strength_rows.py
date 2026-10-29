# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings row for the DUC Bala method (SPEC-STR-001 §7.5, Settings > Zodiac).

Kept out of ``ui/settings_tab.py`` (which only calls ``build_rows``, ``read_rows`` and
``apply_rows``) so the tab does not grow. The row writes ``strength.duc_method``, the key
the Strength panel, the Avastha views, the capabilities and the CLIs read; the panels
listen to it (``on_changed``), so a change redraws them at once.
"""
from PySide6.QtWidgets import QComboBox, QSizePolicy

from core import settings_registry as _registry
from ui.settings_rows import calculation_tooltip as _tooltip
from ui.settings_rows import choices as _choices

KEYS = ("strength.duc_method",)


def build_rows(form, locked_row):
    """Add the row to ``form`` with the tab's padlock row builder; returns {key: combo}."""
    combos = {}
    for key in KEYS:
        combo = QComboBox()
        for value, text in _choices(key):
            combo.addItem(text, value)
        # the item texts carry the rule, so the box fits them rather than the 220 px cap
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        _tooltip(combo, key)
        locked_row(form, key, _registry.get(key).label, combo)
        combos[key] = combo
    return combos


def read_rows(combos, settings):
    """Show the saved values (an unknown saved value shows the factory item)."""
    for key, combo in combos.items():
        idx = combo.findData(settings.get(key, _registry.default(key)))
        combo.setCurrentIndex(idx if idx >= 0 else 0)


def apply_rows(combos, settings):
    """Write every row's value; True when any of them changed."""
    changed = False
    for key, combo in combos.items():
        value = combo.currentData()
        if settings.get(key, _registry.default(key)) != value:
            changed = True
        settings.set(key, value)
    return changed
