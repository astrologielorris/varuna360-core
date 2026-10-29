# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Glance Chart (SPEC-FIND-007): a fast South Indian mini chart for the
Find Chart inspector, one painted widget.

Reads only ``facts.ChartFacts.glance`` / ``sign_labels`` and a
``facts.Centre`` (INV-1). Layout runs when data, size, theme or fonts
change (``_relayout``) and produces a paint plan; ``paintEvent`` only runs
the plan (INV-3). Glyphs come from the app's planet icon path
(``planet_icon_style.selected_pack`` / ``passes_for`` ->
``planet_svg_provider.renderers_for`` + ``paint_renderers``; the artistic
set uses the main chart's images), rendered once per (body, size, dpr,
``appearance_signature()``) into a cached QPixmap and blitted.

The centre is the Seal Frame V1 design (§2.2): a rounded frame in the
category accent whose corner curves stay visible, a short category tab,
the emblem large and faint bottom right, the glyph inline with the value
as hero, a sub line, never clipped from 240 to 480 px.

Category accents: ``ACCENTS`` below is the one place they are defined
(light, dark); never red (retrograde).
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from apps.widgets.action_bar.bar_types import draw_bar_text, text_advance
from core.chart_search import facts
from panels.find_chart import kit

#: (row, col) -> 0-based sign index; the main chart's layout, kept local so
#: the widget never imports the heavy SouthIndianView (INV-2). Parity with
#: ``chart_view.SouthIndianView.ZODIAC_POSITIONS`` is tested.
ZODIAC_POSITIONS = {
    (0, 0): 11, (0, 1): 0, (0, 2): 1, (0, 3): 2,
    (1, 0): 10, (2, 0): 9,
    (1, 3): 3, (2, 3): 4,
    (3, 0): 8, (3, 1): 7, (3, 2): 6, (3, 3): 5,
}
CELL_OF_SIGN = {index: cell for cell, index in ZODIAC_POSITIONS.items()}

MAX_SIDE = 480
GLYPH_FLOOR = 10.0
NO_RETRO = frozenset({"Rahu", "Ketu"})
TOOLTIP = "Open this chart"
#: Mockup reference width: every size below is at a 308 px chart.
REF = 308.0

#: Category accent colours, (light theme, dark theme) (§2.1, Seal Frame).
ACCENTS: dict[str, tuple[str, str]] = {
    facts.SIGN: ("#2f6dbd", "#79aef0"),
    facts.HOUSE: ("#16857a", "#5fcfc0"),
    facts.CUSP: ("#b35a22", "#eda070"),
    facts.MOTION: ("#6d47b8", "#b39cf0"),
    facts.NAKSHATRA: ("#a2367f", "#e88cc8"),
    facts.DIGNITY: ("#33813a", "#86cf8a"),
    facts.AVASTHA: ("#c2661a", "#f0a861"),
    facts.SHAYANADI: ("#1f7fa6", "#6cc4e8"),
    facts.RETINUE: ("#6f7a1c", "#c3cf6a"),
    facts.HUMAN_DESIGN: ("#b83a62", "#f08aa9"),
    facts.CARDS: ("#4a5a70", "#a9bad2"),
}
#: Tab ink on the accent, and the red-suit ink of a playing card.
ON_ACCENT = ("#ffffff", "#1f2326")
CARD_RED = ("#c62828", "#ef6b6b")

BADGES = {
    facts.SIGN: "SIGN", facts.HOUSE: "HOUSE", facts.CUSP: "CUSP", facts.MOTION: "MOTION",
    facts.NAKSHATRA: "NAKSHATRA", facts.DIGNITY: "DIGNITY", facts.AVASTHA: "AVASTHA",
    facts.SHAYANADI: "SHAYANADI", facts.RETINUE: "RETINUE",
    facts.HUMAN_DESIGN: "HUMAN DESIGN", facts.CARDS: "CARDS OF TRUTH",
}
STATE_TEXT = {
    facts.NOT_COMPUTED: "Not computed",
    facts.CENTRE_FAILED: "Could not be computed",
    facts.NOT_FOUND: "Not stored",
}

