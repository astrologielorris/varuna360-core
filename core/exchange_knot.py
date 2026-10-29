# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""How big the exchange knot is and how much chain it leaves (SPEC-EXCH-002
3.4.1 and 3.5, td-jr6cd), Qt-free: the knot tiers, the free length on each side
of a knot (NEED_LINKS link pitches between pin and knot), the South Indian frame
and path, and the wheel seal step-down. Where each South Indian knot goes:
``core.exchange_knot_place``."""
from __future__ import annotations

import math
from typing import NamedTuple

from core.exchange_chain import DIM, ROLO, ExchangeLink, bezier, link_pitch, quad

NEED_LINKS = 2.5          # links that must show on EACH side between pin and knot (3.4.1)


class KnotTier(NamedTuple):
    """A South Indian knot size (SPEC-EXCH-002 3.4.1), mockup px."""
    name: str
    pw: float            # pill width
    ph: float            # pill height
    bh: float            # knot box height (the pill + the letter tab)
    dy: float            # the pill under the knot point
    pulls: tuple         # pulls toward the centre tried, in order


FULL = KnotTier("full", 176, 64, 84, 8, (0.35,))
COMPACT = KnotTier("compact", 124, 44, 58, 6, (0.35, 0.5, 0.65))
MINI = KnotTier("mini", 92, 34, 48, 0, (0.35, 0.5, 0.65, 0.8))
SEAL = KnotTier("seal", 34, 34, 48, 0, (0.35, 0.5, 0.65, 0.8))   # crowded: the seal alone


class SiKnot(NamedTuple):
    link: ExchangeLink
    A: tuple             # doorstep of sign_a
    B: tuple
    C: tuple             # control point
    K: tuple             # knot centre (on the path, t = .5)
    tier: KnotTier = FULL


def _clamp_pt(pt, x0, y0, x1, y1):
    return (min(max(pt[0], x0), x1), min(max(pt[1], y0), y1))


def free_sides(pts, inside, r0):
    """Arc length from each end's pin edge (``r0``) to the first point
    ``inside`` the knot: the visible chain on each side (3.4.1)."""
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
    hits = [i for i, pt in enumerate(pts) if inside(pt)]
    if not hits:
        return cum[-1] / 2 - r0, cum[-1] / 2 - r0
    return cum[hits[0]] - r0, cum[-1] - cum[hits[-1]] - r0


def _pill_inside(K, tier, u):
    cx, cy = K[0], K[1] + tier.dy * u
    hw, hh = (tier.pw / 2 + 3.5) * u, (tier.ph / 2 + 3.5) * u
    return lambda pt: abs(pt[0] - cx) <= hw and abs(pt[1] - cy) <= hh


class _SiFrame(NamedTuple):
    """What every knot candidate of one South Indian layout shares."""
    ctr: tuple
    box: tuple           # the centre box (x0, y0, x1, y1)
    u: float
    pin_r: float
    need: dict           # rank -> free length needed on each side


def _knot_box(f: _SiFrame, tier):
    x0, y0, x1, y1 = f.box
    u = f.u
    return (x0 + (tier.pw / 2 + 8) * u, y0 + (38 + tier.bh / 2) * u,
            x1 - (tier.pw / 2 + 8) * u, y1 - (38 + tier.bh / 2) * u)


def _path_of(f: _SiFrame, A, B, M, K):
    """The control point through K (the curve never reaches it, so it is not
    clamped; ``_inside_box`` checks the curve itself)."""
    return (2 * K[0] - M[0], 2 * K[1] - M[1]), K


def _inside_box(f: _SiFrame, pts):
    x0, y0, x1, y1 = f.box
    m = 6 * f.u
    return all(x0 + m <= x <= x1 - m and y0 + m <= y <= y1 - m for x, y in pts)


def wheel_seal_r(s0, c, s1, kpt, radii, rank, style, k, px, hidden=0.0):
    """The wheel seal radius (3.5, td-jr6cd): the first of ``radii`` whose seal
    leaves NEED_LINKS link pitches of hub chain on both sides, else the smallest;
    ``hidden``: the path's start under each number ring's casing."""
    pts = bezier(s0, c, s1, 64)
    need = NEED_LINKS * link_pitch(rank, style, k, px)
    for r in radii:
        reach = r * 1.12

        def inside(pt, r=reach):
            return math.hypot(pt[0] - kpt[0], pt[1] - kpt[1]) <= r
        if min(free_sides(pts, inside, hidden)) >= need:
            return r
    return radii[-1]
