# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Qt-free SPEC-SIC-006 placements and frozen Squared Rings coordinates."""
from dataclasses import dataclass
from math import isfinite
from .retinue_constants import (ADITYA_SIGN_ORDER, TRIMSAMSA_ODD,
                               TRIMSAMSA_EVEN, get_hora, get_trimsamsa_being)

# Canonical sector zero is Dhata, independently of displayed sign language.
CELLS = ((0, 1), (0, 2), (0, 3), (1, 3), (2, 3), (3, 3),
         (3, 2), (3, 1), (3, 0), (2, 0), (1, 0), (0, 0))

@dataclass(frozen=True)
class Placement:
    identity: str
    sign: int
    degree: float
    anchor: tuple[float, float] | None = None

    @property
    def label(self):
        return f"{int(self.degree)}°{int((self.degree % 1)*60):02d}′"

    @property
    def hora(self):
        return get_hora(ADITYA_SIGN_ORDER[self.sign], self.degree)

    @property
    def trim(self):
        return get_trimsamsa_being(ADITYA_SIGN_ORDER[self.sign], self.degree)


def placement(identity, sign, degree, anchor=None):
    """Validate the adapter boundary; exact sign end belongs to next sign."""
    if not isinstance(sign, int) or isinstance(sign, bool) or not 0 <= sign < 12:
        raise ValueError(f"{identity}: invalid sign {sign!r}")
    if degree is None or not isfinite(degree) or not 0 <= degree <= 30:
        raise ValueError(f"{identity}: invalid in-sign degree {degree!r}")
    if degree == 30:
        sign, degree = (sign + 1) % 12, 0.0
    return Placement(identity, sign, float(degree), anchor)


def from_object(identity, obj, varga_code=None, anchor=None):
    # D1 is explicitly an amsha accessor, as in the existing SI/Wheel labels.
    degree = (obj.real_in_sign_longitude() if varga_code is None
              else obj.amsha_raw_in_sign_longitude())
    return placement(identity, obj.sign() - 1, degree, anchor)


def partitions(sign):
    return TRIMSAMSA_ODD if sign % 2 == 0 else TRIMSAMSA_EVEN


@dataclass(frozen=True)
class HouseConnection:
    ring: str
    house: int
    sign: int


def house_connections(p, ring=None):
    """Wheel connections: houses are relative to the source Aditya, not lagna."""
    result = []
    if ring in (None, 'hora'):
        h = p.hora['house_connection']
        result.append(HouseConnection('hora', h, (p.sign + h - 1) % 12))
    if ring in (None, 'trim'):
        result.extend(HouseConnection('trim', h, (p.sign + h - 1) % 12)
                      for h in p.trim['house_connections'])
    return tuple(result)

@dataclass(frozen=True)
class Box:
    sign: int
    natal_size: float = 2048

    @property
    def row(self):
        return CELLS[self.sign][0]

    @property
    def column(self):
        return CELLS[self.sign][1]

    @property
    def scale(self):
        return self.natal_size / 600

    @property
    def horizontal(self):
        return self.row in (0, 3)

    def point(self, fraction, depth):
        """Reference mkPt, translated around the immutable natal rectangle."""
        a = 7 + fraction * 280
        if self.row == 0:
            x, y = a, depth
        elif self.row == 3:
            x, y = 294-a, 294-depth
        elif self.column == 0:
            x, y = depth, 294-a
        else:
            x, y = 294-depth, a
        return ((self.column*300+3+x)*self.scale-self.natal_size/2,
                (self.row*300+3+y)*self.scale-self.natal_size/2)

    def rect(self, start=0, end=1, near=0, far=294):
        a, b = self.point(start, near), self.point(end, far)
        return min(a[0], b[0]), min(a[1], b[1]), abs(a[0]-b[0]), abs(a[1]-b[1])

    @property
    def card(self):
        s = self.scale
        return ((self.column*300+3)*s-self.natal_size/2,
                (self.row*300+3)*s-self.natal_size/2, 294*s, 294*s)


def pack_chips(degrees, sizes, horizontal=True):
    """Pack measured screen-oriented rectangles in reference units.

    Try nearest available points, then compact ordered lanes if greedy placement
    fragments otherwise usable space.
    None requests a keyboard-accessible local member list; beams never move.
    """
    if len(degrees) > 8:
        return None
    # Candidate edges are formed by adding/subtracting measured font widths.
    # A few ULPs must not turn an exact gap into a collision (or a false stack).
    epsilon = 1e-9
    placed = []
    for degree, (width, height) in zip(degrees, sizes):
        along, across = (width, height) if horizontal else (height, width)
        if across > 78 or along > 280:
            return None
        candidates = []
        depths = sorted(set(max(162+across/2, min(240-across/2, d)) for d in (182,220)))
        for depth in depths:
            starts = [max(along/2, min(280-along/2, degree/30*280)), along/2]
            starts += [p[0]+p[2]/2+4+along/2 for p in placed]
            for center in starts:
                if center+along/2 > 280 + epsilon:
                    continue
                if all(abs(depth-p[1]) + epsilon >= (across+p[3])/2+2 or
                       abs(center-p[0]) + epsilon >= (along+p[2])/2+4 for p in placed):
                    candidates.append((abs(center-degree/30*280), depth, center))
        if not candidates:
            return _compact_chip_lanes(degrees, sizes, horizontal)
        _, depth, center = min(candidates)
        placed.append((center, depth, along, across))
    return tuple((p[0]/280, p[1]) for p in placed)


def _compact_chip_lanes(degrees, sizes, horizontal):
    """At most eight chips: enumerate two-lane partitions before collapsing.

    Keep degree order in each lane, with exact measured widths and 4-unit gaps.
    A backward pass shifts a crowded run left without changing the beam degrees.
    """
    dimensions = [(w, h) if horizontal else (h, w) for w, h in sizes]
    best = None
    for mask in range(1 << len(degrees)):
        lanes = [[i for i in sorted(range(len(degrees)), key=degrees.__getitem__)
                  if ((mask >> i) & 1) == lane] for lane in (0, 1)]
        widths = [max((dimensions[i][1] for i in lane), default=0) for lane in lanes]
        if sum(widths) + (2 if all(lanes) else 0) > 78 + 1e-9:
            continue
        slots = [None] * len(degrees)
        for lane_number, lane in enumerate(lanes):
            if not lane:
                continue
            if sum(dimensions[i][0] for i in lane) + 4*(len(lane)-1) > 280 + 1e-9:
                break
            centers = []
            edge = 0
            for i in lane:
                half = dimensions[i][0]/2
                center = max(edge + half, min(280-half, degrees[i]/30*280))
                centers.append(center)
                edge = center + half + 4
            edge = 280
            for j in range(len(lane)-1, -1, -1):
                half = dimensions[lane[j]][0]/2
                centers[j] = min(centers[j], edge-half)
                edge = centers[j]-half-4
            depth = (162 + widths[0]/2 if lane_number == 0 else 240-widths[1]/2)
            for i, center in zip(lane, centers):
                slots[i] = (center/280, depth)
        else:
            cost = sum(abs(t*280-degrees[i]/30*280) for i, (t, _) in enumerate(slots))
            if best is None or cost < best[0]:
                best = (cost, tuple(slots))
    return best[1] if best else None
