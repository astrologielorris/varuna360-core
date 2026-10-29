# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The search-system bar (design.md §4.3, §4.9; SPEC-FIND-004 §3.2).

It follows the app ("same as app") until the user changes a field; that field
is then pinned (a visible mark and "Reset to app"). The pins are Find Chart's
own setting (``PINS_KEY``), so the bar reopens as the user left it; it never
writes the app's zodiac settings. ``inline=True`` exposes every field directly
in Advanced, in a responsive grid. The legacy standalone layout keeps the core
fields on the System line; the
Human Design frame and the Cards of Truth order sit on a second line behind a
"More" toggle, collapsed by default, whose label names any of them that is
pinned (system-bar.md D16, D19). The ayanamsa field shows the three common
ids, then a "More Ayanamsas" submenu with the rest (D20).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.ayanamsa_data import AYANAMSA_OPTIONS
from core.chart_search.errors import BadSystemError
from core.chart_search.system import (
    CORE_FIELDS,
    ECLIPTIC_GC_MID_MULA_ID,
    ECLIPTIC_VEDANGA_ID,
    EQUATORIAL_DHRUVA_ID,
    EQUATORIAL_VEDANGA_ID,
    CotPlanetOrder,
    Field,
    HdFrame,
    Mode,
    SearchSystem,
    valid_ayanamsa_ids,
)
from core.hd_model import hd_frame_for
from core.house_systems import HOUSE_SYSTEM_CODES, house_system_label
from managers.settings_manager import get_settings
from panels.find_chart.combos import MenuCombo, ReadableCombo
from panels.find_chart import kit
from ui.qt_theme import get_secondary_button_style, get_theme_colors, scaled_area_px

#: The second line's fields, in order: (caption, the toggle's short name).
MORE_FIELDS: Mapping[Field, tuple[str, str]] = {
    Field.HD_FRAME: ("Human Design:", "HD"),
    Field.COT_PLANET_ORDER: ("Cards of Truth:", "Cards"),
}
#: Captions for the independent core fields in form and inline layouts.
FORM_CAPTIONS: Mapping[Field, str] = {
    Field.MODE: "Zodiac:",
    Field.AYANAMSA_ID: "Ayanamsa:",
    Field.HOUSE_SYSTEM: "Houses:",
}
MODE_LABELS: Mapping[Mode, str] = {
    Mode.ADITYA: "Aditya Circle",
    Mode.TROPICAL_CLASSIC: "Tropical Classic",
    Mode.SIDEREAL: "Sidereal",
}
#: The nakshatra-division ids, named for their division; ``AYANAMSA_OPTIONS``
#: has one entry for each equatorial id and none for its ecliptic counterpart.
AYANAMSA_LABELS: Mapping[int, str] = {
    ECLIPTIC_GC_MID_MULA_ID: "Ecliptic GC mid-Mula",
    EQUATORIAL_DHRUVA_ID: "Equatorial Dhruva GC mid-Mula",
    ECLIPTIC_VEDANGA_ID: "Ecliptic Vedanga Jyotisha",
    EQUATORIAL_VEDANGA_ID: "Equatorial Vedanga Jyotisha",
}
#: system-bar.md D20: the ayanamsas on the menu itself, in order; the rest of
#: ``valid_ayanamsa_ids()`` sit in the ``MORE_AYANAMSAS`` submenu.
COMMON_AYANAMSA_IDS: tuple[int, ...] = (
    1,
    ECLIPTIC_VEDANGA_ID,
    EQUATORIAL_DHRUVA_ID,
)  # 1: Lahiri
MORE_AYANAMSAS = "More Ayanamsas"
COT_LABELS: Mapping[CotPlanetOrder, str] = {
    CotPlanetOrder.SOLAR_SYSTEM: "Solar System order",
    CotPlanetOrder.VEDIC: "Week Day order",
}
#: system-bar.md: the gate-1 frame named by what it computes.
HD_LABELS: Mapping[HdFrame, str] = {
    HdFrame.STANDARD: "Gate 1 at 13°15′ Scorpio (Traditional Human Design)",
    HdFrame.ADITYA: "Gate 1 at 13°15′ Vishnu (Aditya Circle)",
    HdFrame.SIDEREAL: "Sidereal: gate 1 moved by the ayanamsa",
}
#: The collapsed toggle's names for a pinned second-line value.
SHORT_LABELS: Mapping[object, str] = {
    HdFrame.STANDARD.value: "Traditional",
    HdFrame.ADITYA.value: "Aditya Circle",
    HdFrame.SIDEREAL.value: "Sidereal",
    CotPlanetOrder.SOLAR_SYSTEM.value: "Solar System",
    CotPlanetOrder.VEDIC.value: "Week Day",
}
FOLLOWING = "Same as app"
#: The settings registry key the pinned fields persist under (house rule 2).
PINS_KEY = "ui.find_chart_system_pins"
PINNED = "Pinned"
MORE = "More"


