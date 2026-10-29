# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Settings side of the custom ayanamsa (id 255): the three registry keys and the
one function that installs them into the engine (libaditya.custom_ayanamsa).

Qt-free. The app installs at startup and on every change of the keys
(managers/zodiac_settings_manager.py); a CLI installs in resolve_settings, so a
command computes 255 with the same definition the app shows.
"""
from contextlib import contextmanager

from core.settings_registry import default as _registry_default

NAME_KEY = "zodiac.custom_ayanamsa_name"
VALUE_KEY = "zodiac.custom_ayanamsa_value"
YEAR_KEY = "zodiac.custom_ayanamsa_year"
KEYS = (NAME_KEY, VALUE_KEY, YEAR_KEY)
AYANAMSA_KEYS = frozenset(("zodiac.ayanamsa_id", "dasha.left.ayanamsa_id",
                          "dasha.right.ayanamsa_id"))


def dependencies(keys):
    """Settings closure: every ayanamsa selector can select the user's id 255."""
    out = set(keys)
    if out & AYANAMSA_KEYS:
        out.update(KEYS)
    return tuple(sorted(out))


def read(settings):
    """(name, value_deg, year) from any settings object with ``get(key, default)``."""
    if getattr(settings, "status", None) == "frozen":
        # No default expression is evaluated here: these values must be recorded
        # (or version-pinned) and a malformed definition cannot borrow app state.
        name, value, year = (settings.get(key) for key in KEYS)
        if name is None or value is None or year is None:
            raise ValueError("capture has an incomplete custom ayanamsa definition")
        return str(name), float(value), int(year)
    out = []
    for key in KEYS:
        try:
            value = settings.get(key, _registry_default(key))
        except Exception as exc:
            from core.settings_registry.effective import MissingSetting
            if isinstance(exc, MissingSetting):
                raise  # a frozen capture may never borrow today's definition
            value = _registry_default(key)
        out.append(_registry_default(key) if value is None else value)
    name, value, year = out
    try:
        return str(name), float(value), int(year)
    except (TypeError, ValueError):
        return tuple(_registry_default(k) for k in KEYS)


def install_from(settings):
    """Make the engine compute id 255 as ``settings`` defines it; True on a change."""
    from libaditya.custom_ayanamsa import set_custom_ayanamsa
    name, value, year = read(settings)
    return set_custom_ayanamsa(value, year, name)


@contextmanager
def calculation_context(settings, ayanamsas):
    """Install a run's custom definition only while it calculates; restore the app's.

    Frozen views raise MissingSetting for an old capture without the definition,
    rather than using process state or a modern factory fallback.
    """
    if 255 not in ayanamsas:
        yield
        return
    from libaditya.custom_ayanamsa import using_custom_ayanamsa
    name, value, year = read(settings)
    with using_custom_ayanamsa(value, year, name):
        yield


def frame_part(ayanamsa_id):
    """(value, year) of the installed id-255 definition when ``ayanamsa_id``
    is 255, else None. A chart's frame includes it: editing the value keeps
    the id, and a frame of (mode, id, houses) alone would not change."""
    from core.ayanamsa_data import CUSTOM_AYANAMSA_ID
    if ayanamsa_id != CUSTOM_AYANAMSA_ID:
        return None
    from libaditya.custom_ayanamsa import get_custom_ayanamsa
    _name, value, year = get_custom_ayanamsa()
    return (value, year)
