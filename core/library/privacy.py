# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The one privacy rule of SPEC-LIB-001, SPEC-LIB-002 and SPEC-BIO-001 (LIB-001 §3.5).

1. A confirmed ``[rating]`` decides first (its zone).
2. Else ``[library].privacy`` and the guess; the strictest wins.
3. Nothing known gives ``review``.

Only ``private`` never leaves the computer (D-36); ``review`` and ``mixed``
names may go, name only, to AI guesses and identity lookups.
"""
from typing import Any, Iterable, Mapping, Optional

from core.library import rating as _rating

PRIVATE, REVIEW, MIXED, PUBLIC = "private", "review", "mixed", "public"
LEVELS = (PRIVATE, REVIEW, MIXED, PUBLIC)  # strictest first
_RANK = {level: i for i, level in enumerate(LEVELS)}
_FROM_ZONE = {_rating.PRIVATE: PRIVATE, _rating.MIXED: MIXED, _rating.PUBLIC: PUBLIC}


def _level(value: Any) -> Optional[str]:
    """A privacy level from a folder class, a level or a zone name; None if unknown."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value in _FROM_ZONE:
        return _FROM_ZONE[value]
    value = value.lower()
    return value if value in _RANK else None


def strictest(levels: Iterable[Any]) -> Optional[str]:
    """The strictest known level of ``levels`` (None when none is known)."""
    known = [lv for lv in map(_level, levels) if lv]
    return min(known, key=_RANK.__getitem__) if known else None


def effective_privacy(record: Mapping[str, Any]) -> str:
    """``private``, ``review``, ``mixed`` or ``public`` for one record.

    ``record`` keys (all optional): ``rating`` (the confirmed ``[rating]``
    table), ``library`` (the ``[library]`` table, its ``privacy`` is read) or
    ``privacy`` (that value directly), ``guess`` (the guessed zone or level).
    """
    confirmed = _rating.table_zone(record.get("rating"))
    if confirmed:
        return _FROM_ZONE[confirmed]
    library = record.get("library")
    folder_class = library.get("privacy") if isinstance(library, Mapping) else None
    if folder_class is None:
        folder_class = record.get("privacy")
    return strictest((folder_class, record.get("guess"))) or REVIEW


def may_leave_computer(record: Mapping[str, Any]) -> bool:
    """True when a record's name may go to an AI request or a network lookup."""
    return effective_privacy(record) != PRIVATE


def stays_owner_only(level: str) -> bool:
    """``private`` and ``review`` are handled the same way on disk (0700)."""
    return level in (PRIVATE, REVIEW)
