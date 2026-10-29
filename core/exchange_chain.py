# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The exchange chain overlay, Qt-free part (SPEC-EXCH-002, td-m79zy).

Which exchanges a chart holds (in the EXCH panel's card order, with their rank,
house marks and letter), the metal and link size of each rank, and the pure
geometry the painter replays: link poses along a path (the mockup's ``chain()``),
the South Indian knot layout and the wheel knot spacing. Every number comes from
the round 4 winner's MC-INTENT (``mockups_exchange-yoga_20261014-1400/round4/
designer_a/mockup_3.html``, Rolo; ``mockup_1.html``, Cable); sizes are mockup px
at South Indian full size, multiplied by a view scale.
"""
from __future__ import annotations

import math
import weakref
from typing import NamedTuple

from AI_tools.AI_main_function.interchange_rank import Marks, exchange_rank, house_marks

KEY_ON = "chart.exchange_chain_on"
KEY_STYLE = "chart.exchange_chain_style"
ROLO, CABLE = "rolo", "cable"
STYLES = (ROLO, CABLE)

# the panel's card order (ParivartanaWidget._CLASS_ORDER): letters follow it
from AI_tools.AI_main_function.interchange_rank import CLASS_ORDER, LETTERS  # noqa: E402
CASE = "#1E150C"                 # the dark casing of every link and knot
FOCUS_DIM = 0.18                 # the other exchanges while one card is focused


def chain_on(get) -> bool:
    from core import settings_registry as registry
    return bool(get(KEY_ON, registry.default(KEY_ON)))


def chain_style(get) -> str:
    from core import settings_registry as registry
    style = get(KEY_STYLE, registry.default(KEY_STYLE))
    return style if style in STYLES else ROLO


def compact(n: int) -> bool:
    """The size rule: full size for 1 or 2 exchanges, compact for 3."""
    return n >= 3


def letters(n: int):
    """Letters A, B, C in card order when a chart has 2 or 3 exchanges."""
    return LETTERS[:n] if n >= 2 else ("",) * n


# ---------------------------------------------------------------- metal / size
class Metal(NamedTuple):
    hi: str          # specular
    li: str          # light
    ba: str          # body
    dk: str          # shadow
    ink: str         # text on it
    hi_op: float     # specular arc strength
    glint: int       # a star glint every n-th link (0 none)
    glint_size: float


METAL = {
    6: Metal("#FFF8DC", "#FFE08A", "#D2A12E", "#6E4C0E", "#2A1D08", 1.0, 4, 2.0),
    5: Metal("#FFFFFF", "#F1F1EE", "#BEBEBA", "#5E5E5A", "#24231F", 0.95, 5, 1.5),
    4: Metal("#FAE2BC", "#E4B474", "#AE7B3C", "#553615", "#24160A", 0.7, 0, 0.0),
    3: Metal("#B3AC9A", "#958E7C", "#6F6857", "#37322A", "#1F1D19", 0.28, 0, 0.0),
    2: Metal("#D29055", "#B4672F", "#86431F", "#371C0E", "#F6E6D2", 0.18, 0, 0.0),
    1: Metal("#A66A3E", "#8E4C22", "#653015", "#26130A", "#F6E6D2", 0.1, 0, 0.0),
}
# link length L, height H, wire w (mockup px at South Indian full size): ONE size
# for every rank, the metal alone tells the rank (td-arixy, Lorris 2026-10-15)
DIM = {r: (25.0, 16.0, 4.5) for r in (6, 5, 4, 3, 2, 1)}
RUST = ("#2A1309", "#C8732F")    # dark, light rust flake
HAZARD = ("#17100A", "#E8A33A")
WORD_ON_LIGHT = "#6B5320"        # rank word on gold and silver (contrast on a light card)


# ---------------------------------------------------------------- the links
class ExchangeLink(NamedTuple):
    pair: tuple          # (planet_a, planet_b): the identity of the exchange
    planet_a: str
    sign_a: int          # sign index 0..11 of planet_a in the chart drawn
    house_a: int
    planet_b: str
    sign_b: int
    house_b: int
    cls: str
    rank: int
    marks: Marks
    letter: str


def ordered_records(interchanges):
    """The engine's 7-tuples in the panel's card order (class order, then engine)."""
    by_type = (interchanges or {}).get("by_type", {}) or {}
    return [rec for cls in CLASS_ORDER for rec in by_type.get(cls, [])]


def links_from(interchanges, sign_of):
    """ExchangeLink tuple from engine output; ``sign_of(planet)`` -> sign index."""
    recs = ordered_records(interchanges)
    lets = letters(len(recs))
    out = []
    for rec, letter in zip(recs, lets):
        pa, _sa, ha, pb, _sb, hb, cls = rec
        rank = exchange_rank(ha, hb, cls)
        out.append(ExchangeLink((pa, pb), pa, sign_of(pa), ha, pb, sign_of(pb), hb, cls,
                                rank, house_marks(ha, hb, rank), letter))
    return tuple(out)


_MEMO = {}                       # id(chart) -> (weakref(chart), links)


def chart_links(chart):
    """The exchanges of ``chart`` (the chart a view draws), memoised per chart
    object: a redraw of the same chart never recomputes them."""
    if chart is None:
        return ()
    hit = _MEMO.get(id(chart))
    if hit is not None and hit[0]() is chart:
        return hit[1]
    from AI_tools.AI_main_function.interchange import get_all_interchanges
    from core.chart_helpers import get_planet_sign_index
    links = links_from(get_all_interchanges(chart),
                       lambda p: get_planet_sign_index(chart, p, default=-1))
    links = tuple(lk for lk in links if lk.sign_a >= 0 and lk.sign_b >= 0)
    if len(_MEMO) > 32:
        _MEMO.clear()
    try:
        _MEMO[id(chart)] = (weakref.ref(chart), links)
    except TypeError:
        pass
    return links


# ---------------------------------------------------------------- vector helpers
def rnd(a):
    """The mockup's seeded generator (stable between redraws), 0 <= r < 1."""
    m = 0xFFFFFFFF
    t = (int(a) + 0x6D2B79F5) & m
    t = ((t ^ (t >> 15)) * (t | 1)) & m
    t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & m)) & m
    return ((t ^ (t >> 14)) & m) / 4294967296.0


