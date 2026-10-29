# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Domain term access (SPEC-LOC-002 §3.2, §4.4).

``term(kind, ident, form="name", lang=None)`` returns the display text of a term
(planet, sign, aditya, nakshatra, month, weekday, ...). Term tables are data:
``i18n/en/terms/<kind>.json`` is GENERATED from the engine tables by
tools/i18n_extract.py; ``i18n/<code>/terms/<kind>.json`` are authored and
reviewed. Spelling variants map through ``i18n/terms_aliases.json``.

The implementation lives in core/i18n/catalog.py (templates resolve TermRef
params through the same catalogs); this module is the public face.
"""
from core.i18n.catalog import (  # noqa: F401
    TermRef, canonical_ident, term, term_gender, term_idents, term_misses, term_tooltip,
    untranslated_terms)

__all__ = ["TermRef", "canonical_ident", "term", "term_gender", "term_idents",
           "term_misses", "term_tooltip", "untranslated_terms"]
