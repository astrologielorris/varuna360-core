"""SPEC-BAR-001 — CONTROL painting: segments, capsule, close glyph, icons.

THE DESIGN SURFACE (M1). This module owns every pixel of the bar's
interactive controls. The widget classes are thin: they maintain state and
call these functions from paintEvent with a ready QPainter. Nothing here may
touch geometry — the box is decided by ControlMetrics before paint (INV-1).

Contract (binding):
- Colors come ONLY from the ``tokens`` dict (``ui.qt_theme.bar_tokens()``),
  keys documented there. No hex literal in this module (Rule 20 / AC-4).
- Fidelity target: the mockup's rendered pixels, gated by
  ``test/fidelity_bar`` goldens. CSS ground truth:
  ``proprietary_docs/spec_design/action_bar_v2/vibrancy_segmented.html``
  (.btn :248-320, tint blocks :288-305, .zod :335-350, .btn.mod :357-373,
  .xbtn :409-418), techniques report 06, token sheet report 05.
- Hairlines: 0.5 LOGICAL px coverage-equivalent, device-snapped (spec §4):
  DPR 1 -> 1 device px at ~half alpha; DPR 2 -> 1 device px full alpha;
  fractional DPR -> snap to nearest device row. The shared primitives live
  in paint_surfaces (hairline_ink / inset_hairline / snap_edge — M2
  consolidation); no hairline code is defined here.
- States change COLOR ONLY. Focus ring is NOT painted here (D-14: the
  cluster container paints it in its overlay pass).
- Disabled (D-12): label+icon at 0.45 alpha over the IDLE fill; hover/press
  suppressed by the state object already.
- The ``.acc`` accent hairline is ALWAYS in the box: rect at
  (acc_inset, h - acc_bottom - 1.5, w - 2*acc_inset, 1.5), radius 2,
  transparent when not lit. Lit colors per role (tint blocks).
- The live dot paints at FULL opacity in M1 (motion is M4); top-right
  (live_off, live_off), diameter live_d, green + glow.
- Icons: ``icon_pixmap`` renders the SVG assets in ``img/icons/bar_<id>.svg``
  recolored to the state's foreground, cached per (id, size, color, dpr).
  The Dhata glyph follows the D-8 snap contract: below 20 logical px at
  DPR<1.5 use ``img/aditya_glyph/dhata_mini.svg`` in an integer-multiple-of-13
  device box at an integer device offset, centered in the slot.

TEXT (mandatory): every label goes through ``bar_types.draw_bar_text`` /
``text_advance``. A bare ``painter.drawText`` with a widget font renders at
Qt's integer ppem (11.5px -> 12px) and silently inflates every label ~4%.
"""
from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFontMetricsF, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtSvg import QSvgRenderer

from .motion import lerp_premul
from .paint_surfaces import (hairline_ink, inset_hairline, outset_hairline,
                             snap_edge)
from .bar_types import (BTN_TEXT, PLUS_TEXT, BarMetrics, Role, SegInk,
                        SegMotion, SegPaintState, SegPos, draw_bar_text,
                        scaled_font, text_advance)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ICON_DIR = _REPO_ROOT / "img" / "icons"
_GLYPH_DIR = _REPO_ROOT / "img" / "aditya_glyph"

# --- CSS constants that are not geometry (INV-3 keeps sizes in BarMetrics;
# these are paint-local ratios the mockup writes inline in a rule). ---------
_ACC_H = 1.5                # .acc height        :285
_ACC_R = 2.0                # .acc border-radius :285
# .btn .ico declares ``translate:0 -.25px`` (:265) as an optical nudge AGAINST
# the cap height. The golden's rasterised ink says the opposite: solving the
# info glyph's two horizontal borders for the box origin gives 6.731 at fs 1.0
# (CSS layout centre 6.5), and a sub-pixel fit of all nine non-Dhata glyphs
# against the golden lands on +0.25 for every one of them. The mockup CSS and
# the golden pixels disagree about this quarter pixel; the goldens are the
# contract, so the sign here follows them. See the return report.
_ICO_NUDGE = +0.25
_ICO_IDLE_OPACITY = 0.90    # .btn .ico opacity:.9          :264
_DISABLED_ALPHA = 0.45      # D-12
_DHATA_MINI_ENABLED = False  # D-8 as amended at CP-1: mockup's thickened
                             # glyph matches the golden; mini = M5 contingency
_DHATA_MINI_MAX_PX = 20.0   # D-8 selection threshold
_DHATA_MINI_MAX_DPR = 1.5   # D-8 selection threshold
_DHATA_MINI_GRID = 13       # D-8 rasterisation contract
_DHATA_MINI_MIN_FILL = 0.78  # below this the mini reads as a shrunken mark
_GLOW_STEPS = 6             # report 06 §7 falloff rings (no real blur)
_GLOW_EDGE = 0.10           # glow alpha at the shape edge (measured)


# ===========================================================================
# hairlines — imported from paint_surfaces (M2 consolidation, D-20 amend).
# The M1 copies that lived here are gone; paint_surfaces owns ALL hairline
# code (its module comment documents the two verified variants). snap_edge
# is the half-away-from-zero EDGE snap the accent bar depends on.
# ===========================================================================