def jround(x):
    return int(math.floor(x + 0.5))


def _norm(dx, dy):
    d = math.hypot(dx, dy) or 1.0
    return dx / d, dy / d


def quad(p0, c, p1, t):
    u = 1 - t
    return (u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0],
            u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1])


def bezier(p0, c, p1, n):
    return [quad(p0, c, p1, i / n) for i in range(n + 1)]


class Poly:
    """A polyline with arc length (the mockup's ``poly`` / ``at``)."""

    def __init__(self, pts):
        self.pts = list(pts)
        cum = [0.0]
        for i in range(1, len(self.pts)):
            a, b = self.pts[i - 1], self.pts[i]
            cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
        self.cum = cum
        self.T = cum[-1]

    def at(self, s):
        c, p = self.cum, self.pts
        s = min(max(s, 0.0), self.T)
        lo, hi = 0, len(c) - 1
        while hi - lo > 1:
            m = (lo + hi) >> 1
            if c[m] <= s:
                lo = m
            else:
                hi = m
        seg = (c[hi] - c[lo]) or 1.0
        t = (s - c[lo]) / seg
        a, b = p[lo], p[hi]
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), _norm(b[0] - a[0], b[1] - a[1])


class LinkPose(NamedTuple):
    i: int
    x: float
    y: float
    ang: float           # degrees, y down (QPainter.rotate)
    op: float
    crush: bool
    open: int            # 0 closed, +1 / -1 the side of the break the gap faces
    edge: bool           # cable: an edge-on link
    r1: float
    r2: float
    r3: float


