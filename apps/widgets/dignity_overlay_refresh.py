# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The DIGNITY key's light redraw (td-m6xyo, SPEC-DIG-001 §4.2).

Measured 2026-10-13 (DIGNITY_PROFILE, Lorris.chtk, Light Orange): a toggle went
through the Strength keys' Apply-tail redraw, which rebuilt every chart host of
the window (28 South Indian views, 14 wheels, 12 North Indian views, mostly
hidden): 0.8 to 1.8 s per click. The overlay is a post-pass on a finished
scene, so a toggle only has to take the old overlay off and run the pass again
on the views that draw it: the South Indian vector view, the classic South
Indian view and the wheel, subclasses included (the Pro South Indian Compass
inherits the vector view's draw); the views that draw no overlay are not
touched. R2 review (2026-10-13): only the views on screen are updated at once;
a hidden view catches up at its next show, before it paints.
"""
from __future__ import annotations

from apps.widgets import dignity_overlay_items as doi


def clear_overlay(scene):
    """Take the overlay off ``scene``: the sheen items (their moving parts are
    their children) and the greyed glyphs (children of the planet icons)."""
    gone = [i for i in scene.items() if isinstance(i, (doi.SheenItem, doi._GreyGlyph))]
    for item in gone:
        if item.scene() is scene:          # a sheen's child goes with its parent
            scene.removeItem(item)
    del gone
    animator = doi.DignityAnimator.of(scene, create=False)
    if animator is not None:
        animator.reset([])


def refresh_overlays():
    """Re-run the overlay pass on every view that draws it (with the Ember Aura's,
    one shared light redraw: planet_decoration_refresh.py): now on the views on
    screen, when shown on the others. Returns the views done now."""
    from apps.widgets.planet_decoration_refresh import refresh_planet_passes
    return refresh_planet_passes()