def _glow(p: QPainter, path_fn, rect: QRectF, color: QColor,
          radius_px: float) -> None:
    """``box-shadow: 0 0 <radius>px <color>`` without a real blur.

    Concentric expanded shapes at a small constant alpha (report 06 §7): N
    layers composited give ~N*a at the shape's edge and ramp linearly to zero
    at ``radius_px``, which is close enough to the Gaussian a real blur would
    lay down over 5-6px that no reviewer can pick it out.

    ``_GLOW_EDGE`` is measured, not guessed. The golden's green accent lifts
    the pixel immediately above the bar by 6/255 of the way to full green and
    the pixel 5px above by 3/255 — i.e. the CSS shadow lands ~0.06 alpha at
    the edge for a token carrying 0.60. A naive "0.16 peak plus a 0.02 floor"
    falloff (report 06's sketch) puts the FLOOR on the outermost ring too and
    hazes the whole control green; the measured constant is an order of
    magnitude smaller.
    """
    p.setPen(Qt.NoPen)
    a = color.alphaF() * _GLOW_EDGE / _GLOW_STEPS
    for i in range(_GLOW_STEPS, 0, -1):
        t = i / _GLOW_STEPS
        c = QColor(color)
        c.setAlphaF(a)
        e = radius_px * t
        p.setBrush(c)
        p.drawPath(path_fn(rect.adjusted(-e, -e, e, e)))


# ===========================================================================
# vertical text placement — the mockup's line box, not Qt's
# ===========================================================================
#
# The label is a flex item with ``line-height:1`` centred in the 26px control,
# and CSS puts its baseline at
#
#     (h - F)/2  +  floor( half_leading + ascent )         F = font px size
#
# where ``half_leading = (F - (ascent+descent))/2`` and the font's ascent and
# descent are the browser's INTEGER-ROUNDED ones. That floor is not decoration:
# it is why the golden's fs 1.0 baseline sits at 16.25 in the box and not at
# the 17.18 that centring the *fractional* ascent/descent (what Qt's
# AlignVCenter does) would give — a full device pixel of drift on the gate's
# primary capture. Verified against the live mockup's own baseline probe at
# fs 0.8 / 1.0 / 1.25 / 1.5 / 2.0: exact at all five.
#
# Qt is then aimed at that baseline by OFFSETTING the rect handed to
# ``draw_bar_text``: Qt's AlignVCenter resolves to
# ``rect.top + (rect.h - (A+D))/2 + A`` on the fractional metrics, so shifting
# the rect by (target - that) lands the baseline exactly. Going through the
# shared primitive keeps the scale trick — and its 4%-inflation fix — intact.

_BASELINE_CACHE: dict[tuple, float] = {}


def _fractional_metrics(style: tuple, fs: float) -> tuple[float, float]:
    """(ascent, descent) at the TRUE fractional pixel size."""
    font, k = scaled_font(*style, fs=fs)
    fm = QFontMetricsF(font)
    return fm.ascent() / k, fm.descent() / k


def css_baseline(h: float, fs: float, style: tuple = BTN_TEXT) -> float:
    """Baseline offset from the control's top, per the CSS line-box rule."""
    key = ("t", round(h, 4), round(fs, 4), style)
    v = _BASELINE_CACHE.get(key)
    if v is None:
        a, d = _fractional_metrics(style, fs)
        px = style[0] * fs
        v = (h - px) / 2.0 + math.floor((px + round(a) - round(d)) / 2.0)
        _BASELINE_CACHE[key] = v
    return v


def _text_rect(rect: QRectF, x: float, w: float, baseline: float,
               style: tuple, fs: float) -> QRectF:
    """A rect whose AlignVCenter puts ``style``'s baseline on ``baseline``."""
    key = ("q", round(rect.height(), 4), round(fs, 4), style)
    qt_base = _BASELINE_CACHE.get(key)
    if qt_base is None:
        a, d = _fractional_metrics(style, fs)
        qt_base = (rect.height() - (a + d)) / 2.0 + a
        _BASELINE_CACHE[key] = qt_base
    return QRectF(x, rect.top() + baseline - qt_base, w, rect.height())


def clear_text_cache() -> None:
    """Drop the memoised baselines (font-scale or font-family change)."""
    _BASELINE_CACHE.clear()


# ===========================================================================
# per-corner rounding (SegPos) — the mockup's .seg-first / .seg-last radii
# ===========================================================================

def _corner_radii(pos: SegPos, role: Role, rect: QRectF,
                  m: BarMetrics) -> tuple[float, float, float, float]:
    """(top-left, top-right, bottom-right, bottom-left) radii."""
    if role is Role.MOD:                       # border-radius:999px  :360
        r = rect.height() / 2.0
        return (r, r, r, r)
    r = float(m.radius)
    if role is Role.SOLO or pos is SegPos.SOLO:
        return (r, r, r, r)
    if pos is SegPos.FIRST:
        return (r, 0.0, 0.0, r)
    if pos is SegPos.LAST:
        return (0.0, r, r, 0.0)
    return (0.0, 0.0, 0.0, 0.0)                # .seg > .btn{border-radius:0}