class ChainOpts(NamedTuple):
    rank: int
    k: float             # scale (mockup px -> scene units)
    marks: Marks
    end8: int            # 0: the 8th house at the start of the path, 1: at the end
    end12: int
    seed: int
    band: bool = False   # sector band / cell rim: no break, no hazard, flat see-through
    shadow: bool = True
    style: str = ROLO
    px: float = 1.0      # scene units per mockup px (casing, shadow offset, floors)


class ChainGeom(NamedTuple):
    L: float
    H: float
    w: float
    rx: float
    ry: float
    pitch: float


def link_pitch(rank, style, k, px=1.0):
    """The nominal distance between two links (before fitting a whole number)."""
    L0, H0, w0 = DIM[rank]
    L, H, w = L0 * k, H0 * k, max(1.1 * px, w0 * k)
    ry = (H * 0.56 if style == ROLO else H / 2) - w / 2
    return L * 0.74 if style == CABLE else (2 * (ry + w / 2)) * 0.82


def chain_geom(o: ChainOpts, T: float) -> ChainGeom:
    L0, H0, w0 = DIM[o.rank]
    L, H, w = L0 * o.k, H0 * o.k, max(1.1 * o.px, w0 * o.k)
    rx = L / 2 - w / 2
    ry = (H * 0.56 if o.style == ROLO else H / 2) - w / 2
    pitch0 = link_pitch(o.rank, o.style, o.k, o.px)
    n = max(2, jround(T / pitch0)) if pitch0 > 0 else 2
    return ChainGeom(L, H, w, rx, ry, T / n)


def break_at(o: ChainOpts, T: float) -> float:
    return T * 0.3 if o.marks.broken and not o.band else -1.0


def _chaos(o: ChainOpts, g: ChainGeom, T, s8, r1, r2):
    """(sideways offset, extra turn, crushed) of one link under the 8th's mark."""
    if not o.marks.chaos:
        return 0.0, 0.0, False
    if o.style != CABLE:
        return 0.0, (r1 - 0.5) * 34, r2 < 0.5
    off, k0, k1 = 0.0, T * 0.1, T * 0.44
    if k0 < s8 < k1:
        u = (s8 - k0) / (k1 - k0)
        tri = abs(((u * 3.2) % 1) * 4 - 2) - 1
        off = tri * g.H * 0.75 * math.sin(math.pi * u)
    return off, (r1 - 0.5) * 18, False


def _opacity(o: ChainOpts, i, s12, T):
    """The 12th's see-through: Rolo fades toward the 12th house end (flat 40 % on
    bands and rims), Cable alternates 55 % / 20 %."""
    if not o.marks.see_through:
        return 1.0
    if o.style == CABLE:
        return 0.2 if i % 2 else 0.55
    if o.band:
        return 0.4
    return 0.16 + 0.84 * min(max(s12 / T, 0.0), 1.0) if T else 1.0


def _open_side(o: ChainOpts, pitch, s8, sb):
    """None: the link is in the break (removed); +1 / -1: a neighbour of the
    break, drawn open on that side; 0: closed."""
    if sb < 0:
        return 0
    dd = abs(s8 - sb)
    if dd < pitch * 0.95:
        return None
    if dd >= pitch * 1.95:
        return 0
    direction = (1 if sb > s8 else -1) * (1 if o.end8 == 0 else -1)
    return 1 if direction > 0 else -1


def _raw_link(P: Poly, o: ChainOpts, g: ChainGeom, i, sb):
    T = P.T
    s = i * g.pitch
    s8 = s if o.end8 == 0 else T - s
    s12 = s if o.end12 == 0 else T - s
    opened = _open_side(o, g.pitch, s8, sb)
    if opened is None:
        return None
    base = o.seed * 977 + i * 31
    r1, r2, r3 = rnd(base + 1), rnd(base + 2), rnd(base + 3)
    (px, py), d = P.at(s)
    off, rot, crush = _chaos(o, g, T, s8, r1, r2)
    return [i, s, px - d[1] * off, py + d[0] * off, _opacity(o, i, s12, T), rot, crush,
            opened, r1, r2, r3]


