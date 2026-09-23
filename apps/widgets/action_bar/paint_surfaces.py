"""SPEC-BAR-001 — SURFACE painting: bar body, clusters, tray, well, hairlines.

THE DESIGN SURFACE (M1). This module owns the bar's chrome: the vibrancy
gradient body, the recessed containers, the gold stripe, the separators.
Widget classes call these from paintEvent; geometry is theirs, pixels are
yours.

Contract (binding):
- Colors ONLY from ``tokens`` (``ui.qt_theme.bar_tokens()``); no hex here.
- CSS ground truth ``vibrancy_segmented.html``: #bar :195-210 (gradient
  bar-a->bar-b + inset gloss + under + lip shadow lines), .seg :224-245
  (ctl fill, inset 0.5px hairline, top gloss, drop; divider .divide::before
  suppressed next to a lit segment), .zodunit :325-334 (zodtray fill, inset
  hairline + inset 0 1px 2.5px black@.28 recess), .modsplit :351-355
  (gradient hairline), .title :376-408 (well fill, inset hairline, recess,
  hover brighten, gold stripe 3x14 gold_hi->gold + glow, chevron), .sep :221.
  Techniques: report 06 (gradient recess = 2-3px QLinearGradient clipped to
  the rounded path; glow = one larger rect behind at low alpha, no real blur).
- Vibrancy: v1 is the flattened gradient (D-3) — bar_a -> bar_b vertical,
  NO blur. Nothing renders behind the bar.
- Hairlines: 0.5 LOGICAL px coverage-equivalent, device-snapped (spec §4).
  Implement ``hairline_pen(tokens_color, dpr)`` here once, share with
  paint_controls (single implementation).
- The focus ring (D-14) is painted by ``paint_cluster_overlay`` into the
  reserved inter-control gaps — an OVERLAY pass the cluster runs after
  children paint; it never enters a neighbor's box (INV-2 exclusion).

MEASURED against the committed goldens (Chromium 149 @DPR1, flat --canvas-core
backdrop, `test/fidelity_bar/golden/bar_w1920_*_hdvis_fs100_short.png`).
Three things the CSS text does not tell you and the golden pixels do — all
three are reproduced here on purpose:

1. A `.5px` BOX-SHADOW and a `.5px` ELEMENT do not render the same way.
   Shadows (`inset 0 0 0 .5px hair`, `inset 0 .5px 0 gloss`) are antialiased
   at their true geometry: at DPR1 they land in ONE device row at HALF the
   token alpha. Elements (`.sep`, `.modsplit`, `.divide::before`) are snapped
   by layout to a whole device pixel and paint at FULL alpha. Golden proof
   (dark, w1920): the cluster rim row reads 73.5 where full alpha would read
   ~96; the `.sep` column reads 63.1 where half alpha would read ~49.
   => ``hairline_pen``/``draw_inset_hairline`` default to css_px=0.5 (half
   coverage at DPR1), the line helpers are called with css_px=1.0.
   This is a deliberate divergence from report 06 §2's "render 0.5px at full
   alpha at DPR1, do not fix it" — the goldens are the gate, and the coverage
   -equivalent rule (0.5 logical px of ink, however the device grid slices it)
   is what makes DPR1 and DPR2 agree with the design at the same time.

2. The recess is a GAUSSIAN inner shadow, not a linear ramp. Report 06 §3's
   `black -> transparent over depth+1` ramp is ~17 RGB too dark two rows into
   the light-theme tray. CSS `inset 0 1px 2.5px` blurs with sigma = blur/2, so
   the profile is alpha * Phi((offset - depth) / sigma) — matched to <=3.2 RGB
   against the goldens on both themes (worst case: the second row of the ramp
   in light). ``_inner_shadow`` samples that CDF into
   the gradient stops, and runs the left/right/bottom edges too (report 06's
   "EXACT upgrade": the golden's well side columns need it — 196.1 measured vs
   231.3 for a top-only recess).

3. The glow is separable, so it is cheaper to be exact than to approximate.
   Concentric expanded rects (report 06 §7) overshoot the stripe's peak by
   1.6x and its vertical falloff by 2.3x (a 3px-wide caster glows much less
   above than beside itself). ``soft_glow`` builds the true product
   Cx(x)*Cy(y) into a tiny cached QImage instead — 672 device px for the
   stripe, built once per (size, blur, color, dpr).

NOT PAINTED here, and why (see the agent report / register):
- `#bar`'s `0 .5px 0 bar_under` + `0 1px 0 bar_lip` sit BELOW the bar box, and
  `ChartActionBar` is exactly `bar_h` tall — painting them inside would eat the
  last gradient row (~20 RGB off golden). They need either a 2px allowance on
  the bar widget or a paint by whatever sits under the bar.
  (`.seg`'s `var(--drop)` is the same class of problem and IS painted — by
  `paint_bar`, from the cluster boxes the bar is handed; see `cluster_rects`.)

ONE PLACE THE GOLDEN IS NOT REPRODUCIBLE FROM THE CSS, and the measurement:
the `.seg` drop band. Fitting the golden's four affected rows gives a profile
no single blurred rectangle can produce. Coverage (shadow alpha / token alpha,
both themes agreeing to ~15%) reads 0.03 / 0.21 at 1.5 and 0.5px above the box,
and 0.84 / 0.21 at 0.5 and 1.5px below it. The 0.5px-above and 1.5px-below
readings being equal fixes the offset at exactly the CSS 0.5px, and the top
band's decay fits sigma ~1.1 — but a blurred edge is 0.5 AT the edge by
construction, and the row under the box reads 0.84. Chrome is laying down
~2.3x the CSS-Gaussian one pixel out and 1.7x at the edge. This module paints
the CSS (offset 0.5, blur 1.5, `drop` token) and leaves the residual measured
rather than dialling in a fudge factor: the band halves the error it was
opened to close (dark 5.0/12.0/3.0 -> 3.0/5.0/2.0 RGB on the rows above/below
a cluster, light 7.8/34.0/8.0 -> 3.8/12.0/4.0) and the rest is Chrome's.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen)

from .bar_types import BarMetrics
from .motion import lerp_premul

# Geometry the mockup states as raw CSS lengths rather than as `calc(... *
# var(--fs))`, i.e. values that do NOT scale with the font-scale ladder. The
# goldens confirm each one at fs 1.25 and 1.5 (e.g. title_chev stays w=11).
_CHEV_PX = 11.0          # .title .chev  <svg width="11" height="11">  :377
_CHEV_VIEWBOX = 12.0     # #i-chev viewBox="0 0 12 12"                 :521
_CHEV_STROKE = 1.4       # #i-chev stroke-width                        :521
_RECESS_OFFSET = 1.0     # inset 0 >1px< 2.5px  (.zodunit :332/.title :386)
_RECESS_BLUR = 2.5       # inset 0 1px >2.5px<
_STRIPE_RADIUS = 2.0     # .title .stripe border-radius:2px            :391
_STRIPE_GLOW_BLUR = 6.0  # .title .stripe box-shadow 0 0 >6px<         :393
_DIVIDER_INSET = 5.0     # .divide::before top/bottom (scales with fs) :241
_DROP_OFFSET = 0.5       # --drop: 0 >.5px< 1.5px black          :52 / :113
_DROP_BLUR = 1.5         # --drop: 0 .5px >1.5px< black          :52 / :113

_SQRT2 = math.sqrt(2.0)
_GLOW_CACHE: dict = {}
_GLOW_CACHE_MAX = 48


# ---------------------------------------------------------------------------
# hairline primitives — the single implementation (module contract)
# ---------------------------------------------------------------------------

def _alpha_scaled(color, factor: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, c.alphaF() * factor)))
    return c


def hairline_coverage(dpr: float, css_px: float = 0.5) -> float:
    """Alpha multiplier for a `css_px` line drawn as ONE device pixel.

    Coverage-equivalent: the ink a `css_px`-wide line would deposit is
    `css_px * dpr` device pixels; we always draw exactly one device pixel, so
    the alpha carries the remainder. DPR1 -> 0.5, DPR1.5 -> 0.75, DPR2+ -> 1.0
    for a 0.5px line; always 1.0 for a 1px line.
    """
    return max(0.0, min(1.0, css_px * max(dpr, 0.0)))


def hairline_width(dpr: float) -> float:
    """One DEVICE pixel expressed in logical units."""
    return 1.0 / max(dpr, 0.01)


def hairline_pen(color, dpr: float, css_px: float = 0.5) -> QPen:
    """A pen that strokes exactly one device pixel at coverage-equivalent alpha."""
    pen = QPen(_alpha_scaled(color, hairline_coverage(dpr, css_px)))
    pen.setWidthF(hairline_width(dpr))
    pen.setCapStyle(Qt.FlatCap)
    return pen


def snap_to_device(p: QPainter, value: float, dpr: float,
                   vertical: bool = True) -> float:
    """Nudge a logical coordinate so it lands on a DEVICE pixel boundary.

    Snapping in widget-local logical space is wrong at fractional DPR: a child
    at logical x=451 sits at device x=563.75 when dpr=1.25. The painter's
    device transform carries that offset, so the snap is computed there and
    mapped back (report 06 §2 technique B/D, made transform-aware).
    """
    dev = p.deviceTransform()
    scale = dev.m22() if vertical else dev.m11()
    offset = dev.dy() if vertical else dev.dx()
    if not scale:
        scale, offset = (dpr or 1.0), 0.0
    device = value * scale + offset
    return (round(device) - offset) / scale


def draw_hline(p: QPainter, x: float, y: float, w: float, color,
               dpr: float, css_px: float = 0.5) -> None:
    """A horizontal hairline whose TOP edge is `y` (report 06 §2 technique D)."""
    p.fillRect(QRectF(x, snap_to_device(p, y, dpr, True), w, hairline_width(dpr)),
               _alpha_scaled(color, hairline_coverage(dpr, css_px)))


def draw_vline(p: QPainter, x: float, y: float, h: float, color,
               dpr: float, css_px: float = 0.5) -> None:
    """A vertical hairline whose LEFT edge is `x`."""
    p.fillRect(QRectF(snap_to_device(p, x, dpr, False), y, hairline_width(dpr), h),
               _alpha_scaled(color, hairline_coverage(dpr, css_px)))


def draw_inset_hairline(p: QPainter, rect: QRectF, radius: float, color,
                        dpr: float, css_px: float = 0.5) -> None:
    """CSS `inset 0 0 0 <css_px>px <color>` — a rim drawn INSIDE `rect`.

    `drawRoundedRect` centres the stroke on the path, so a one-device-px pen on
    a path inset by half a device px puts the whole rim inside the box: the
    control's outer box, hit box and fill are untouched in every state (the
    zero-shift contract).
    """
    # A FILLED RING AT ITS TRUE WIDTH, not a one-device-px pen at coverage-
    # equivalent alpha. The alpha trick is right for an axis-aligned line — same
    # ink, same device column — but a rim follows an arc, where a 1px-wide band
    # covers 1.3 device px horizontally against the real 0.5px band's 0.63, so
    # half the ink lands in the wrong column (measured worst 29 RGB light).
    # A 0.5px ring filled at FULL alpha reproduces both: on the straight edge
    # the rasteriser resolves it to one column at half coverage (exactly what
    # Chrome does), on the arc it keeps the ink where Chrome puts it.
    # Both radii shrink with their inset: insetting a rounded rect keeps the
    # corner CENTRE and loses `inset` of radius.
    t = css_px
    outer = _rounded_path(rect, radius)
    inner = _rounded_path(rect.adjusted(t, t, -t, -t), max(0.0, radius - t))
    p.setPen(Qt.NoPen)
    p.fillPath(outer.subtracted(inner), QColor(color))


# ---------------------------------------------------------------------------
# hairline primitives, ink-conserving variant (M2 consolidation, D-20 amend)
#
# Moved verbatim from paint_controls (its M1 copy at :81-153 is deleted; this
# module now owns ALL hairline code). Two variants coexist ON PURPOSE — both
# are pixel-verified against the goldens and they differ only at DPR >= 2.5:
#
#   hairline_coverage/_width/_pen (above)  — ALWAYS one device row, alpha
#       carries the coverage. Used by the structural surface hairlines
#       (gloss bands, seps, tray rims) where a single row is the measured
#       golden reality.
#   hairline_ink / inset_hairline (below)  — ink-conserving: at DPR >= 2.5
#       the >1 device px of coverage becomes multiple rows at scaled alpha
#       instead of clamping. Used by the CONTROL rims and gloss (state
#       chrome), where the M1 agent verified this rows/alpha split.
#
# At the gate's DPR 1 (and any DPR <= 2.25) the two are numerically
# IDENTICAL: rows == 1 and alpha == coverage. Any tuning lands here once.
# ---------------------------------------------------------------------------

def hairline_ink(color, dpr: float, css_px: float = 0.5
                 ) -> tuple[float, QColor]:
    """``(logical width to paint, alpha-corrected color)`` for a CSS hairline.

    The mockup's hairlines are ``.5px`` — half a CSS pixel, i.e. a line whose
    INK COVERAGE is 0.5 logical px. A device row cannot be a fraction, so the
    coverage is moved into the alpha instead of the width (spec §4):

        DPR 1    -> 1 device row at ~half the token alpha
        DPR 1.5  -> 1 device row at 0.75 alpha
        DPR 2    -> 1 device row at FULL alpha  (0.5 logical == 1 device)
        DPR 3    -> 2 device rows at 0.75 alpha  (1.5 device px of coverage)
    """
    coverage = max(css_px * dpr, 1e-6)          # device px of ink wanted
    rows = max(1.0, round(coverage))            # rows we can actually paint
    out = QColor(color)
    out.setAlphaF(max(0.0, min(1.0, out.alphaF() * coverage / rows)))
    return rows / dpr, out


def snap_edge(v: float, dpr: float) -> float:
    """Snap a box EDGE to the device grid, half away from zero (CSS rounding).

    ``round()`` is banker's in Python: round(28.5) is 28, which loses the row
    the browser keeps. The accent bar sits on exactly such a .5 boundary.
    """
    return math.floor(v * dpr + 0.5) / dpr


def inset_hairline(p: QPainter, rect: QRectF, path_fn, color,
                   dpr: float) -> None:
    """CSS ``inset 0 0 0 .5px <color>`` — the stroke lies INSIDE ``rect``.

    ``path_fn(rect)`` builds the (per-corner rounded) outline, so the same
    helper serves rectangles, capsules and segment ends. Insetting by half the
    pen width keeps the control's outer box identical in every state, which is
    the mockup's zero-shift contract. (The scalar-radius, filled-ring sibling
    ``draw_inset_hairline`` above serves the recessed SURFACES, where the arc
    ink placement was measured to need the true-width ring.)
    """
    w, ink = hairline_ink(color, dpr)
    pen = QPen(ink)
    pen.setWidthF(w)
    pen.setCosmetic(False)
    inset = w / 2.0
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path_fn(rect.adjusted(inset, inset, -inset, -inset)))


def outset_hairline(p: QPainter, rect: QRectF, path_fn, color,
                    dpr: float) -> None:
    """CSS ``box-shadow: 0 0 0 .5px <color>`` (NO inset keyword) — the ring
    hugs the OUTSIDE of ``rect``. Same one-device-pixel + coverage-alpha
    The caller must own the pixels outside ``rect``: a child widget cannot
    paint past its own box, so e.g. the close button's hover rim is painted
    by the WELL (CP-4m S6 caught the inset placement as a chroma-bin flip —
    red-over-dark vs red-over-fill).

    Unlike the inset twin this strokes the TRUE 0.5 css-px band and lets the
    AA rasterizer compute per-pixel coverage: on a pill's end arcs the
    one-device-pixel + coverage-alpha convention deposits ~half the ink
    Chromium does, which CP-4m measured as a missing C25 strip at the lit
    capsule's edge (light theme)."""
    w = 0.5
    pen = QPen(color)
    pen.setWidthF(w)
    pen.setCosmetic(False)
    out = w / 2.0
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path_fn(rect.adjusted(-out, -out, out, out)))


