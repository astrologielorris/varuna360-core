# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The two computed read-outs (§4.5): privacy 1..10 and preference 1..10.

Derived on read from the rating rows, ``effective_privacy`` and the manifest's
signals; never written to a chart file (O-4, recommendation applied).
"""
from typing import Mapping, Optional

from core.library import rating as _rating
from core.library.privacy import effective_privacy

_CLOSE = ("family", "close_friend")


def privacy_readout(record: Mapping, *, has_biography: bool = False,
                    guess: Optional[Mapping] = None) -> int:
    """1 public .. 10 most private. ``record`` is a manifest row (``rating``,
    ``privacy``, ``kind``, ``copies``, ``variants``); ``guess`` the guessed rows."""
    rows = _rating.clean(record.get("rating")) or _rating.clean(guess)
    level = effective_privacy({"rating": record.get("rating"), "privacy": record.get("privacy"),
                               "guess": _rating.table_zone(guess) if guess else None})
    if level == "public":
        return 1 if has_biography else 3
    if level == "review" or record.get("kind") == "case" or not rows.get("who"):
        return 5 if level == "review" else 7
    if rows["who"] in _CLOSE:
        closeness = int(record.get("copies") or 1) + int(record.get("variants") or 1) - 1
        return 10 if closeness >= 3 else 9
    return 8 if rows["who"] in ("friend", "follow") else 7


def preference_readout(record: Mapping, *, old_favourite: bool = False) -> int:
    """1 rarely used .. 10 favourite: twice the ``favourite`` row when set (0
    reads 1), else copies, variants and the old favourites, capped to 10."""
    rows = _rating.clean(record.get("rating"))
    if "favourite" in rows:
        return max(1, 2 * rows["favourite"])
    value = int(record.get("copies") or 1) + int(record.get("variants") or 1) - 1
    if old_favourite:
        value += 4
    return max(1, min(10, value))
