"""Button-operated guide text that leaves wheel gestures to chart zoom."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTextBrowser, QPushButton
from ui.qt_theme import scaled_area_px


class GuideReader(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._buttons = []
        for label, direction in [('Up', -1), ('Down', 1)]:
            button = QPushButton(label, self)
            button.setObjectName('ascendantGuide' + label)
            button.setToolTip('Scroll guide ' + label.lower())
            button.setAutoRepeat(True)
            button.clicked.connect(lambda checked=False, step=direction: self.scroll_page(step))
            button.hide()
            self._buttons.append(button)
        self.verticalScrollBar().rangeChanged.connect(self.sync_buttons)
        self.verticalScrollBar().valueChanged.connect(self.sync_buttons)

    def wheelEvent(self, event):
        event.ignore()

    def scroll_page(self, direction):
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() + direction * max(1, int(bar.pageStep() * 0.8)))

    def sync_buttons(self, *_):
        bar = self.verticalScrollBar()
        for button, available in zip(self._buttons,
                                     (bar.value() > bar.minimum(), bar.value() < bar.maximum())):
            button.setVisible(bar.maximum() > bar.minimum())
            button.setEnabled(available)

    def resizeEvent(self, event):
        footer = max(28, scaled_area_px('buttons') + 16)
        self.setViewportMargins(0, 0, 0, footer + 4)
        super().resizeEvent(event)
        width = max(1, (self.width() - 6) // 2)
        for index, button in enumerate(self._buttons):
            button.setGeometry(index * (width + 6), self.height() - footer, width, footer)
        self.sync_buttons()
