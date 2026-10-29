# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Name normalisation, compatible names (INV-4) and clear file names (§3.1)."""
import re
import unicodedata
from typing import Iterable, Optional, Tuple

# Words that never make two names "the same person" on their own.
_NOISE = frozenset((
    "the", "and", "of", "de", "du", "des", "la", "le", "les", "von", "van", "der",
    "jr", "sr", "chart", "natal", "birth", "copy", "new", "test", "rectified",
    "rectification", "rect", "noon", "time", "unknown",
))
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')


def repair(name: str) -> str:
    """Undo UTF-8 read as Latin-1 / cp1252 ("FaÃ¯d" -> "Faïd"); else unchanged."""
    text = str(name or "")
    if not any(c in text for c in "ÃÂâ"):
        return text
    for codec in ("cp1252", "latin-1"):
        try:
            return text.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def normalise(name: str) -> str:
    """Lower case, accents and punctuation removed, single spaces."""
    text = unicodedata.normalize("NFKD", repair(name))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def tokens(name: str) -> frozenset:
    """The meaningful words of a name (two letters or more, no noise words)."""
    return frozenset(t for t in normalise(name).split()
                     if len(t) >= 2 and t not in _NOISE and not t.isdigit())


def compatible(a: str, b: str, aliases: Iterable[Tuple[str, str]] = ()) -> bool:
    """True when two names may be one subject: a shared word, one name contained
    in the other, or an alias pair Lorris confirmed (``verdicts.json``)."""
    if (a or "").strip() and (a or "").strip() == (b or "").strip():
        return True
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return False
    if na == nb or f" {na} " in f" {nb} " or f" {nb} " in f" {na} ":
        return True
    if tokens(a) & tokens(b):
        return True
    pair = {na, nb}
    return any({normalise(x), normalise(y)} == pair for x, y in aliases)


def most_complete(names: Iterable[str]) -> str:
    """The display name: most words, then most frequent, then first seen."""
    names = [repair(n).strip() for n in names if n and n.strip()]
    if not names:
        return ""
    count = {}
    for n in names:
        count[n] = count.get(n, 0) + 1
    order = {n: i for i, n in reversed(list(enumerate(names)))}
    return max(count, key=lambda n: (len(n.split()), count[n], -order[n]))


def clear_name(name: str, *, limit: int = 80) -> str:
    """A file or folder name: forbidden characters removed, underscores read
    as spaces, single spaces, no leading or trailing dots."""
    text = _FORBIDDEN.sub(" ", str(name or "")).replace("_", " ")
    text = " ".join(text.split()).strip(" .")
    return (text[:limit].rstrip(" .") or "Unnamed")


def clear_section(section: Optional[str]) -> str:
    """A section folder name in clear English: first letter capital."""
    text = clear_name(section or "Unsorted")
    return text[:1].upper() + text[1:]
