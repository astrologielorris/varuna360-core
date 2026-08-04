# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
E5, per-cell inner shading — SPEC-THM-002.

A faint light wash at the top of a cell and a faint dark wash at the bottom,
painted AFTER the cell's semantic base fill so a category colour keeps its
identity and merely gains a curve.

WHY THIS IS NOT A STYLESHEET
    Measured (SPEC-THM-002 INV-5): a QSS ``QTableWidget::item`` rule DEFEATS a
    delegate's own ``fillRect``. Every avastha / tajika / karaka / strength cell
    gets its colour from a delegate, so an ``::item`` background would silently
    erase the entire semantic palette. Cell depth therefore has to live inside
    ``paint()``, and ``elevation_table_style()`` deliberately emits no ``::item``
    rule at all.

COST
    Measured 1.27x a flat-fill delegate on a 14x8 table WITH the brush cached
    per row height, 1.36x without. The cache is mandatory. Its key is the row
    HEIGHT, not anything static, because a font-scale change resizes rows and a
    stale brush would then be the wrong height. A theme change does not alter
    the height, so ``clear_depth_cache()`` on theme switch is also mandatory —
    forgetting it is exactly the construction-time-orphan bug class this spec
    exists to close, one layer down.
"""

from PySide6.QtGui import QLinearGradient, QBrush, QColor

from ui.qt_theme import get_theme_colors, is_light_theme

# SPEC-THM-002 D-1: the ONE tuning pair, (top_alpha, bottom_alpha). Kept low on
# purpose — this rides on top of saturated category colours and its job is to
# suggest a curve, not to tint.
DEPTH_ALPHAS = (0.055, 0.10)


def _ink_pair():
    """(top_ink, bottom_ink) as QColor, from live tokens.

    Light wash on top, dark wash at the bottom, in BOTH polarities: which token
    is "light" flips with the theme, so the pair is chosen by polarity rather
    than by token name — the same INV-1 trap the elevation ramp navigates.
    """
    theme = get_theme_colors()
    if is_light_theme():
        return QColor(theme["secondary_light"]), QColor(theme["secondary_text"])
    return QColor(theme["secondary_text"]), QColor(theme["secondary_light"])


class CellDepthMixin:
    """Mix in BEFORE ``QStyledItemDelegate``.

        class MyDelegate(CellDepthMixin, QStyledItemDelegate): ...

    Then, inside ``paint()``, between the base fill and ``super().paint()``::

        painter.fillRect(fill_rect, base_brush)
        self.paint_depth(painter, fill_rect)
        super().paint(painter, option, index)
    """

    _depth_enabled = True

    def set_depth_enabled(self, enabled):
        self._depth_enabled = bool(enabled)
        self.clear_depth_cache()

    def clear_depth_cache(self):
        """Drop cached brushes. MUST be called on a theme change — the cache key
        is the row height, which a theme switch does not alter, so nothing else
        would invalidate it."""
        self.__dict__["_depth_brushes"] = {}

    def _depth_brush(self, height):
        cache = self.__dict__.setdefault("_depth_brushes", {})
        brush = cache.get(height)
        if brush is None:
            top_ink, bottom_ink = _ink_pair()
            top = QColor(top_ink)
            top.setAlphaF(DEPTH_ALPHAS[0])
            bottom = QColor(bottom_ink)
            bottom.setAlphaF(DEPTH_ALPHAS[1])
            gradient = QLinearGradient(0, 0, 0, max(1, height))
            gradient.setColorAt(0.0, top)
            gradient.setColorAt(1.0, bottom)
            brush = QBrush(gradient)
            cache[height] = brush
        return brush

    def paint_depth(self, painter, rect):
        """Overlay the depth wash on ``rect``. No-op when disabled."""
        if not self._depth_enabled or rect.height() <= 0:
            return
        painter.save()
        # The gradient is defined in 0..height space, so translate to the cell
        # rather than rebuilding a gradient per row position (that would defeat
        # the cache and cost the 1.36x measured without it).
        painter.translate(rect.topLeft())
        painter.fillRect(0, 0, rect.width(), rect.height(),
                         self._depth_brush(rect.height()))
        painter.restore()
