# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Name blinding: which words of a text are a person's name or a file's, and
how they are replaced (SPEC-AIC-001 privacy, every edition).

Moved out of ``core/ai_capture/privacy`` (the AI task privacy, Pro only,
SPEC-EDN-002) so the basic problem report of every edition can scrub names
without the AI package; ``core.ai_capture.privacy`` re-exports all of it."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

NAME_WITHHELD = "the native"
CHART_LABEL = "Chart"
# Packet keys that name the chart or point to its file (every other string is
# scrubbed by text: a region's own "name" such as "Strength" stays).
_NAME_KEYS = ("chart_title", "chart", "source_path")   # "chart": list_captures' label
# R1-fix 5 (Astra R1 review finding 5) and R1-fix2 N4: two kinds of name,
# two tokenizers.
#
# An IDENTITY field (the task title, a chart title) is a name as the user
# wrote it: EVERY token of it is scrubbed, whatever it is ("An Nguyen"
# scrubs "An", "Jane Do" scrubs "Do", "Agent 7" scrubs "7", "J. Smith"
# scrubs "J"): an explicit identity fragment stays an identity when it
# happens to equal a common word. To keep prose readable, a token that
# equals a common word is scrubbed CASE-SENSITIVELY, as written ("An"
# scrubbed, "an" not); a one-letter token likewise (an initial is written
# in capitals: "R" scrubbed, "r" not); every other token is scrubbed
# case-insensitively. The one exception: a four-digit year (1000 to 2099)
# is not scrubbed ALONE (a reading keeps its birth year; orchestrator
# decision, D21-help-drafts.md); every other digit token is.
_COMMON_WORDS = frozenset({"the", "and", "of", "a", "an", "or", "in", "at", "on",
                           "de", "du", "la", "le", "les", "et", "y", "da", "di", "do",
                           "das", "dos", "el", "los", "las", "und", "der",
                           "to", "by", "for", "is", "as", "it", "no", "so", "up"})
# ("van", "von", "del" are name particles, not prose words: scrubbed whatever the case.)
_YEAR = re.compile(r"^(1\d{3}|20\d{2})$")
# A FILE or FOLDER name (a chart file's stem, the task folder) carries the
# name plus decorations: dates, counters, versions and these words. The
# decorations are stripped BEFORE tokenizing, so "ZeldaSecret_chart.chtk"
# names "ZeldaSecret" (never the word "chart"), and the rest is an identity.
_DECORATIONS = frozenset({"chart", "charts", "natal", "birth", "horoscope", "reading", "task",
                          "capture", "data", "file", "copy", "new", "old", "final", "draft",
                          "test", "backup", "bak", "export", "import", "chtk", "toml", "json",
                          "txt", "md"})
_DATE_LIKE = re.compile(r"^(\d{4}[-_.]?\d{2}[-_.]?\d{2}|\d{1,4}|v\d+)$", re.IGNORECASE)
_EXTENSIONS = (".chtk", ".toml", ".json", ".txt", ".md", ".png")


def _fold(text: str) -> str:
    """'José Álvarez' -> 'Jose Alvarez' (accents dropped)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))


def _tokens(text: str) -> List[str]:
    return [w for w in re.split(r"[\s_\-.,]+", text) if w]


def exact_token(token: str) -> bool:
    """A token scrubbed as written (case-sensitively): a common word, or a
    single letter (an initial)."""
    return token.lower() in _COMMON_WORDS or (len(token) == 1 and token.isalpha())


def identity_parts(name: str) -> List[str]:
    """'Anandamayi Ma' -> ['Anandamayi Ma', 'Anandamayi', 'Ma']; '_' and '-'
    read as spaces; accent-free spellings too. Every token is scrubbed
    alone (R1-fix2 N4), a four-digit year excepted."""
    full = re.sub(r"[_\-]+", " ", str(name or "")).strip()
    if not full:
        return []
    out = [full]
    out += [w for w in _tokens(full) if w != full and not _YEAR.match(w)]
    out += [_fold(w) for w in out if _fold(w) != w]
    return out


def file_parts(name: str) -> List[str]:
    """A chart file's stem or a task folder's name -> the identity it carries,
    decorations (extension, dates, counters, versions, generic words) stripped
    first: '2026-10-05_Lorris_tools' -> identity 'Lorris tools';
    'Agent_1234_chart.chtk' -> 'Agent 1234'."""
    stem = str(name or "")
    low = stem.lower()
    for ext in _EXTENSIONS:
        if low.endswith(ext):
            stem = stem[:-len(ext)]
            break
    raw = stem
    stem = re.sub(r"\d{4}-\d{2}-\d{2}", " ", stem)              # a date stamp anywhere
    kept = [w for w in _tokens(stem)
            if w.lower() not in _DECORATIONS and not _DATE_LIKE.match(w)]
    out = identity_parts(" ".join(kept))
    # The whole stem as written is a name too ('Zoe_Angstrom_v2' in a text
    # must not leave 'the native_v2' behind).
    whole = re.sub(r"[_\-]+", " ", raw).strip()
    if whole and whole not in out:
        out.append(whole)
    return out


def _parts(name: str) -> List[str]:
    """Kept for callers of the old single tokenizer: an identity."""
    return identity_parts(name)


# A name's words may be joined by spaces, '_', '-', dots or nothing
# ('KN Rao', 'KN_Rao', 'K.N. Rao', 'K.N.Rao').
_SEP = r"[\s_\-.]*"
# Word boundary that treats '_' as a separator ('2026-10-03_KN_Rao_reading').
_LEFT, _RIGHT = r"(?<![^\W_])", r"(?![^\W_])"


def _pattern(name: str) -> str:
    """One name -> regex. An initials word ('KN', 'J.R.R.') matches with or
    without dots between its letters."""
    words = [w for w in re.split(r"[\s.]+", name) if w]
    out = []
    for w in words:
        if w.isupper() and len(w) <= 3:
            out.append(r"\.?\s*".join(re.escape(c) for c in w) + r"\.?")
        else:
            out.append(re.escape(w))
    return _LEFT + _SEP.join(out) + _RIGHT


# A schema word as a dictionary key (W6c R3-1): lowercase and digits joined
# by '_', '.' or '-' ("chart_title", "dasha.chara.overrides", "region-1").
_SCHEMA_KEY = re.compile(r"^[a-z0-9_]+(?:[.\-][a-z0-9_]+)*$")


def _is_setting_key(key: Any) -> bool:
    """A registry setting's key (``dasha.chara.overrides``): its value is the
    user's, never schema."""
    if not isinstance(key, str) or "." not in key or not _SCHEMA_KEY.match(key):
        return False
    try:
        from core import settings_registry as registry
        registry.get(key)
    except Exception:                                             # noqa: BLE001
        return False
    return True


