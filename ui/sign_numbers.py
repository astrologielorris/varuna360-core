# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Signs as numbers: Settings > Chart Display > "Signs as numbers".

``display.sign_number_views`` lists the chart views that show each sign as its
NUMBER (1 = Aries = Dhata ... 12 = Pisces = Parjanya: division #1 in every
zodiac system, SPEC-ZOD-001) instead of what ``display.sign_display`` draws.
For a ticked view ``effective_sign_display`` returns the internal mode
``numbers``: drawn like ``names`` (text only, no icon or glyph) with the number
as the text. ``numbers`` is never stored in ``display.sign_display``.
SPEC-NIC-001 §3.7.
"""
from core.aditya_mode import displayed_sign_name

#: Views that can show signs as numbers, in Settings order (chart.view_type values).
SIGN_NUMBER_VIEWS = ("north_indian", "south_indian", "wheel", "nakshatra")
NUMBERS = "numbers"
#: Modes that draw sign text only, no icon or glyph.
TEXT_ONLY = ("names", NUMBERS)


def _settings(settings):
    if settings is None:
        from managers.settings_manager import get_settings
        settings = get_settings()
    return settings


def numbers_on(view, settings=None):
    """True when ``view`` (a SIGN_NUMBER_VIEWS key) shows signs as numbers."""
    views = _settings(settings).get('display.sign_number_views', [])
    return isinstance(views, (list, tuple)) and view in views


def effective_sign_display(view, mode=None, settings=None):
    """The sign mode ``view`` draws with: ``numbers`` when the view is ticked,
    else ``mode`` (default: the stored display.sign_display)."""
    settings = _settings(settings)
    if numbers_on(view, settings):
        return NUMBERS
    if mode is None:
        from core.settings_registry import default
        mode = settings.get('display.sign_display', default('display.sign_display'))
    return mode


def sign_number(index):
    """The sign's number as text: division index 0..11 -> "1".."12"."""
    return str(int(index) % 12 + 1)


def sign_label(view, index, aditya_mode, use_western_names, language='en'):
    """The text a view writes for sign ``index``: its number when ``view`` is
    ticked, else its displayed name."""
    if numbers_on(view):
        return sign_number(index)
    return displayed_sign_name(index, aditya_mode, use_western_names, language)
