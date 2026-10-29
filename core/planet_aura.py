# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Ember Aura maths (SPEC-RST-001 D-21a, td-647kl, td-3zaz7, td-ws82s). Qt-free, raw floats.

Size and VISIBLE strength follow the value only (``t = clamp(value / 60)``):
``R = r_ref (1.10 + 1.10 t)`` (``r_ref``: ONE reference half size per view);
``V = 0.08 + 0.52 t``; ``d`` = ``difference`` of the colour to the ground UNDER THE
PLANET ITSELF (``own_ground``: its own card or band, never a border or gap the aura
reaches over); alpha ``a = min(FILL_CAP, V / d)``, stops 0 -> a, .40 -> .85a,
.70 -> .35a, 1 -> 0. ALWAYS the planet's own colour fading to fully transparent,
nothing else (td-ws82s: no edge ring, no shade): "colour carried" when ``a d = V``;
else "size carried", the SIZE carries the value with the plain colour at ``FILL_CAP``."""
from __future__ import annotations

import math
from typing import Callable

from core.planet_strength_glow import STRENGTH_PALETTE, strength_t
from core.retinue_strength import RGB

AURA_STOPS = ((0.00, 1.00), (0.40, 0.85), (0.70, 0.35), (1.00, 0.00))
FILL_CAP = 0.85      # the colour's largest centre alpha: a soft light, never a lid
OWN_REACH = 1.0      # the planet's own ground: the samples within this many r_ref (its icon)
OWN_NEAR = 0.06      # own_ground: shades this close vote together (a texture, antialiasing)


def reference_half_size(size_of: Callable[[str], float]) -> float:
    """``r_ref``: half the mean nominal icon size of the seven classical planets,
    ``size_of(planet)`` read from the view's own size settings."""
    sizes = [float(size_of(p)) for p in STRENGTH_PALETTE]
    return 0.5 * sum(sizes) / len(sizes)


def aura_radius(r_ref: float, value) -> float:
    """Aura radius for the view's reference half size: 1.10 r_ref at 0, 2.20 r_ref at 60."""
    return r_ref * (1.10 + 1.10 * strength_t(value))


def visible_target(value) -> float:
    """``V``: the colour difference the aura makes at its centre, 0.08 at 0, 0.60 at 60."""
    return 0.08 + 0.52 * strength_t(value)


def difference(a: RGB, b: RGB) -> float:
    """Perceptual colour difference 0..1 (luma-weighted RGB distance)."""
    return math.sqrt(.299 * (a[0] - b[0]) ** 2 + .587 * (a[1] - b[1]) ** 2
                     + .114 * (a[2] - b[2]) ** 2)


def own_ground(samples, reach: float) -> RGB:
    """The ground UNDER THE PLANET ITSELF (td-ws82s) from ``samples`` =
    ``[(dx, dy, rgb), ...]`` (offsets from the planet's centre): of the samples
    within ``reach`` (its icon), the densest colour: the sample with the most
    others within ``OWN_NEAR`` of it (ties: the nearest the centre, then the
    first), returned as the mean of those. A thin line, a gap at the icon's corner
    or a texture grain does not outvote the card (a texture's shades stay within
    ``OWN_NEAR`` of each other); the nearest sample when none falls inside. Never
    the mean of a split: a border or gap the aura reaches over does not change it.

    Linear in the samples (R2 review: it compared every sample with every other):
    equal colours are counted once, and a colour is compared only with the colours
    in its own and the adjacent cells of an ``OWN_NEAR`` grid in the difference's
    own (luma-weighted) space, where no colour within ``OWN_NEAR`` lies farther."""
    r2 = reach * reach
    near = [(dx * dx + dy * dy, rgb) for dx, dy, rgb in samples if dx * dx + dy * dy <= r2]
    if not near:
        return tuple(min(samples, key=lambda e: e[0] * e[0] + e[1] * e[1])[2])
    members = _densest(_colours(near))
    group = [rgb for _, rgb in near if rgb in members]
    return tuple(sum(c[i] for c in group) / len(group) for i in range(3))


def _colours(near):
    """``{rgb: [count, nearest distance, that sample's index]}`` of ``near``."""
    colours = {}
    for i, (dist, rgb) in enumerate(near):
        seen = colours.get(rgb)
        if seen is None:
            colours[rgb] = [1, dist, i]
        elif dist < seen[1]:
            seen[0], seen[1], seen[2] = seen[0] + 1, dist, i
        else:
            seen[0] += 1
    return colours


def _densest(colours):
    """The colours within ``OWN_NEAR`` of the densest one (most samples within it; ties: nearest the
    centre, then first). ``difference`` squared, inline (exact, test-checked); candidates per cell."""
    cells, near, best, near2 = {}, {}, None, OWN_NEAR * OWN_NEAR
    for rgb in colours:
        cells.setdefault(_cell(rgb), []).append(rgb)
    for rgb, (_count, dist, i) in colours.items():
        cell, (r, g, b) = _cell(rgb), rgb
        cands = near.get(cell) or near.setdefault(cell, _neighbours(cells, cell))
        group = [c for c in cands
                 if .299 * (c[0] - r) ** 2 + .587 * (c[1] - g) ** 2 + .114 * (c[2] - b) ** 2 <= near2]
        key = (sum(colours[c][0] for c in group), -dist, -i)
        best = (key, group) if best is None or key > best[0] else best
    return set(best[1])


_WEIGHT = (math.sqrt(.299), math.sqrt(.587), math.sqrt(.114))


def _cell(rgb):
    """The ``OWN_NEAR`` grid cell of a colour in the space where ``difference``
    is the plain distance."""
    return tuple(math.floor(v * w / OWN_NEAR) for v, w in zip(rgb, _WEIGHT))


def _neighbours(cells, cell):
    """The colours in ``cell`` and the 26 around it: all within ``OWN_NEAR`` of its colours."""
    cx, cy, cz = cell
    return [c for x in (cx - 1, cx, cx + 1) for y in (cy - 1, cy, cy + 1)
            for z in (cz - 1, cz, cz + 1) for c in cells.get((x, y, z), ())]


def aura_alpha(value, colour: RGB, ground: RGB) -> float:
    """Centre alpha ``min(FILL_CAP, V / d)``, ``d`` the colour's difference to the
    planet's own ground."""
    return min(FILL_CAP, visible_target(value) / max(difference(colour, ground), 1e-3))


def colour_carries(value, colour: RGB, ground: RGB) -> bool:
    """The colour alone shows the value on the planet's own ground (the alpha is
    not capped); else the size does, with the same plain colour (no ring)."""
    return aura_alpha(value, colour, ground) * difference(colour, ground) >= visible_target(value) * (1 - 1e-9)


def aura_stops(value, colour: RGB, ground: RGB):
    """The aura gradient's ``(position, alpha)`` stops: ``a k(s)``, its own colour,
    fully transparent at the rim."""
    a = aura_alpha(value, colour, ground)
    return tuple((pos, a * k) for pos, k in AURA_STOPS)