def field_items(field: Field) -> tuple[tuple[str, object], ...]:
    """``(label, value)`` per choice; the value is what ``with_values`` takes."""
    if field is Field.MODE:
        return tuple((label, mode.value) for mode, label in MODE_LABELS.items())
    if field is Field.AYANAMSA_ID:
        names = {aid: name for aid, name, _cat, _tip in AYANAMSA_OPTIONS}
        names.update(AYANAMSA_LABELS)
        return tuple((names[aid], aid) for aid in valid_ayanamsa_ids())
    if field is Field.HOUSE_SYSTEM:
        return tuple((house_system_label(key), key) for key in HOUSE_SYSTEM_CODES)
    if field is Field.COT_PLANET_ORDER:
        return tuple((label, o.value) for o, label in COT_LABELS.items())
    return tuple((label, frame.value) for frame, label in HD_LABELS.items())


def field_value(system: SearchSystem, field: Field) -> object:
    """A field as its combo item data (an enum member as its str value)."""
    value = getattr(system, field.value)
    return value.value if isinstance(value, StrEnum) else value


#: The field ``hd_frame`` replaced (varuna/52); a saved pin of it is migrated.
_OLD_HD_LEVEL = "hd_experience_level"


def _migrate_hd_level(
    saved: Mapping[str, object], app: SearchSystem
) -> dict[str, object]:
    """An old ``hd_experience_level`` pin as the ``hd_frame`` it meant: the
    frame the level gave in the bar's mode (its own mode pin, else the app's).
    An explicit ``hd_frame`` pin wins."""
    out = {name: value for name, value in saved.items() if name != _OLD_HD_LEVEL}
    if _OLD_HD_LEVEL in saved and Field.HD_FRAME.value not in out:
        mode = out.get(Field.MODE.value, app.mode.value)
        out[Field.HD_FRAME.value] = hd_frame_for(mode, saved[_OLD_HD_LEVEL])
    return out


def _saved_pins(app: SearchSystem) -> dict[Field, object]:
    """The saved pins, or none when they no longer make a system (a field or
    value this build does not know): the bar then follows the app. A migrated
    pin that equals the app's value is not a pin."""
    saved = get_settings().get(PINS_KEY, {})
    if not isinstance(saved, dict):
        return {}
    if _OLD_HD_LEVEL in saved:
        saved = _migrate_hd_level(saved, app)
        if saved.get(Field.HD_FRAME.value) == app.hd_frame.value:
            saved.pop(Field.HD_FRAME.value)
        get_settings().set(PINS_KEY, saved)
    try:
        app.with_values(saved)
        return {Field(name): value for name, value in saved.items()}
    except (BadSystemError, ValueError):
        return {}