def _rounded_path(rect: QRectF, radii: tuple[float, float, float, float]
                  ) -> QPainterPath:
    """A rounded rect with independent corner radii (QPainterPath has no
    per-corner API; each corner is an explicit 90 degree arc)."""
    tl, tr, br, bl = (max(0.0, min(r, rect.width() / 2.0, rect.height() / 2.0))
                      for r in radii)
    path = QPainterPath()
    path.moveTo(rect.left() + tl, rect.top())
    path.lineTo(rect.right() - tr, rect.top())
    if tr:
        path.arcTo(QRectF(rect.right() - 2 * tr, rect.top(), 2 * tr, 2 * tr),
                   90, -90)
    path.lineTo(rect.right(), rect.bottom() - br)
    if br:
        path.arcTo(QRectF(rect.right() - 2 * br, rect.bottom() - 2 * br,
                          2 * br, 2 * br), 0, -90)
    path.lineTo(rect.left() + bl, rect.bottom())
    if bl:
        path.arcTo(QRectF(rect.left(), rect.bottom() - 2 * bl, 2 * bl, 2 * bl),
                   270, -90)
    path.lineTo(rect.left(), rect.top() + tl)
    if tl:
        path.arcTo(QRectF(rect.left(), rect.top(), 2 * tl, 2 * tl), 180, -90)
    path.closeSubpath()
    return path


# ===========================================================================
# icons
# ===========================================================================

_SVG_BYTES: dict[str, bytes] = {}
# LRU (Dm4-19): animated icon colours would otherwise grow this without
# bound — quantised to 8 steps AND capped, belt and braces. dicts preserve
# insertion order; a hit re-inserts to mark recency.
_ICON_CACHE: dict[tuple, QPixmap] = {}
_ICON_CACHE_MAX = 512


def _svg_source(name: str) -> bytes | None:
    """Raw SVG bytes for an icon id, read once. ``dhata``/``dhata_mini`` live
    with the Aditya glyph family; everything else is a bar asset."""
    if name in _SVG_BYTES:
        return _SVG_BYTES[name]
    if name == "dhata_mini":
        path = _GLYPH_DIR / "dhata_mini.svg"
    else:
        path = _ICON_DIR / ("bar_%s.svg" % name)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    _SVG_BYTES[name] = data
    return data


def _recolored(name: str, color: QColor) -> bytes | None:
    """Report 06 form A: substitute the ink literal. Both asset families are
    authored in ``currentColor`` (which QSvgRenderer does not resolve), so ONE
    substitution covers strokes, fills and the mini's ``fill="currentColor"``
    (D-8 notes that the old ``stroke="#e0d8c8"`` substitution no-ops there).
    Per-path ``opacity`` attributes survive untouched."""
    raw = _svg_source(name)
    if raw is None:
        return None
    return raw.replace(b"currentColor", color.name(QColor.HexRgb).encode())


