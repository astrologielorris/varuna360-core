"""Planet zone for one North Indian cell: the biggest planet grid that fits the
cell without touching anything already drawn in it (stateless, Qt-free).

Reserved rectangles (sign badge, Cards of Truth plaque, ASC label) are never
crossed. Centres and aspect ratios are sampled over the whole cell, each
rectangle sized in closed form against the convex cell and every reserved
rect, scored by the planet size its grid allows. A stellium in a triangle
uses rows that follow the cell outline, beside the badge (flow_layout).
"""

from functools import lru_cache

GAP = 10.0            # clearance kept from each reserved rectangle
SAMPLES = 12          # centre grid per axis over the cell's bounding box
ASPECTS = (0.5, 0.8, 1.25, 2.0, 3.2)


def _half_planes(points):
    """Inward unit normals (nx, ny, c) of a convex polygon: inside where
    nx*x + ny*y + c >= 0. Works for either winding."""
    n = len(points)
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    planes = []
    for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1]):
        nx, ny = ay - by, bx - ax
        length = (nx * nx + ny * ny) ** 0.5
        if length < 1e-9:
            continue
        nx, ny = nx / length, ny / length
        c = -(nx * ax + ny * ay)
        sign = 1 if nx * cx + ny * cy + c >= 0 else -1
        planes.append((sign * nx, sign * ny, sign * c))
    return planes


def _padded(rects):
    return [(l - GAP, t - GAP, w + 2 * GAP, h + 2 * GAP) for l, t, w, h in rects]


def _avoid_half_h(cx, cy, aspect, rect):
    """Largest half-height a rect centred at (cx, cy) keeps clear of ``rect``
    (0 when the centre is inside it)."""
    left, top, w, h = rect
    options = [(left - cx) / aspect, (cx - left - w) / aspect, top - cy, cy - top - h]
    return max(0.0, max(options))


def _max_half_h(cx, cy, aspect, planes, avoid, margin):
    """Largest half-height of a rect at (cx, cy), width = aspect * height,
    inside every half-plane by ``margin``, clear of every (padded) avoid rect."""
    best = float("inf")
    for nx, ny, c in planes:
        d = nx * cx + ny * cy + c - margin
        best = min(best, max(0.0, d) / (abs(nx) * aspect + abs(ny)))
    for rect in avoid:
        best = min(best, _avoid_half_h(cx, cy, aspect, rect))
    return best


