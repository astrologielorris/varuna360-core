# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Capture rectangle math (SPEC-REC-001 §4.2), in X screen pixels.

Every rectangle is clipped to the X screen and rounded down to even width and
height (yuv420p). Capture is always the root window at an offset, never a
window id: a window capture would miss the highlight and bubble overlays.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

REGION_WINDOW = "window"
REGION_SCREEN = "screen"
REGION_RECT = "rect"
REGION_CHOICES = (REGION_WINDOW, REGION_SCREEN, REGION_RECT)
MIN_SIDE = 64


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def as_list(self):
        return [self.x, self.y, self.w, self.h]

    @classmethod
    def from_list(cls, values) -> Optional["Rect"]:
        try:
            x, y, w, h = (int(v) for v in values)
        except (TypeError, ValueError):
            return None
        return cls(x, y, w, h)


def union(a: Rect, b: Rect) -> Rect:
    x0, y0 = min(a.x, b.x), min(a.y, b.y)
    return Rect(x0, y0, max(a.x + a.w, b.x + b.w) - x0, max(a.y + a.h, b.y + b.h) - y0)


def intersect(a: Rect, b: Rect) -> Optional[Rect]:
    x0, y0 = max(a.x, b.x), max(a.y, b.y)
    x1, y1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    return Rect(x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None


def scale(rect: Rect, dpr: float) -> Rect:
    """Logical Qt coordinates to device (X) pixels."""
    return Rect(round(rect.x * dpr), round(rect.y * dpr), round(rect.w * dpr), round(rect.h * dpr))


def clip_even(rect: Rect, screen: Rect) -> Optional[Rect]:
    """Clip to the X screen, round the size down to even. None when what is
    left is smaller than MIN_SIDE on a side (nothing worth recording)."""
    x0 = max(rect.x, screen.x)
    y0 = max(rect.y, screen.y)
    x1 = min(rect.x + rect.w, screen.x + screen.w)
    y1 = min(rect.y + rect.h, screen.y + screen.h)
    w = (x1 - x0) // 2 * 2
    h = (y1 - y0) // 2 * 2
    if w < MIN_SIDE or h < MIN_SIDE:
        return None
    return Rect(x0, y0, w, h)


def normalized(x0: int, y0: int, x1: int, y1: int) -> Rect:
    """A dragged rectangle in any direction."""
    return Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))


def to_native(rect: Rect, screen_origin, dpr: float) -> Rect:
    """A Qt logical rectangle on one screen to X root pixels (review R2 F4).

    Qt 6 keeps each screen's top-left at its native position and scales only
    what lies inside the screen, so a point maps as
    ``origin + (p - origin) * dpr`` with THAT screen's own ratio."""
    ox, oy = screen_origin
    return Rect(round(ox + (rect.x - ox) * dpr), round(oy + (rect.y - oy) * dpr),
                round(rect.w * dpr), round(rect.h * dpr))


def native_union(rect: Rect, screens) -> Optional[Rect]:
    """A logical rectangle that may span screens with different pixel ratios:
    each screen maps its own part (``screens``: (logical Rect, dpr) pairs,
    the Rect's top-left being that screen's native origin), and the result is
    the bounding box of the mapped parts (review R3 F5). None when the
    rectangle touches no screen."""
    out = None
    for geo, dpr in screens:
        x0, y0 = max(rect.x, geo.x), max(rect.y, geo.y)
        x1, y1 = min(rect.x + rect.w, geo.x + geo.w), min(rect.y + rect.h, geo.y + geo.h)
        if x1 <= x0 or y1 <= y0:
            continue
        n = to_native(Rect(x0, y0, x1 - x0, y1 - y0), (geo.x, geo.y), dpr)
        if out is None:
            out = n
        else:
            ax0, ay0 = min(out.x, n.x), min(out.y, n.y)
            ax1, ay1 = max(out.x + out.w, n.x + n.w), max(out.y + out.h, n.y + n.h)
            out = Rect(ax0, ay0, ax1 - ax0, ay1 - ay0)
    return out