# ---------------------------------------------------------------------------
# shadow primitives
# ---------------------------------------------------------------------------

def _phi(z: float) -> float:
    """Standard normal CDF — a CSS shadow blur of N px is a Gaussian, sigma N/2."""
    return 0.5 * (1.0 + math.erf(z / _SQRT2))


def _coverage_1d(x: float, length: float, sigma: float) -> float:
    """How much of a blurred band [0, length] covers the point `x`.

    One kernel for every shadow in the module: the Gaussian. A 3-pass box
    kernel (what Skia uses for its larger blurs) was built and measured against
    the goldens too — mean |delta| over the stripe's glow field came out
    2.77/2.42 RGB (dark/light) against the Gaussian's 2.63/2.47, i.e. a wash —
    so the simpler single kernel stands.
    """
    return _phi(x / sigma) - _phi((x - length) / sigma)


def _rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    r = max(0.0, min(radius, rect.width() / 2.0, rect.height() / 2.0))
    path.addRoundedRect(rect, r, r)
    return path


def _shadow_gradient(rect: QRectF, edge: str, color: QColor, offset: float,
                     sigma: float, stops: int = 12):
    """One edge of a CSS inset shadow, as a QLinearGradient of its true profile.

    Depth `d` inward from the edge carries `alpha * Phi((offset - d) / sigma)`,
    where `offset` is the shadow's displacement along the inward normal (the
    mockup offsets +1px DOWN, so the top edge gets +1, the bottom -1, the sides
    0). Sampling the CDF into stops beats a linear ramp by up to 17 RGB.
    """
    peak = color.alphaF() * _phi(offset / sigma)
    if peak < 1.0 / 512.0:
        return None
    depth = max(offset, 0.0) + 3.0 * sigma
    if edge in ("top", "bottom"):
        depth = min(depth, rect.height())
        x = rect.left()
        y0, y1 = ((rect.top(), rect.top() + depth) if edge == "top"
                  else (rect.bottom(), rect.bottom() - depth))
        grad = QLinearGradient(x, y0, x, y1)
    else:
        depth = min(depth, rect.width())
        y = rect.top()
        x0, x1 = ((rect.left(), rect.left() + depth) if edge == "left"
                  else (rect.right(), rect.right() - depth))
        grad = QLinearGradient(x0, y, x1, y)
    if depth <= 0.0:
        return None
    for i in range(stops + 1):
        t = i / float(stops)
        c = QColor(color)
        c.setAlphaF(color.alphaF() * _phi((offset - t * depth) / sigma))
        grad.setColorAt(t, c)
    return grad