def link_poses(P: Poly, o: ChainOpts):
    """The links of a chain along ``P`` (mockup ``chain()``, first half): equal
    steps, each link turned to the direction between its two neighbours."""
    g = chain_geom(o, P.T)
    n = jround(P.T / g.pitch) if g.pitch > 0 else 0
    sb = break_at(o, P.T)
    raw = [r for r in (_raw_link(P, o, g, i, sb) for i in range(n + 1)) if r is not None]
    out = []
    last = len(raw) - 1
    for j, l in enumerate(raw):
        a, b = raw[max(0, j - 1)], raw[min(last, j + 1)]
        dx, dy = b[2] - a[2], b[3] - a[3]
        if math.hypot(dx, dy) < 0.01:
            _p, (dx, dy) = P.at(l[1])
        ang = math.degrees(math.atan2(dy, dx)) + l[5]
        edge = o.style == CABLE and l[0] % 2 == 1 and not l[7]
        out.append(LinkPose(l[0], l[2], l[3], ang, l[4], l[6], l[7], edge, l[8], l[9], l[10]))
    return g, out


def mark_point(P: Poly, o: ChainOpts, frac):
    """The point ``frac`` of the way from the 8th house end (hazard, break)."""
    s8 = P.T * frac
    s = s8 if o.end8 == 0 else P.T - s8
    return P.at(s)


# ---------------------------------------------------------------- South Indian
def rim_points(x, y, w, h, gap, r):
    """The rounded rectangle ``gap`` outside a card (the cell rim chain path)."""
    x0, y0, x1, y1 = x - gap, y - gap, x + w + gap, y + h + gap
    pts = [(x0 + r, y0), (x1 - r, y0)]
    for j in range(1, 7):
        a = -math.pi / 2 + j / 6 * math.pi / 2
        pts.append((x1 - r + r * math.cos(a), y0 + r + r * math.sin(a)))
    pts.append((x1, y1 - r))
    for j in range(1, 7):
        a = j / 6 * math.pi / 2
        pts.append((x1 - r + r * math.cos(a), y1 - r + r * math.sin(a)))
    pts.append((x0 + r, y1))
    for j in range(1, 7):
        a = math.pi / 2 + j / 6 * math.pi / 2
        pts.append((x0 + r + r * math.cos(a), y1 - r + r * math.sin(a)))
    pts.append((x0, y0 + r))
    for j in range(1, 7):
        a = math.pi + j / 6 * math.pi / 2
        pts.append((x0 + r + r * math.cos(a), y0 + r + r * math.sin(a)))
    return pts


# ---------------------------------------------------------------- wheel
class WheelGeom(NamedTuple):
    cx: float
    cy: float
    R: float             # hub radius
    Rn: float            # house number radius
    Ro: float            # sign sector outer radius
    rot: float           # rotation offset (degrees)


def polar(g: WheelGeom, r, a):
    t = math.radians(a)
    return g.cx + r * math.cos(t), g.cy - r * math.sin(t)


def sign_angles(g: WheelGeom, sign):
    a0 = sign * 30 + g.rot
    return a0, a0 + 30, a0 + 15


def wheel_knot_t(s0, c, s1, knots, min_gap):
    """The wheel knot spacing rule: the first t of .5, .34, .66, .22, .78, .14, .86
    lying ``min_gap`` from every earlier knot, else the farthest one."""
    best, bt, bk = -1.0, 0.5, quad(s0, c, s1, 0.5)
    for tt in (0.5, 0.34, 0.66, 0.22, 0.78, 0.14, 0.86):
        kk = quad(s0, c, s1, tt)
        dm = min((math.hypot(o[0] - kk[0], o[1] - kk[1]) for o in knots), default=1e9)
        if dm >= min_gap:
            return tt, kk
        if dm > best:
            best, bt, bk = dm, tt, kk
    return bt, bk


def arc_points(g: WheelGeom, r, a0, a1, n=40):
    return [polar(g, r, a0 + (a1 - a0) * j / n) for j in range(n + 1)]
