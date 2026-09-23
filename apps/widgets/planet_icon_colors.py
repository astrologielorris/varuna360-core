"""Draft SVG palettes: individual or all bodies, saved by Chart settings Apply."""
from copy import deepcopy
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                              QComboBox, QPushButton, QColorDialog, QLabel, QListView)
from apps.widgets.planet_icon_style import ICON_NAMES, PLANET_NAMES, colors_from
from apps.widgets.planet_icon_palette import PRESETS, scheme_passes
from apps.widgets.planet_svg_provider import renderers_for, paint_renderers, PASSES
from libaditya.optional_bodies import BODY_BY_NAME
from ui.qt_theme import scaled_area_px


def _tag_area(widget, area):
    """Give a QSS-styled widget its OWN font-size and record the font area, so it
    tracks the Font Sizes setting instead of freezing at the universal qt-material
    13px rule (the O-6 trap). The `_c038_font_area` property is the contract read
    by the parent Settings section's _replay_fonts() on a live font change
    (settings_tab._replay_fonts recurses into this embedded widget). td-iaqm.3 G6.
    """
    css = widget.styleSheet()
    widget.setStyleSheet((css + f" font-size: {scaled_area_px(area)}px;").strip())
    widget.setProperty("_c038_font_area", area)
    return widget


def _form_label(text, area='info_text'):
    """A QFormLayout row label built explicitly so it honours the font settings.

    The editor is a nested sub-panel; its row labels follow 'info_text' (secondary
    text) rather than the 'buttons' area used by the parent settings section's own
    control rows, per the td-iaqm.3 G6 mapping (labels -> info_text, controls ->
    buttons)."""
    return _tag_area(QLabel(text), area)


class PaletteCombo(QComboBox):
    def showPopup(self):
        self.view().setFont(self.font())
        self.view().setMinimumWidth(self.sizeHint().width())
        super().showPopup()


def readable_combo(items):
    combo = PaletteCombo()
    combo.addItems(items)
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    combo.setMinimumContentsLength(18)
    combo.setMinimumWidth(210)
    view = QListView(combo)
    view.setSpacing(4)
    combo.setView(view)
    view.setStyleSheet("QListView::item { padding: 6px 12px; }")
    return combo


class IconPreview(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setFixedSize(72, 72)

    def paintEvent(self, event):
        name = self.editor.body.currentText()
        pack = 'simple-planets' if name in PLANET_NAMES else 'optional-symbols'
        scheme = self.editor.colors.get(name)
        # td-kdbb: preview an unset optional body as the shared two-tone default
        # (PASSES), matching the chart's passes_for, never a flat black pass.
        if scheme is None and name in BODY_BY_NAME:
            passes = PASSES
        else:
            passes = scheme_passes(scheme, name in PLANET_NAMES)
        renderers = renderers_for(pack, name, passes)
        if renderers:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_renderers(painter, QRectF(6, 6, 60, 60), renderers)
            painter.end()


class PlanetIconColors(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.colors = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.body = readable_combo(ICON_NAMES)
        form.addRow(_form_label('Body:'), self.body)
        self.preset = readable_combo(['Solid black (default)'] + [p[0] for p in PRESETS] + ['Custom colors'])
        form.addRow(_form_label('Color scheme:'), self.preset)
        self.outer = _tag_area(QPushButton(), 'buttons')
        self.inner = _tag_area(QPushButton(), 'buttons')
        form.addRow(_form_label('Outer frame:'), self.outer)
        form.addRow(_form_label('Inside / solid color:'), self.inner)
        layout.addLayout(form)
        self.preview = IconPreview(self)
        layout.addWidget(self.preview)
        self.apply_all = _tag_area(QPushButton('Use this scheme for all 22 bodies'), 'buttons')
        layout.addWidget(self.apply_all)
        row = QHBoxLayout()
        self.default = _tag_area(QPushButton('Reset this body'), 'buttons')
        self.reset = _tag_area(QPushButton('Reset all to black'), 'buttons')
        row.addWidget(self.default); row.addWidget(self.reset); row.addStretch()
        layout.addLayout(row)
        self.status = _tag_area(QLabel(), 'info_text')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        hint = _tag_area(QLabel('Choose a preset or edit the two colors. To use one color, select Solid black and change the inside color. Apply saves your changes.'), 'info_text')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.body.currentIndexChanged.connect(self.refresh)
        self.preset.activated.connect(self.select_preset)
        self.outer.clicked.connect(lambda: self.pick_color('outer'))
        self.inner.clicked.connect(lambda: self.pick_color('inner'))
        self.default.clicked.connect(lambda: self.set_color(None))
        self.reset.clicked.connect(lambda: self.load({}))
        self.apply_all.clicked.connect(self.copy_to_all)
        self.refresh()

    def load(self, colors):
        self.colors = colors_from(colors)
        self.refresh()

    def set_color(self, color):
        name = self.body.currentText()
        if color is None:
            self.colors.pop(name, None)
        else:
            self.colors.update(colors_from({name: color}))
        self.refresh()

    def select_preset(self, index):
        if index == 0:
            self.set_color(None)
        elif 1 <= index <= len(PRESETS):
            _, outer, inner = PRESETS[index - 1]
            self.set_color({'outer': outer, 'inner': inner})
        else:
            value = self.colors.get(self.body.currentText(), '#000000')
            self.set_color(value if isinstance(value, dict) else {'outer': '#000000', 'inner': value})

    def pick_color(self, component):
        value = self.colors.get(self.body.currentText(), '#000000')
        initial = value.get(component) if isinstance(value, dict) else value
        color = QColorDialog.getColor(QColor(initial), self, 'Outer frame color' if component == 'outer' else 'Inside color')
        if color.isValid():
            if isinstance(value, dict):
                self.set_color(dict(value, **{component: color.name()}))
            else:
                self.set_color(color.name())

    def copy_to_all(self):
        value = self.colors.get(self.body.currentText(), '#000000')
        self.colors = {name: deepcopy(value) for name in ICON_NAMES}
        self.refresh()
        self.status.setText('Scheme set for all 22 bodies, including additional bodies. Apply to save.')

    def refresh(self, *_):
        value = self.colors.get(self.body.currentText(), '#000000')
        pair = isinstance(value, dict)
        index = 0 if value == '#000000' else len(PRESETS) + 1
        if pair:
            index = next((i + 1 for i, (_, a, b) in enumerate(PRESETS)
                          if value == {'outer': a, 'inner': b}), len(PRESETS) + 1)
        self.preset.setCurrentIndex(index)
        self.outer.setEnabled(pair)
        self.outer.setText(value['outer'] if pair else 'Not used — solid color')
        self.inner.setText(value['inner'] if pair else value)
        self.status.setText(f'{self.body.currentText()}: ' + ('two-tone' if pair else 'solid color'))
        self.preview.update()
