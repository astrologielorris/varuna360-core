# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The four rating rows and the zone (SPEC-LIB-002 §3.1, §3.2).

``zone(who, known)`` is the only place the zone rule lives. Privacy decisions
read ``core.library.privacy.effective_privacy``, which uses it.
"""
from typing import Any, Mapping, Optional

WHO = ("family", "close_friend", "friend", "short_friend", "met_online", "follow",
       "not_personal")
PERSONAL = frozenset(WHO[:-1])
LEVEL_ROWS = ("known", "know_them", "favourite")

PRIVATE, MIXED, PUBLIC = "PRIVATE", "MIXED", "PUBLIC"


def _level(value: Any) -> Optional[int]:
    """A 0..5 row value, or None when missing or invalid (counts as unrated)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 5 else None


def zone(who: Optional[str], known: Optional[int]) -> Optional[str]:
    """PRIVATE, MIXED or PUBLIC from rows 1 and 2; None when either is unset.

    A personal relation known 0-1 is PRIVATE, known 2+ MIXED; ``not_personal``
    known 0 (a stranger seen only on social media) is PRIVATE, known 1+ PUBLIC.
    """
    known = _level(known)
    if who not in WHO or known is None:
        return None
    if who in PERSONAL:
        return MIXED if known >= 2 else PRIVATE
    return PUBLIC if known >= 1 else PRIVATE


def clean(table: Any) -> dict:
    """The valid rows of a ``[rating]`` table; missing or invalid rows are
    dropped (unrated), unknown keys ignored, ``rated`` and ``accepted`` kept."""
    if not isinstance(table, Mapping):
        return {}
    out = {}
    if table.get("who") in WHO:
        out["who"] = table["who"]
    for row in LEVEL_ROWS:
        level = _level(table.get(row))
        if level is not None:
            out[row] = level
    if isinstance(table.get("rated"), str):
        out["rated"] = table["rated"]
    accepted = table.get("accepted")
    if isinstance(accepted, list):
        out["accepted"] = [a for a in accepted if isinstance(a, str)]
    if isinstance(table.get("rated_by"), str):
        out["rated_by"] = table["rated_by"]
    return out


def table_zone(table: Any) -> Optional[str]:
    """The zone of a confirmed ``[rating]`` table, or None when rows 1-2 are unset."""
    rows = clean(table)
    return zone(rows.get("who"), rows.get("known"))


# ------------------------------------------------------------------ words
ROWS = ("who",) + LEVEL_ROWS

WHO_LABELS = {"family": "Family", "close_friend": "Close friend", "friend": "Friend",
              "short_friend": "Short friend", "met_online": "Met online",
              "follow": "Follow", "not_personal": "Not personal"}
WHO_SHORT = {"family": "Family", "close_friend": "Close", "friend": "Friend",
             "short_friend": "Short", "met_online": "Online", "follow": "Follow",
             "not_personal": "Not personal"}
ROW_TITLES = {"who": "Who this person is to you", "known": "How known",
              "know_them": "How well you know them", "favourite": "Favourite"}
LEVEL_WORDS = {
    "known": ("only their social media", "a model or a small public page",
              "a career on the web", "known in their field", "a celebrity", "a superstar"),
    "know_them": ("not at all", "a little", "some", "fairly well", "well",
                  "could describe their character"),
    "favourite": ("not a favourite", "a little", "some", "a favourite", "a strong favourite",
                  "a top favourite"),
}


def words(row: str, value) -> str:
    """The plain words under a row for its value ("" when unset)."""
    if value is None:
        return ""
    if row == "who":
        return WHO_LABELS.get(value, "")
    level = _level(value)
    return LEVEL_WORDS[row][level] if level is not None else ""


# ------------------------------------------------------------------ the file
class Changed(Exception):
    """The chart file changed since the card was shown (INV-3); checked by
    ``tables`` on the bytes the write itself reads."""


def fingerprint(path) -> tuple:
    import hashlib
    from pathlib import Path
    data = Path(path).read_bytes()
    return (len(data), hashlib.sha256(data).hexdigest())


def read(path) -> dict:
    """The confirmed ``[rating]`` of a ``.toml`` chart (cleaned), ``{}`` when none."""
    from core.library import tables
    return clean(tables.get(path, "rating"))


def build(values: Mapping, accepted=(), today: Optional[str] = None) -> dict:
    """The ``[rating]`` table written on confirm: the set rows, ``accepted``
    (rows confirmed untouched), the date, ``rated_by = "user"``."""
    import datetime
    out = {row: values[row] for row in ROWS if values.get(row) is not None}
    rows = clean(out)
    if "who" not in rows or "known" not in rows:
        raise ValueError("rows 1 and 2 must be set to confirm a rating")
    rows["accepted"] = [r for r in ROWS if r in accepted and r in rows]
    rows["rated"] = today or datetime.date.today().isoformat()
    rows["rated_by"] = "user"
    return rows


def write(path, table: Optional[dict], expect=None) -> Optional[dict]:
    """Set (or with ``None`` remove) the chart's ``[rating]``; returns the
    raw table that was there (None when none), for UNDO. ``expect`` is the
    file's ``fingerprint`` when the card was shown: a changed file is refused."""
    from core.library import tables
    if not str(path).lower().endswith(".toml"):
        raise ValueError("ratings are written to .toml charts only")
    previous = tables.get(path, "rating")
    try:
        if table is None:
            tables.remove_table(path, "rating", expect)
        else:
            tables.set_table(path, "rating", table, expect)
    except tables.Changed as exc:
        raise Changed(str(exc)) from exc
    return previous