ARTISTIC_DIR = Path(__file__).resolve().parents[2] / "img" / "planets"
#: The main chart's artistic file names (chart_view.PLANET_ICON_NAMES).
ARTISTIC_NAMES = {
    "Sun": "sun", "Moon": "moon", "Mars": "Mars", "Mercury": "Mercury",
    "Jupiter": "Jupiter", "Venus": "Venus", "Saturn": "Saturn", "Rahu": "rahu",
    "Ketu": "ketu", "Uranus": "uranus", "Neptune": "neptune", "Pluto": "pluto",
}
SHORT = {"Earth": "⊕"}


def _light() -> bool:
    try:
        from ui.qt_theme import is_light_theme
        return bool(is_light_theme())
    except Exception:  # noqa: BLE001
        return True


def accent(category: str, light: bool | None = None) -> QColor:
    pair = ACCENTS.get(category, ACCENTS[facts.SIGN])
    return QColor(pair[0 if (_light() if light is None else light) else 1])


# ------------------------------------------------------------------ emblems


def _stroked(path: QPainterPath, width: float) -> QPainterPath:
    from PySide6.QtGui import QPainterPathStroker
    stroker = QPainterPathStroker()
    stroker.setWidth(width)
    return stroker.createStroke(path)


def _emblem(category: str) -> tuple[QPainterPath, bool]:
    """The category emblem in a 16x16 box: (path, filled)."""
    p = QPainterPath()
    if category == facts.SIGN:
        p.moveTo(2, 14); p.lineTo(14, 14); p.quadTo(14, 10, 12.4, 8); p.closeSubpath()  # noqa: E702
        return p, True
    if category == facts.HOUSE:
        p.moveTo(2, 8); p.lineTo(8, 2.5); p.lineTo(14, 8)  # noqa: E702
        p.moveTo(4, 7); p.lineTo(4, 14); p.lineTo(12, 14); p.lineTo(12, 7)  # noqa: E702
        return p, False
    if category == facts.CUSP:
        p.moveTo(1, 12); p.lineTo(15, 12); p.moveTo(8, 10); p.lineTo(8, 3)  # noqa: E702
        p.moveTo(5, 6); p.lineTo(8, 3); p.lineTo(11, 6)  # noqa: E702
        return p, False
    if category == facts.MOTION:
        p.moveTo(13, 9); p.arcTo(QRectF(3, 4, 10, 10), 0, 270); p.lineTo(11, 4)  # noqa: E702
        p.moveTo(9, 1.5); p.lineTo(11.5, 4); p.lineTo(9, 6.5)  # noqa: E702
        return p, False
    if category == facts.NAKSHATRA:
        pts = [(8, 1), (9.6, 6.4), (15, 8), (9.6, 9.6), (8, 15), (6.4, 9.6), (1, 8), (6.4, 6.4)]
        p.moveTo(*pts[0])
        for pt in pts[1:]:
            p.lineTo(*pt)
        p.closeSubpath()
        return p, True
    if category == facts.DIGNITY:
        p.moveTo(3, 8); p.lineTo(8, 4); p.lineTo(13, 8)  # noqa: E702
        p.moveTo(3, 12.5); p.lineTo(8, 8.5); p.lineTo(13, 12.5)  # noqa: E702
        return p, False
    if category == facts.AVASTHA:
        ring = QPainterPath()
        ring.addEllipse(QRectF(2, 2, 12, 12))
        p.moveTo(8, 2); p.arcTo(QRectF(2, 2, 12, 12), 90, -180); p.closeSubpath()  # noqa: E702
        return _stroked(ring, 1.6).united(p), True
    if category == facts.SHAYANADI:
        p.moveTo(1, 8); p.quadTo(8, 1, 15, 8); p.quadTo(8, 15, 1, 8)  # noqa: E702
        pupil = QPainterPath()
        pupil.addEllipse(QPointF(8, 8), 2.3, 2.3)
        return _stroked(p, 1.6).united(pupil), True
    if category == facts.RETINUE:
        for x, y in ((8, 4), (3.5, 11.5), (12.5, 11.5)):
            p.addEllipse(QPointF(x, y), 2.3, 2.3)
        return p, True
    if category == facts.HUMAN_DESIGN:
        for poly in (((8, .5), (10, 3), (6, 3)), ((6, 3.8), (10, 3.8), (8, 6.3)),
                     ((8, 9.6), (9.8, 11), (8, 12.4), (6.2, 11)),
                     ((1, 9.5), (4.5, 11.2), (1, 13)), ((15, 9.5), (11.5, 11.2), (15, 13))):
            p.moveTo(*poly[0])
            for pt in poly[1:]:
                p.lineTo(*pt)
            p.closeSubpath()
        p.addRect(QRectF(6.2, 6.8, 3.6, 2.4))
        p.addRect(QRectF(6.2, 12.9, 3.6, 2.6))
        return p, True
    # Cards of Truth: a card outline with a spade.
    p.addRoundedRect(QRectF(3, 1.5, 10, 13), 1.6, 1.6)
    p.moveTo(8, 5); p.cubicTo(6, 7.3, 5.6, 8.3, 6.6, 9.2); p.cubicTo(7.3, 9.7, 7.8, 9.4, 8, 9)  # noqa: E702
    p.cubicTo(8.2, 9.4, 8.7, 9.7, 9.4, 9.2); p.cubicTo(10.4, 8.3, 10, 7.3, 8, 5)  # noqa: E702
    return p, False