class SystemBar(QWidget):
    changed = Signal()

    def __init__(self, app_system: Callable[[], SearchSystem], *, form: bool = False,
                 inline: bool = False) -> None:
        """``inline`` exposes all fields in a responsive grid. ``form`` keeps
        the legacy captioned form for standalone consumers."""
        super().__init__()
        self._form_mode = form
        self._inline = inline
        self._field_cells: list[QWidget] = []
        self._inline_columns = 0
        self._app_system = app_system
        self._app = app_system()
        self.pinned: dict[Field, object] = _saved_pins(self._app)
        rows = QVBoxLayout(self)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(4)
        self._line = QHBoxLayout()
        self._line.setSpacing(6)
        rows.addLayout(self._line)
        self.caption = QLabel("System:")
        self._line.addWidget(self.caption)
        self.combos: dict[Field, QComboBox | MenuCombo] = {}
        for field in CORE_FIELDS:
            self._line.addWidget(self._combo(field))
        self.state_label = QLabel(FOLLOWING)
        self.reset_btn = QPushButton("Reset to app")
        self.reset_btn.setToolTip("Follow the app's zodiac settings again")
        self.reset_btn.clicked.connect(self.reset)
        self._line.addWidget(self.state_label)
        self._line.addWidget(self.reset_btn)
        self.more_btn = QToolButton()
        self.more_btn.setCheckable(True)
        self.more_btn.setToolTip("The Human Design frame and the Cards of Truth order")
        self.more_btn.toggled.connect(self._on_more)
        self._line.addWidget(self.more_btn)
        self._line.addStretch(1)
        self.more_line = QWidget()
        more = QHBoxLayout(self.more_line)
        more.setContentsMargins(0, 0, 0, 0)
        more.setSpacing(6)
        self.more_captions: list[QLabel] = []
        for field, (caption, _short) in MORE_FIELDS.items():
            label = QLabel(caption)
            self.more_captions.append(label)
            more.addWidget(label)
            more.addWidget(self._combo(field))
        more.addStretch(1)
        self.more_line.setVisible(False)
        rows.addWidget(self.more_line)
        if inline:
            self._to_inline(rows)
        elif form:
            self._to_form(rows)
        self._show()
        self.refresh_style()

    def _to_inline(self, rows: QVBoxLayout) -> None:
        """All independent fields in Advanced, with no preset or More gate."""
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        rows.insertLayout(1, self._grid)
        self._line.removeWidget(self.more_btn)
        self.more_btn.hide()
        for field in CORE_FIELDS:
            self._line.removeWidget(self.combos[field])
            self._add_inline_field(self.combos[field], FORM_CAPTIONS[field])
        for field, (caption, _short) in MORE_FIELDS.items():
            self.more_line.layout().removeWidget(self.combos[field])
            self._add_inline_field(self.combos[field], caption)
        self.more_line.hide()

    def _add_inline_field(self, widget: QWidget, caption: str, index=None) -> None:
        cell = QWidget(self)
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        label = QLabel(caption.rstrip(":"))
        self.more_captions.append(label)
        layout.addWidget(label)
        # Closed controls can shrink; their original menus still show the full
        # choice text. Long HD/ayanamsa names must not widen a narrow panel.
        widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        widget.setMinimumWidth(0)
        layout.addWidget(widget)
        widget.show()
        if index is None:
            self._field_cells.append(cell)
        else:
            self._field_cells.insert(index, cell)
        self._inline_columns = 0
        self._reflow_inline()

    def _reflow_inline(self) -> None:
        if not self._inline:
            return
        columns = max(1, min(3, self.width() // max(1, round(240 * kit.area_fs("buttons")))))
        if columns == self._inline_columns:
            return
        for cell in self._field_cells:
            self._grid.removeWidget(cell)
        for column in range(3):
            self._grid.setColumnStretch(column, int(column < columns))
        for index, cell in enumerate(self._field_cells):
            self._grid.addWidget(cell, index // columns, index % columns)
        self._inline_columns = columns
        self.updateGeometry()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._reflow_inline()

    def _to_form(self, rows: QVBoxLayout) -> None:
        """Move the line's widgets into a captioned form, one per row."""
        self._line.removeWidget(self.caption)
        self.caption.hide()
        self._form = QFormLayout()
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        self._form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        rows.insertLayout(0, self._form)
        for field in CORE_FIELDS:
            combo = self.combos[field]
            self._line.removeWidget(combo)
            caption = QLabel(FORM_CAPTIONS[field])
            self.more_captions.append(caption)
            self._form.addRow(caption, combo)
        state = QHBoxLayout()
        state.setSpacing(6)
        for w in (self.state_label, self.reset_btn):
            self._line.removeWidget(w)
            state.addWidget(w)
        state.addStretch(1)
        self._form.addRow(state)
        self._line.removeWidget(self.more_btn)
        self._form.addRow(self.more_btn)
        # The second line's pairs become form rows too.
        old = self.more_line.layout()
        pairs = []
        while old.count():
            item = old.takeAt(0)
            if item.widget() is not None:
                pairs.append(item.widget())
        more_form = QFormLayout()
        more_form.setContentsMargins(0, 0, 0, 0)
        more_form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        more_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for caption, combo in zip(pairs[::2], pairs[1::2], strict=True):
            more_form.addRow(caption, combo)
        QWidget().setLayout(old)  # drop the old layout (Qt owns it)
        self.more_line.setLayout(more_form)

    def system(self) -> SearchSystem:
        """The app's system with the pinned fields."""
        return self._app.with_values(self.pinned)

    def app_system(self) -> SearchSystem:
        """The app's system as last read (``follow_app``), no pin applied."""
        return self._app

    def follow_app(self) -> None:
        """Re-read the app's system (its frame or settings changed)."""
        self._app = self._app_system()
        self._show()

    def set_pins(self, pins: dict[Field, object]) -> None:
        """Pin exactly ``pins`` (saved or externally supplied settings): kept
        as pinned even where they equal the app today, so they stay when the
        app changes."""
        self.pinned = dict(pins)
        self._save()
        self._show()
        self.changed.emit()

    def reset(self) -> None:
        self.pinned.clear()
        self._save()
        self._show()
        self.changed.emit()

    def _combo(self, field: Field) -> QComboBox | MenuCombo:
        combo: QComboBox | MenuCombo
        if field is Field.AYANAMSA_ID:
            combo = MenuCombo(COMMON_AYANAMSA_IDS, MORE_AYANAMSAS)
        else:
            combo = ReadableCombo()
        for label, value in field_items(field):
            combo.addItem(label, value)
        combo.currentIndexChanged.connect(lambda _index, f=field: self._on_field(f))
        self.combos[field] = combo
        return combo

    def _on_more(self, expanded: bool) -> None:
        self.more_line.setVisible(expanded)
        self._show_more()

    def _on_field(self, field: Field) -> None:
        value = self.combos[field].currentData()
        if value == field_value(self._app, field):
            self.pinned.pop(field, None)
        else:
            self.pinned[field] = value
        self._save()
        self._show_state()
        self.changed.emit()

    def add_trailing(self, widget: QWidget, caption: str = "") -> None:
        """Put ``widget`` at the end of the System line, before the stretch
        (in form mode: a row of its own after the core fields)."""
        if self._inline:
            self._add_inline_field(widget, caption, len(CORE_FIELDS))
            self.refresh_style()
            return
        if self._form_mode:
            label = QLabel(caption)
            self.more_captions.append(label)
            self._form.insertRow(len(CORE_FIELDS), label, widget)
            return
        self._line.insertWidget(self._line.count() - 1, widget)

    def _save(self) -> None:
        get_settings().set(PINS_KEY, {f.value: v for f, v in self.pinned.items()})

    def _show(self) -> None:
        """Every combo on the current system's value, signals blocked."""
        current = self.system()
        for field, combo in self.combos.items():
            combo.blockSignals(True)
            combo.setCurrentIndex(max(combo.findData(field_value(current, field)), 0))
            combo.blockSignals(False)
        self._show_state()

    def _show_state(self) -> None:
        pinned = bool(self.pinned)
        self.state_label.setText(PINNED if pinned else FOLLOWING)
        self.state_label.setToolTip(
            "Pinned: " + ", ".join(f.value.replace("_", " ") for f in self.pinned)
            if pinned
            else "The search uses the app's zodiac settings"
        )
        self.reset_btn.setVisible(pinned)
        self._show_more()
        self.refresh_style()

    def _show_more(self) -> None:
        """The toggle's label; collapsed, it names each pinned field (D19)."""
        expanded = self.more_btn.isChecked()
        names = [
            f"{short}: {SHORT_LABELS[self.pinned[field]]}"
            for field, (_caption, short) in MORE_FIELDS.items()
            if field in self.pinned and not expanded
        ]
        arrow = "▾" if expanded else "▸"
        text = f"{arrow} {MORE}" + (f" ({', '.join(names)})" if names else "")
        self.more_btn.setText(text)

    def refresh_style(self) -> None:
        font = f"font-size: {scaled_area_px('buttons')}px;"
        self.caption.setStyleSheet(font + " font-weight: bold;")
        for label in self.more_captions:
            label.setStyleSheet(font)
        for combo in self.combos.values():
            kind = "QToolButton" if isinstance(combo, MenuCombo) else "QComboBox"
            combo.setStyleSheet(f"{kind} {{ {font} }}")
        weight = " font-weight: bold;" if self.pinned else " font-style: italic;"
        self.state_label.setStyleSheet(
            f"font-size: {scaled_area_px('status')}px;{weight}"
        )
        self.reset_btn.setStyleSheet(get_secondary_button_style())
        self.more_btn.setStyleSheet(f"QToolButton {{ {font} }}")
        if self._inline:
            self._refresh_inline_style()

    def _refresh_inline_style(self) -> None:
        theme = get_theme_colors()
        px = scaled_area_px("buttons")
        height = max(26, round(px * 2.4))
        style = (
            f"QComboBox, QToolButton {{ background: {theme['secondary_light']};"
            f" color: {theme['secondary_text']}; border: 1px solid {theme['secondary_dark']};"
            f" border-radius: 6px; padding: 2px 8px; font-size: {px}px;"
            f" height: {height}px; min-height: {height}px; max-height: {height}px; }}"
            f"QComboBox:hover, QToolButton:hover {{ border-color: {theme['primary']}; }}"
            f"QAbstractItemView, QMenu, QToolTip {{ background: {theme['secondary_light']};"
            f" color: {theme['secondary_text']}; border: 1px solid {theme['secondary_dark']};"
            f" font-size: {px}px; }}"
            f"QAbstractItemView {{ selection-background-color: {theme['primary']};"
            f" selection-color: {kit.tokens()['fg_on_accent'].name()}; }}"
            f"QMenu::item:selected {{ background: {theme['primary']};"
            f" color: {kit.tokens()['fg_on_accent'].name()}; }}"
        )
        for cell in self._field_cells:
            cell.layout().itemAt(1).widget().setStyleSheet(style)
        self._grid.setHorizontalSpacing(round(12 * kit.area_fs("buttons")))
        self._grid.setVerticalSpacing(round(8 * kit.area_fs("buttons")))
        self._reflow_inline()