def _inner_shadow(p: QPainter, path: QPainterPath, rect: QRectF, color,
                  offset: float = _RECESS_OFFSET, blur: float = _RECESS_BLUR,
                  sides: bool = True) -> None:
    """CSS `inset 0 <offset>px <blur>px <color>`, one gradient band per edge.

    Filled INTO the rounded path rather than `fillRect` under `setClipPath`:
    the raster engine's clip is hard-edged even with Antialiasing on, so a
    clipped fill drops the shadow entirely on every partially-covered corner
    pixel while the fill beneath it was laid down antialiased. Measured on the
    goldens, that left the well's corner arc up to 17 RGB too light.
    """
    sigma = max(blur * 0.5, 0.01)
    col = QColor(color)
    edges = (("top", offset), ("bottom", -offset))
    if sides:
        edges = edges + (("left", 0.0), ("right", 0.0))
    p.setPen(Qt.NoPen)
    for edge, off in edges:
        grad = _shadow_gradient(rect, edge, col, off, sigma)
        if grad is not None:
            p.fillPath(path, grad)


def _glow_image(w: float, h: float, blur: float, color: QColor, dpr: float,
                extent: float) -> QImage:
    """The exact separable field of `box-shadow: 0 0 <blur>px <color>`.

    A box shadow is the source rect convolved with a Gaussian, and that
    convolution is separable: alpha(x, y) = a * Cx(x) * Cy(y) where
    Cx(x) = Phi((w-x)/sigma) - Phi(-x/sigma). Building it into a small ARGB
    image is both exact and (once cached) free, unlike the concentric-rect
    stack, which cannot express that a narrow caster glows weakly above itself.
    """
    key = (round(w, 2), round(h, 2), round(blur, 2), color.rgba(),
           round(dpr, 3), round(extent, 2))
    cached = _GLOW_CACHE.get(key)
    if cached is not None:
        return cached

    sigma = max(blur * 0.5, 0.01)
    dev_w = max(1, int(math.ceil((w + 2.0 * extent) * dpr)))
    dev_h = max(1, int(math.ceil((h + 2.0 * extent) * dpr)))
    cx = [_coverage_1d((i + 0.5) / dpr - extent, w, sigma) for i in range(dev_w)]
    cy = [_coverage_1d((j + 0.5) / dpr - extent, h, sigma) for j in range(dev_h)]

    a0, red, green, blue = color.alphaF(), color.red(), color.green(), color.blue()
    buf = bytearray(dev_w * dev_h * 4)
    idx = 0
    for j in range(dev_h):
        row = cy[j] * a0
        for i in range(dev_w):
            a = int(cx[i] * row * 255.0 + 0.5)
            if a > 0:
                buf[idx] = (blue * a + 127) // 255      # ARGB32 is BGRA in memory
                buf[idx + 1] = (green * a + 127) // 255
                buf[idx + 2] = (red * a + 127) // 255
                buf[idx + 3] = a
            idx += 4
    img = QImage(bytes(buf), dev_w, dev_h,
                 QImage.Format_ARGB32_Premultiplied).copy()
    img.setDevicePixelRatio(dpr)
    if len(_GLOW_CACHE) >= _GLOW_CACHE_MAX:
        _GLOW_CACHE.clear()
    _GLOW_CACHE[key] = img
    return img