def _dhata_mini_box(size_px: float, dpr: float) -> int | None:
    """The device box for ``dhata_mini``, or None to use the full glyph (D-8).

    D-8 selects the mini below ~20 logical px at DPR < 1.5, where the 48-unit
    glyph rasterises with ZERO fully-opaque pixels. Its crispness claim,
    though, holds only in a device box that is an integer MULTIPLE of 13, so
    the box is the largest multiple that FITS the slot — never one that
    overflows it, which is what "nearest multiple" would do at a 20px device
    box (26 px of glyph in a 20 px hole) and at fs 0.8 (13 in a 10 px hole).

    If the largest fitting multiple is under ~78% of the slot the mini would
    read as a shrunken mark inside its own control, so the full glyph is used
    instead and takes the antialiasing: correct size beats crisp edges once
    the size error is visible. In the shipped ladder this hands the mini
    fs 0.8-1.25 at DPR 1 and fs 1.0 at DPR 1.25, and the full glyph everything
    at fs >= 1.5 (where it holds up anyway, report 06 §5).

    D-8 AMENDED at CP-1 (orchestrator ruling): the substitution is OFF by
    default. Its premise — zero opaque pixels at 13px — was measured on
    Josh's thin 48-unit glyph; the mockup's own thickened `#i-dhata`
    (bar_dhata.svg, stroke 3.6) keeps the full centre-plus-petals structure
    at a 13px AA render and matches the golden (the mini cost a dE 15.8 FAIL
    on the lit-thumb glyph probe). The mini remains the M5 real-screen
    contingency: flip _DHATA_MINI_ENABLED if 13px AA proves illegible on the
    physical 2K screen (that flip re-triggers the recorded D-8 deviation).
    """
    if not _DHATA_MINI_ENABLED:
        return None
    if size_px >= _DHATA_MINI_MAX_PX or dpr >= _DHATA_MINI_MAX_DPR:
        return None
    dev = max(1, int(round(size_px * dpr)))
    box = (dev // _DHATA_MINI_GRID) * _DHATA_MINI_GRID
    if box < _DHATA_MINI_GRID or box < dev * _DHATA_MINI_MIN_FILL:
        return None
    return box


def icon_pixmap(icon_id: str, size_px: float, color: QColor, dpr: float,
                phase: tuple[float, float] = (0.0, 0.0)) -> QPixmap | None:
    """A DPR-correct, recolored glyph pixmap for a ``size_px`` logical box.

    Cached on (id, size, color, dpr, phase) — the DPR must be in the key or the
    glyph re-rasterises soft when the window moves to another screen (report
    06 §5).

    ``phase`` is the glyph's SUB-DEVICE-PIXEL offset, and it is not a detail:
    the icon slot's top lands on x.25 in the mockup (the 13px box centred in a
    26px control, minus the .ico's -0.25px optical nudge). Rounding that away
    shortens every glyph by a row against the golden. The renderer therefore
    draws into a pixmap one device pixel larger with the fraction baked in,
    and the caller blits on a whole device pixel — sharper than letting
    drawPixmap resample, and positionally exact.

    D-8 RASTERISATION CONTRACT for the Dhata: ``dhata_mini.svg`` is authored on
    a 13-unit integer grid, so it is only 100% opaque when painted into a
    device box that is an integer MULTIPLE of 13 at an INTEGER device offset
    (``_dhata_mini_box`` picks it). The phase is therefore FORCED to zero and
    the caller centres the result in the icon slot on a whole device pixel.
    Scaling the mini into the fractional slot instead drops it to ~6% opaque
    coverage, i.e. throws away the whole reason the asset exists.
    """
    if not icon_id:
        return None
    name = icon_id
    dev = max(1, int(round(size_px * dpr)))
    if icon_id == "dhata":
        box = _dhata_mini_box(size_px, dpr)
        if box is not None:
            name, dev, phase = "dhata_mini", box, (0.0, 0.0)

    fx = round(phase[0] * 8) / 8.0
    fy = round(phase[1] * 8) / 8.0
    key = (name, dev, color.rgba(), round(dpr, 4), fx, fy)
    pm = _ICON_CACHE.pop(key, None)
    if pm is not None:
        _ICON_CACHE[key] = pm          # re-insert: most-recently-used
        return pm

    raw = _recolored(name, color)
    if raw is None:
        return None
    renderer = QSvgRenderer(QByteArray(raw))
    if not renderer.isValid():
        return None
    pad = 1 if (fx or fy) else 0
    pm = QPixmap(dev + pad, dev + pad)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    ip = QPainter(pm)
    # The mini is pixel-authored: antialiasing would soften the very edges the
    # 13-grid exists to keep hard.
    ip.setRenderHint(QPainter.Antialiasing, name != "dhata_mini")
    renderer.render(ip, QRectF(fx / dpr, fy / dpr, dev / dpr, dev / dpr))
    ip.end()
    while len(_ICON_CACHE) >= _ICON_CACHE_MAX:         # Dm4-19 LRU cap
        _ICON_CACHE.pop(next(iter(_ICON_CACHE)))
    _ICON_CACHE[key] = pm
    return pm


def _draw_icon(p: QPainter, icon_id: str, slot: QRectF, color: QColor,
               opacity: float, dpr: float) -> None:
    """Blit a glyph into ``slot``: sub-pixel phase in the raster, whole device
    pixel in the blit (see ``icon_pixmap``). The D-8 mini has no phase, so it
    is centred in the slot on the device grid instead."""
    # X is SNAPPED to the device grid, Y keeps its sub-pixel phase. That is
    # not a compromise, it is what the golden shows: fitting the five glyphs
    # whose box lands on a .5+ fraction (INFO, NOW, ADD CHART, BIRTH TIME,
    # the mod rim) picks the rounded column every time, while the same fit on
    # the vertical axis picks +0.25 off the layout centre for all nine. In a
    # real bar the snap is a no-op anyway (integer widget x + integer
    # padding); it only bites when reproducing the mockup's fractional flex
    # positions, and it keeps stems on whole pixels rather than smearing them.
    mini = (icon_id == "dhata"
            and _dhata_mini_box(slot.width(), dpr) is not None)
    dx, dy = round(slot.x() * dpr), slot.y() * dpr
    ix, iy = int(dx), math.floor(dy)
    pm = icon_pixmap(icon_id, slot.width(), color, dpr,
                     (0.0, 0.0) if mini else (0.0, dy - iy))
    if pm is None:
        return
    if mini:
        # D-8: no phase, integer device offset, centred in the slot.
        ix = round((slot.x() + (slot.width() - pm.width() / dpr) / 2.0) * dpr)
        iy = round((slot.y()
                    + (slot.height() - pm.height() / dpr) / 2.0) * dpr)
    prev = p.opacity()
    p.setOpacity(prev * opacity)
    p.drawPixmap(QPointF(ix / dpr, iy / dpr), pm)
    p.setOpacity(prev)


def clear_icon_cache() -> None:
    """Drop the rasterised glyphs (theme switch / saturation change)."""
    _ICON_CACHE.clear()


# ===========================================================================
# per-state colour resolution (the tint blocks, :281-305 / :335-373)
# ===========================================================================

def _background(st: SegPaintState, tokens: dict) -> QColor | None:
    """The state fill, or None for "leave the container showing through"."""
    hot = st.hovered or st.pressed
    if st.lit:
        if st.role is Role.TINT_BLUE:                              # :288-290
            return tokens["primary_dark"] if hot else tokens["tint_blue"]
        if st.role is Role.TINT_GREEN:                             # :292-294
            return tokens["tint_green_h"] if hot else tokens["tint_green"]
        if st.role is Role.TINT_GOLD:              # D-23(d): ACTIVE / RETURN
            # ACTIVE = --tint-gold; RETURN (hover while lit) = tint_gold_h,
            # the color-mix(--gold 32%) lift above the resting gold.
            return tokens["tint_gold_h"] if hot else tokens["tint_gold"]
        if st.role is Role.MOD:
            # .btn.mod.on (:366) and .btn.mod:hover (:365) tie on
            # specificity, and .on is the LATER rule — so hovering (or
            # pressing, :260 loses outright) a lit mod changes NOTHING.
            # CP-4m S4 caught the tint_gold_h swap as a 2170px chroma
            # flood vs the golden.
            return tokens["tint_gold"]
        if st.role is Role.ZOD:
            return None                     # the thumb gradient, below
        return tokens["ctl_on_h"] if hot else tokens["ctl_on"]     # :281-282
    if st.pressed:
        return tokens["ctl_a"]                                     # :259
    if st.hovered:
        return tokens["ctl_h"]                                     # :258
    if st.role is Role.SOLO:
        return tokens["ctl"]                                  # .btn.solo :272
    return None


def _foreground(st: SegPaintState, tokens: dict) -> QColor:
    """The label colour (CSS ``color``, which the glyph inherits)."""
    if st.lit:
        if st.role is Role.TINT_BLUE:
            return tokens["tint_blue_fg"]
        if st.role is Role.TINT_GREEN:
            return tokens["tint_green_fg"]
        if st.role is Role.TINT_GOLD:                              # D-23(d)
            return tokens["tint_gold_fg"]
        if st.role is Role.MOD:
            return tokens["tint_gold_fg"]
        return tokens["primary_text"]                         # :281 / :341
    if st.role is Role.PRIMARY:                                    # :299-302
        return tokens["primary"] if st.hovered else tokens["primary_action"]
    return tokens["primary_text"] if st.hovered else tokens["secondary_text"]


def _icon_color(st: SegPaintState, tokens: dict, fg: QColor) -> QColor:
    if st.lit and st.role in (Role.ZOD, Role.MOD):            # :345 / :372
        return tokens["gold_hi"]
    if st.role is Role.PRIMARY and not st.lit:                     # :300
        return tokens["primary"]
    return fg                                             # color:currentColor


def _icon_opacity(st: SegPaintState) -> float:
    if st.hovered:                                                 # :267
        return 1.0
    if st.lit and st.role in (Role.ZOD, Role.MOD):            # :345 / :372
        return 1.0
    return _ICO_IDLE_OPACITY


def _accent(st: SegPaintState, tokens: dict) -> tuple[QColor, QColor] | None:
    """``(bar colour, glow colour)`` for the lit .acc, or None when it stays
    transparent. The rect is ALWAYS reserved — only the colour changes."""
    if not st.lit or st.role is Role.MOD:       # .btn.mod .acc{display:none}
        return None
    if st.role is Role.TINT_BLUE:
        return tokens["acc_blue"], None                            # :291
    if st.role is Role.TINT_GREEN:
        return tokens["green"], tokens["acc_green_glow"]           # :294
    if st.role is Role.TINT_GOLD:              # D-23(d): gold hairline + glow
        return tokens["gold"], tokens["acc_gold_glow"]             # :297
    if st.role is Role.ZOD:
        # D-24: the hairline's shade is FROZEN at `gold` — it says "this cell
        # is live" and nothing else; the naming scheme is carried by the
        # glyph swap (st.icon), not by a shade nobody could see (Dm3-17 was).
        return tokens["gold"], tokens["thumb_acc_glow"]            # :347
    return None                   # .btn.on .acc has no background of its own


def resolve_ink(st: SegPaintState, tokens: dict) -> SegInk:
    """The full resolved appearance of one segment, as one frozen value.

    M4 (Dm4-3/7): fades snapshot this as their `from` and re-resolve the
    target from live tokens at paint time. Composes the per-state helpers
    above plus _paint_chrome's two rim choices and the gold "+" run colour —
    bodies unchanged, so this factoring is pixel-neutral by construction.
    """
    fg = _foreground(st, tokens)
    acc_pair = _accent(st, tokens)
    if st.role is Role.SOLO:
        rim = tokens["hair"]
    elif st.role is Role.MOD:
        rim = tokens["mod_rim_on"] if st.lit else tokens["hair"]
    else:
        rim = None
    return SegInk(
        fill=_background(st, tokens),
        fg=fg,
        ico=_icon_color(st, tokens, fg),
        ico_opacity=_icon_opacity(st),
        acc=acc_pair[0] if acc_pair else None,
        acc_glow=acc_pair[1] if acc_pair else None,
        rim=rim,
        plus=((tokens["gold_hi"] if st.lit else tokens["gold"])
              if st.gold_plus else None),
    )


# ===========================================================================
# the segment painter
# ===========================================================================

def _paint_thumb(p: QPainter, rect: QRectF, path: QPainterPath, tokens: dict,
                 dpr: float, radii) -> None:
    """``.zod > .btn.on`` — the sliding lit thumb (:339-343).

    ``background:var(--thumb)`` (a 180deg gradient) plus
    ``inset 0 .5px 0 var(--gloss), inset 0 0 0 .5px var(--hair-soft),
    var(--drop)``. The two insets STACK on the top device row, and both are
    needed: the golden's top row reads 87 over a 73 body, which is the gloss
    at half alpha (81) then hair-soft at half alpha on top (88) — dropping
    either one leaves the thumb's lit edge visibly flat.

    ``var(--drop)`` is an OUTER shadow that lands on the tray, outside this
    widget's fixed box; a child cannot paint there and the golden shows no
    darkening inside the box, so it is left to the tray painter.
    """
    g = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    g.setColorAt(0.0, tokens["thumb_top"])
    g.setColorAt(1.0, tokens["thumb_bottom"])
    p.setPen(Qt.NoPen)
    p.fillPath(path, QBrush(g))

    p.save()
    p.setClipPath(path)
    lw, ink = hairline_ink(tokens["gloss"], dpr)       # inset 0 .5px 0 gloss
    p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), lw), ink)
    p.restore()
    inset_hairline(p, rect, lambda r: _rounded_path(r, radii),
                   tokens["hair_soft"], dpr)           # inset 0 0 0 .5px


