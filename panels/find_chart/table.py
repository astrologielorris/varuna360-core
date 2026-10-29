# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Paint the mockup's quiet result rows without changing the table API."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from panels.find_chart import kit


class ResultDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if not (index.flags() & Qt.ItemIsSelectable):
            super().paint(painter, option, index)
            return
        t = kit.tokens()
        fs = kit.area_fs("tables")
        selected = bool(option.state & QStyle.State_Selected)
        painter.save()
        painter.setClipRect(option.rect)
        painter.fillRect(option.rect, t["secondary_light"])
        if selected:
            painter.fillRect(option.rect, kit._alpha(t["primary"], .14))
            if index.column() == 0:
                stripe = option.rect.adjusted(0, 0, 0, 0)
                stripe.setWidth(max(2, round(2.5 * fs)))
                painter.fillRect(stripe, t["primary"])
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, t["ctl_h"])
        elif index.row() % 2 == 0:
            painter.fillRect(option.rect, kit._alpha(t["primary_text"], .025))
        font = QFont(option.font)
        if index.column() == 0:
            font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(t["primary_text"] if index.column() == 0 else t["secondary_text"])
        rect = option.rect.adjusted(round(10 * fs), 0, -round(10 * fs), 0)
        text = str(index.data(Qt.DisplayRole) or "")
        text = painter.fontMetrics().elidedText(text, Qt.ElideRight, max(0, rect.width()))
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()
