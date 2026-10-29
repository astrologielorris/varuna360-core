# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The active filters (SPEC-FIND-005 §3.4, §3.2 retained filters).

One kit ``Chip`` per filter, joined by small "AND" separators, each with an
x, and CLEAR FILTERS at the end; the row wraps to several lines when narrow
(a flow layout). A chip carries the ``ADV`` tag when its filter is outside
the Easy set (``picker_model.is_easy`` on the raw ``Filter``) and an amber
dot with the host's tooltip when its group is not computed. Texts come from
``picker_model.chip_text`` in the model's system and naming; a filter the
picker cannot load keeps a chip (still searched) labelled by ``path_text``.

``path_text`` lives here (moved from ``filter_rows.py``, plan W6).

API
---
``FilterChips(model=None)``

Methods: ``set_filters(filters)``, ``filters() -> tuple[Filter, ...]``,
``relabel(model)``, ``set_not_computed({index: tooltip})``, ``chips()``,
``refresh_theme()``, ``refresh_metrics()``.

Signals: ``changed()`` (a user removal or CLEAR, after the list changed),
``edit_requested(int, Filter)`` (a chip clicked), ``removed(int)`` (x),
``cleared()`` (CLEAR FILTERS).

Host wiring (W6): ``chips.edit_requested`` -> ``picker.load_filter(f)``;
``chips.changed`` -> ``_refresh_results()``; ``picker.filter_added`` ->
``chips.set_filters(chips.filters() + (f,))``; ``picker.filter_saved`` ->
replace the equal filter; ``relabel(picker.model())`` after a context change.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

from core.chart_search import facets
from core.chart_search.errors import InvariantError
from core.chart_search.facets import Path
from core.chart_search.search import Filter
from core.chart_search.system import SearchSystem
from core.chart_search.taxonomy import Naming
from panels.find_chart import kit
from panels.find_chart import picker_model as pm
from panels.find_chart.picker_model import PickerModel
from ui.qt_theme import scaled_area_px

ARROW = " → "
NOT_EDITABLE_TIP = "This filter cannot be edited in the picker. It is still searched."
EDIT_TIP = "Click to edit this filter"


# ------------------------------------------------------------------ pure logic


def path_text(path: Path, system: SearchSystem, naming: Naming) -> str:
    """``Planets: Sun → Signs: Leo``; a menu step is its label alone."""
    parts: list[str] = []
    for index, step in enumerate(path):
        name = facets.facet_label(step.facet, system)
        if step.pick is None:
            parts.append(name)
            continue
        offered = facets.choices(path[:index], step.facet, system.mode, naming)
        label = next((c.label for c in offered if c.pick == step.pick), None)
        if label is None:
            raise InvariantError(
                f"invariant: {step.pick!r} is a choice of {step.facet.key!r}"
            )
        parts.append(f"{name}: {label}")
    return ARROW.join(parts)


def chip_label(model: PickerModel | None, f: Filter) -> str:
    """The chip text: ``chip_text`` when the picker loads the filter, else the
    canonical path's text, else the filter's own form."""
    if model is None:
        return str(f)
    try:
        return pm.chip_text(model, f)
    except Exception:  # noqa: BLE001 - a chip label never raises
        pass
    try:
        return path_text(facets.path_of(f), model.system, model.naming)
    except Exception:  # noqa: BLE001
        return str(f)


def editable(model: PickerModel | None, f: Filter) -> bool:
    if model is None:
        return False
    try:
        model.load(f)
    except Exception:  # noqa: BLE001 - refused or invalid: not editable
        return False
    return True


FlowLayout = kit.FlowLayout  # moved to the kit (review r5 #4); kept for imports


# ------------------------------------------------------------------ widget


class _AndLabel(QLabel):
    def __init__(self):
        super().__init__("AND")
        self.setObjectName("fc_chips_and")
        self.setAlignment(Qt.AlignCenter)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = kit.tokens()
        px = max(6, round(scaled_area_px("info_text") * 0.84))
        self.setStyleSheet(
            f"color: {t['muted'].name()}; font-size: {px}px; font-weight: 650;"
            " letter-spacing: 0.1em; background: transparent;"
        )
        self.setFixedHeight(round(24 * kit.area_fs("info_text")))