def _paint_chrome(p: QPainter, rect: QRectF, path: QPainterPath,
                  st: SegPaintState, tokens: dict, dpr: float,
                  radii, rim: QColor | None = None) -> None:
    """The permanent rims a role carries in EVERY state (never geometry).

    ``rim`` (M4): an already-interpolated hairline colour to use instead of
    the state-resolved one — the rim rides the `ink` clock (`.btn`'s
    box-shadow transition). ``None`` == resolve from state, unchanged.
    """
    def mk(r):
        return _rounded_path(r, radii)

    if st.role is Role.SOLO:                              # .btn.solo :270
        inset_hairline(p, rect, mk,
                       tokens["hair"] if rim is None else rim, dpr)
        p.save()
        p.setClipPath(path)
        lw, ink = hairline_ink(tokens["gloss"], dpr)
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), lw), ink)
        p.restore()
    elif st.role is Role.MOD:
        if rim is not None:
            inset_hairline(p, rect, mk, rim, dpr)
        elif st.lit:
            # The mockup's DOUBLE rim (:368-369) is one ring inside the box
            # (gold@.55) and one OUTSIDE it (gold@.22). Only the inner one is
            # this widget's to paint: the box is fixed, and the golden shows
            # nothing on the capsule's second row — a stand-in ring painted
            # one row further in reads as a visible gold outline the design
            # never had. The outer ring belongs to whatever paints the tray.
            inset_hairline(p, rect, mk, tokens["mod_rim_on"], dpr)
        else:                                                      # :361
            inset_hairline(p, rect, mk, tokens["hair"], dpr)


