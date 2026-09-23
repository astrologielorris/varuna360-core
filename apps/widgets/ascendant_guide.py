"""One optional center reader, owned by the vector view, not by ChartGUI."""
from html import escape
from shiboken6 import isValid
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QPushButton, QFrame
from apps.widgets.ascendant_guide_reader import GuideReader
from core.ascendant_guide import build_guide
from apps.widgets.south_indian_geometry import center_rect, varga_label
from ui.qt_theme import get_theme_colors, scaled_area_px

def guide_html(model):
    e = escape
    if 'notice' in model:
        return '<p>' + e(model['notice']) + '</p>'
    title = e(model['name']) + ' · ' + str(model['sign'] + 1)
    if model['varga'] not in (None, 1):
        title += ' · ' + e(varga_label(model['varga']) or '')
    parts = ['<h3>' + title + '</h3>']
    if model['birth']:
        parts.append('<p><b>Birth ascendant</b> · Overall life</p>')
    parts.extend(frame_labels(model))
    parts.extend(teaching_html(model))
    parts.extend(placement_html(model))
    return ''.join(parts)

def frame_labels(model):
    labels = {'Sun': ('Surya Lagna', '#704000', '#fff0c2', 'Soul and purpose: who you are and what you need to do to be yourself. A reference for your dharma and ideals.'),
              'Moon': ('Chandra Lagna', '#164b70', '#dfF2ff', 'A major reference for your emotional personality: who you are emotionally, your intuition, connections and inner needs. It also reflects your love life and your ability to give yourself love.')}
    parts = []
    for planet in model['occupants']:
        if planet in labels:
            name, ink, background, meaning = labels[planet]
            parts.append(f'<p><b style="color:{ink}; background-color:{background}">{name}</b><br>{meaning}</p>')
        else:
            parts.append('<p>' + escape(planet) + ' ascendant</p>')
    return parts

def teaching_html(model):
    teaching = model['teaching']
    if teaching:
        return ['<p><b>Aditya Structure</b><br><b>' + escape(teaching['title'])
                + '</b><br>' + escape(teaching['text']).replace('\n\n', '</p><p>') + '</p>']
    return ['<p>Aditya D1 structure does not apply to this chart frame.</p>']

def placement_html(model):
    e = escape
    parts = ['<p><b>Placements from this frame</b></p>']
    if not model['occupants']:
        parts.append('<p>No planet occupies this sign. Its Aditya function still applies.</p>' if model['supported']
                     else '<p>No planet occupies this sign.</p>')
    for planet in model['occupants']:
        purpose = model['purposes'].get(planet)
        if purpose:
            parts.append('<p><b>Read from ' + e(planet) + '</b><br>' + e(purpose) + '</p>')
    parts.append('<p>' + '<br>'.join(
        e(planet) + ' · house ' + str(house) for planet, house in model['placements']) + '</p>')
    if model['supported']:
        parts.append('<p>Dhata, the foundation · house ' + str(model['foundation']) + '</p>')
    return parts

def guide_font_px():
    return round(scaled_area_px("info_text") * 1.18)
class AscendantGuide(QObject):
    def __init__(self, viewport, mapper, center, redraw):
        super().__init__(viewport)
        self.viewport = viewport
        self.mapper = mapper
        self.center = center
        self.redraw = redraw
        self.button = None
        self.enabled = False
        self.reader = GuideReader(viewport)
        self.reader.setObjectName('ascendantGuideReader')
        self.reader.setFrameShape(QFrame.Shape.NoFrame)
        self.reader.setOpenExternalLinks(False)
        self.reader.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.reader.hide()
        self.model = {}
        self._html = None
        viewport.installEventFilter(self)

    def center_chart(self, chart):
        return None if self.enabled else chart

    def create_button(self, parent):
        from managers.settings_manager import get_settings
        self.button = QPushButton('Guide', parent)
        self.button.setObjectName('ascendantGuideButton')
        self.button.setCheckable(True)
        self.button.setToolTip('Show the ascendant reading guide in the chart center')
        self.enabled = bool(get_settings().get('display.ascendant_guide', False))
        self.button.setChecked(self.enabled)
        self.button.toggled.connect(self.set_enabled)
        self.sync_geometry()
        return self.button

    def set_enabled(self, enabled):
        from managers.settings_manager import get_settings
        self.enabled = bool(enabled)
        get_settings().set('display.ascendant_guide', self.enabled)
        self.redraw()

    def update(self, snapshot, style, birth_sign):
        self.model = build_guide(snapshot, birth_sign)
        colors = get_theme_colors()
        ink = style.ink('main', colors['secondary_text']).name()
        self.reader.setStyleSheet(f'QTextBrowser {{background: transparent; color: {ink}; '
                                  f'font-size: {guide_font_px()}px; border: none;}}')
        self.reader.document().setDefaultStyleSheet('h3 { margin: 0 0 8px; } p { margin: 0 0 10px; }')
        html = guide_html(self.model)
        if html != self._html:
            self.reader.setHtml(html)
            self._html = html
        if self.button and isValid(self.button):
            self.button.setText("?" if scaled_area_px("sidebar") > 12 else "Guide")
            self.button.setStyleSheet(f'QPushButton {{font-size: {scaled_area_px("sidebar")}px; '
                f'color: {colors["secondary_text"]}; background: {colors["secondary_dark"]}; '
                f'border: 1px solid {colors["secondary_light"]}; border-radius: 3px; padding: 0px; '
                f'min-height: 22px; max-height: 22px;}} '
                f'QPushButton:checked {{border: 1px solid {colors["primary"]};}}')
        self.sync_geometry()

    def widgets_alive(self):
        return hasattr(self, 'viewport') and isValid(self.viewport) and isValid(self.reader)

    def sync_geometry(self, *_):
        if not self.widgets_alive():
            return
        visible = self.viewport.isVisible()
        if self.button and isValid(self.button):
            self.button.setVisible(visible)
            self.button.setEnabled(not self.center.time_adjust_mode)
        show = visible and self.enabled and not self.center.time_adjust_mode
        if show:
            rect = self.mapper(center_rect()).boundingRect().adjusted(10, 10, -10, -10)
            rect = rect.intersected(self.viewport.rect())
            show = rect.width() > 30 and rect.height() > 30
            if show:
                self.reader.setGeometry(rect)
                self.reader.raise_()
        self.reader.setVisible(show)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Paint, QEvent.Type.Show, QEvent.Type.Hide):
            self.sync_geometry()
        return False
