# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Where each South Indian exchange knot goes (SPEC-EXCH-002 3.4.1, td-jr6cd),
Qt-free. Knots are placed one at a time and never moved after: each candidate
(tier, spot) must leave NEED_LINKS free on both sides of its knot, keep its
curve inside the centre box and clear every other knot and every pin. FULL is
used only when it fits at today's spot, so a close pair gets a smaller knot."""
from __future__ import annotations

import math
from itertools import permutations
from typing import NamedTuple

from core.exchange_chain import DIM, ROLO, bezier, link_pitch
from core.exchange_knot import (COMPACT, FULL, MINI, NEED_LINKS, SEAL, SiKnot, _SiFrame,
                                _clamp_pt, _inside_box, _knot_box, _path_of, _pill_inside,
                                free_sides)

SHIFTS = (0, -1, 1, -2, 2, -3, 3)   # vertical steps of the knot (x STEP u) to clear other knots
STEP = 24


class _Placed(NamedTuple):
    """A knot already placed: its pill box (half sizes include the 8 u gap)."""
    cx: float
    cy: float
    hw: float
    hh: float


def _box(f: _SiFrame, Kp, tier):
    return (Kp[0], Kp[1] + tier.dy * f.u, (tier.pw / 2 + 4) * f.u, (tier.bh / 2 + 4) * f.u)


def _clash(f: _SiFrame, box, pins, placed):
    """The candidate's box meets a placed knot or covers any other exchange's pin
    (placed or not yet: every pin is known before the first knot is placed)."""
    cx, cy, hw, hh = box
    if any(abs(cx - q.cx) < hw + q.hw and abs(cy - q.cy) < hh + q.hh for q in placed):
        return True
    return any(abs(px - cx) < hw + f.pin_r and abs(py - cy) < hh + f.pin_r for px, py in pins)


def _spots(f: _SiFrame, M, tier):
    """Knot points of a tier, best first: along the pull toward the centre with
    small vertical steps, then a STEP-u grid over the knot box, nearest first."""
    kb = _knot_box(f, tier)
    for pull in tier.pulls:
        K0 = (M[0] + (f.ctr[0] - M[0]) * pull, M[1] + (f.ctr[1] - M[1]) * pull)
        for sh in SHIFTS:
            yield _clamp_pt((K0[0], K0[1] + sh * STEP * f.u), *kb)
    home = _clamp_pt((M[0] + (f.ctr[0] - M[0]) * tier.pulls[0], M[1] + (f.ctr[1] - M[1]) * tier.pulls[0]), *kb)
    s = STEP * f.u
    nx, ny = int((kb[2] - kb[0]) // s) + 1, int((kb[3] - kb[1]) // s) + 1
    grid = [(kb[0] + i * s, kb[1] + j * s) for i in range(nx) for j in range(ny)]
    yield from sorted(grid, key=lambda q: math.dist(q, home))


def _candidates(f: _SiFrame, A, B, tiers):
    """(tier, control, knot, natural): ``natural`` marks a tier's first spot."""
    M = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
    for tier in tiers:
        for n, K in enumerate(_spots(f, M, tier)):
            C, Kp = _path_of(f, A, B, M, K)
            yield tier, C, Kp, n == 0


def _judge(f: _SiFrame, A, B, C, Kp, tier, others, placed):
    """(free length of the shorter side, no clash and inside the box, the box)."""
    box, pts = _box(f, Kp, tier), bezier(A, C, B, 64)
    free = min(free_sides(pts, _pill_inside(Kp, tier, f.u), f.pin_r))
    return free, _inside_box(f, pts) and not _clash(f, box, others, placed), box


def _place(f: _SiFrame, lk, A, B, tiers, placed, others):
    """The first candidate (tier, spot) leaving NEED_LINKS free on both sides,
    its curve inside the centre box and clashing with no knot or pin; else the
    best one (3.4.1). FULL is tried only when it fits at today's spot."""
    best, skip, need = None, None, f.need[lk.rank]
    for tier, C, Kp, natural in _candidates(f, A, B, tiers):
        if tier is skip:
            continue
        free, ok, box = _judge(f, A, B, C, Kp, tier, others, placed)
        if ok and free >= need:
            return SiKnot(lk, A, B, C, Kp, tier), _Placed(*box), True
        if natural and tier is FULL:
            skip = FULL                # a failed full knot gets smaller, never moved
            continue
        if best is None or (ok, free) > best[0]:
            best = ((ok, free), SiKnot(lk, A, B, C, Kp, tier), _Placed(*box))
    return best[1], best[2], False


def _in_order(f: _SiFrame, links, doors, tiers, order):
    """Place the knots in ``order``; returns (knots, how many fell back)."""
    out, placed, misses = [None] * len(links), [], 0
    for i in order:
        others = [p for j, d in enumerate(doors) if j != i for p in d]
        out[i], box, good = _place(f, links[i], *doors[i], tiers, placed, others)
        placed.append(box)
        misses += not good
    return out, misses


def _frame(centre_box, u, small, style):
    x0, y0, x1, y1 = centre_box
    k = (0.7 if small else 1.0) * u
    return _SiFrame(((x0 + x1) / 2, (y0 + y1) / 2), centre_box, u, (16 if small else 19) * u,
                    {r: NEED_LINKS * link_pitch(r, style, k, u) for r in DIM})


def _doors(links, sign_rect, centre_box, u):
    """Each exchange's two doorsteps: the cell centres clamped into the centre box inset 15 u."""
    x0, y0, x1, y1 = centre_box
    box = (x0 + 15 * u, y0 + 15 * u, x1 - 15 * u, y1 - 15 * u)

    def door(i):
        x, y, w, h = sign_rect(i)
        return _clamp_pt((x + w / 2, y + h / 2), *box)
    return [(door(lk.sign_a), door(lk.sign_b)) for lk in links]


def si_layout(links, sign_rect, centre_box, u, small=False, style=ROLO):
    """Doorsteps, knots and control points (mockup ``siLayout`` + 3.4.1), scene
    units. ``sign_rect(i)`` -> (x, y, w, h); ``centre_box`` -> (x0, y0, x1, y1).
    Knots are placed one by one, the closest pair first (another order when that
    one leaves a knot without room); a placed knot never moves, so each keeps the
    free length it was checked with."""
    f = _frame(centre_box, u, small, style)
    tiers = (COMPACT, MINI, SEAL) if small else (FULL, COMPACT, MINI, SEAL)
    doors = _doors(links, sign_rect, centre_box, u)
    first = tuple(sorted(range(len(links)), key=lambda i: math.dist(*doors[i])))
    best = None
    for order in (first,) + tuple(o for o in permutations(first) if o != first):
        out, misses = _in_order(f, links, doors, tiers, order)
        if best is None or misses < best[1]:
            best = (out, misses)
        if not misses:
            break
    return best[0]
