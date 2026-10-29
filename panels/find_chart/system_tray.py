# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Advanced system tray (SPEC-FIND-005 §4.4).

SYSTEM: SAME AS APP | TROPICAL . PLACIDUS | SIDEREAL . LAHIRI | CUSTOM v,
over the existing ``SystemBar`` (pins, persistence, follow-the-app logic
unchanged; its fields live in the Custom sheet). The lit segment is the
preset whose pins equal the current pins exactly; any other pin set lights
CUSTOM, which then names it."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QLabel, QMenu, QWidget

from core.chart_search.system import Field
from panels.find_chart import kit
from panels.find_chart.system_bar import FOLLOWING, PINNED, SystemBar, field_items

SAME = "same"
TROPICAL = "tropical"
SIDEREAL = "sidereal"
CUSTOM = "custom"

#: Preset -> its exact pins (mode values as ``Field.MODE`` takes them).
PRESETS: Mapping[str, dict[Field, object]] = {
    SAME: {},
    TROPICAL: {Field.MODE: "tropical_classic", Field.HOUSE_SYSTEM: "placidus"},
    SIDEREAL: {Field.MODE: "sidereal", Field.AYANAMSA_ID: 1},
}
LABELS: Mapping[str, str] = {
    SAME: "SAME AS APP",
    TROPICAL: "TROPICAL · PLACIDUS",
    SIDEREAL: "SIDEREAL · LAHIRI",
    CUSTOM: "CUSTOM",
}
#: Narrow panels (T3, T4): the short labels; the tooltips keep the detail.
COMPACT_LABELS: Mapping[str, str] = {
    SAME: "APP",
    TROPICAL: "TROPICAL",
    SIDEREAL: "SIDEREAL",
    CUSTOM: "CUSTOM",
}
TIPS: Mapping[str, str] = {
    SAME: "Search in the app's zodiac settings",
    TROPICAL: "Tropical zodiac, Placidus houses",
    SIDEREAL: "Sidereal zodiac, Lahiri ayanamsa (the house system follows the app)",
    CUSTOM: "Pick each field of the search system",
}


def preset_of(pins: Mapping[Field, object]) -> str:
    """The preset whose pins equal ``pins`` exactly, else CUSTOM."""
    for key, preset in PRESETS.items():
        if dict(pins) == preset:
            return key
    return CUSTOM


def pins_text(pins: Mapping[Field, object]) -> str:
    """Short names of the pinned values ("Koch", "Sidereal, Raman")."""
    names = []
    for field in Field:
        if field in pins:
            value = pins[field]
            label = next((lbl for lbl, v in field_items(field) if v == value), str(value))
            names.append(label)
    return ", ".join(names)


