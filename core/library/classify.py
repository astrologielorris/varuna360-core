# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Local name rules for charts of mixed folders (§4.2 step 3). No network.

A name that reads as a situation (an eclipse, a question, a meeting) is a
private event; an annotated name (a relation, a dating app, a test), a handle,
a name with digits, a single word or a name starting with ``_`` is a private
person. Anything else stays for review (phase 2's identity check or Lorris).
"""
import re
from typing import Optional, Tuple

from core.library.names import normalise

_SITUATION = frozenset((
    "eclipse", "transit", "transite", "transits", "lunar", "solar", "saros", "horary",
    "prasna", "prashna", "question", "questio", "meeting", "accident", "wedding",
    "mariage", "annif", "anniversary", "cyclone", "hurricane", "typhoon", "earthquake",
    "election", "launch", "ingress", "return", "moment", "event", "death", "suicide",
    "conjunction", "muhurta", "muhurtha",
))
_ANNOTATION = frozenset((
    "tinder", "badoo", "facebook", "fb", "insta", "instagram", "snap", "snapchat",
    "forum", "girl", "boy", "guy", "friend", "friends", "copine", "copain", "ami", "amie",
    "mom", "mum", "mother", "mere", "dad", "father", "pere", "son", "daughter", "fille",
    "fils", "brother", "frere", "sister", "soeur", "husband", "wife", "mari", "femme",
    "cousin", "cousine", "niece", "nephew", "neveu", "aunt", "tante", "uncle", "oncle",
    "baby", "bebe", "child", "kid", "enfant", "client", "test", "example", "exemple",
    "exo", "rencontre", "nobd", "inconnu", "inconnue", "unknown", "possible", "match",
    "request", "crush", "boss", "collegue", "colleague", "voisin", "voisine",
    "neighbour", "neighbor",
))
_HANDLE = re.compile(r"@|^\w*_\w*\d|\d\w*_")


def name_rule(name: str) -> Optional[Tuple[str, str, str]]:
    """``(privacy, kind, reason)`` when a local rule decides, else None."""
    raw = (name or "").strip()
    words = normalise(raw).split()
    if not words:
        return ("private", "person", "no name")
    if any(w in _SITUATION for w in words):
        return ("private", "event", "situation word")
    if raw.startswith("_"):
        return ("private", "person", "leading underscore")
    if _HANDLE.search(raw):
        return ("private", "person", "handle")
    if any(w in _ANNOTATION for w in words):
        return ("private", "person", "annotation")
    if any(c.isdigit() for c in raw):
        return ("private", "person", "digits")
    if len(words) == 1:
        return ("private", "person", "single word")
    return None
