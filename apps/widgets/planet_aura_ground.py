# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Ember Aura ground per planet, kept per scene for the PLANET/DIGNITY light redraw."""
from __future__ import annotations

import weakref
from contextlib import contextmanager

from apps.widgets.planet_aura_items import sample_grounds
from core import planet_aura as pa
from core.planet_strength_glow import KEY_MODE
from ui.qt_theme import get_theme_colors, is_light_theme

_GROUNDS = weakref.WeakKeyDictionary()   # scene -> (chart, key, grounds)
_EPOCH, _REUSE = [0], [0]                # settings writes; > 0 inside ``reusing()``
_WATCHING = []                           # the settings managers watched


def own_grounds(scene, chart, centres, r_ref, hide):
    """``pa.own_ground`` under each of ``centres`` (one render). Read back only by a light
    redraw (``reusing``) with the same ``_ground_key``; a full draw always samples (view
    state that is no setting, e.g. a Sign-as-Ascendant override). Preview: never kept."""
    key = _ground_key(scene, chart, centres, r_ref) if chart is not None else None
    kept = _GROUNDS.get(scene, (None, None, None)) if _REUSE[0] else (None, None, None)
    if key is not None and kept[0] is chart and kept[1] == key:
        return kept[2]
    reach = pa.OWN_REACH * r_ref
    grounds = [pa.own_ground(samples, reach)
               for samples in sample_grounds(scene, centres, r_ref, hide, reach)]
    if key is not None:
        _GROUNDS[scene] = (chart, key, grounds)
    return grounds


@contextmanager
def reusing():
    _REUSE[0] += 1
    try:
        yield
    finally:
        _REUSE[0] -= 1


def _settings_epoch():                   # moves on every settings write but the PLANET mode
    from managers.settings_manager import get_settings
    s = get_settings()
    if not any(w is s for w in _WATCHING):
        _WATCHING.append(s)
        s.add_change_callback(_settings_written)
    return id(s), _EPOCH[0]


def _settings_written(key, _value=None):
    _EPOCH[0] += str(key) != KEY_MODE


def _ground_key(scene, chart, centres, r_ref):  # varga, theme, size, places, items, rect, epoch
    return (getattr(next(iter(scene.views()), None), "_varga_code", None),
            tuple(sorted(get_theme_colors().items())), is_light_theme(), round(r_ref, 4),
            tuple((round(c.x(), 3), round(c.y(), 3)) for c in centres), len(scene.items()),
            scene.sceneRect().getRect(), _settings_epoch())
