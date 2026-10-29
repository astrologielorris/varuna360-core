# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The GUI's current app language, read where the GUI reads it (SPEC-LOC-002 §3.2).

Core text producers take the language explicitly (T-19); only the GUI layer
decides it from the saved setting. AI, CLI and capability callers pass "en"
(or their own request's language) and never come through here.
"""
from __future__ import annotations

ENGLISH = "en"


def gui_language() -> str:
    """The saved app language ("zodiac.sign_language", View > Language or
    Settings > Appearance); English when the settings cannot be read."""
    try:
        from managers.settings_manager import get_settings
        from core.settings_registry import default as registry_default
        return get_settings().get("zodiac.sign_language",
                                  registry_default("zodiac.sign_language")) or ENGLISH
    except Exception:  # noqa: BLE001  (a label never fails a dialog)
        return ENGLISH


def gui_ui_language() -> str:
    """The language of GUI text, card labels included (R2-5): the saved app
    language itself. Labels come from the UI catalog, which falls back per key,
    so a language with labels but no prose file still shows its labels."""
    return gui_language()


def gui_description_language() -> str:
    """The language of the Aditya description PROSE for the GUI's language: the
    first language of its chain that has the content file (i18n/content.json),
    else English. Only prose lookups use it; card labels use gui_ui_language()."""
    from core.aditya_data import description_language
    return description_language(gui_language())
