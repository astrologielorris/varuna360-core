"""Local reading enlargement for long rich-text dialogs."""
import re
from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QShortcut, QTextCursor, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from ui.qt_theme import scaled_area_px
from ui.popup_fonts import tier_px

_SIZE = re.compile(r'(font-size\s*:\s*)([\d.]+)(px|pt)')


def _scale_css(text, factor):
    return _SIZE.sub(lambda m: f'{m[1]}{float(m[2]) * factor:g}{m[3]}', text)


def fit_reading_dialog(dialog):
    """Qt available geometry is in logical pixels, including on Retina screens."""
    screen = dialog.parentWidget().screen() if dialog.parentWidget() else dialog.screen()
    if screen is None:
        return
    area = screen.availableGeometry().adjusted(20, 20, -20, -20)
    dialog.setMinimumSize(min(600, area.width()), min(420, area.height()))
    dialog.resize(min(900, area.width()), min(800, area.height()))
    dialog.move(area.center() - dialog.rect().center())


class ReadingControls(QWidget):
    """Zoom the complete document, including explicit rich-text sizes and TOC."""
    def __init__(self, browser, toc, parent=None):
        super().__init__(parent)
        self.browser, self.toc = browser, toc
        self._runs = []
        block = browser.document().begin()
        while block.isValid():
            fragment_it = block.begin()
            while not fragment_it.atEnd():
                fragment = fragment_it.fragment()
                if fragment.isValid():
                    self._runs.append((fragment.position(), fragment.length(),
                                       QTextCharFormat(fragment.charFormat())))
                fragment_it += 1
            block = block.next()
        self._toc_style = toc.styleSheet()
        self._toc_px = tier_px('sidebar', 11)   # contents list = navigation (td-168ze)
        self._fonts = [QFont(toc.item(i).font()) for i in range(toc.count())]
        self._label_styles = {
            i: toc.itemWidget(toc.item(i)).styleSheet() for i in range(toc.count())
            if toc.itemWidget(toc.item(i)) is not None
        }
        self.percent = 100
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        row.addWidget(QLabel('Reading size', self))
        self.smaller = QPushButton('A−', self)
        self.larger = QPushButton('A+', self)
        self.reset = QPushButton('100%', self)
        for button, name, callback in (
            (self.smaller, 'Smaller reading text', lambda: self.set_percent(self.percent - 25)),
            (self.larger, 'Larger reading text', lambda: self.set_percent(self.percent + 25)),
            (self.reset, 'Reset reading size', lambda: self.set_percent(100)),
        ):
            button.setAccessibleName(name)
            button.setToolTip(name)
            button.setStyleSheet(f'font-size: {scaled_area_px("buttons")}px; padding: 4px 10px;')
            button.clicked.connect(callback)
            row.addWidget(button)
        for key, button in [('Ctrl++', self.larger), ('Ctrl+=', self.larger),
                            ('Ctrl+-', self.smaller), ('Ctrl+0', self.reset)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(button.click)
        toc.viewport().installEventFilter(self)
        QTimer.singleShot(0, self._fit_labels)

    def set_percent(self, value):
        self.percent = max(75, min(250, value))
        factor = self.percent / 100
        scroll = self.browser.verticalScrollBar()
        position = scroll.value() / max(1, scroll.maximum())
        cursor = QTextCursor(self.browser.document())
        cursor.beginEditBlock()
        for start, length, original in self._runs:
            fmt = QTextCharFormat(original)
            font = QFont(original.font())
            if font.pixelSize() > 0:
                font.setPixelSize(round(font.pixelSize() * factor))
            elif font.pointSizeF() > 0:
                font.setPointSizeF(font.pointSizeF() * factor)
            fmt.setFont(font)
            fmt.clearProperty(QTextFormat.Property.FontSizeAdjustment)
            cursor.setPosition(start)
            cursor.setPosition(start + length, QTextCursor.MoveMode.KeepAnchor)
            cursor.setCharFormat(fmt if self.percent != 100 else original)
        cursor.endEditBlock()
        scroll.setValue(round(position * scroll.maximum()))
        self.toc.setStyleSheet(_scale_css(self._toc_style, factor))
        for i, original in enumerate(self._fonts):
            font = QFont(original)
            # QListWidgetItem font roles override QSS. Use the same pixel
            # baseline as the list so nested entries cannot grow twice.
            font.setPixelSize(round(self._toc_px * factor))
            self.toc.item(i).setFont(font)
        for i, style in self._label_styles.items():
            self.toc.itemWidget(self.toc.item(i)).setStyleSheet(_scale_css(style, factor))
        self.reset.setText(f'{self.percent}%')
        self.smaller.setEnabled(self.percent > 75)
        self.larger.setEnabled(self.percent < 250)
        splitter = self.toc.parentWidget().parentWidget()
        if hasattr(splitter, 'setSizes'):
            width = splitter.width()
            contents = min(round(width * .4), round(200 * factor))
            splitter.setSizes([contents, width - contents])
        self._fit_labels()

    def _fit_labels(self):
        width = max(30, self.toc.viewport().width() - 24)
        for i in range(self.toc.count()):
            item = self.toc.item(i)
            label = self.toc.itemWidget(item)
            if label is not None:
                label.setFixedWidth(width)
                # The list delegate removes its 6px top/bottom item padding
                # before placing an embedded widget. Reserve that space too.
                height = max(label.sizeHint().height(), label.heightForWidth(width)) + 12
            else:
                font = item.font() if item.font().resolveMask() else self.toc.font()
                height = QFontMetrics(font).boundingRect(
                    QRect(0, 0, max(10, width - 16), 10000),
                    Qt.TextFlag.TextWordWrap, item.text()).height() + 16
            item.setSizeHint(QSize(width, height))
        self.toc.doItemsLayout()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._fit_labels)
        return super().eventFilter(watched, event)