def _unique_keys(pairs: Iterable[Tuple[Any, Any]]) -> Dict[Any, Any]:
    """A dict from (key, value) pairs whose scrubbed keys may collide
    ("Lorris" and "lorris" both become "the native"): a later one is
    numbered, never dropped."""
    out: Dict[Any, Any] = {}
    for k, v in pairs:
        if k in out:
            n = 2
            while f"{k} ({n})" in out:
                n += 1
            k = f"{k} ({n})"
        out[k] = v
    return out


class Blind:
    """The names of one task, and the scrubbing that removes them.
    ``names``: identity fields (titles); ``files``: file and folder names
    (their decorations are not names). Two expressions: the exact tokens
    (common words and initials, matched as written) and the rest (matched
    whatever the case); each longest first."""

    def __init__(self, names: Iterable[str], files: Iterable[str] = ()):
        found = set()
        for n in names:
            found.update(identity_parts(n))
        for f in files:
            found.update(file_parts(f))
        # Longest first: 'KN Rao' goes before a part of it would.
        self.names = sorted(found, key=len, reverse=True)
        loose = [n for n in self.names if not exact_token(n)]
        exact = [n for n in self.names if exact_token(n)]
        self._re = (re.compile("|".join(_pattern(n) for n in loose), re.IGNORECASE)
                    if loose else None)
        self._re_exact = re.compile("|".join(_pattern(n) for n in exact)) if exact else None

    @classmethod
    def for_task(cls, task_folder: Path) -> "Blind":
        """The names of the task NOW (one snapshot; see TaskPrivacy for a
        conversation, which must take a new one per payload)."""
        return TaskPrivacy(task_folder).snapshot().blind

    def text(self, value: str) -> str:
        if not isinstance(value, str):
            return value
        if self._re is not None:
            value = self._re.sub(NAME_WITHHELD, value)
        if self._re_exact is not None:
            value = self._re_exact.sub(NAME_WITHHELD, value)
        return value

    def key(self, key: Any) -> Any:
        """A dictionary KEY as a payload carries it (W6c R3-1). A schema word
        (lowercase and digits joined by ``_``, ``.`` or ``-``: ``chart_title``,
        ``dasha.chara.overrides``) is the payload's own vocabulary and stays
        as written, so a chart titled "Chart" never renames ``chart_title``
        (R1-fix 5: not even a key ``chart`` for a chart titled "Chart"); any
        other key is data (a map keyed by a name, ``{"Lorris": true}``) and
        is scrubbed like a value. A USER value's keys are all data
        (``deep``), whatever their form."""
        if not isinstance(key, str) or _SCHEMA_KEY.match(key):
            return key
        return self.text(key)

    def deep(self, value: Any) -> Any:
        """A USER value (a setting's value: an override map, a note) with the
        names removed from every string in it, dictionary keys included
        whatever their form (W6c R3-1): nothing in a user value is schema."""
        if isinstance(value, dict):
            return _unique_keys((self.text(k) if isinstance(k, str) else k, self.deep(v))
                                for k, v in value.items())
        if isinstance(value, (list, tuple)):
            return [self.deep(v) for v in value]
        return self.text(value)

    def doc(self, value: Any) -> Any:
        """A JSON-like value with the names removed. chart_title becomes
        "Chart", source_path is dropped, every other string value is
        scrubbed. Keys (W6c R3-1): a schema word stays as written (R1-fix 5),
        any other key is scrubbed (``key``); the value of a registry setting
        key (a capture's frozen ``settings``: an override map may be keyed by
        a name) is a user value, scrubbed keys and all (``deep``)."""
        if isinstance(value, dict):
            pairs = []
            for k, v in value.items():
                if k in _NAME_KEYS and isinstance(v, str):
                    pairs.append((k, None if k == "source_path" else CHART_LABEL))
                elif isinstance(v, (dict, list, tuple)) and _is_setting_key(k):
                    pairs.append((k, self.deep(v)))
                else:
                    pairs.append((self.key(k), self.doc(v)))
            return _unique_keys(pairs)
        if isinstance(value, (list, tuple)):
            return [self.doc(v) for v in value]
        return self.text(value)


# ------------------------------------------------------------- provider
