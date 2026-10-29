# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Pure layout arithmetic of the Chart-tab info panels (SPEC-LAYOUT-001 B).

No Qt here: ``InfoPanelStack`` measures its widgets (folded height, natural
height, open minimum) and asks these functions what to do with them, so the
rules are unit-testable and a resize never does more than integer math.

Vocabulary
----------
- *weights*: one number per panel of a splitter, 0 = folded (header bar plus
  its one-line summary), > 0 = open, sharing the free height in proportion.
- *fractions*: the open panels' weights normalized to 1 (what is remembered).
- *topology*: "stack" (Karakas / Strength / bottom panel in one column) or
  "magazine" (Karakas + Strength on the left, the bottom panel full height on
  the right).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

PANEL_NAMES = ("karakas", "strength", "bottom")
STACK_NAMES = PANEL_NAMES
MAGAZINE_NAMES = ("karakas", "strength")      # the left column; bottom is the right one
FOLD_TOLERANCE = 2        # px: a height this close to the folded height counts as folded
SQUEEZE = 0.8             # the last open panel may be squeezed to 80 % when others are open
CLICK_SLOP = 4            # px: a press that moves less is a click, not a drag


def names_for(magazine: bool) -> Tuple[str, ...]:
    return MAGAZINE_NAMES if magazine else STACK_NAMES


# ------------------------------------------------------------------ auto mode
def auto_weights(names: Sequence[str], avail: int, natural: Dict[str, int],
                 fold_h: Dict[str, int], handles: int) -> List[float]:
    """Automatic open count from the splitter's own height (plan B.4).

    Every panel open when all natural heights fit; else the topmost panels fold
    one by one (the last one, Avastha's panel in the stacked column, keeps
    priority). With more than one panel open the last may be squeezed to
    ``SQUEEZE`` of its natural height; alone it takes whatever is left."""
    n = len(names)
    for k in range(n, 0, -1):                       # k = number of open panels
        folded, opened = names[:n - k], names[n - k:]
        need = handles + sum(fold_h[p] for p in folded)
        need += sum(natural[p] for p in opened[:-1])
        need += natural[opened[-1]] * (1.0 if k == n else SQUEEZE)
        if k == 1 or need <= avail:
            return [0.0] * (n - k) + [float(max(1, natural[p])) for p in opened]
    return [0.0] * (n - 1) + [1.0]                  # pragma: no cover (k == 1 returns)


def ensure_one_open(weights: Sequence[float]) -> List[float]:
    """The last open panel cannot be folded: all-folded opens the last one."""
    w = [max(0.0, float(x)) for x in weights]
    if w and not any(x > 0 for x in w):
        w[-1] = 1.0
    return w


# ------------------------------------------------------------------- heights
def heights(weights: Sequence[float], total: int, fold_h: Sequence[int],
            open_min: Sequence[int]) -> List[int]:
    """Integer heights for ``weights`` inside ``total`` px.

    Folded panels get their folded height; open ones share the rest in
    proportion to their weights, never below their open minimum; the last open
    panel takes the rounding remainder so the sum is exactly ``total`` whenever
    the minimums fit (otherwise the minimums win and the column scrolls)."""
    w = ensure_one_open(weights)
    out = [int(fold_h[i]) if w[i] <= 0 else 0 for i in range(len(w))]
    open_idx = [i for i in range(len(w)) if w[i] > 0]
    rest = int(total) - sum(out)
    fixed = {}
    # Clamp to minimums iteratively: a panel whose share is below its minimum
    # takes its minimum and leaves the others the remainder.
    while True:
        free = [i for i in open_idx if i not in fixed]
        free_rest = rest - sum(fixed.values())
        wsum = sum(w[i] for i in free) or 1.0
        newly = {i: int(open_min[i]) for i in free
                 if free_rest * w[i] / wsum < open_min[i]}
        if not newly:
            break
        fixed.update(newly)
        if len(fixed) == len(open_idx):
            break
    free = [i for i in open_idx if i not in fixed]
    free_rest = rest - sum(fixed.values())
    wsum = sum(w[i] for i in free) or 1.0
    for i in open_idx:
        out[i] = fixed[i] if i in fixed else int(math.floor(free_rest * w[i] / wsum))
    if free:
        out[free[-1]] += int(total) - sum(out)
    return out


