# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Which edition has which feature: one Qt-free table (SPEC-EDN-002 §3.3).

Code asks ``edition_has("ai")``; it never compares edition strings inline
(INV-5). The sets nest (INV-1): a feature is in every edition, in Pro and
Personal, or in Personal only, so nothing Pro has can be missing from
Lorris's own build.

The table says what an EDITION has. ``core.build_features`` stays the
per-branch switch (a kill switch); a user-facing AI surface installs only
when both say yes, which is ``ai_enabled()``.

Stdlib only.
"""
from __future__ import annotations

from typing import Optional

from core import edition as _edition

LITE, PRO, PERSONAL = _edition.LITE, _edition.PRO, _edition.PERSONAL
ALL = frozenset({LITE, PRO, PERSONAL})
PRO_UP = frozenset({PRO, PERSONAL})
PERSONAL_ONLY = frozenset({PERSONAL})
ALLOWED_SHAPES = (ALL, PRO_UP, PERSONAL_ONLY)

FEATURES = {
    # Every AI surface: capture, library, AI settings, AI search, the coach
    # and the hub's tiles, Connect AI apps. Future AI features join this key.
    # Lite's two exceptions (the chart image paste with its provider setting,
    # and Report a problem, D-12 / D-17) are not behind it.
    "ai": PRO_UP,
    "mcp_server": PRO_UP,          # Varuna360 --mcp
    "partner_reading": PRO_UP,     # the mynatal readings
}


def edition_has(feature: str, edition: Optional[str] = None) -> bool:
    """True when ``edition`` (default: the running one) has ``feature``.
    An unknown feature raises KeyError: a typo must not read as "no"."""
    allowed = FEATURES[feature]
    return (edition or _edition.current_edition()) in allowed


def running_edition() -> str:
    """The edition this process runs: a build is its own; otherwise the
    launcher's choice (run_app), else Pro exactly when the Pro package
    registered its main window. ``current_edition()`` without a launcher
    reads argv, which the GUI strips of ``--lite``. (Moved from
    core/ai_capture/packet, which re-exports it.)"""
    if _edition._BUILD_EDITION is not None:
        return _edition._BUILD_EDITION
    from core.edition_hooks import MAIN_WINDOW_CLASS, provider, resolve
    chosen = resolve(_edition.PROCESS_EDITION)
    if chosen in _edition.EDITIONS:
        return chosen
    return _edition.PRO if provider(MAIN_WINDOW_CLASS) is not None else _edition.LITE


def ai_enabled() -> bool:
    """A user-facing AI surface may install: the edition has AI and the
    branch has not switched AI capture off (SPEC-EDN-002 §3.3)."""
    from core.build_features import ai_capture_enabled
    return edition_has("ai") and ai_capture_enabled()


def ai_features(edition: Optional[str] = None):
    """``apps.ai_features``, the one door from shared code to the AI
    surfaces, or None in Lite: the Lite build ships no AI file, and its
    manifest gate counts every import, so shared code never names an AI
    module (SPEC-EDN-002 P4). Found by name; callers that need the branch
    switch too still ask ``ai_enabled()``. ``edition`` given (a launcher
    mode's own arguments) = that edition decides."""
    if not edition_has("ai", edition):
        return None
    import importlib
    try:
        return importlib.import_module("apps.ai_features")
    except ModuleNotFoundError as e:
        if e.name != "apps.ai_features":
            raise
        return None


def partner_reading_available() -> bool:
    """The mynatal readings may show: the edition has them and the branch
    switch is on (SPEC-PRT-001 D-3)."""
    from core.build_features import partner_reading_enabled
    return edition_has("partner_reading") and partner_reading_enabled()