def _rrect_sdf(x: float, y: float, hw: float, hh: float, r: float) -> float:
    """Signed distance to a rounded rect centred at the origin (>0 outside)."""
    qx = abs(x) - (hw - r)
    qy = abs(y) - (hh - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - r


def drop_extent(blur: float = _DROP_BLUR, offset: float = _DROP_OFFSET) -> float:
    """How far outside its box a `0 <offset> <blur>` shadow reaches."""
    return math.ceil(3.0 * max(blur * 0.5, 0.01) + abs(offset))


def _drop_image(w: float, h: float, radius: float, offset: float, blur: float,
                color: QColor, dpr: float) -> QImage:
    """CSS `box-shadow: 0 <offset>px <blur>px <color>` cast by a rounded rect.

    Distance-field form: alpha = A * Phi(-d/sigma) with `d` the signed distance
    to the SHIFTED rounded rect. The separable Cx*Cy used for the stripe cannot
    be used here — the caster has 6px corners and the goldens show that corner
    plainly, the band under a cluster ramping in over exactly one radius. The
    box's own interior is punched out: CSS clips an outer shadow to outside the
    border box, and the cluster's fill above it is translucent.
    """
    key = (round(w, 2), round(h, 2), round(radius, 2), round(offset, 2),
           round(blur, 2), color.rgba(), round(dpr, 3))
    cached = _GLOW_CACHE.get(key)
    if cached is not None:
        return cached

    sigma = max(blur * 0.5, 0.01)
    e = drop_extent(blur, offset)
    dev_w = max(1, int(math.ceil((w + 2.0 * e) * dpr)))
    dev_h = max(1, int(math.ceil((h + 2.0 * e) * dpr)))
    hw, hh = w / 2.0, h / 2.0
    cx, cy = e + hw, e + hh
    r = max(0.0, min(radius, hw, hh))
    a0, red, green, blue = color.alphaF(), color.red(), color.green(), color.blue()

    def _px(v: int) -> bytes:
        return bytes(((blue * v + 127) // 255, (green * v + 127) // 255,
                      (red * v + 127) // 255, v))

    def _alpha_at(dx: float, dy: float) -> int:
        a = a0 * _phi(-_rrect_sdf(dx, dy - offset, hw, hh, r) / sigma)
        if a <= 0.0:
            return 0
        inside = _rrect_sdf(dx, dy, hw, hh, r)      # CSS clips to outside the box
        a *= 1.0 - max(0.0, min(1.0, 0.5 - inside * dpr))
        return int(a * 255.0 + 0.5)

    # between the corner arcs the field depends on y alone, so a row there is
    # one value and one slice assignment instead of `w` distance evaluations
    run_lo = max(0, int(math.ceil(((e + r) * dpr) - 0.5)))
    run_hi = min(dev_w, int(((e + w - r) * dpr) - 0.5))
    buf = bytearray(dev_w * dev_h * 4)
    for j in range(dev_h):
        y = (j + 0.5) / dpr
        base = j * dev_w * 4
        interior = (e + 1.0 <= y <= e + h - 1.0)
        if not interior and run_hi > run_lo:
            v = _alpha_at(0.0, y - cy)
            if v > 0:
                buf[base + run_lo * 4:base + run_hi * 4] = _px(v) * (run_hi - run_lo)
        for i in list(range(0, min(run_lo, dev_w))) + list(range(max(run_hi, 0), dev_w)):
            v = _alpha_at((i + 0.5) / dpr - cx, y - cy)
            if v > 0:
                buf[base + i * 4:base + i * 4 + 4] = _px(v)
    img = QImage(bytes(buf), dev_w, dev_h,
                 QImage.Format_ARGB32_Premultiplied).copy()
    img.setDevicePixelRatio(dpr)
    if len(_GLOW_CACHE) >= _GLOW_CACHE_MAX:
        _GLOW_CACHE.clear()
    _GLOW_CACHE[key] = img
    return img


def soft_glow(p: QPainter, rect: QRectF, color, dpr: float,
              blur: float = _STRIPE_GLOW_BLUR) -> None:
    """CSS `box-shadow: 0 0 <blur>px <color>` behind `rect` (spread 0, offset 0)."""
    col = QColor(color)
    if col.alphaF() <= 0.0 or rect.isEmpty():
        return
    extent = math.ceil(1.5 * blur)          # 3 sigma
    img = _glow_image(rect.width(), rect.height(), blur, col, dpr, extent)
    p.drawImage(QPointF(snap_to_device(p, rect.left() - extent, dpr, False),
                        snap_to_device(p, rect.top() - extent, dpr, True)), img)


# ---------------------------------------------------------------------------
# surfaces
# ---------------------------------------------------------------------------

def paint_bar(p: QPainter, rect: QRectF, tokens: dict, m: BarMetrics,
              dpr: float, cluster_rects: list[QRectF] = ()) -> None:
    """The 40px vibrancy bar body (#bar :195-210) + the clusters' cast shadows.

    `background: linear-gradient(180deg, bar-a, bar-b)` + `inset 0 .5px 0
    bar-gloss`. The backdrop blur is flattened away (D-3); `bar_under`/`bar_lip`
    fall below the widget box — see the module header.

    ``cluster_rects`` are the .seg cluster boxes in BAR coordinates. Their CSS
    `var(--drop)` (`0 .5px 1.5px`) is an OUTER shadow landing on bar rows above
    and below each cluster, and a child cannot paint outside its own rect
    (INV-2) — so the bar lays those bands down here, after its own inset gloss
    (CSS paint order: a descendant's shadow is above its ancestor's decoration).
    """
    # The bar OWNS its backdrop (T-319 flatten, integration decision at CP-1):
    # the translucent gradient composites over an opaque canvas_core base, the
    # exact field the goldens rendered over. Without it the widget's palette
    # background bleeds through the 78-88% alpha and every surface washes.
    # The T-317 live-blur upgrade replaces THIS fill, not the gradient.
    p.fillRect(rect, tokens["canvas_core"])
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, tokens["bar_a"])
    grad.setColorAt(1.0, tokens["bar_b"])
    p.fillRect(rect, grad)
    draw_hline(p, rect.left(), rect.top(), rect.width(), tokens["bar_gloss"], dpr)

    drop = tokens["drop"]
    e = drop_extent(_DROP_BLUR, _DROP_OFFSET)   # must match _drop_image's own
    for box in cluster_rects:
        if box.isEmpty():
            continue
        img = _drop_image(box.width(), box.height(), m.radius, _DROP_OFFSET,
                          _DROP_BLUR, QColor(drop), dpr)
        p.drawImage(QPointF(snap_to_device(p, box.left() - e, dpr, False),
                            snap_to_device(p, box.top() - e, dpr, True)), img)


def paint_cluster(p: QPainter, rect: QRectF, tokens: dict, m: BarMetrics,
                  dpr: float, dividers: list[tuple[float, bool]] = (),
                  transparent_bg: bool = False) -> None:
    """Segmented-cluster chrome (.seg :224-245). ``dividers`` = [(x, suppressed)].

    `background: ctl` + `inset 0 0 0 .5px hair` + `inset 0 .5px 0 gloss`; the
    rim paints ON TOP of the gloss (CSS paints a shadow list front-to-back, and
    both land in the same top row). ``transparent_bg`` is the tray's inner
    .seg.zod (`background:transparent; box-shadow:none` :335-337) — which still
    carries its inter-segment dividers.
    """
    p.setRenderHint(QPainter.Antialiasing, True)
    if not transparent_bg:
        path = _rounded_path(rect, m.radius)
        p.setPen(Qt.NoPen)
        p.setBrush(tokens["ctl"])
        p.drawPath(path)
        # the top gloss line, cut to the corner arcs by PATH INTERSECTION —
        # setClipPath would alias the two top corners (see _inner_shadow)
        band = QPainterPath()
        band.addRect(QRectF(rect.left(), snap_to_device(p, rect.top(), dpr),
                            rect.width(), hairline_width(dpr)))
        p.fillPath(path.intersected(band),
                   _alpha_scaled(tokens["gloss"], hairline_coverage(dpr)))
        draw_inset_hairline(p, rect, m.radius, tokens["hair"], dpr)

    inset = round(_DIVIDER_INSET * m.fs)
    top, height = rect.top() + inset, rect.height() - 2 * inset
    for x, vis in dividers:
        # M4 (Dm4-38): the second member is now the divider's VISIBILITY as a
        # float 0..1 (the 160 ms suppression fade). Legacy bool callers keep
        # their meaning — True meant "suppressed", i.e. visibility 0.
        if isinstance(vis, bool):
            a = 0.0 if vis else 1.0
        else:
            a = float(vis)
        if a <= 0.0:
            continue
        # an ELEMENT hairline, not a shadow: full alpha, one device px
        draw_vline(p, x, top, height,
                   tokens["hair_soft"] if a >= 1.0
                   else _alpha_scaled(tokens["hair_soft"], a),
                   dpr, css_px=1.0)


def paint_cluster_overlay(p: QPainter, rect: QRectF, tokens: dict,
                          m: BarMetrics, dpr: float,
                          focus_rects: list[QRectF] = ()) -> None:
    """Post-children overlay: focus rings in the reserved gaps (D-14).

    M1 PLACEHOLDER — no-op (keyboard focus paint lands with the state work).
    """


def paint_tray(p: QPainter, rect: QRectF, tokens: dict, m: BarMetrics,
               dpr: float) -> None:
    """The recessed zodiac tray (.zodunit :325-334).

    `background: zodtray` + `inset 0 0 0 .5px hair` + `inset 0 1px 2.5px
    black@.28` (the `recess` token). Fill, then the inner shadow clipped to the
    rounded path, then the rim on top of both.
    """
    p.setRenderHint(QPainter.Antialiasing, True)
    path = _rounded_path(rect, m.tray_radius)
    p.setPen(Qt.NoPen)
    p.setBrush(tokens["zodtray"])
    p.drawPath(path)
    _inner_shadow(p, path, rect, tokens["recess"])
    draw_inset_hairline(p, rect, m.tray_radius, tokens["hair"], dpr)


def paint_modsplit(p: QPainter, rect: QRectF, tokens: dict, m: BarMetrics,
                   dpr: float) -> None:
    """The gradient-faded vertical hairline before the capsule (.modsplit :351-355).

    `linear-gradient(180deg, transparent, hair 22%, hair 78%, transparent)` on a
    `.5px` ELEMENT — layout-snapped, so full alpha in one device column.

    The widget is `1 + 2*round(1*fs)` wide (the mockup's `margin:0 1px*fs`,
    :354, folded into the box — D-22i); the column sits at the horizontal
    CENTRE, which is the old left edge plus the margin.
    """
    x = snap_to_device(p, rect.center().x() - 0.5, dpr, False)
    grad = QLinearGradient(x, rect.top(), x, rect.bottom())
    hair = tokens["hair"]
    fade = _alpha_scaled(hair, 0.0)
    grad.setColorAt(0.0, fade)
    grad.setColorAt(0.22, hair)
    grad.setColorAt(0.78, hair)
    grad.setColorAt(1.0, fade)
    p.fillRect(QRectF(x, rect.top(), hairline_width(dpr), rect.height()), grad)


def paint_hairline_sep(p: QPainter, rect: QRectF, tokens: dict,
                       m: BarMetrics, dpr: float) -> None:
    """A plain track-level separator (.sep :221) — `.5px` element, `hair`."""
    draw_vline(p, rect.left(), rect.top(), rect.height(), tokens["hair"], dpr,
               css_px=1.0)


def paint_title_well(p: QPainter, rect: QRectF, tokens: dict, m: BarMetrics,
                     dpr: float, hovered: float = 0.0,
                     chev_t: float | None = None) -> None:
    """The recessed document well + gold stripe + chevron (.title :376-408).

    Idle: `well` fill, `inset 0 0 0 .5px well-line`, `inset 0 1px 2.5px
    black@.28`. Hover (:387-390) swaps all three: `well-h`, `hair`, black@.22.
    The stripe is a child element, so it and its glow paint OVER the rim.
    Children (name, meta, close) are real widgets laid out by TitleWell; the
    chevron is chrome and lives in the gap the layout reserves before close.

    M4 (Dm4-41): ``hovered`` is the well clock's position 0..1 (bool callers
    still work — True == 1.0, and endpoints resolve to the exact tokens);
    ``chev_t`` is the chevron's own 160 ms clock, defaulting to ``hovered``
    because the mockup declares two clocks but one trigger.
    """
    t = float(hovered)
    p.setRenderHint(QPainter.Antialiasing, True)
    path = _rounded_path(rect, m.radius)
    p.setPen(Qt.NoPen)
    p.setBrush(lerp_premul(tokens["well"], tokens["well_h"], t))
    p.drawPath(path)
    _inner_shadow(p, path, rect,
                  lerp_premul(tokens["recess"], tokens["recess_hover"], t))
    draw_inset_hairline(p, rect, m.radius,
                        lerp_premul(tokens["well_line"], tokens["hair"], t),
                        dpr)

    # --- gold stripe (.stripe :390-394) -------------------------------------
    stripe = QRectF(snap_to_device(p, rect.left() + m.title_pad_l, dpr, False),
                    snap_to_device(p, rect.center().y() - m.stripe_h / 2.0,
                                   dpr, True),
                    m.stripe_w, m.stripe_h)
    soft_glow(p, stripe, tokens["stripe_glow"], dpr)
    grad = QLinearGradient(stripe.topLeft(), stripe.bottomLeft())
    grad.setColorAt(0.0, tokens["gold_hi"])
    grad.setColorAt(1.0, tokens["gold"])
    p.setPen(Qt.NoPen)
    p.fillPath(_rounded_path(stripe, _STRIPE_RADIUS * m.fs), grad)

    # --- chevron (.chev :377 / #i-chev :521) --------------------------------
    _paint_chevron(p, rect, tokens, m, dpr, t if chev_t is None else chev_t)


def chevron_rect(rect: QRectF, m: BarMetrics) -> QRectF:
    """The 11x11 chevron glyph box inside ``rect`` (the well), or an empty rect
    when the well is too narrow to seat it. Shared by the painter and the well's
    click hit-test (F2/MAJOR 2: the chevron is the overlay-clear affordance, so
    it must be hittable at exactly the pixels it is drawn)."""
    size = _CHEV_PX
    right = rect.right() - m.title_pad_r - m.close_d - m.title_gap
    left = right - size
    top = rect.center().y() - size / 2.0
    if left < rect.left():
        return QRectF()
    return QRectF(left, top, size, size)


def _paint_chevron(p: QPainter, rect: QRectF, tokens: dict, m: BarMetrics,
                   dpr: float, hovered: float) -> None:
    """The 11x11 disclosure chevron, just left of the close button's box.

    The layout reserves no widget for it: the close glyph sits at
    `right - title_pad_r - close_d` and the chevron owns the `title_gap` slot
    before it. Golden landmark check at fs 1.0/1.25/1.5: the glyph stays 11x11
    at every scale (the mockup writes `width="11"`, not `calc(11px*var(--fs))`)
    while the gap around it scales — reproduced literally.
    """
    size = _CHEV_PX
    box = chevron_rect(rect, m)
    if box.isEmpty():
        return
    left = box.left()
    top = box.top()
    s = size / _CHEV_VIEWBOX
    path = QPainterPath()
    path.moveTo(left + 3.0 * s, top + 4.8 * s)
    path.lineTo(left + 6.0 * s, top + 7.8 * s)
    path.lineTo(left + 9.0 * s, top + 4.8 * s)
    pen = QPen(lerp_premul(tokens["muted"], tokens["secondary_text"],
                           float(hovered)))
    pen.setWidthF(_CHEV_STROKE * s)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