def give_surplus(hs: Sequence[int], natural: Sequence[int],
                 open_flags: Sequence[bool]) -> List[int]:
    """No blank space while another panel is cut: height an open panel holds
    beyond its natural height moves to the open panels short of theirs (top
    first). The total is unchanged, so manual proportions only yield what
    would have shown as empty ground (Lorris 2026-10-15: Strength cut while
    the Avastha panel showed a blank area under its table)."""
    out = [int(h) for h in hs]
    opened = [i for i, o in enumerate(open_flags) if o]
    sur = [i for i in opened if out[i] > natural[i]]
    short = [i for i in opened if out[i] < natural[i]]
    surplus = sum(out[i] - natural[i] for i in sur)
    if not sur or not short:
        return out
    move = min(surplus, sum(natural[i] - out[i] for i in short))
    taken = 0
    for i in sur:
        t = move * (out[i] - natural[i]) // surplus
        out[i] -= t
        taken += t
    for i in short:
        g = min(natural[i] - out[i], taken)
        out[i] += g
        taken -= g
    out[sur[-1]] += taken                           # rounding remainder
    return out


def auto_heights(weights: Sequence[float], total: int, fold_h: Sequence[int],
                 natural: Sequence[int], open_min: Sequence[int]) -> List[int]:
    """AUTO heights: when the open panels' natural heights do not all fit,
    every open panel but the last keeps its natural height (its whole table)
    and the last takes the rest (the squeeze ``auto_weights`` allowed);
    otherwise the free height is shared in proportion to the naturals."""
    w = ensure_one_open(weights)
    open_idx = [i for i in range(len(w)) if w[i] > 0]
    rest = int(total) - sum(int(fold_h[i]) for i in range(len(w)) if w[i] <= 0)
    if len(open_idx) > 1 and sum(natural[i] for i in open_idx) > rest:
        out = [int(fold_h[i]) if w[i] <= 0 else int(natural[i]) for i in range(len(w))]
        last = open_idx[-1]
        out[last] = max(int(open_min[last]), int(total) - (sum(out) - out[last]))
        return out
    return heights(w, total, fold_h, open_min)


def fold_strength(names: Sequence[str], weights: Sequence[float], avail: int,
                  natural: Dict[str, int], fold_h: Dict[str, int], handles: int,
                  bottom_need: int, auto: bool) -> Optional[List[float]]:
    """The focus hold's Strength fold (SPEC-VAC-001 D-13, Lorris 2026-10-28): while the
    Vedic drawing is shown in the stacked column, Strength folds whenever the three
    panels do not all fit at their natural heights (``bottom_need`` = the whole height
    the bottom panel needs). Every other panel above keeps its natural height when it is
    open (AUTO: whenever it fits) and still leaves the bottom panel ``bottom_need``;
    otherwise it folds too. The bottom panel takes the rest. ``None`` when all three fit.
    Inputs are natural and folded heights only, never the heights this fold produces."""
    if "strength" not in names or "bottom" not in names:
        return None
    if handles + bottom_need + sum(natural[n] for n in names if n != "bottom") <= avail:
        return None
    room = avail - handles - bottom_need - sum(fold_h[n] for n in names if n != "bottom")
    out = []
    for n, w in zip(names, weights):
        cost = natural[n] - fold_h[n]
        if n in ("strength", "bottom") or not (auto or w > 0) or cost > room:
            out.append(0.0)
            continue
        room -= cost
        out.append(float(max(1, natural[n])))
    used = handles + sum(natural[n] if w > 0 else fold_h[n]
                         for n, w in zip(names, out) if n != "bottom")
    out[names.index("bottom")] = float(max(1, avail - used))
    return out


