"""SPEC-BAR-001 action bar v2 — shared types, fonts, and per-control metrics.

Everything geometric derives from ONE place (INV-3): `ControlMetrics.measure`
computes each control's fixed box from the metrics constants below and real
QFontMetrics on the real fonts. No widget invents a size; no state variable
ever enters the geometry path (INV-1 structural form).

Sizing model (mockup ``vibrancy_segmented.html``, all logical px at fs 1.0):
bar 40, controls 26, tray 30 (2px padding), radius 6 (tray 8), btn padding
0 10, icon 13, icon-label gap 5, track side padding 9, track gap 8, group gap
6, seg internal spacing 0. Fonts: buttons 11.5px wght 530 tracking +2.8%
UPPERCASE; name 12.5px wght 590 tracking -0.8%; meta 10.5px wght 490 tracking
+2.2%.

FRACTIONAL PIXEL SIZES — THE SCALE TRICK (load-bearing, measured):
``QFont.setPixelSize`` is integer-only, and a fractional ``setPointSizeF``
does NOT help — Qt's raster engine rounds the resulting ppem to an integer
(measured: pointSizeF 8.625 at 96dpi == pixelSize 12, advances identical),
inflating every 11.5px label ~4% and failing the fidelity gate's anchored-x
tolerances once accumulated across a cluster. The fix: build the font at an
INTEGER multiple k of the target size (11.5 x 2 = 23px, exact) and draw under
``painter.scale(1/k)``; glyph advances then scale linearly to the true
fractional size. Measured parity: "ADITYA CIRCLE" @11.5px wght 530 with
+0.028em tracking = 90.95px vs Chromium's 90.94px in the goldens. ALL bar
text — painting AND measurement — must go through ``draw_bar_text`` /
``text_advance``; a bare ``painter.drawText`` with a widget font reintroduces
the 4% drift silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication

from ui.font_bootstrap import bar_font


class Role(Enum):
    """Which checked-identity family a segment paints (mockup .btn classes)."""
    PLAIN = "plain"            # KALA / INFO / NOW
    TINT_BLUE = "tint_blue"    # TRANSIT / BIRTH TIME / HUMAN DESIGN
    TINT_GREEN = "tint_green"  # NORTH (chart style)
    TINT_GOLD = "tint_gold"    # CARDS (D-23(d)) — mirrors TINT_GREEN in gold;
    #                            NOT MOD (no capsule geometry, keeps the accent)
    PRIMARY = "primary"        # ADD CHART (label at primary_action)
    ZOD = "zod"                # zodiac segments (gold accents, thumb when lit)
    MOD = "mod"                # + TROPICAL capsule (gold tint, radius=h/2)
    SOLO = "solo"              # overflow "..." (icon-only, all corners round)


class SegPos(Enum):
    FIRST = "first"
    MID = "mid"
    LAST = "last"
    SOLO = "solo"


# ---------------------------------------------------------------------------
# fonts
# ---------------------------------------------------------------------------

def _logical_dpi() -> float:
    screen = QGuiApplication.primaryScreen()
    return float(screen.logicalDotsPerInch()) if screen is not None else 96.0


def _scale_multiplier(px: float) -> int:
    """Smallest k in 2..8 whose k*px lands nearest an integer pixel size."""
    best_k, best_err = 2, abs(px * 2 - round(px * 2))
    for k in range(2, 9):
        err = abs(px * k - round(px * k))
        if err < best_err - 1e-9:
            best_k, best_err = k, err
        if best_err < 1e-9:
            break
    return best_k


def scaled_font(px_size: float, weight: float, tracking_em: float,
                fs: float = 1.0) -> tuple[QFont, float]:
    """(font built at k x the target size, k) for the scale trick.

    ``tracking_em`` is the mockup's CSS ``letter-spacing`` in em; CSS adds
    ``em * font-size`` px per glyph, so the k-scaled font carries
    ``tracking_em * px * fs * k`` of ABSOLUTE spacing (divides back to the
    true value under the painter scale).
    """
    px = px_size * fs
    k = _scale_multiplier(px)
    font = bar_font(max(1, round(px * k)), weight)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,
                          tracking_em * px * k)
    # Grayscale AA only: the goldens render with --disable-lcd-text, and a
    # subpixel-AA'd capture tints text ink (measured #F6FCF3 vs #FEFEFE at
    # the gate's name-ink probe).
    font.setStyleStrategy(QFont.StyleStrategy.NoSubpixelAntialias)
    return font, float(k)


def text_advance(text: str, px_size: float, weight: float,
                 tracking_em: float, fs: float = 1.0) -> float:
    """True fractional-pixel advance — THE sizing primitive (INV-3)."""
    font, k = scaled_font(px_size, weight, tracking_em, fs)
    return QFontMetricsF(font).horizontalAdvance(text) / k


def draw_bar_text(p, rect, flags, text: str, px_size: float, weight: float,
                  tracking_em: float, fs: float = 1.0) -> None:
    """Draw ``text`` at the true fractional pixel size via the scale trick.

    ``rect`` is in the painter's CURRENT coordinates; pen color is the
    caller's. Import QRectF locally to keep this module Qt-light at import.
    """
    from PySide6.QtCore import QRectF
    font, k = scaled_font(px_size, weight, tracking_em, fs)
    p.save()
    p.scale(1.0 / k, 1.0 / k)
    p.setFont(font)
    p.drawText(QRectF(rect.x() * k, rect.y() * k,
                      rect.width() * k, rect.height() * k), flags, text)
    p.restore()


# Widget-level fonts (tooltips, QFontMetrics fallbacks). Rendering and
# measurement do NOT use these — they carry the integer-ppem rounding.
def button_font(fs: float = 1.0) -> QFont:
    g = bar_font(round(11.5 * fs), 530)
    g.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.028 * 11.5 * fs)
    return g


def name_font(fs: float = 1.0) -> QFont:
    g = bar_font(round(12.5 * fs), 590)
    g.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.008 * 12.5 * fs)
    return g


def meta_font(fs: float = 1.0) -> QFont:
    g = bar_font(round(10.5 * fs), 490)
    g.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.022 * 10.5 * fs)
    return g


# CSS text style constants (px, weight, tracking-em) — single naming point.
BTN_TEXT = (11.5, 530, 0.028)
NAME_TEXT = (12.5, 590, -0.008)
META_TEXT = (10.5, 490, 0.022)
PLUS_TEXT = (11.5, 660, 0.028)     # the mod capsule's gold "+" run


def effective_bar_fs(fs: float) -> float:
    """Fold the bar's font scale with the ``action_buttons`` font-area ratio, so
    the action bar answers the Font Sizes > action_buttons control the way its
    shared-button siblings already do (td-l0jfa). Every logical dimension is
    ``round(N * fs)`` and every text px is ``N * fs``, so a larger ratio grows
    the bar AND its text together (no clipping). At the default area base the
    ratio is EXACTLY 1.0, so the default live bar -- and every SPEC-BAR-001
    golden, which builds ``BarMetrics(fs=...)`` directly and bypasses this -- is
    pixel-identical. Applied only at the two app build sites, never inside
    BarMetrics/scaled_font, to keep the golden path pure. The per-area ratio is
    computed inline from qt_theme's exported base/default (qt_theme's own module
    line ceiling is ratcheted, so no helper is added there)."""
    from ui.qt_theme import get_area_font_size, AREA_DEFAULTS
    default = AREA_DEFAULTS.get("action_buttons") or 12
    return fs * (get_area_font_size("action_buttons") / default)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BarMetrics:
    """Every logical dimension of the bar at a given font scale (INV-3).

    ROUNDING POLICY (M1 controls delivery, measured): dimensions consumed by
    PAINTERS stay FLOAT — CSS lays out pad 12.5 / icon 16.25 / gap 6.25 at
    fs 1.25, and rounding each one individually put every box 1-2px narrow
    and all content ~0.75-1px left of its golden (that shift WAS the fs125
    delta). Only Qt-facing values round: widget fixed sizes (setFixedSize is
    int) and layout margins/spacings. Box widths round ONCE, on the final sum
    (`button_width`).
    """
    fs: float = 1.0

    # -- Qt-facing (int: setFixedSize / layout margins / spacing) ----------
    @property
    def bar_h(self): return round(40 * self.fs)
    @property
    def ctl_h(self): return round(26 * self.fs)
    @property
    def tray_h(self): return round(30 * self.fs)
    @property
    def tray_pad(self): return round(2 * self.fs)
    @property
    def side_pad(self): return round(9 * self.fs)
    @property
    def track_gap(self): return round(8 * self.fs)
    @property
    def grp_gap(self): return round(6 * self.fs)
    @property
    def grp_margin(self): return round(2 * self.fs)
    @property
    def sep_h(self): return round(17 * self.fs)
    @property
    def modsplit_h(self): return round(15 * self.fs)
    @property
    def close_d(self): return round(18 * self.fs)
    @property
    def title_min_w(self): return round(158 * self.fs)
    # title_max_w (560*fs) removed under D-1 rev2: the well has no width cap —
    # it absorbs all surplus so the clusters always hug the bar ends.
    @property
    def title_pad_l(self): return round(7 * self.fs)
    @property
    def title_pad_r(self): return round(4 * self.fs)
    @property
    def title_gap(self): return round(7 * self.fs)

    # -- painter-facing (float: fractional CSS lengths survive) -----------
    @property
    def radius(self): return 6 * self.fs
    @property
    def tray_radius(self): return 8 * self.fs
    @property
    def btn_pad_x(self): return 10 * self.fs
    @property
    def icon(self): return 13 * self.fs
    @property
    def ico_gap(self): return 5 * self.fs
    @property
    def acc_inset(self): return 7 * self.fs
    @property
    def acc_bottom(self): return 3 * self.fs
    @property
    def live_d(self): return 4 * self.fs
    @property
    def live_off(self): return 4 * self.fs
    @property
    def stripe_w(self): return 3 * self.fs
    @property
    def stripe_h(self): return 14 * self.fs

    def button_width(self, labels: list[str], with_icon: bool = True,
                     pad_x: int | None = None) -> int:
        """Fixed width = max over label variants (constant box, INV-1).

        Uses `text_advance` (the scale-trick primitive) — the widget font's
        integer-ppem advances are ~4% wide and MUST NOT size anything.
        """
        text_w = max((text_advance(lbl, *BTN_TEXT, fs=self.fs)
                      for lbl in labels), default=0.0)
        w = 2 * (self.btn_pad_x if pad_x is None else pad_x) + text_w
        if with_icon:
            w += self.icon + (self.ico_gap if labels and any(labels) else 0)
        return round(w)


@dataclass
class SegSpec:
    """Construction-time description of one segment button."""
    key: str
    labels: list[str]                 # all variants sharing the box (max wins)
    icon: str = ""                    # icon id ("transit", "dhata", ...)
    role: Role = Role.PLAIN
    tooltip: str = ""
    checkable: bool = False
    live_dot: bool = False
    gold_plus: bool = False           # the mod capsule's gold "+" text run
    # D-24: the glyph names the NAME SET. ``alt_icon`` replaces ``icon`` while
    # the lit segment is in its non-native naming state; ``name_sets`` =
    # (native, alternate) wording for the lit cell's tooltip token.
    alt_icon: str = ""
    name_sets: tuple = ()
    # D-5 dual role: the tooltip base the classic cell uses while it stands
    # in as SIDEREAL (its click and Alt+S both land on sidereal then).
    dual_tooltip: str = ""


@dataclass
class SegPaintState:
    """Everything paint_controls needs to draw one segment; read-only there.

    ``lit`` is the VISUAL checked state (mockup ``.on``): for controls whose
    old-bar widget is not checkable (INV-5), state observers drive `lit`
    without touching Qt's checked bookkeeping. Setters call update() ONLY
    (M0 spike: repaint is layout-silent, updateGeometry is not).
    """
    role: Role = Role.PLAIN
    pos: SegPos = SegPos.MID
    lit: bool = False
    hovered: bool = False
    pressed: bool = False
    focused: bool = False
    enabled: bool = True
    label: str = ""                   # the CURRENT variant to draw
    icon: str = ""
    live_dot: bool = False
    gold_plus: bool = False
    drop_hover: bool = False          # TransitDropButton dashed ring (M3)
    alt_names: bool = False           # Dm3-17: `*` accent recolor (paint-only)


# ---------------------------------------------------------------------------
# M4 motion types (16_opus_m4_motion.md Dm4-3/6/23) — pure data, no Qt logic
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SegInk:
    """The RESOLVED appearance of one segment — what is on screen, as RGBA.

    Frozen snapshots of this are what a fade interpolates FROM (Dm4-3); the
    target ink is re-resolved from live tokens at paint time (Dm4-7).
    ``None`` fill == "container shows through" (mockup: transparent).
    """
    fill: QColor | None
    fg: QColor
    ico: QColor
    ico_opacity: float
    acc: QColor | None
    acc_glow: QColor | None
    rim: QColor | None        # _paint_chrome's inset hairline colour (SOLO/MOD)
    plus: QColor | None       # the mod capsule's gold "+" run


@dataclass(frozen=True)
class ThumbPose:
    """The travelling zodiac thumb, mid-slide (§3.3 Option B)."""
    rect: QRectF                                   # in CLUSTER coordinates
    radii: tuple[float, float, float, float]


@dataclass(frozen=True)
class SegMotion:
    """In-flight motion for one segment, passed to paint_segment_button as
    ``motion=``. ``None`` motion == resting == the byte-identical M3 path
    (Dm4-6). Three snapshots because the three groups can sit at three
    different points on three different clocks after a rapid retarget.
    """
    frm_fill: SegInk | None = None   # snapshot for the `fill` group
    frm_ink: SegInk | None = None    # snapshot for the `ink` group
    frm_acc: SegInk | None = None    # snapshot for the `acc` group
    t_fill: float = 1.0
    t_ink: float = 1.0
    t_acc: float = 1.0
    label_in: str = ""               # the incoming label variant (A14)
    t_label: float = 1.0
    dot: float = 1.0                 # live-dot opacity; static 1.0, only the
                                     #   disabled-dim path drives it below 1
    thumb: ThumbPose | None = None   # travelling zodiac thumb (§3.3)
