#!/usr/bin/env python3
"""
Highlight Delegates for QTableWidget
Provides custom painting to highlight specific rows with theme colors
"""
from PySide6.QtWidgets import QStyledItemDelegate
from PySide6.QtGui import QBrush, QColor, QPalette, QPen, QPainterPath, QPolygonF
from PySide6.QtCore import Qt as QtCore_Qt, QPointF, QRectF

# Import theme for dynamic color updates
from ui.qt_theme import get_theme_colors, ACCENTS


class KarakaHighlightDelegate(QStyledItemDelegate):
    """
    Highlights AK (Atma Karaka) and DK (Dara Karaka) rows in Karakas table.

    This delegate works WITH stylesheets - it doesn't conflict with
    QTableWidget::item styling.

    Theme colors are fetched dynamically on each paint to support theme switching.
    Uses subtle secondary_light background (gray) for dark theme readability.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlight_rows = set()  # Set of row indices to highlight (0 for AK, 6 for DK)

    def paint(self, painter, option, index):
        """Override paint to add background highlighting for specific rows"""
        # Get current theme colors dynamically (supports theme switching)
        theme = get_theme_colors()

        painter.save()

        # Shrink fill rect by 1px on bottom/right to preserve grid lines
        fill_rect = option.rect.adjusted(0, 0, -1, -1)

        if index.row() in self.highlight_rows:
            # Draw subtle highlight using secondary_light (gray) - readable on dark themes
            painter.fillRect(fill_rect, QBrush(QColor(theme["secondary_light"])))
            # Keep white text for good contrast on gray background
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["secondary_text"]))
        else:
            # Draw normal dark background for non-highlighted cells
            painter.fillRect(fill_rect, QBrush(QColor(theme["secondary_dark"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["secondary_text"]))

        painter.restore()

        # Call parent implementation with modified option
        super().paint(painter, option, index)

    def update_highlights(self, highlight_rows):
        """Update which rows should be highlighted"""
        self.highlight_rows = set(highlight_rows)


class StrengthHighlightDelegate(QStyledItemDelegate):
    """
    Highlights individual cells in Strength table where strength value > 45.

    This delegate works WITH stylesheets - it doesn't conflict with
    QTableWidget::item styling.

    Theme colors are fetched dynamically on each paint to support theme switching.
    Uses secondary colors to differentiate from Karakas highlighting.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlight_cells = set()  # Set of (row, col) tuples with high strength
        self.retrograde_rows = set()  # Set of row indices where planet is retrograde

    def paint(self, painter, option, index):
        """Override paint to add background highlighting for high-strength values"""
        # Get current theme colors dynamically (supports theme switching)
        theme = get_theme_colors()

        painter.save()

        # Shrink fill rect by 1px on bottom/right to preserve grid lines
        fill_rect = option.rect.adjusted(0, 0, -1, -1)

        if (index.row(), index.column()) in self.highlight_cells:
            # Draw highlight background using secondary_light for differentiation
            painter.fillRect(fill_rect, QBrush(QColor(theme["secondary_light"])))
            # Change text color for contrast
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["secondary_text"]))
        else:
            # Draw normal dark background for non-highlighted cells
            painter.fillRect(fill_rect, QBrush(QColor(theme["secondary_dark"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["secondary_text"]))

        painter.restore()

        # Disable text elision so "R*" suffix is not truncated
        option.textElideMode = QtCore_Qt.TextElideMode.ElideNone

        # Call parent implementation with modified option
        super().paint(painter, option, index)

    def update_highlights(self, highlight_cells):
        """Update which cells should be highlighted (set of (row, col) tuples)"""
        self.highlight_cells = set(highlight_cells)

    def update_retrogrades(self, retrograde_rows):
        """Update which rows have retrograde planets (set of row indices)."""
        self.retrograde_rows = set(retrograde_rows)


class DashaHighlightDelegate(QStyledItemDelegate):
    """
    Highlights dasha period rows in QListWidget with multiple color channels.

    Paint priority (first match wins):
    1. highlight_rows   → theme primary (blue)  — current dasha period
    2. selected_row     → ACCENTS green         — user click-selection
    3. karaka_rows      → ACCENTS gold          — karaka match (AK/AmK/etc)
    4. cusp_lord_rows   → ACCENTS cyan          — cusp-based house lord match
    5. whole_sign_rows  → ACCENTS orange        — whole-sign house lord match
    6. maturation_rows  → secondary_light       — Nisarga maturation year
    7. (else)           → secondary_dark        — normal row
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlight_rows = set()      # Current dasha period
        self.selected_row = None         # User click-selection (single row or None)
        self.karaka_rows = set()         # Karaka-match rows
        self.cusp_lord_rows = set()      # Cusp lord-match rows
        self.whole_sign_rows = set()     # Whole-sign lord-match rows
        self.maturation_rows = set()     # Nisarga maturation year

    def paint(self, painter, option, index):
        """Override paint to add background highlighting for dasha periods"""
        theme = get_theme_colors()

        painter.save()
        row = index.row()

        if row in self.highlight_rows:
            # Current period — theme primary (blue)
            painter.fillRect(option.rect, QBrush(QColor(theme["primary"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["primary_text"]))
        elif self.selected_row is not None and row == self.selected_row:
            # User click-selection — green
            painter.fillRect(option.rect, QBrush(QColor(ACCENTS["green"]["base"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor("#FFFFFF"))
        elif row in self.karaka_rows:
            # Karaka match — gold
            painter.fillRect(option.rect, QBrush(QColor(ACCENTS["gold"]["base"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor("#1A1A1A"))
        elif row in self.cusp_lord_rows:
            # Cusp lord match — cyan
            painter.fillRect(option.rect, QBrush(QColor(ACCENTS["cyan"]["base"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor("#1A1A1A"))
        elif row in self.whole_sign_rows:
            # Whole-sign lord match — orange
            painter.fillRect(option.rect, QBrush(QColor(ACCENTS["orange"]["base"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor("#1A1A1A"))
        elif row in self.maturation_rows:
            # Maturation year — secondary_light
            painter.fillRect(option.rect, QBrush(QColor(theme["secondary_light"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["secondary_text"]))
        else:
            # Normal row
            painter.fillRect(option.rect, QBrush(QColor(theme["secondary_dark"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["secondary_text"]))

        painter.restore()
        super().paint(painter, option, index)

    def update_highlights(self, highlight_rows):
        """Update which rows should be highlighted with primary color"""
        self.highlight_rows = set(highlight_rows)

    def update_selected_row(self, row_or_none):
        """Update the user click-selected row (single int or None to clear)"""
        self.selected_row = row_or_none

    def update_karaka_highlights(self, rows):
        """Update rows matching the selected karaka's planet"""
        self.karaka_rows = set(rows)

    def update_cusp_lord_highlights(self, rows):
        """Update rows matching the selected cusp lord's planet"""
        self.cusp_lord_rows = set(rows)

    def update_whole_sign_highlights(self, rows):
        """Update rows matching the selected whole-sign lord's planet"""
        self.whole_sign_rows = set(rows)

    def update_maturation_highlights(self, maturation_rows):
        """Update which rows should be highlighted with maturation (gold) color"""
        self.maturation_rows = set(maturation_rows)


class AspectHighlightDelegate(QStyledItemDelegate):
    """
    Highlights strong aspects (>= 45 Virupas) in the Aspects table.

    This delegate works WITH stylesheets - it doesn't conflict with
    QTableWidget::item styling.

    Theme colors are fetched dynamically on each paint to support theme switching.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlight_cells = set()  # Set of (row, col) tuples with strong aspects

    def paint(self, painter, option, index):
        """Override paint to add background highlighting for strong aspects"""
        # Get current theme colors dynamically (supports theme switching)
        theme = get_theme_colors()

        painter.save()

        # Shrink fill rect by 1px on bottom/right to preserve grid lines
        fill_rect = option.rect.adjusted(0, 0, -1, -1)

        if (index.row(), index.column()) in self.highlight_cells:
            # Draw highlight background using secondary_light for strong aspects
            painter.fillRect(fill_rect, QBrush(QColor(theme["secondary_light"])))
            # Change text color for contrast
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["secondary_text"]))
        else:
            # Draw normal dark background for non-highlighted cells
            painter.fillRect(fill_rect, QBrush(QColor(theme["secondary_dark"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["secondary_text"]))

        painter.restore()

        # Call parent implementation with modified option
        super().paint(painter, option, index)

    def update_highlights(self, highlight_cells):
        """Update which cells should be highlighted (set of (row, col) tuples)"""
        self.highlight_cells = set(highlight_cells)


class AvasthaHighlightDelegate(QStyledItemDelegate):
    """
    Per-cell category coloring for the Avastha (Drishti Yuti) table.

    Each cell can be assigned a category: FRIEND, ENEMY, NEUTRAL, DUAL, SHAME, PROUD.
    Colors are semantic (green=friend, red=enemy, etc.) — semantic-meaning is the
    documented exception to the "use theme colors, not hardcoded values" rule.
    """

    # Semantic color map: category -> (dark_bg, dark_text, light_bg, light_text)
    CATEGORY_COLORS_MAP = {
        "FRIEND":  ("#1B3A1B", "#66BB6A", "#C8E6C9", "#2E7D32"),
        "ENEMY":   ("#3A1B1B", "#EF5350", "#FFCDD2", "#C62828"),
        "NEUTRAL": ("#1B1B3A", "#42A5F5", "#BBDEFB", "#1565C0"),
        "DUAL":    ("#3A3A1B", "#FFD54F", "#FFF9C4", "#F9A825"),
        "SHAME":   ("#3A1010", "#FF3B30", "#FFCDD2", "#B71C1C"),
        "PROUD":   ("#2A1B2A", "#CE93D8", "#E1BEE7", "#7B1FA2"),
    }

    @staticmethod
    def _is_light_theme():
        """Detect if current theme is light based on secondary text brightness."""
        import os
        text_color = os.environ.get("QTMATERIAL_SECONDARYTEXTCOLOR", "#FFFFFF")
        r = int(text_color[1:3], 16)
        g = int(text_color[3:5], 16)
        b = int(text_color[5:7], 16)
        return (r + g + b) < 400  # dark text = light theme

    @classmethod
    def get_category_colors(cls):
        """Return (bg, text) dict adapted to current theme."""
        light = cls._is_light_theme()
        return {
            cat: (vals[2], vals[3]) if light else (vals[0], vals[1])
            for cat, vals in cls.CATEGORY_COLORS_MAP.items()
        }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cell_categories = {}  # (row, col) -> category string

    def paint(self, painter, option, index):
        """Override paint to apply per-cell category coloring."""
        theme = get_theme_colors()
        painter.save()

        key = (index.row(), index.column())
        cat = self.cell_categories.get(key)

        # Shrink fill rect by 1px on bottom/right to preserve grid lines
        fill_rect = option.rect.adjusted(0, 0, -1, -1)

        colors = self.get_category_colors()
        if cat and cat in colors:
            bg_hex, text_hex = colors[cat]
            painter.fillRect(fill_rect, QBrush(QColor(bg_hex)))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(text_hex))
        else:
            painter.fillRect(fill_rect, QBrush(QColor(theme["secondary_dark"])))
            option.palette.setColor(QPalette.ColorRole.Text, QColor(theme["secondary_text"]))

        painter.restore()
        super().paint(painter, option, index)

    def update_categories(self, cell_categories):
        """Update per-cell category map. Dict of (row, col) -> category string."""
        self.cell_categories = dict(cell_categories)


class TajikaHighlightDelegate(QStyledItemDelegate):
    """
    Custom-painted geometric shapes for the Tajika 11x11 aspect matrix.

    Draws actual vector shapes (circle, star, square, triangle, opposition symbol)
    using QPainter for crisp, scalable rendering at any zoom level.
    Each cell stores a shape key + relationship category for coloring.

    Shapes:
    - conjunction: filled circle
    - sextile: 6-pointed star
    - square: square outline (thick)
    - trine: equilateral triangle outline
    - opposition: circle with horizontal line through it
    - diagonal: thin dash (self-aspect)
    """

    # Background + foreground colors: (dark_bg, dark_fg, light_bg, light_fg)
    CATEGORY_COLORS_MAP = {
        "FRIENDLY_OPEN":   ("#1B3A1B", "#66BB6A", "#C8E6C9", "#2E7D32"),
        "FRIENDLY_SECRET": ("#1B2E1B", "#4CAF50", "#DCEDC8", "#558B2F"),
        "INIMICAL_OPEN":   ("#3A1B1B", "#EF5350", "#FFCDD2", "#C62828"),
        "INIMICAL_SECRET": ("#2E1B1B", "#E57373", "#FFEBEE", "#D32F2F"),
        "NEUTRAL":         ("#1B1B3A", "#42A5F5", "#BBDEFB", "#1565C0"),
        "STRONG":          ("#2A2A1B", "#FFD54F", "#FFF9C4", "#F9A825"),
    }

    @classmethod
    def get_category_colors(cls):
        """Return (bg, fg) dict adapted to current theme."""
        light = AvasthaHighlightDelegate._is_light_theme()
        return {
            cat: (vals[2], vals[3]) if light else (vals[0], vals[1])
            for cat, vals in cls.CATEGORY_COLORS_MAP.items()
        }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cell_categories = {}  # (row, col) -> category string
        self.cell_shapes = {}      # (row, col) -> shape key string

    def paint(self, painter, option, index):
        """Custom paint: draw background + geometric shape (no text)."""
        import math
        theme = get_theme_colors()
        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)

        key = (index.row(), index.column())
        cat = self.cell_categories.get(key)
        shape = self.cell_shapes.get(key)
        rect = option.rect

        # --- Background ---
        colors = self.get_category_colors()
        if cat and cat in colors:
            bg_hex, fg_hex = colors[cat]
            painter.fillRect(rect, QBrush(QColor(bg_hex)))
            shape_color = QColor(fg_hex)
        else:
            painter.fillRect(rect, QBrush(QColor(theme["secondary_dark"])))
            shape_color = QColor(theme["secondary_text"])

        # --- Draw shape ---
        if shape:
            cx = rect.center().x()
            cy = rect.center().y()
            # Shape fills ~55% of the smaller cell dimension
            cell_size = min(rect.width(), rect.height())
            r = cell_size * 0.28  # radius

            pen = QPen(shape_color, max(1.5, cell_size * 0.07))
            pen.setCapStyle(QtCore_Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(QtCore_Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)

            if shape == "conjunction":
                # Two overlapping circles (Venn diagram — "coming together")
                painter.setBrush(QBrush())  # no fill
                cr = r * 0.55
                offset = cr * 0.45
                painter.drawEllipse(QPointF(cx - offset, cy), cr, cr)
                painter.drawEllipse(QPointF(cx + offset, cy), cr, cr)

            elif shape == "sextile":
                # 6-pointed star (two overlapping triangles)
                painter.setBrush(QBrush(shape_color))
                path = QPainterPath()
                outer = r
                inner = r * 0.5
                for i in range(6):
                    angle_out = math.radians(i * 60 - 90)
                    angle_in = math.radians(i * 60 - 90 + 30)
                    ox = cx + outer * math.cos(angle_out)
                    oy = cy + outer * math.sin(angle_out)
                    ix = cx + inner * math.cos(angle_in)
                    iy = cy + inner * math.sin(angle_in)
                    if i == 0:
                        path.moveTo(ox, oy)
                    else:
                        path.lineTo(ox, oy)
                    path.lineTo(ix, iy)
                path.closeSubpath()
                painter.drawPath(path)

            elif shape == "square":
                # Square outline
                painter.setBrush(QBrush())  # no fill
                half = r * 0.8
                painter.drawRect(QRectF(cx - half, cy - half, half * 2, half * 2))

            elif shape == "trine":
                # Equilateral triangle pointing up
                painter.setBrush(QBrush())  # no fill
                tri = QPolygonF([
                    QPointF(cx, cy - r),                          # top
                    QPointF(cx - r * 0.866, cy + r * 0.5),       # bottom-left
                    QPointF(cx + r * 0.866, cy + r * 0.5),       # bottom-right
                ])
                painter.drawPolygon(tri)

            elif shape == "opposition":
                # Two circles connected by a line (dumbbell — "facing each other")
                painter.setBrush(QBrush(shape_color))
                cr = r * 0.3
                span = r * 0.75
                painter.drawEllipse(QPointF(cx - span, cy), cr, cr)
                painter.drawEllipse(QPointF(cx + span, cy), cr, cr)
                painter.drawLine(QPointF(cx - span, cy), QPointF(cx + span, cy))

            elif shape == "diagonal":
                # Thin dash for self-aspect
                dash_color = QColor(theme["secondary_light"])
                painter.setPen(QPen(dash_color, 1.5))
                hw = cell_size * 0.2
                painter.drawLine(QPointF(cx - hw, cy), QPointF(cx + hw, cy))

        painter.restore()

        if not shape:
            # No shape → render cell text normally (needed for relationships table)
            # For shape cells we skip super() so text stays hidden behind the shape
            super().paint(painter, option, index)

    def update_categories(self, cell_categories):
        """Update per-cell category map. Dict of (row, col) -> category string."""
        self.cell_categories = dict(cell_categories)

    def update_shapes(self, cell_shapes):
        """Update per-cell shape map. Dict of (row, col) -> shape key string."""
        self.cell_shapes = dict(cell_shapes)


class RetinueColorDelegate(QStyledItemDelegate):
    """Delegate that paints background AND text directly via QPainter.

    qt-material's global stylesheet overrides both setBackground() and
    palette text colors on QTableWidget items. This delegate bypasses
    the style engine entirely by painting background with fillRect()
    and text with drawText().

    Used for Hora and Trimsamsa tables where row colors indicate
    Aditya/Naga side or being type (Gandharva/Rakshasa/Rishi/Yaksha/Apsara).
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter, option, index):
        theme = get_theme_colors()

        painter.save()
        fill_rect = option.rect.adjusted(0, 0, -1, -1)

        bg_data = index.data(QtCore_Qt.ItemDataRole.BackgroundRole)
        fg_data = index.data(QtCore_Qt.ItemDataRole.ForegroundRole)

        if bg_data is not None:
            bg_color = bg_data.color() if isinstance(bg_data, QBrush) else QColor(bg_data)
        else:
            bg_color = QColor(theme["secondary_dark"])
        painter.fillRect(fill_rect, bg_color)

        if fg_data is not None:
            fg_color = fg_data.color() if isinstance(fg_data, QBrush) else QColor(fg_data)
        else:
            fg_color = QColor(theme["secondary_text"])

        text = index.data(QtCore_Qt.ItemDataRole.DisplayRole)
        if text:
            painter.setPen(fg_color)
            font_data = index.data(QtCore_Qt.ItemDataRole.FontRole)
            if font_data is not None:
                painter.setFont(font_data)
            alignment = index.data(QtCore_Qt.ItemDataRole.TextAlignmentRole)
            if alignment is None:
                alignment = int(QtCore_Qt.AlignmentFlag.AlignLeft | QtCore_Qt.AlignmentFlag.AlignVCenter)
            text_rect = option.rect.adjusted(6, 0, -4, 0)
            painter.drawText(text_rect, int(alignment), str(text))

        painter.restore()