class FilterChips(QWidget):
    changed = Signal()
    edit_requested = Signal(int, object)
    removed = Signal(int)
    cleared = Signal()

    def __init__(self, model: PickerModel | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("fc_chips")
        self._model = model
        self._filters: tuple[Filter, ...] = ()
        self._not_computed: dict[int, str] = {}
        self._chips: list[kit.Chip] = []
        self._ands: list[_AndLabel] = []
        self._flow = FlowLayout(self)
        self.caption = kit.SectionHeader("Active")
        m = kit.metrics()
        self.clear_button = kit.KitSegment("chips_clear", "CLEAR FILTERS", m,
                                           tooltip="Remove every filter")
        self.clear_button.clicked.connect(self._on_clear)
        self.clear_cluster = kit.kit_cluster([self.clear_button], m)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self._rebuild()

    # -- API ----------------------------------------------------------------
    def filters(self) -> tuple[Filter, ...]:
        return self._filters

    def set_filters(self, filters: Iterable[Filter]) -> None:
        self._filters = tuple(filters)
        self._not_computed = {}
        self._rebuild()

    def relabel(self, model: PickerModel | None) -> None:
        self._model = model
        self._rebuild()

    def set_not_computed(self, dots: Mapping[int, str]) -> None:
        self._not_computed = {i: text for i, text in dots.items() if 0 <= i < len(self._filters)}
        self._sync_dots()

    def chips(self) -> list[kit.Chip]:
        return list(self._chips)

    def label(self, f: Filter) -> str:
        """``f`` as a chip would read ("Sun · Signs · Indra"): the Ask AI
        sheet names its changes the same way (SPEC-FIND-006)."""
        return chip_label(self._model, f)

    def texts(self) -> list[str]:
        return [c.text() for c in self._chips]

    # -- build --------------------------------------------------------------
    def _rebuild(self) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            w = item.widget()
            if w is not None and w not in (self.caption, self.clear_cluster):
                w.setParent(None)
                w.deleteLater()
        self._chips, self._ands = [], []
        self._flow.addWidget(self.caption)
        for i, f in enumerate(self._filters):
            if i:
                sep = _AndLabel()
                self._flow.addWidget(sep)
                self._ands.append(sep)
            chip = kit.Chip(chip_label(self._model, f), closable=True, active=True,
                            adv=not pm.is_easy(f))
            chip.setObjectName(f"fc_chip{i}")
            chip.setFocusPolicy(Qt.StrongFocus)
            chip.clicked.connect(lambda _c=False, i=i: self._on_clicked(i))
            chip.close_clicked.connect(lambda i=i: self._on_remove(i))
            self._flow.addWidget(chip)
            self._chips.append(chip)
        self._flow.addWidget(self.clear_cluster)
        empty = not self._filters
        self.caption.setVisible(not empty)
        self.clear_cluster.setVisible(not empty)
        self._sync_dots()
        self.refresh_metrics()

    def _sync_dots(self) -> None:
        for i, chip in enumerate(self._chips):
            text = self._not_computed.get(i)
            chip.set_dot("amber" if text else "")
            f = self._filters[i]
            base = EDIT_TIP if editable(self._model, f) else NOT_EDITABLE_TIP
            chip.setToolTip(f"{text}\n{base}" if text else base)

    # -- events -------------------------------------------------------------
    def _on_clicked(self, index: int) -> None:
        if 0 <= index < len(self._filters):
            self.edit_requested.emit(index, self._filters[index])

    def _on_remove(self, index: int) -> None:
        if not 0 <= index < len(self._filters):
            return
        dots = {(i if i < index else i - 1): t for i, t in self._not_computed.items() if i != index}
        self._filters = self._filters[:index] + self._filters[index + 1:]
        self._rebuild()
        self._not_computed = dots
        self._sync_dots()
        self.removed.emit(index)
        self.changed.emit()

    def _on_clear(self) -> None:
        if not self._filters:
            return
        self._filters = ()
        self._not_computed = {}
        self._rebuild()
        self.cleared.emit()
        self.changed.emit()

    # -- style --------------------------------------------------------------
    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._flow.heightForWidth(width)

    def refresh_theme(self) -> None:
        self.caption.refresh_theme()
        for sep in self._ands:
            sep.refresh_theme()
        for chip in self._chips:
            chip.update()
        self.clear_button.update()

    def refresh_metrics(self) -> None:
        fs = kit.area_fs("info_text")
        self._flow.set_spacing(round(6 * fs), round(6 * fs))
        self.clear_cluster.set_metrics(kit.metrics())
        for chip in self._chips:
            chip.refresh_metrics()
        self.refresh_theme()
        self._flow.invalidate()
        self.updateGeometry()


__all__ = ("FilterChips", "FlowLayout", "path_text", "chip_label", "editable")
