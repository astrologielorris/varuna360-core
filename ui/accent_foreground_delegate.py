"""Qt item delegate for text drawn on the theme primary selection."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QStyledItemDelegate
from ui.qt_theme import get_theme_colors

class AccentSelectionForegroundDelegate(QStyledItemDelegate):
    """Paint selected item text directly so global QSS cannot replace it."""
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not option.state & option.state.State_Selected:
            return
        theme = get_theme_colors()
        icon_offset = 52 if index.data(Qt.ItemDataRole.DecorationRole) else 16
        text_rect = option.rect.adjusted(icon_offset, 0, 0, 0)
        painter.save()
        painter.fillRect(text_rect, QColor(theme["primary"]))
        painter.setPen(QColor(theme["primary_text"]))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        painter.restore()
