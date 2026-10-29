"""Combo boxes that carry their values in itemData (SPEC-LOC-002 INV-3).

A combo's item text is display text and will be translated; the value code
persists, compares or searches on rides in itemData. These two helpers keep
that pattern one call long at every site.
"""

from __future__ import annotations


def add_valued_items(combo, pairs) -> None:
    """Append ``(label, value)`` pairs; a bare string item is its own value."""
    for pair in pairs:
        if isinstance(pair, str):
            combo.addItem(pair, pair)
        else:
            label, value = pair
            combo.addItem(label, value)


def select_by_data(combo, value) -> bool:
    """Select the item whose itemData equals ``value``. Leaves the selection
    unchanged and returns False when no item carries it (the same outcome
    ``setCurrentText`` had for an unknown text)."""
    index = combo.findData(value)
    if index < 0:
        return False
    combo.setCurrentIndex(index)
    return True