def grid_fit(count, w, h, label_reserve, label_w):
    """(planet size, cols, rows) of the best grid of ``count`` planets in a
    w x h zone (10 % padding, ``label_reserve`` px under each planet). A
    column narrower than its label scores negative: captions would collide."""
    best = (-1e9, 1, count)
    for cols in range(1, count + 1):
        rows = -(-count // cols)
        cell_w, cell_h = w / cols, h / rows
        size = min(cell_w * 0.9, cell_h * 0.9 - label_reserve)
        if cell_w < label_w:
            size = cell_w - label_w - 1000
        best = max(best, (size, cols, rows))
    return best


def find_planet_zone(points, avoid_rects, count, wanted_size, label_reserve,
                     label_w, margin):
    """Best (left, top, w, h, size, cols, rows) for ``count`` planets in the
    convex cell ``points`` [(x, y), ...], never crossing ``avoid_rects``.

    The score is the planet size, capped at ``wanted_size`` (what the user
    asked for); among zones that reach it the bigger zone wins, so the grid
    breathes. Returns None when the cell has no free room at all.
    """
    planes, avoid = _half_planes(points), _padded(avoid_rects)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, y0 = min(xs), min(ys)
    step_x, step_y = (max(xs) - x0) / SAMPLES, (max(ys) - y0) / SAMPLES
    best_key, best = None, None
    for i in range(SAMPLES * SAMPLES):
        cx, cy = x0 + (i // SAMPLES + 0.5) * step_x, y0 + (i % SAMPLES + 0.5) * step_y
        for aspect in ASPECTS:
            hh = _max_half_h(cx, cy, aspect, planes, avoid, margin)
            w, h = 2 * hh * aspect, 2 * hh
            size, cols, rows = grid_fit(count, w, h, label_reserve, label_w)
            key = (round(min(size, wanted_size)), w * h)
            if hh > 4 and (best_key is None or key > best_key):
                best_key, best = key, (cx - w / 2, cy - hh, w, h, size, cols, rows)
    return best


def _x_extent(points, y):
    """[x_min, x_max] of the convex polygon on the horizontal line y, or None."""
    xs = [ax + (y - ay) * (bx - ax) / (by - ay)
          for (ax, ay), (bx, by) in zip(points, points[1:] + points[:1])
          if ay != by and (ay - y) * (by - y) <= 0]
    return (min(xs), max(xs)) if xs else None


def _cut(pieces, left, right):
    """``pieces`` (x intervals) minus [left, right]."""
    out = [(p0, min(p1, left)) for p0, p1 in pieces if left > p0]
    out += [(max(p0, right), p1) for p0, p1 in pieces if right < p1]
    return [(p0, p1) for p0, p1 in out if p1 > p0]


def _band_interval(points, avoid, top, bottom, margin):
    """Widest free [x0, x1] across the band top..bottom: inside the cell by
    ``margin`` (convex, so the band's narrower edge bounds it) and clear of
    every avoid rect overlapping the band."""
    a, b = _x_extent(points, top), _x_extent(points, bottom)
    if a is None or b is None:
        return None
    # A slanted edge's distance grows slower than x: widen the inset so the
    # slot corners keep ``margin`` from the edge.
    pieces = [(max(a[0], b[0]) + margin * 1.5, min(a[1], b[1]) - margin * 1.5)]
    for left, t, w, h in avoid:
        if t < bottom and t + h > top:
            pieces = _cut(pieces, left, left + w)
    return max(pieces, key=lambda p: p[1] - p[0]) if pieces else None


def _rows(points, avoid, y, y_end, slot_w, slot_h, margin):
    """(top, interval, capacity) of each band of height ``slot_h``."""
    rows = []
    while y + slot_h <= y_end:
        iv = _band_interval(points, avoid, y, y + slot_h, margin)
        rows.append((y, iv, int((iv[1] - iv[0]) // slot_w) if iv else 0))
        y += slot_h
    return rows


def _best_run(rows, count, best):
    """The fewest consecutive rows that hold every planet, the roomiest such
    run on a tie: one compact group. ``best`` = (key, run) so far."""
    for i in range(len(rows)):
        cap = 0
        for j in range(i, len(rows)):
            cap += rows[j][2]
            if rows[j][2] == 0 or cap >= count:
                break
        key = (-(j - i), cap)
        if rows[j][2] and cap >= count and (best is None or key > best[0]):
            best = (key, rows[i:j + 1])
    return best


def _fill(run, count, slot_w, slot_h, label_reserve):
    """Planet centres for a run of rows: round-robin, so rows stay balanced,
    on one shared centre line where the rows' free intervals allow it."""
    takes, left = [0] * len(run), count
    while left:
        for k, row in enumerate(run):
            if left and takes[k] < row[2]:
                takes[k] += 1
                left -= 1
    mid = sum((iv[0] + iv[1]) / 2 * t for (_y, iv, _n), t in zip(run, takes)) / count
    centres = []
    for (y, (x0, x1), _n), take in zip(run, takes):
        start = min(max(mid - take * slot_w / 2, x0), x1 - take * slot_w)
        centres += [(start + (c + 0.5) * slot_w, y + (slot_h - label_reserve) / 2)
                    for c in range(take)]
    return centres


def flow_layout(points, avoid_rects, count, wanted_size, label_reserve,
                label_w, margin, min_size=16):
    """Planets in rows following the cell outline (a triangle's wide part,
    beside the badge): (size, slot_w, centres) for the biggest size, or None."""
    avoid = _padded(avoid_rects)
    ys = [p[1] for p in points]
    y0, y1 = min(ys) + margin, max(ys) - margin
    for size in range(int(wanted_size), min_size - 1, -2):
        slot_w = max(size / 0.9, label_w * 1.05)
        slot_h = size / 0.9 + label_reserve
        best = None
        for off in range(4):
            rows = _rows(points, avoid, y0 + off * slot_h / 4, y1, slot_w, slot_h, margin)
            best = _best_run(rows, count, best)
        if best is not None:
            return size, slot_w, _fill(best[1], count, slot_w, slot_h, label_reserve)
    return None


@lru_cache(maxsize=512)
def plan_cell(points, avoid_rects, count, wanted_size, label_w, reserve,
              margin, hard_min=16, flow_below=48):
    """Where the ``count`` planets of one cell go: the better of the
    rectangle grid and the row flow. The tidy grid is kept unless it would
    shrink the planets under ``flow_below`` and the flow does better.
    ``label_w`` / ``reserve``: the widest caption and the room it takes
    under its planet. Returns a dict: ``centres`` (one per planet),
    ``max_fit`` (largest planet side), ``column_w`` (room per caption),
    ``center`` (the zone's middle), ``fits`` (False when no layout keeps
    the captions apart at ``hard_min``: the caller shrinks them and asks
    again); None when the cell has no free room. ``points`` and
    ``avoid_rects`` are tuples: a redraw with nothing changed (resize, theme)
    reuses the layout. Callers must not mutate the returned dict."""
    zone = find_planet_zone(points, avoid_rects, count, wanted_size, reserve,
                            label_w, margin)
    rect_size = min(zone[4], wanted_size) if zone else -1
    flow = (flow_layout(points, avoid_rects, count, wanted_size, reserve,
                        label_w, margin, hard_min)
            if rect_size < flow_below else None)
    if flow is not None and flow[0] > rect_size * 1.15:
        size, slot_w, centres = flow
        xs, ys = [c[0] for c in centres], [c[1] for c in centres]
        return {"centres": centres, "max_fit": size, "column_w": slot_w,
                "center": ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
                "fits": True}
    if zone is None:
        return None
    left, top, w, h, fit, cols, rows = zone
    cell_w, cell_h = w / cols, h / rows
    max_fit = max(hard_min, min(cell_w * 0.9, cell_h * 0.9 - reserve))
    # A grid too tight for its captions still keeps every planet inside
    # its zone, so the planets never reach the reserved rects around it.
    half = min(max_fit, w, h) / 2
    centres = [(min(max(left + (i % cols + 0.5) * cell_w, left + half), left + w - half),
                min(max(top + (i // cols + 0.5) * cell_h - reserve / 2, top + half), top + h - half))
               for i in range(count)]
    return {"centres": centres, "column_w": cell_w, "max_fit": max_fit,
            "center": (left + w / 2, top + h / 2), "fits": fit >= hard_min}
