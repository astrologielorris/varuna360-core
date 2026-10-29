# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The library scrub of Find Chart's Ask AI (SPEC-FIND-006 §6): every chart
name of the store removed from what leaves for the AI, when the names switch
is off.

The blind scrub (``privacy.Blind``) removes every token of one chart's name:
right for one chart, wrong for a library of thousands, where "Mars Bonfire"
would take the word "Mars" out of every question. This scrub removes WHOLE
names only:

- a name of two or more words matches whatever the case and the accents,
  its words joined by spaces, ``_``, ``-`` or ``.`` ("Jane Doe", "jane_doe",
  "Jané Doe"); initials also match run together ("K.N. Rao" and "KN Rao");
- a one-word name matches as written (case-sensitive, accents folded):
  "Madonna" is scrubbed, "hope" is not scrubbed for a chart named "Hope";
- a name that is a word of the filter vocabulary (a subject, a property, a
  value label in any naming, a qualifier value: "Chart", "Mars", "Leo") or
  of ``privacy._COMMON_WORDS`` is never scrubbed: questions must keep them.

A ``privacy.Blind`` in every other respect (``doc``, ``deep``, ``key``), so
it plugs into the task tools' guard and the settings request's scrub points
unchanged. No Qt, no store access: the caller passes the names.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Iterable

from core.name_blind import _COMMON_WORDS, NAME_WITHHELD, Blind, _fold

#: A word of a name or of a text: letters and digits.
_WORD = re.compile(r"[^\W_]+")
#: What may stand between two words of one name.
_GAP = re.compile(r"^[\s_\-.]*$")


def _key(word: str) -> str:
    return _fold(word).casefold()


def _merge_initials(words: list[str]) -> list[str]:
    """``["K", "N", "Rao"]`` -> ``["KN", "Rao"]``: runs of one-letter words."""
    out: list[str] = []
    run = ""
    for w in words:
        if len(w) == 1 and w.isalpha():
            run += w
            continue
        if run:
            out.append(run)
            run = ""
        out.append(w)
    if run:
        out.append(run)
    return out


@functools.lru_cache(maxsize=1)
def vocabulary() -> frozenset[str]:
    """Every word a filter question may need, folded: properties, subjects,
    groups, value labels in every naming, qualifier names and values."""
    from core.chart_search import guide, taxonomy
    from core.chart_search.extractors.subjects import SUBJECT_GROUPS

    words: set[str] = set(SUBJECT_GROUPS) | set(taxonomy.SUBJECT_ALIASES)
    for name, spec in taxonomy.catalogue().items():
        words.add(name)
        words.update(spec.subjects)
        for q in spec.qualifiers:
            words.add(q.name)
            words.update(v for v in q.values or () if v)
        first = guide.property_guide(name)
        for page in range(1, first["pages"] + 1):
            for item in guide.property_guide(name, page=page)["values"]:
                words.add(str(item["label"]))
                words.update(str(a) for a in item["also"])
        for naming in taxonomy.ALL_NAMINGS:
            for value in spec.values:
                words.add(taxonomy.label(spec, value, taxonomy.Mode.ADITYA, naming))
    return frozenset(_key(w) for w in words)


class LibraryScrub(Blind):
    """The whole names of ``names`` (store entry names), minus ``keep``
    (folded words never scrubbed; default: ``vocabulary()`` and the common
    words). ``marker``: what replaces a name (default ``NAME_WITHHELD``;
    the problem-report scrubber, SPEC-AIR-001 §3.3, uses typed markers)."""

    marker = NAME_WITHHELD

    def __init__(self, names: Iterable[str], keep: frozenset[str] | None = None,
                 marker: str | None = None):
        if marker is not None:
            self.marker = marker
        keep = (vocabulary() if keep is None else keep) | frozenset(_COMMON_WORDS)
        names = tuple(str(n) for n in names if n)
        #: The names as given (a later scrub of the conversation keeps them).
        self.source_names = tuple(dict.fromkeys(names))
        self._multi: set[tuple[str, ...]] = set()
        self._single: set[str] = set()
        for name in names:
            words = _WORD.findall(unicodedata.normalize("NFC", name))
            if not words:
                continue
            if " ".join(_key(w) for w in words) in keep:
                continue
            if len(words) == 1:
                if _key(words[0]) not in keep:
                    self._single.add(_fold(words[0]))
                continue
            for variant in (words, _merge_initials(words)):
                if len(variant) >= 2:
                    self._multi.add(tuple(_key(w) for w in variant))
                elif _key(variant[0]) not in keep:
                    self._single.add(_fold(variant[0]))
        self._longest = max((len(m) for m in self._multi), default=1)
        # Blind's attributes, for code that reads them (nothing to compile).
        self.names = sorted(self._single) + [" ".join(m) for m in sorted(self._multi)]
        self._re = self._re_exact = None

    def __len__(self) -> int:
        return len(self._single) + len(self._multi)

    def text(self, value: str) -> str:
        if not isinstance(value, str) or not value:
            return value
        # One spelling of each accent: a decomposed "E\u0301milie" matches
        # "Émilie" (the text goes on in its composed form).
        value = unicodedata.normalize("NFC", value)
        tokens = [(m.start(), m.end(), m.group()) for m in _WORD.finditer(value)]
        out: list[str] = []
        pos = 0
        i = 0
        while i < len(tokens):
            hit = self._match(value, tokens, i)
            if hit:
                start, end = tokens[i][0], tokens[i + hit - 1][1]
                out.append(value[pos:start])
                out.append(self.marker)
                pos = end
                i += hit
            else:
                i += 1
        out.append(value[pos:])
        return "".join(out)

    def _match(self, text: str, tokens, i: int) -> int:
        """How many tokens from ``i`` form a name (longest first), 0 none."""
        top = min(self._longest, len(tokens) - i)
        for n in range(top, 1, -1):
            run = tokens[i : i + n]
            if not all(
                _GAP.match(text[a[1] : b[0]]) for a, b in zip(run, run[1:])
            ):
                continue
            words = [w for _s, _e, w in run]
            if tuple(_key(w) for w in words) in self._multi:
                return n
            merged = _merge_initials(words)
            if len(merged) >= 2 and tuple(_key(w) for w in merged) in self._multi:
                return n
        word = tokens[i][2]
        return 1 if _fold(word) in self._single else 0
