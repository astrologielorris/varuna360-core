"""Chart list D-pad: four keys in a plus, like a game controller's direction pad.

LEFT / RIGHT page through the chart list; UP / DOWN go back / forward through
the charts viewed this session (core/chart_view_history). Design: the "Keycap
Cluster" mockup (mockups_nav-dpad_20261021-1810/designer_a/mockup_3.html):
a recessed plus-shaped tray, four raised keys around a read-only page pill.
The history keys carry the theme primary (glyph, faint tint, an inner accent
hairline) so the two axes read apart at a glance. States change colour only,
never geometry.

All drawing is in a fixed 85 x 58 design space, scaled to the widget size.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from ui.qt_theme import get_theme_colors, is_light_theme

DESIGN_W, DESIGN_H = 85.0, 58.0

# Key boxes in design units: (x, y, w, h) and chevron centre.
_KEYS = {
    "up": (QRectF(26.5, 1.5, 32, 17.5), QPointF(42.5, 9.6)),
    "down": (QRectF(26.5, 39, 32, 17.5), QPointF(42.5, 48.4)),
    "left": (QRectF(1.5, 20, 24, 18), QPointF(13.3, 29)),
    "right": (QRectF(59.5, 20, 24, 18), QPointF(71.7, 29)),
}
_HISTORY = ("up", "down")
_PILL = QRectF(26.5, 20, 32, 18)


def _rgba(r, g, b, a):
    return QColor(r, g, b, round(a * 255))


def _with_alpha(hex_color, a):
    c = QColor(hex_color)
    c.setAlphaF(a)
    return c


def _plus_path(W=DESIGN_W, H=DESIGN_H, X1=25.0, X2=60.0, Y1=18.5, Y2=39.5, R=8.0, r=3.0):
    """The tray: a plus with outer corners R and concave inner corners r."""
    p = QPainterPath()
    p.moveTo(X1 + R, 0)
    p.lineTo(X2 - R, 0); p.arcTo(X2 - 2 * R, 0, 2 * R, 2 * R, 90, -90)
    p.lineTo(X2, Y1 - r); p.arcTo(X2, Y1 - 2 * r, 2 * r, 2 * r, 180, 90)
    p.lineTo(W - R, Y1); p.arcTo(W - 2 * R, Y1, 2 * R, 2 * R, 90, -90)
    p.lineTo(W, Y2 - R); p.arcTo(W - 2 * R, Y2 - 2 * R, 2 * R, 2 * R, 0, -90)
    p.lineTo(X2 + r, Y2); p.arcTo(X2, Y2, 2 * r, 2 * r, 90, 90)
    p.lineTo(X2, H - R); p.arcTo(X2 - 2 * R, H - 2 * R, 2 * R, 2 * R, 0, -90)
    p.lineTo(X1 + R, H); p.arcTo(X1, H - 2 * R, 2 * R, 2 * R, 270, -90)
    p.lineTo(X1, Y2 + r); p.arcTo(X1 - 2 * r, Y2, 2 * r, 2 * r, 0, 90)
    p.lineTo(R, Y2); p.arcTo(0, Y2 - 2 * R, 2 * R, 2 * R, 270, -90)
    p.lineTo(0, Y1 + R); p.arcTo(0, Y1, 2 * R, 2 * R, 180, -90)
    p.lineTo(X1 - r, Y1); p.arcTo(X1 - 2 * r, Y1 - 2 * r, 2 * r, 2 * r, 270, 90)
    p.lineTo(X1, R); p.arcTo(X1, 0, 2 * R, 2 * R, 180, -90)
    p.closeSubpath()
    return p


def _chevron(direction, c, a=3.3, b=1.75):
    x, y = c.x(), c.y()
    pts = {
        "up": ((x - a, y + b), (x, y - b), (x + a, y + b)),
        "down": ((x - a, y - b), (x, y + b), (x + a, y - b)),
        "left": ((x + b, y - a), (x - b, y), (x + b, y + a)),
        "right": ((x - b, y - a), (x + b, y), (x - b, y + a)),
    }[direction]
    p = QPainterPath(QPointF(*pts[0]))
    p.lineTo(QPointF(*pts[1]))
    p.lineTo(QPointF(*pts[2]))
    return p


def _tokens():
    """Colours for the current theme (vibrancy segmented tokens; the accent
    and glyph colours come from the live theme, Rule 20)."""
    t = get_theme_colors()
    light = is_light_theme()
    primary = QColor(t["primary"])
    if light:
        return dict(
            well=_rgba(0, 0, 0, .055), well_line=_rgba(0, 0, 0, .14), well_shade=_rgba(0, 0, 0, .075),
            key1=QColor("#FFFFFF"), key2=QColor("#FAFAFB"),
            hair=_rgba(0, 0, 0, .17), hair_soft=_rgba(0, 0, 0, .085), gloss=_rgba(255, 255, 255, .85),
            shadow=_rgba(0, 0, 0, .18),
            ov_hover=_rgba(0, 0, 0, .04), ov_press=_rgba(0, 0, 0, .085),
            h_tint=_with_alpha(primary, .06), h_hover=_with_alpha(primary, .11), h_press=_with_alpha(primary, .19),
            glyph_page=QColor(t["secondary_text"]), glyph_page_hot=QColor(t["secondary_text"]).darker(130),
            glyph_hist=primary, glyph_hist_hot=primary.darker(115),
            glyph_off=_rgba(0, 0, 0, .20), text=QColor(t["secondary_text"]))
    return dict(
        well=_rgba(0, 0, 0, .30), well_line=_rgba(255, 255, 255, .10), well_shade=_rgba(0, 0, 0, .35),
        key1=_rgba(255, 255, 255, .21), key2=_rgba(255, 255, 255, .145),
        hair=_rgba(255, 255, 255, .13), hair_soft=_rgba(255, 255, 255, .075), gloss=_rgba(255, 255, 255, .09),
        shadow=_rgba(0, 0, 0, .5),
        ov_hover=_rgba(255, 255, 255, .055), ov_press=_rgba(255, 255, 255, .10),
        h_tint=_with_alpha(primary, .10), h_hover=_with_alpha(primary, .18), h_press=_with_alpha(primary, .28),
        glyph_page=_with_alpha(t["secondary_text"], .67), glyph_page_hot=QColor(t["secondary_text"]),
        glyph_hist=primary.lighter(130), glyph_hist_hot=primary.lighter(160),
        glyph_off=_rgba(255, 255, 255, .20), text=QColor(t["secondary_text"]))


class ChartNavPad(QWidget):
    """Four-way chart navigation pad. Emits ``pressed_dir`` with "left",
    "right", "up" or "down" when an enabled key is clicked."""

    pressed_dir = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(int(DESIGN_W), int(DESIGN_H))
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._enabled = {d: False for d in _KEYS}
        self._tips = {d: "" for d in _KEYS}
        self._hover = None
        self._down = None
        self._page_text = "0/0"
        self._tray = _plus_path()

    # -- state API --------------------------------------------------------

    def set_key_enabled(self, direction, enabled):
        enabled = bool(enabled)
        if self._enabled[direction] != enabled:
            self._enabled[direction] = enabled
            self.update()

    def is_key_enabled(self, direction):
        return self._enabled[direction]

    def set_key_tooltip(self, direction, text):
        self._tips[direction] = text or ""

    def key_tooltip(self, direction):
        return self._tips[direction]

    def set_page_text(self, text):
        if text != self._page_text:
            self._page_text = text
            self.update()

    def page_text(self):
        return self._page_text

    def click(self, direction):
        """Programmatic press (tests, keyboard): same as clicking the key."""
        if self._enabled[direction]:
            self.pressed_dir.emit(direction)

    def refresh_theme(self):
        self.update()

    # -- geometry ---------------------------------------------------------

    def _scale(self):
        return min(self.width() / DESIGN_W, self.height() / DESIGN_H)

    def _offset(self):
        s = self._scale()
        return QPointF((self.width() - DESIGN_W * s) / 2, (self.height() - DESIGN_H * s) / 2)

    def key_at(self, pos):
        s = self._scale()
        o = self._offset()
        p = QPointF((pos.x() - o.x()) / s, (pos.y() - o.y()) / s)
        for d, (rect, _c) in _KEYS.items():
            if rect.adjusted(-0.75, -0.75, 0.75, 0.75).contains(p):
                return d
        return None

    def key_center(self, direction):
        """Widget-space centre of a key (tests send real mouse clicks here)."""
        s = self._scale()
        o = self._offset()
        c = _KEYS[direction][0].center()
        return QPointF(o.x() + c.x() * s, o.y() + c.y() * s).toPoint()

    # -- events -----------------------------------------------------------

    def mouseMoveEvent(self, e):
        k = self.key_at(e.position())
        if k != self._hover:
            self._hover = k
            self.setCursor(Qt.CursorShape.PointingHandCursor if k and self._enabled[k]
                           else Qt.CursorShape.ArrowCursor)
            self.update()
            if QToolTip.isVisible():
                QToolTip.hideText()

    def leaveEvent(self, e):
        self._hover = None
        self._down = None
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            k = self.key_at(e.position())
            self._down = k if k and self._enabled[k] else None
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        k = self.key_at(e.position())
        down, self._down = self._down, None
        self.update()
        if down and k == down:
            self.click(down)

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.Type.ToolTip:
            k = self.key_at(e.position() if hasattr(e, "position") else QPointF(e.pos()))
            tip = self._tips.get(k) if k else ""
            if tip:
                QToolTip.showText(e.globalPos(), tip, self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    # -- painting ---------------------------------------------------------

    def paintEvent(self, _e):
        tk = _tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        o = self._offset()
        s = self._scale()
        p.translate(o)
        p.scale(s, s)

        # Tray (recessed well) with its top inner shade.
        p.setPen(QPen(tk["well_line"], 0.5))
        p.setBrush(tk["well"])
        p.drawPath(self._tray)
        shade = QPen(tk["well_shade"], 0.75)
        shade.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(shade)
        for x1, y, x2 in ((33, .7, 52), (8, 19.2, 22), (63, 19.2, 77)):
            p.drawLine(QPointF(x1, y), QPointF(x2, y))

        # Page pill (read-only).
        p.setPen(QPen(tk["hair_soft"], 0.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(_PILL, 9, 9)
        font = QFont(self.font())
        font.setPixelSize(21)                  # 10.5 px, drawn at 2x (fractional size)
        font.setWeight(QFont.Weight.DemiBold)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        p.save()
        p.scale(0.5, 0.5)
        p.setFont(font)
        p.setPen(tk["text"])
        r = _PILL
        p.drawText(QRectF(r.x() * 2, r.y() * 2 + 1, r.width() * 2, r.height() * 2),
                   Qt.AlignmentFlag.AlignCenter, self._page_text)
        p.restore()

        for d, (rect, centre) in _KEYS.items():
            self._paint_key(p, tk, d, rect, centre)
        p.end()

    def _paint_key(self, p, tk, d, rect, centre):
        on = self._enabled[d]
        hist = d in _HISTORY
        pressed = on and self._down == d
        hot = on and self._hover == d
        p.save()
        if not on:
            p.setOpacity(0.6)
        if not pressed:                           # drop shadow 0 .5px 1.5px
            sh = QColor(tk["shadow"])
            for grow, a in ((1.0, .35), (0.5, .5)):
                c = QColor(sh); c.setAlphaF(sh.alphaF() * a)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(c)
                p.drawRoundedRect(rect.adjusted(-grow, -grow + .5, grow, grow + .5), 5 + grow, 5 + grow)
        g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        g.setColorAt(0, tk["key1"]); g.setColorAt(1, tk["key2"])
        p.setPen(QPen(tk["hair"], 0.5))
        p.setBrush(g)
        p.drawRoundedRect(rect, 5, 5)
        overlay = None
        if hist and on:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(tk["h_tint"])
            p.drawRoundedRect(rect, 5, 5)
            overlay = tk["h_press"] if pressed else tk["h_hover"] if hot else None
        elif on:
            overlay = tk["ov_press"] if pressed else tk["ov_hover"] if hot else None
        if overlay is not None:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(overlay)
            p.drawRoundedRect(rect, 5, 5)
        gl = QPen(tk["gloss"], 0.5); gl.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(gl)
        p.drawLine(QPointF(rect.x() + 5, rect.y() + .55), QPointF(rect.right() - 5, rect.y() + .55))
        if hist:                                  # inner-edge accent hairline
            acc = QColor(tk["glyph_hist"]); acc.setAlphaF(.55 if on else .08)
            pen = QPen(acc, 1.2); pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            y = rect.bottom() - 1.6 if d == "up" else rect.y() + 1.6
            p.drawLine(QPointF(centre.x() - 4.5, y), QPointF(centre.x() + 4.5, y))
        if not on:
            col = tk["glyph_off"]
        elif hist:
            col = tk["glyph_hist_hot"] if hot else tk["glyph_hist"]
        else:
            col = tk["glyph_page_hot"] if hot else tk["glyph_page"]
        pen = QPen(col, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap); pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(_chevron(d, centre))
        p.restore()
