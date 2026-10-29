# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The light redraws of the Strength, PLANET and DIGNITY keys (SPEC-RST-001 §4.4,
SPEC-DIG-001 §4.2): on the views on screen now, on a hidden view when it is shown.

R2 review 2026-10-13: a key click rebuilt all 63 graphics views (1 visible), 0.75-2.2 s.

- PLANET on/off and DIGNITY on/off change only post-passes on a finished scene
  (the Ember Aura, the dignity overlay): ``refresh_planet_passes`` takes both off,
  gives each planet its manual shadow back and runs the view's own post-pass
  (``planet_pass``, the same call its full draw makes).
- A Strength key or F10 also changes the retinue cells, so the view is drawn
  again (``managers.retinue_strength_shortcut.redraw_strength_hosts``), once per view.

Only views on screen work now; a hidden view runs its jobs at its next Show event
(``apps.widgets.paint_on_show.when_shown``).
"""
from __future__ import annotations

import shiboken6
from PySide6.QtWidgets import QApplication, QGraphicsView

from apps.widgets.paint_on_show import pending, when_shown  # noqa: F401  (the show-time job table)


# ---------------------------------------------------------------- post-passes

_PASSES = []                             # (view class, its post-pass, its manual shadow)


def register_planet_pass(view_class, rerun, shadow):
    """A view class that draws the Ember Aura and the dignity overlay (each view
    module registers itself): ``rerun(view)`` is the post-pass its full draw runs,
    ``shadow(view, planet)`` the manual drop shadow it gives a planet (None: none).
    Subclasses count (the Pro South Indian Compass inherits the vector view's draw)."""
    _PASSES.append((view_class, rerun, shadow))


def _graphics_views():
    views = []
    for top in QApplication.topLevelWidgets():   # graphics views only: allWidgets() cost 12 ms
        views += [top] if isinstance(top, QGraphicsView) else []
        views += top.findChildren(QGraphicsView)
    return views


def clear_glow(scene, shadow_for):
    """Take the Ember Aura off a finished scene (the PLANET key's light redraw):
    the discs, the halos, and each decorated planet gets back the manual shadow
    ``shadow_for(planet)`` (None: the view draws none). Returns the planets restored."""
    from apps.widgets.planet_aura_items import VALUE_ROLE, AuraItem
    from apps.widgets.planet_strength_glow import HaloItem
    restored = 0
    for item in scene.items():
        if isinstance(item, (AuraItem, HaloItem)):
            if item.scene() is scene:          # a removed parent took its children
                scene.removeItem(item)
        elif item.data(VALUE_ROLE) is not None and hasattr(item, "planet_name"):
            item.setData(VALUE_ROLE, None)
            shadow = shadow_for(item.planet_name)
            if shadow is not None:
                item.setGraphicsEffect(shadow)
                del shadow                     # Rule 18: Qt owns it
            restored += 1
    return restored


def _repass(view):
    """Take every planet post-pass off ``view``'s scene and run them again."""
    from apps.widgets import dignity_overlay_refresh as dor
    for cls, rerun, shadow in _PASSES:
        if isinstance(view, cls):
            if getattr(view, "_chart", None) is None:
                return
            dor.clear_overlay(view.scene)
            clear_glow(view.scene, lambda p: shadow(view, p))
            from apps.widgets.planet_aura_ground import reusing
            with reusing():                # the scene is the one last sampled
                rerun(view)
            return


def refresh_planet_passes():
    """Re-run the planet post-passes (Ember Aura + dignity overlay) on every
    view that draws them: now on the views on screen, at show on the others.
    Returns the views done now. A view without a chart is skipped."""
    kinds = tuple(k[0] for k in _PASSES)
    done = 0
    for view in _graphics_views():
        if (isinstance(view, kinds) and shiboken6.isValid(view)
                and getattr(view, "_chart", None) is not None):
            done += when_shown(view, "planet_pass", _repass)
    return done