# ------------------------------------------------------------------- glyphs

_GLYPHS: dict[tuple, QPixmap | None] = {}


def appearance() -> tuple:
    try:
        from apps.widgets.planet_icon_style import appearance_signature
        return appearance_signature()
    except Exception:  # noqa: BLE001
        return ()


def glyph_pixmap(body: str, px: int, dpr: float, signature: tuple) -> QPixmap | None:
    """The body's icon at ``px`` logical pixels, cached per palette
    signature; ``None`` when no icon exists (the caller draws a letter)."""
    key = (body, px, round(dpr, 2), signature)
    if key in _GLYPHS:
        return _GLYPHS[key]
    pix = _render_glyph(body, px, dpr)
    if len(_GLYPHS) > 512:
        _GLYPHS.clear()
    _GLYPHS[key] = pix
    return pix


def _render_glyph(body: str, px: int, dpr: float) -> QPixmap | None:
    side = max(1, round(px * dpr))
    try:
        from apps.widgets.planet_icon_style import passes_for, selected_pack
        from apps.widgets.planet_svg_provider import paint_renderers, renderers_for
        pack = selected_pack(body)
        renderers = renderers_for(pack, body, passes_for(body)) if pack else None
    except Exception:  # noqa: BLE001
        renderers = None
    if renderers:
        img = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        paint_renderers(p, QRectF(0, 0, side, side), renderers)
        p.end()
        pix = QPixmap.fromImage(img)
        pix.setDevicePixelRatio(dpr)
        return pix
    name = ARTISTIC_NAMES.get(body)
    if name is None:
        return None
    img = QImage(str(ARTISTIC_DIR / f"{name}.webp"))
    if img.isNull():
        return None
    pix = QPixmap.fromImage(img.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    pix.setDevicePixelRatio(dpr)
    return pix


# ------------------------------------------------------------------- layout


def lagna_strikes(box: QRectF) -> list[tuple]:
    """The main South Indian chart's Ascendant mark, scaled to ``box``
    (``south_indian_planets.draw_lagna_stripe``): two parallel 45° strikes
    at the card's TOP-RIGHT corner, round caps kissing the top and right
    edges, inner reach a third of the card, one stroke width of air between
    them. Always black: the main chart's pale element tint vanishes on the
    small snapshot (Lorris, 2026-10-25)."""
    color = QColor(0, 0, 0)
    w = max(2.5, box.width() * .035)
    half = w / 2
    top, right = box.top(), box.right()
    reach = box.width() / 3
    gap = 2 * w * math.sqrt(2)
    return [("line", QLineF(right - r, top + half, right - half, top + r), color, w, Qt.RoundCap)
            for r in (reach, reach - gap)]


def box_layout(n: int, area: QRectF, target: float, gap: float = 3.0):
    """INV-8: rows by count (1-3 one row, 4-6 two, 7+ three); glyph size =
    min(target, width / columns, height / rows), never below the floor.
    Returns (rects, overflow): ``overflow`` > 0 means the last rect holds
    "+overflow" instead of a glyph."""
    if n <= 0:
        return [], 0
    rows = 1 if n <= 3 else 2 if n <= 6 else 3
    cols = math.ceil(n / rows)
    size = min(target, (area.width() - (cols - 1) * gap) / cols,
               (area.height() - (rows - 1) * gap) / rows)
    shown, overflow = n, 0
    if size < GLYPH_FLOOR:
        size = GLYPH_FLOOR
        cols = max(1, int((area.width() + gap) // (size + gap)))
        rows = max(1, int((area.height() + gap) // (size + gap)))
        cap = cols * rows
        if cap < n:
            shown, overflow = cap, n - cap + 1
    size = math.floor(size)
    rects = []
    rows_used = math.ceil(shown / cols)
    total_h = rows_used * size + (rows_used - 1) * gap
    y = area.top() + (area.height() - total_h) / 2
    for r in range(rows_used):
        in_row = min(cols, shown - r * cols)
        total_w = in_row * size + (in_row - 1) * gap
        x = area.left() + (area.width() - total_w) / 2
        for _c in range(in_row):
            rects.append(QRectF(x, y, size, size))
            x += size + gap
        y += size + gap
    return rects, overflow


def fit_lines(text: str, width: float, start: float, floor: float, weight: float,
              max_lines: int = 3) -> tuple[float, list[str]]:
    """The largest size from ``start`` down to ``floor`` where ``text`` fits
    ``width`` on one line; else word-wrapped on up to ``max_lines`` at the
    largest size that fits, shrinking under the floor only as a last resort
    (never clipped, T12)."""
    px = start
    while px >= floor:
        if text_advance(text, px, weight, -0.015) <= width:
            return px, [text]
        px -= 1
    px = floor
    while px >= 6:
        lines = _wrap(text, width, px, weight)
        if lines is not None and len(lines) <= max_lines:
            return px, lines
        px -= 0.5
    return 6, [text]


def _wrap(text, width, px, weight):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if text_advance(trial, px, weight, -0.015) <= width:
            cur = trial
        elif not cur or text_advance(word, px, weight, -0.015) > width:
            return None
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


class GlanceChart(QWidget):
    """``set_labels``, ``set_chart(glance | None)``, ``set_centre(Centre |
    None)``; ``clicked`` = open the chart (INV-11)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(TOOLTIP)
        self.setAccessibleName("Glance chart")
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._labels: tuple[str, ...] = ("",) * 12
        self._glance: tuple[tuple[str, int, bool], ...] | None = None
        self._centre: facts.Centre | None = None
        self._signature = appearance()
        self._plan: list[tuple] = []
        self._dirty = True
        self.glyph_rects: dict[str, QRectF] = {}
        self.cell_rects: dict[int, QRectF] = {}
        self.strip_rects: dict[int, QRectF] = {}
        self.centre_rect = QRectF()
        self.centre_text_rects: list[QRectF] = []
        self.overflow: dict[int, tuple[QRectF, tuple[str, ...]]] = {}
        self.last_paint_ops = 0

    # ------------------------------------------------------------- data
    def set_labels(self, labels) -> None:
        labels = tuple(labels) if labels else ("",) * 12
        if labels != self._labels:
            self._labels = labels
            self._invalidate()

    def set_chart(self, glance) -> None:
        """``None`` = facts loading (the old glyphs clear at once)."""
        self._glance = tuple(glance) if glance is not None else None
        self._invalidate()

    def set_centre(self, centre: facts.Centre | None) -> None:
        if centre != self._centre:
            self._centre = centre
            self._invalidate()

    def centre(self) -> facts.Centre | None:
        return self._centre

    def refresh_theme(self) -> None:
        self._signature = appearance()
        self._invalidate()

    def refresh_metrics(self) -> None:
        self.updateGeometry()
        self._invalidate()

    def _invalidate(self) -> None:
        self._dirty = True
        self.update()

    # ------------------------------------------------------------- size
    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, w: int) -> int:  # noqa: N802
        return min(w, MAX_SIDE)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(308, 308)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(160, 160)

    def resizeEvent(self, e):  # noqa: N802
        side = min(self.width(), MAX_SIDE)
        if self.height() != side:
            self.setFixedHeight(side)
        self._dirty = True
        super().resizeEvent(e)

    # ------------------------------------------------------------ events
    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()
            return
        super().mousePressEvent(e)

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            pos = QPointF(e.pos())
            for rect, names in self.overflow.values():
                if rect.contains(pos):
                    QToolTip.showText(e.globalPos(), ", ".join(names), self)
                    return True
            QToolTip.showText(e.globalPos(), TOOLTIP, self)
            return True
        return super().event(e)

    # ------------------------------------------------------------ layout
    def _relayout(self) -> None:
        self._signature = appearance()  # the palette may have changed since
        t = kit.tokens()
        light = _light()
        side = float(min(self.width(), MAX_SIDE, self.height() or MAX_SIDE))
        x0 = (self.width() - side) / 2
        s = side / REF
        cell = side / 4
        dpr = self.devicePixelRatioF()
        plan: list[tuple] = []
        self.glyph_rects, self.cell_rects, self.strip_rects, self.overflow = {}, {}, {}, {}
        outer = QRectF(x0 + .5, .5, side - 1, side - 1)
        radius = 6 * max(s, .8)
        plan.append(("frame", outer, radius, t["ctl"], t["hair"]))
        lines = []
        for i in (1, 2, 3):
            x = x0 + i * cell
            y = i * cell
            if i == 2:
                lines += [QLineF(x, 0, x, cell), QLineF(x, 3 * cell, x, side),
                          QLineF(x0, y, x0 + cell, y), QLineF(x0 + 3 * cell, y, x0 + side, y)]
            else:
                lines += [QLineF(x, 0, x, side), QLineF(x0, y, x0 + side, y)]
        plan.append(("lines", lines, t["hair_soft"]))

        label_px = max(7.5, min(10.5, 9 * s * 1.05))
        strip_h = label_px * 1.3 + 3
        asc_sign = None
        by_sign: dict[int, list[tuple[str, bool]]] = {i: [] for i in range(12)}
        for body, index, retro in self._glance or ():
            if body == "Ascendant":
                asc_sign = index
            else:
                by_sign[index].append((body, retro and body not in NO_RETRO))
        target = 34 * s
        for index in range(12):
            r, c = CELL_OF_SIGN[index]
            box = QRectF(x0 + c * cell, r * cell, cell, cell)
            self.cell_rects[index] = box
            strip = QRectF(box.left() + 4 * s, box.top() + 2, box.width() - 8 * s, strip_h)
            self.strip_rects[index] = strip
            text = self._labels[index] if index < len(self._labels) else ""
            px = label_px
            while px > 6.5 and text_advance(text, px, 500, 0) > strip.width():
                px -= .5
            if index == asc_sign:
                plan += lagna_strikes(box)
            plan.append(("text", strip, Qt.AlignLeft | Qt.AlignVCenter, text, px, 500, 0, t["muted"]))
            bodies = by_sign[index]
            area = QRectF(box.left() + 3, strip.bottom() + 1, box.width() - 6,
                          box.bottom() - strip.bottom() - 4)
            rects, extra = box_layout(len(bodies), area, target)
            for i, rect in enumerate(rects):
                if extra and i == len(rects) - 1:
                    rest = tuple(b for b, _r in bodies[i:])
                    self.overflow[index] = (rect, rest)
                    plan.append(("text", rect, Qt.AlignCenter, f"+{extra}", max(7, rect.height() * .6),
                                 650, 0, t["primary_text"]))
                    break
                body, retro = bodies[i]
                self.glyph_rects[body] = rect
                plan.append(self._glyph_op(body, rect, dpr, t))
                if retro:
                    rp = max(6.5, rect.height() * .32)
                    rr = QRectF(rect.right() - rp * .8, rect.bottom() - rp, rp * .9, rp)
                    plan.append(("text", rr, Qt.AlignCenter, "R", rp, 760, 0, t["red"]))
        self.centre_rect = QRectF(x0 + cell, cell, 2 * cell, 2 * cell)
        plan += self._centre_plan(self.centre_rect, s, dpr, t, light)
        self._plan = plan
        self._dirty = False

    def _glyph_op(self, body, rect, dpr, t):
        pix = glyph_pixmap(body, int(rect.width()), dpr, self._signature)
        if pix is None:
            return ("text", rect, Qt.AlignCenter, SHORT.get(body, body[:2]), rect.height() * .55,
                    650, 0, t["primary_text"])
        return ("pixmap", rect.topLeft(), pix)

    def _centre_plan(self, box: QRectF, s: float, dpr: float, t: dict, light: bool) -> list:
        self.centre_text_rects = []
        c = self._centre
        if c is None:
            return []
        acc = accent(c.category, light)
        # ~7 % of the accent over the chart surface already painted (the
        # surface token may be translucent, so never blend its raw RGB).
        tint = QColor(acc)
        tint.setAlphaF(.08)
        inset = 5 * s
        frame = box.adjusted(inset, inset, -inset, -inset)
        radius = 8 * s
        ops: list[tuple] = [("cframe", frame, radius, tint, acc, max(1.5, 2 * s))]
        # watermark emblem, bottom right, faint, clipped to the frame
        em, filled = _emblem(c.category)
        wm = frame.width() * .46
        faint = QColor(acc)
        faint.setAlphaF(.14)
        ops.append(("emblem", em, filled, QRectF(frame.right() - wm + 6 * s, frame.bottom() - wm + 6 * s,
                                                 wm, wm), faint, frame, radius))
        # tab: short, stops before the corner curves
        ink = QColor(ON_ACCENT[0 if light else 1])
        tab_px = max(7.5, 9 * s)
        badge = BADGES[c.category]
        max_w = frame.width() - 2 * (radius + 4 * s)
        icon = tab_px * 1.1
        while tab_px > 6.5 and text_advance(badge, tab_px, 700, .09) + icon + 14 * s > max_w:
            tab_px -= .5
            icon = tab_px * 1.1
        tw = min(max_w, text_advance(badge, tab_px, 700, .09) + icon + 14 * s)
        th = tab_px * 1.6 + 2
        tab = QRectF(frame.center().x() - tw / 2, frame.top() - 1, tw, th)
        ops.append(("tab", tab, 8 * s, acc))
        ops.append(("emblem", em, filled, QRectF(tab.left() + 6 * s, tab.center().y() - icon / 2, icon, icon),
                    ink, None, 0))
        ops.append(("text", QRectF(tab.left() + 6 * s + icon + 3, tab.top(), tw - icon - 9 * s, th),
                    Qt.AlignLeft | Qt.AlignVCenter, badge, tab_px, 700, .09, ink))
        # body lines, top to bottom, centred in the frame below the tab
        pad = 6 * s
        inner_w = frame.width() - 2 * pad
        sub_px, who_px = max(9, 11 * s), max(8.5, 10 * s)
        rows: list[tuple] = []  # (height, builder)
        if c.category == facts.CUSP and c.cusp:
            rows.append(("small", c.cusp, who_px, t["muted"], 500))
        glyph_px = round(24 * s) if c.body and c.category != facts.CUSP else 0
        state_text = STATE_TEXT.get(c.state)
        if state_text:
            rows.append(("state", state_text, max(10, 13 * s)))
        elif c.card is not None:
            rows.append(("card", c.card))
        elif c.value:
            room = inner_w - (glyph_px + 6 * s if glyph_px else 0)
            px, lines = fit_lines(c.value, room, 28 * s, 13, 800)
            rows.append(("hero", lines, px))
        elif glyph_px:
            rows.append(("glyphonly",))
        if c.detail and not state_text:
            rows.append(("small", c.detail, sub_px, acc, 600))
        if c.matched_any and c.body and not state_text:
            rows.append(("small", f"matched: {c.body}", who_px, t["muted"], 500))

        def height(row):
            kind = row[0]
            if kind == "small":
                return row[2] * 1.3
            if kind == "state":
                return row[2] * 1.4
            if kind == "card":
                return 64 * s
            if kind == "hero":
                return max(len(row[1]) * row[2] * 1.08, glyph_px)
            return glyph_px

        total = sum(height(r) for r in rows) + 2 * max(0, len(rows) - 1)
        top_room = tab.bottom() + 2
        y = max(top_room, frame.center().y() - total / 2 + th * .3)
        for row in rows:
            h = height(row)
            kind = row[0]
            if kind == "small":
                text, px, color, weight = row[1], row[2], row[3], row[4]
                while px > 6 and text_advance(text, px, weight, 0) > inner_w:
                    px -= .5
                r = QRectF(frame.left() + pad, y, inner_w, h)
                ops.append(("text", r, Qt.AlignCenter, text, px, weight, 0, color))
                self.centre_text_rects.append(self._ink_rect(r, text, px, weight, 0))
            elif kind == "state":
                r = QRectF(frame.left() + pad, y, inner_w, h)
                ops.append(("text", r, Qt.AlignCenter, row[1], row[2], 450, 0, t["muted"]))
                self.centre_text_rects.append(self._ink_rect(r, row[1], row[2], 450, 0))
                if glyph_px:
                    pass
            elif kind == "card":
                cw, ch = 46 * s, 64 * s
                cr = QRectF(frame.center().x() - cw / 2, y, cw, ch)
                red = row[1][1] in ("♥", "♦")
                ink_c = QColor(CARD_RED[0 if light else 1]) if red else t["primary_text"]
                ops.append(("cframe", cr, 5 * s, t["secondary_light"], acc, max(1.2, 1.5 * s)))
                rank, suit = row[1]
                rp = 14 * s
                ops.append(("text", QRectF(cr.left() + 5 * s, cr.top() + 3 * s, cw, rp * 1.1),
                            Qt.AlignLeft | Qt.AlignTop, rank, rp, 700, 0, ink_c))
                ops.append(("text", cr, Qt.AlignCenter, suit, 26 * s, 700, 0, ink_c))
                ops.append(("rtext", QRectF(cr.left(), cr.bottom() - 3 * s - rp * 1.1, cw - 5 * s, rp * 1.1),
                            rank, rp, ink_c))
                self.centre_text_rects.append(cr)
            elif kind in ("hero", "glyphonly"):
                lines = row[1] if kind == "hero" else []
                px = row[2] if kind == "hero" else 0
                gate = (c.category == facts.HUMAN_DESIGN and len(lines) == 1
                        and "." in lines[0] and lines[0].replace(".", "").isdigit())
                if gate:
                    head, _dot, rest = lines[0].partition(".")
                    widths = [text_advance(head, px, 800, -0.015)
                              + text_advance("." + rest, px * .6, 650, 0)]
                else:
                    widths = [text_advance(line, px, 800, -0.015) for line in lines] or [0]
                gap = 6 * s if glyph_px and lines else 0
                block_w = glyph_px + gap + max(widths)
                x = frame.center().x() - block_w / 2
                if glyph_px:
                    g = QRectF(x, y + (h - glyph_px) / 2, glyph_px, glyph_px)
                    ops.append(self._glyph_op(c.body, g, dpr, t))
                    x += glyph_px + gap
                ly = y + (h - len(lines) * px * 1.08) / 2
                for line, w in zip(lines, widths):
                    r = QRectF(x, ly, max(widths) + 2, px * 1.08)
                    if gate:  # V1: "21" as hero, ".6" smaller and muted
                        head, tail = line.split(".", 1)
                        tail = "." + tail
                        hw = text_advance(head, px, 800, -0.015)
                        ops.append(("text", QRectF(x, ly, hw + 1, px * 1.08), Qt.AlignLeft | Qt.AlignVCenter,
                                    head, px, 800, -0.015, t["primary_text"]))
                        ops.append(("text", QRectF(x + hw, ly + px * .2, w - hw + 2, px * .88),
                                    Qt.AlignLeft | Qt.AlignVCenter, tail, px * .6, 650, 0, t["muted"]))
                        self.centre_text_rects.append(QRectF(x, ly, w, px * 1.08))
                        ly += px * 1.08
                        continue
                    ops.append(("text", r, Qt.AlignCenter, line, px, 800, -0.015, t["primary_text"]))
                    self.centre_text_rects.append(QRectF(x + (max(widths) - w) / 2, ly, w, px * 1.08))
                    ly += px * 1.08
            y += h + 2
        return ops

    @staticmethod
    def _ink_rect(r: QRectF, text, px, weight, track) -> QRectF:
        w = text_advance(text, px, weight, track)
        return QRectF(r.center().x() - w / 2, r.top(), w, r.height())

    # ------------------------------------------------------------- paint
    def paint_plan(self) -> list[tuple]:
        if self._dirty:
            self._relayout()
        return self._plan

    def paintEvent(self, _e):  # noqa: N802
        plan = self.paint_plan()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for op in plan:
            kind = op[0]
            if kind == "frame":
                _k, rect, radius, fill, line = op
                p.setPen(QPen(line, 1))
                p.setBrush(fill)
                p.drawRoundedRect(rect, radius, radius)
            elif kind == "lines":
                p.setPen(QPen(op[2], 1))
                p.drawLines(op[1])
            elif kind == "line":
                pen = QPen(op[2], op[3])
                pen.setCapStyle(op[4] if len(op) > 4 else Qt.FlatCap)
                p.setPen(pen)
                p.drawLine(op[1])
            elif kind == "text":
                _k, rect, flags, text, px, weight, track, color = op
                p.setPen(color)
                draw_bar_text(p, rect, flags, text, px, weight, track)
            elif kind == "rtext":
                _k, rect, text, px, color = op
                p.save()
                p.translate(rect.center())
                p.rotate(180)
                p.setPen(color)
                draw_bar_text(p, QRectF(-rect.width() / 2, -rect.height() / 2, rect.width(),
                                        rect.height()), Qt.AlignLeft | Qt.AlignVCenter, text, px, 700, 0)
                p.restore()
            elif kind == "pixmap":
                p.drawPixmap(op[1], op[2])
            elif kind == "cframe":
                _k, rect, radius, fill, line, width = op
                p.setPen(QPen(line, width))
                p.setBrush(fill)
                hw = width / 2
                p.drawRoundedRect(rect.adjusted(hw, hw, -hw, -hw), radius, radius)
            elif kind == "tab":
                _k, rect, radius, color = op
                path = QPainterPath()
                path.moveTo(rect.topLeft())
                path.lineTo(rect.topRight())
                path.lineTo(rect.right(), rect.bottom() - radius)
                path.quadTo(rect.right(), rect.bottom(), rect.right() - radius, rect.bottom())
                path.lineTo(rect.left() + radius, rect.bottom())
                path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - radius)
                path.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawPath(path)
            elif kind == "emblem":
                _k, path, filled, rect, color, clip, radius = op
                p.save()
                if clip is not None:
                    cp = QPainterPath()
                    cp.addRoundedRect(clip, radius, radius)
                    p.setClipPath(cp)
                p.translate(rect.topLeft())
                p.scale(rect.width() / 16, rect.height() / 16)
                if filled:
                    p.setPen(Qt.NoPen)
                    p.setBrush(color)
                else:
                    pen = QPen(color, 1.8)
                    pen.setCosmetic(False)
                    p.setPen(pen)
                    p.setBrush(Qt.NoBrush)
                p.drawPath(path)
                p.restore()
        p.end()
        self.last_paint_ops = len(plan)
