# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The THREAD key's changed factory default (SPEC-EXCH-002 4.5, td-jr6cd).

``chart.exchange_chain_on`` became True. Every save writes the whole
DEFAULT_SETTINGS under the file, so each profile saved before holds the old
False, inherited, never chosen. The registry's precedent for a changed default
is SPEC-BAR-001 D-15: a one-time flip behind a marker. Qt-free; the settings
object is passed in."""
from __future__ import annotations

from core.exchange_chain import KEY_ON

MARKER = "ui.exchange_chain_on_default_migrated"


def migrate_default(settings):
    """One-time flip of the changed factory default (SPEC-EXCH-002 4.5, the
    SPEC-BAR-001 D-15 pattern): every saved profile holds the inherited old
    False, so set the key True once unless it is locked; then mark it done, so a
    later THREAD off or Settings untick is kept; a read-only manager (a CLI) is
    left alone, like its _migrate_bar_default. Returns True when it flipped."""
    if getattr(settings, "read_only", False) or settings.get(MARKER, False):
        return False             # a CLI's read-only copy draws what its echo shows
    flip = not settings.is_locked(KEY_ON) and settings.get(KEY_ON) is False
    if flip:
        settings.set(KEY_ON, True, save=False)
    settings.set(MARKER, True, save=True)
    return flip