def paint_segment_button(p: QPainter, rect: QRectF, st: SegPaintState,
                         tokens: dict, m: BarMetrics, dpr: float,
                         motion: SegMotion | None = None) -> None:
    """Paint one segment (any Role) into ``rect`` (the widget's own rect).

    Layout inside the box mirrors the mockup's flex line exactly: the
    (icon, gap, label) group is CENTRED (``justify-content:center``), which is
    what makes a short label variant swap in without anything moving.

    ``motion=None`` means RESTING, and the resting path below is byte-for-byte
    the M3 render — 64 committed goldens and the CP-2/CP-3 captures depend on
    it, and preview_controls.py calls this positionally (Dm4-6). In-flight
    interpolation lands in Wave B+.
    """
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)

    radii = _corner_radii(st.pos, st.role, rect, m)
    path = _rounded_path(rect, radii)
    fs = m.fs

    # --- M4 (Dm4-3/6): which clocks are in flight. motion=None (or all
    # clocks settled) is RESTING and every branch below reduces to the
    # certified M3 path — lerp_premul's endpoints return the exact target.
    fade_fill = (motion is not None and motion.t_fill < 1.0
                 and motion.frm_fill is not None)
    fade_ink = (motion is not None and motion.t_ink < 1.0
                and motion.frm_ink is not None)
    fade_acc = (motion is not None and motion.t_acc < 1.0
                and motion.frm_acc is not None)

    # --- 1. state fill --------------------------------------------------
    fill = _background(st, tokens)
    if fade_fill:
        fill = lerp_premul(motion.frm_fill.fill, fill, motion.t_fill)
    p.setPen(Qt.NoPen)
    sliding = (motion is not None and motion.thumb is not None
               and st.role is Role.ZOD)
    if sliding:
        # D-2 (Dm4-23/25): the TRAVELLING thumb — this child's slice of the
        # cluster-owned rect. No child paints a resting thumb mid-slide (the
        # destination would show two); the child's own state fill (a hover
        # ctl_h, if any) still paints over the passing thumb.
        pose = motion.thumb
        _paint_thumb(p, pose.rect, _rounded_path(pose.rect, pose.radii),
                     tokens, dpr, pose.radii)
        if fill is not None and fill.alphaF() > 0.0:
            p.fillPath(path, fill)
    elif st.lit and st.role is Role.ZOD:
        _paint_thumb(p, rect, path, tokens, dpr, radii)
    elif fill is not None and (not fade_fill or fill.alphaF() > 0.0):
        p.fillPath(path, fill)

    # --- 2. permanent rims (rim colour rides the `ink` clock) ------------
    rim_mix = None
    if fade_ink and st.role in (Role.SOLO, Role.MOD):
        if st.role is Role.SOLO:
            rim_target = tokens["hair"]
        else:
            rim_target = tokens["mod_rim_on"] if st.lit else tokens["hair"]
        rim_mix = lerp_premul(motion.frm_ink.rim, rim_target, motion.t_ink)
    _paint_chrome(p, rect, path, st, tokens, dpr, radii, rim=rim_mix)

    # --- 3. the accent hairline (always reserved, :283-287) --------------
    # HEIGHT, RADIUS and GLOW are FIXED-px in the CSS (`height:1.5px`,
    # `border-radius:2px`, `box-shadow:0 0 6px` — no var(--fs) factor,
    # unlike the 7px*fs / 3px*fs insets). Scaling them by fs painted a
    # 3-device-row bar at fs 1.5 that the golden renders as one row —
    # caught by the fidelity gate's entity census (M2 delta5).
    # Rasterisation, measured on the goldens: exactly ONE saturated row
    # at DPR 1 at every fs (the row under NORTH is full-strength green,
    # its neighbours glow only). So the painted height is
    # floor(1.5*dpr) device rows anchored at the SNAPPED BOTTOM EDGE.
    # Do not snap the two edges independently: at the fs 1.5 phase that
    # expands the half-covered top row into a full second row the
    # mockup never shows.
    acc_bot = snap_edge(rect.bottom() - m.acc_bottom, dpr)
    acc_top = acc_bot - max(1, int(_ACC_H * dpr)) / dpr
    acc = QRectF(rect.left() + m.acc_inset, acc_top,
                 rect.width() - 2 * m.acc_inset, acc_bot - acc_top)
    colors = _accent(st, tokens)
    if fade_acc:
        # 180 ms clock (Dm4-20/21): both endpoints may be None (transparent);
        # the glow interpolates as an alpha ramp on the token, never radius.
        tb, tg = colors if colors is not None else (None, None)
        bar_mix = lerp_premul(motion.frm_acc.acc, tb, motion.t_acc)
        glow_mix = lerp_premul(motion.frm_acc.acc_glow, tg, motion.t_acc)
        colors = ((bar_mix, glow_mix if glow_mix.alphaF() > 0.0 else None)
                  if bar_mix.alphaF() > 0.0 or glow_mix.alphaF() > 0.0
                  else None)
    if colors is not None and acc.width() > 0:
        bar_c, glow_c = colors
        r = min(_ACC_R, acc.height() / 2.0)

        def acc_path(rr):
            return _rounded_path(rr, (r, r, r, r))

        if glow_c is not None:
            _glow(p, acc_path, acc, glow_c, 6.0)
        p.setPen(Qt.NoPen)
        p.fillPath(acc_path(acc), bar_c)

    # --- 4. content: icon + label ---------------------------------------
    fg_target = _foreground(st, tokens)
    fg = fg_target
    if fade_ink:
        fg = lerp_premul(motion.frm_ink.fg, fg_target, motion.t_ink)
    p.save()
    if not st.enabled:
        p.setOpacity(_DISABLED_ALPHA)                              # D-12

    icon_w = float(m.icon) if st.icon else 0.0
    gap = float(m.ico_gap) if (st.icon and st.label) else 0.0
    if st.gold_plus and st.label.startswith("+"):
        text_w = (text_advance("+", *PLUS_TEXT, fs=fs)
                  + text_advance(st.label[1:], *BTN_TEXT, fs=fs))
    else:
        text_w = text_advance(st.label, *BTN_TEXT, fs=fs) if st.label else 0.0

    # THE LABEL SLOT, not the label. The box was measured from the WIDEST
    # variant and the mockup stacks the variants in one grid cell
    # (``.swap > span[hidden]{visibility:hidden}`` — hidden, not removed), so
    # the reserved label width still occupies the box and the drawn variant
    # centres inside it. Swapping TRANSIT <-> OVERLAY therefore moves nothing,
    # including the icon. Deriving the slot from the box rather than from a
    # state field keeps that promise with no new plumbing: the box IS
    # 2*pad + icon + gap + widest-label by construction (INV-1).
    if st.label:
        x = rect.left() + m.btn_pad_x
        slot_w = max(text_w, rect.width() - 2 * m.btn_pad_x - icon_w - gap)
        text_x = x + icon_w + gap + (slot_w - text_w) / 2.0
    else:                       # icon-only (the overflow capsule): centred
        x = rect.left() + (rect.width() - icon_w) / 2.0
        text_x = x

    if st.icon:
        slot = QRectF(x, rect.top() + (rect.height() - icon_w) / 2.0
                      + _ICO_NUDGE * fs, icon_w, icon_w)
        ico_c = _icon_color(st, tokens, fg_target)
        ico_op = _icon_opacity(st)
        if fade_ink:
            # Dm4-19: the ICON colour clock is quantised to 8 steps (t==1
            # stays exact) so the pixmap cache sees <=9 inks per transition;
            # opacity goes through p.setOpacity and needs no quantise.
            t_q = round(motion.t_ink * 8) / 8.0
            ico_c = lerp_premul(motion.frm_ink.ico, ico_c, t_q)
            ico_op = (motion.frm_ink.ico_opacity
                      + (ico_op - motion.frm_ink.ico_opacity) * motion.t_ink)
        _draw_icon(p, st.icon, slot, ico_c, ico_op, dpr)
    x = text_x

    if st.label:
        flags = int(Qt.AlignLeft | Qt.AlignVCenter)
        base = css_baseline(rect.height(), fs)     # ONE baseline for all runs
        # A14 (Dm4-39): during a variant swap only the INCOMING label draws,
        # at t_label opacity — st.label already IS the incoming variant, and
        # the outgoing one is simply never painted (no crossfade).
        if motion is not None and motion.t_label < 1.0:
            p.save()
            p.setOpacity(p.opacity() * max(0.0, motion.t_label))
            _label_restore = True
        else:
            _label_restore = False
        if st.gold_plus and st.label.startswith("+"):
            # <span class="plus">+</span> TROPICAL — two inline runs on one
            # baseline, the first at weight 660 in gold (:362 / :371).
            plus_c = tokens["gold_hi"] if st.lit else tokens["gold"]
            if fade_ink and motion.frm_ink.plus is not None:
                plus_c = lerp_premul(motion.frm_ink.plus, plus_c,
                                     motion.t_ink)     # Dm4-18: ink clock
            plus_w = text_advance("+", *PLUS_TEXT, fs=fs)
            p.setPen(plus_c)
            draw_bar_text(p, _text_rect(rect, x, plus_w, base, PLUS_TEXT, fs),
                          flags, "+", *PLUS_TEXT, fs=fs)
            p.setPen(fg)
            draw_bar_text(p, _text_rect(rect, x + plus_w, text_w - plus_w,
                                        base, BTN_TEXT, fs),
                          flags, st.label[1:], *BTN_TEXT, fs=fs)
        else:
            p.setPen(fg)
            draw_bar_text(p, _text_rect(rect, x, text_w, base, BTN_TEXT, fs),
                          flags, st.label, *BTN_TEXT, fs=fs)
        if _label_restore:
            p.restore()
    p.restore()

    # --- 5. the live dot (.live :306-313) --------------------------------
    if st.live_dot:
        d = float(m.live_d)
        dot = QRectF(rect.right() - m.live_off - d, rect.top() + m.live_off,
                     d, d)

        def dot_path(rr):
            r = min(rr.width(), rr.height()) / 2.0
            return _rounded_path(rr, (r, r, r, r))

        p.save()
        # D-21f: the dot itself is static (opacity 1), so motion.dot is the
        # identity here and the only live factor is the disabled dim — a
        # greyed bar still greys its NOW dot. motion=None keeps it untouched.
        dot_op = ((_DISABLED_ALPHA if not st.enabled else 1.0)
                  * (motion.dot if motion is not None else 1.0))
        if dot_op < 1.0:
            p.setOpacity(dot_op)
        _glow(p, dot_path, dot, tokens["live_glow"], 5.0 * fs)
        p.setPen(Qt.NoPen)
        p.setBrush(tokens["green"])
        p.drawEllipse(dot)
        p.restore()

    # --- 6. drop-target affordance (SPEC-TRN-006, report 02 §1 row 7) ----
    # Runtime-only state with no mockup counterpart (golden captures never
    # set it): a dashed accent ring INSIDE the box, so the fixed geometry is
    # untouched — the legacy stylesheet swap is replaced by paint.
    if st.drop_hover:
        ring_w = 1.5 * fs
        inset = ring_w / 2.0 + 0.5
        rr = rect.adjusted(inset, inset, -inset, -inset)
        pen = QPen(tokens["green"], ring_w)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([3.0, 2.5])          # in pen-width units
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        r_in = [max(0.0, r - inset) for r in radii]
        p.drawPath(_rounded_path(rr, tuple(r_in)))