def folded_flags(hs: Sequence[int], fold_h: Sequence[int]) -> List[bool]:
    return [h <= f + FOLD_TOLERANCE for h, f in zip(hs, fold_h)]


def fractions_of(hs: Sequence[int], folded: Sequence[bool]) -> List[float]:
    """Open panels' heights normalized to 1, in order (folded ones skipped)."""
    opened = [float(h) for h, f in zip(hs, folded) if not f]
    s = sum(opened)
    return [h / s for h in opened] if s > 0 else []


def weights_from(names: Sequence[str], folded: Sequence[str],
                 fractions: Optional[Sequence[float]],
                 natural: Dict[str, int]) -> List[float]:
    """Manual mode: folded panels 0, open ones their remembered fractions
    (natural heights when the fractions do not match the open count)."""
    opened = [p for p in names if p not in folded]
    if fractions is not None and len(fractions) == len(opened):
        it = iter(fractions)
        return ensure_one_open([0.0 if p in folded else float(next(it)) for p in names])
    return ensure_one_open([0.0 if p in folded else float(max(1, natural[p])) for p in names])


# --------------------------------------------------------- exchange and snap
def exchange(h_a: int, h_b: int, fold_a: int, fold_b: int) -> Tuple[int, int]:
    """Reciprocal exchange of a pair (plan B.3): the taller one folds and the
    other takes the pair's whole height; the pair's total is preserved."""
    total = h_a + h_b
    if h_a >= h_b:
        return fold_a, total - fold_a
    return total - fold_b, fold_b


def snap_candidates(total: int, fold_a: int, fold_b: int,
                    natural_a: int, natural_b: int) -> List[int]:
    """Heights the upper panel of a dragged pair snaps to: folded, the lower
    one folded, half, and each panel's natural ("fit") height when it fits."""
    cands = [fold_a, total - fold_b, total // 2]
    if fold_a <= natural_a <= total - fold_b:
        cands.append(natural_a)
    if fold_a <= total - natural_b <= total - fold_b:
        cands.append(total - natural_b)
    return sorted(set(int(c) for c in cands))


def snap(value: float, candidates: Sequence[int]) -> int:
    return min(candidates, key=lambda c: (abs(c - value), c))


# ---------------------------------------------------------------- magazine
def want_magazine(width: int, need: int, current: bool, hysteresis: int) -> bool:
    """Magazine when the column holds both columns' minimum widths (plan B.5);
    the hysteresis band keeps a scroll bar or a 1-px jitter from flapping it."""
    if current:
        return width >= need - hysteresis
    return width >= need


# -------------------------------------------------------------- validation
def parse_folded(value) -> Optional[Tuple[str, ...]]:
    """CSV (or list) of known panel names, no duplicates, not all three; None
    when invalid (the caller falls back to the default, plan D5)."""
    if value is None:
        return None
    if isinstance(value, str):
        items = [v.strip() for v in value.split(",") if v.strip()]
    elif isinstance(value, (list, tuple)):
        if not all(isinstance(v, str) for v in value):
            return None
        items = [v.strip() for v in value]
    else:
        return None
    if any(v not in PANEL_NAMES for v in items) or len(set(items)) != len(items):
        return None
    if len(items) >= len(PANEL_NAMES):
        return None
    return tuple(p for p in PANEL_NAMES if p in items)


def parse_fractions(value) -> Optional[List[float]]:
    """CSV (or list) of finite floats > 0, normalized to 1; None when empty or
    invalid. The open-count check happens where the open set is known."""
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            items = [float(v) for v in value.split(",")]
        except (ValueError, OverflowError):
            return None
    elif isinstance(value, (list, tuple)):
        try:
            items = [float(v) for v in value]
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    if not items or any(not math.isfinite(v) or v <= 0 for v in items):
        return None
    s = sum(items)
    if not math.isfinite(s):
        return None
    out = [v / s for v in items]
    if any(not math.isfinite(v) or v <= 0 for v in out):
        return None
    return out


def format_fractions(fractions: Optional[Sequence[float]]) -> str:
    return ",".join(f"{v:.4f}" for v in fractions) if fractions else ""
