# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The language-agnostic text engine (SPEC-LOC-002). Qt-free.

    t(key, default, *, lang=None, **params)   UI text
    term(kind, ident, form="name", *, lang=None)   domain vocabulary
    term_tooltip(kind, ident)                  native gloss of a kept term
    TermRef(kind, ident)                       a term inside a t() template
    catalog_for(code)                          the cached per-language catalog
    set_process_language(code)                 the UI default (LanguageManager only)
    current_process_language()

Headless callers (CLI, capabilities, exporters) pass ``lang=`` explicitly and
never touch the process default (§3.2, T-19).
"""
from core.i18n.catalog import (  # noqa: F401
    TermRef, catalog_for, current_process_language, set_process_language, t)
from core.i18n.terms import term, term_tooltip  # noqa: F401

__all__ = ["t", "term", "term_tooltip", "TermRef", "catalog_for",
           "set_process_language", "current_process_language"]