# ===========================================================================
# the close glyph (.xbtn :409-418)
# ===========================================================================

def paint_close_button(p: QPainter, rect: QRectF, hovered: float,
                       pressed: float, tokens: dict, m: BarMetrics,
                       dpr: float) -> None:
    """The 18x18 circular close glyph (.xbtn).

    ``background:var(--ctl-h)`` idle; ``--red`` on hover with a 0.5px red rim
    and a white glyph; ``--red-press`` while held. The X is a PATH, not a "x"
    character: a font glyph would change shape with the UI font and would not
    hold a 1.7-unit stroke at 8px.

    M4 (Dm4-42): ``hovered``/``pressed`` are clock positions 0..1 on one
    160 ms `ease` clock (bool callers still work — endpoints are exact).
    """
    p.setRenderHint(QPainter.Antialiasing, True)

    h, pr = float(hovered), float(pressed)
    fill = lerp_premul(lerp_premul(tokens["ctl_h"], tokens["red"], h),
                       tokens["red_press"], pr)            # :413/:415/:417
    p.setPen(Qt.NoPen)
    p.setBrush(fill)
    p.drawEllipse(rect)

    hot = max(h, pr)
    # box-shadow:0 0 0 .5px red@.60 (:415) is OUTSET — outside this widget's
    # box, so TitleWell paints it (close_hover_rim below); nothing here.

    fg = lerp_premul(tokens["secondary_text"], tokens["fg_on_accent"], hot)
    # .xbtn svg{width:8px;height:8px} on a 10-unit viewBox: the mockup's
    # stroke-width 1.7 with round caps, spanning 1.6..8.4 of the viewBox.
    side = 8.0 * m.fs
    cx, cy = rect.center().x(), rect.center().y()
    arm = side * (8.4 - 1.6) / 10.0 / 2.0
    pen = QPen(fg)
    pen.setWidthF(max(1.0 / dpr, 1.7 / 10.0 * side))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(cx - arm, cy - arm), QPointF(cx + arm, cy + arm))
    p.drawLine(QPointF(cx + arm, cy - arm), QPointF(cx - arm, cy + arm))


def close_hover_rim(p: QPainter, rect: QRectF, hot: float, tokens: dict,
                    dpr: float) -> None:
    """The .xbtn hover/press rim — ``box-shadow:0 0 0 .5px`` red@.60 (:415),
    an OUTSET ring. Painted by the WELL over its own pixels because the ring
    lies outside the close button's box; ``rect`` is the button's geometry
    in the well's coordinates."""
    if hot <= 0.0:
        return
    def circle(rr):
        r = min(rr.width(), rr.height()) / 2.0
        return _rounded_path(rr, (r, r, r, r))
    outset_hairline(p, rect, circle,
                    lerp_premul(None, tokens["close_rim_h"], hot), dpr)