class SystemTray(QWidget):
    custom_requested = Signal()

    def __init__(self, system_bar: SystemBar) -> None:
        super().__init__()
        self.system_bar = system_bar
        m = kit.metrics()
        self._compact = False
        layout = kit.FlowLayout(self, m.grp_gap, round(4 * m.fs))  # wraps (r5 #4)
        self._flow = layout
        self.caption = kit.SectionHeader("System")
        layout.addWidget(self.caption)
        self.segments: dict[str, kit.KitSegment] = {}
        for key, label in LABELS.items():
            seg = kit.KitSegment(
                "sys_" + key, label, m, icon="fc_chevr" if key == CUSTOM else "",
                tooltip=TIPS[key],
            )
            seg.clicked.connect(lambda _c=False, k=key: self._on_segment(k))
            self.segments[key] = seg
        self.cluster = kit.kit_cluster(list(self.segments.values()), m)
        layout.addWidget(self.cluster)
        # When even the compact cluster is wider than the tray (a large
        # action-button font at phone width), one segment with a menu of the
        # same presets replaces it (review r6 #9).
        self.preset_menu = kit.KitSegment(
            "sys_menu", LABELS[SAME], m, icon="fc_chevr", tooltip="Search system preset"
        )
        self.preset_menu.clicked.connect(self._open_preset_menu)
        self.preset_menu_cluster = kit.kit_cluster([self.preset_menu], m)
        self.preset_menu_cluster.hide()
        layout.addWidget(self.preset_menu_cluster)
        self.state_label = QLabel(FOLLOWING)
        layout.addWidget(self.state_label)
        self.reset = kit.KitSegment(
            "sys_reset", "RESET TO APP", m, tooltip="Follow the app's zodiac settings again"
        )
        self.reset.clicked.connect(self.system_bar.reset)
        layout.addWidget(self.reset)
        system_bar.changed.connect(self.sync)
        self.sync()

    def set_compact(self, on: bool) -> None:
        """Short preset labels on a narrow panel (§4.8)."""
        if on == self._compact:
            return
        self._compact = on
        labels = COMPACT_LABELS if on else LABELS
        for key, seg in self.segments.items():
            if key != CUSTOM:
                seg.compact_label(labels[key])
        self.sync()

    def _open_preset_menu(self) -> None:
        menu = kit.style_menu(QMenu(self))
        lit = self.lit()
        for key in (SAME, TROPICAL, SIDEREAL, CUSTOM):
            action = menu.addAction(LABELS[key])
            action.setCheckable(True)
            action.setChecked(key == lit)
            action.triggered.connect(lambda _c=False, k=key: self._on_segment(k))
        menu.exec(self.preset_menu.mapToGlobal(self.preset_menu.rect().bottomLeft()))
        menu.deleteLater()

    def menu_mode(self) -> bool:
        return not self.preset_menu_cluster.isHidden()

    def _fit(self) -> None:
        """The cluster when it fits the room the parent gives (its own width
        would follow the cluster's minimum), else the menu."""
        parent = self.parentWidget()
        width = parent.contentsRect().width() if parent is not None else self.width()
        menu = self.cluster.sizeHint().width() > max(width, 1)
        if menu != self.menu_mode():
            self.cluster.setVisible(not menu)
            self.preset_menu_cluster.setVisible(menu)
            self._flow.invalidate()
            self.updateGeometry()

    def minimumSizeHint(self):  # noqa: N802
        """Never the cluster's width: the menu can replace it, so the floor
        is the widest of the caption, the menu, the state and RESET."""
        hint = super().minimumSizeHint()
        parts = (self.caption, self.preset_menu_cluster, self.state_label, self.reset)
        widest = max(w.sizeHint().width() for w in parts if w is not None)
        return QSize(widest, hint.height())

    def event(self, e):  # noqa: D401
        if e.type() == e.Type.ParentChange and self.parentWidget() is not None:
            self.parentWidget().installEventFilter(self)
        return super().event(e)

    def eventFilter(self, obj, e):  # noqa: N802
        if obj is self.parentWidget() and e.type() == e.Type.Resize:
            self._fit()
        return False

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._fit()

    def _on_segment(self, key: str) -> None:
        if key == CUSTOM:
            self.custom_requested.emit()
        elif key == SAME:
            self.system_bar.reset()
        else:
            self.system_bar.set_pins(PRESETS[key])

    def sync(self) -> None:
        pins = self.system_bar.pinned
        lit = preset_of(pins)
        for key, seg in self.segments.items():
            seg.set_lit(key == lit)
        custom = LABELS[CUSTOM]
        if lit == CUSTOM and pins and not self._compact:
            custom = f"{custom} · {pins_text(pins)}"
        self.segments[CUSTOM].compact_label(custom)
        self.cluster.notify_state_changed()
        labels = COMPACT_LABELS if self._compact else LABELS
        self.preset_menu.compact_label(labels[lit] if lit != CUSTOM else custom)
        self.preset_menu_cluster.notify_state_changed()
        self._fit()
        self.state_label.setText(PINNED if pins else FOLLOWING)
        self.reset.setVisible(bool(pins))
        self.refresh_style()

    def lit(self) -> str:
        return preset_of(self.system_bar.pinned)

    def refresh_style(self) -> None:
        t = kit.tokens()
        from ui.qt_theme import scaled_area_px

        weight = "font-weight: bold;" if self.system_bar.pinned else "font-style: italic;"
        self.state_label.setStyleSheet(
            f"color: {t['secondary_text'].name()}; font-size: {scaled_area_px('buttons')}px; {weight}"
        )
        self.caption.refresh_theme()

    def refresh_metrics(self) -> None:
        m = kit.metrics()
        self.cluster.set_metrics(m)
        self.preset_menu_cluster.set_metrics(m)
        self.reset.set_metrics(m)
        self._fit()
        self._flow.set_spacing(m.grp_gap, round(4 * m.fs))
        self.refresh_style()
