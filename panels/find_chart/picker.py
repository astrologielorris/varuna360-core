# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The filter picker widget (SPEC-FIND-005 §3.3, §4.5, INV-5).

One picker for Easy and Advanced over ``picker_model.PickerModel``: columns
1 · PLACEMENT, 2 · ATTRIBUTE, 3 · TARGET and, in Advanced, 4 · OPTION (renamed
from Body / Fact / Value / Detail, Lorris 2026-10-25; one labelled
combo per ``DetailSlot``; ``OMITTED`` shows as "Any"). Easy shows the three
list columns, the locked rail ("Varga D1 / Pada: any / Whole sign houses"),
column footers "+N in Advanced: ..." counted by the model, and four
suggestion chips that add their filter directly. The NEW FILTER line previews
the filter; ADD FILTER is enabled only while the selection compiles.

The widget is unwired: the host keeps all policy (level, search, compute) and
listens to the signals.

API
---
``FilterPicker(level, system, naming, narrow=None)``

Methods:
    ``set_level(level)``                 "easy" / "advanced"; Easy clamps the
                                         selection to the Easy set.
    ``set_context(system, naming, narrow)`` rebuilds the model in place and
                                         keeps the picks still valid.
    ``set_system_text(text)``            the set line's "Uses the app settings:
                                         <text>, D1." (Easy).
    ``set_not_computed(fact_keys)``      amber dots on those FACT keys.
    ``set_drill_down(on)``               T3/T4: one column at a time, BACK,
                                         breadcrumb, "Step k of n".
    ``load_filter(f, fact_hint=None)``   edit a chip: ADD reads SAVE FILTER;
                                         returns False (and emits
                                         ``edit_refused``) when the model
                                         refuses it, nothing changed.
    ``cancel_edit()``                    as Esc or the x.
    ``selection()`` / ``set_selection(sel)`` / ``current_filter()``
    ``model()``, ``is_editing()``, ``crumbs()``, ``step()``
    ``refresh_theme()``, ``refresh_metrics()``

Signals:
    ``filter_added(Filter)``             ADD, Enter / double click on a value,
                                         a suggestion chip.
    ``filter_saved(old, new)``           SAVE FILTER in edit mode.
    ``edit_cancelled()``                 Esc or x in edit mode.
    ``edit_refused(Filter, reason)``     ``load_filter`` refused the filter.
    ``level_requested(str)``             the set line / rail links, and a
                                         non-Easy filter loaded in Easy (the
                                         picker has switched to Advanced; the
                                         host syncs the toolbar and trail).

Host wiring (W6): construct with the panel's ``search_context()``; on a
context or level change call ``set_context`` / ``set_level``; connect
``filter_added`` to append a chip and ``_refresh_results()``,
``filter_saved`` to replace the chip, ``FilterChips.edit_requested`` to
``load_filter(f, fact_hint)``; ``ResponsiveController`` tier T3/T4 to
``set_drill_down(True)``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace

from PySide6.QtCore import QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from apps.widgets.action_bar.bar_types import Role
from core.chart_search.errors import BadFilterError
from core.chart_search.search import Filter
from core.chart_search.system import SearchSystem
from core.chart_search.taxonomy import Naming
from panels.find_chart import kit
from panels.find_chart import picker_model as pm
from panels.find_chart.combos import ReadableCombo
from panels.find_chart.picker_model import OMITTED, PickerModel, Selection, ValueItem
from ui.qt_theme import scaled_area_px

NOT_COMPUTED_TIP = "Not computed yet: Compute in Library"
REFUSED_REASON = "This filter cannot be edited in the picker. It is still searched."
EMPTY_PREVIEW = "Pick a placement, an attribute and a target"
NO_DETAIL = "No option for this attribute."
RAIL_LOCKS = ("Varga D1", "Pada: any", "Whole sign houses")
RAIL_WHY = "Easy keeps these fixed."
ANY = "Any"
SEP = " · "

BODY, FACT, VALUE, DETAIL = 0, 1, 2, 3
TITLES = ("1 · Placement", "2 · Attribute", "3 · Target", "4 · Option")
CRUMB_BLANKS = ("Placement", "Attribute", "Target", "Option")

# ------------------------------------------------------------------ pure logic


@dataclass(frozen=True)
class Row:
    """One painted list row. ``key``: body key, fact key or Pick."""

    key: object
    label: str
    adv: bool = False
    dot: bool = False
    any: bool = False
    sub: str = ""
    tooltip: str = ""


Groups = tuple[tuple[str, tuple[Row, ...]], ...]


def _group(rows: Iterable[tuple[str, Row]]) -> Groups:
    """Consecutive rows under one header become one group."""
    out: list[tuple[str, list[Row]]] = []
    for header, row in rows:
        if not out or out[-1][0] != header:
            out.append((header, []))
        out[-1][1].append(row)
    return tuple((h, tuple(r)) for h, r in out)


def body_groups(model: PickerModel) -> Groups:
    adv = model.level == pm.ADVANCED
    return _group(
        (b.section, Row(b.key, b.label, adv=adv and not b.easy,
                        any=b.key in (pm.ANY_PLANET, pm.ANY_CUSP, pm.ANY_SUBJECT, pm.ANY_POSITION)))
        for b in model.bodies()
    )


def fact_groups(model: PickerModel, body: str | None, not_computed: frozenset[str] = frozenset()) -> Groups:
    if body is None:
        return ()
    adv = model.level == pm.ADVANCED
    return _group(
        (x.header, Row(x.key, x.label, adv=adv and not x.easy, dot=x.key in not_computed,
                       tooltip=NOT_COMPUTED_TIP if x.key in not_computed else ""))
        for x in model.facts(body)
    )


def value_groups(model: PickerModel, sel: Selection) -> Groups:
    if sel.body is None or sel.fact is None:
        return ()
    rows = []
    for v in model.values(sel.body, sel.fact, keep=sel.value):
        rows.append((v.section or "", Row(
            v.pick, v.label, any=v.pick.value is None,
            sub="" if v.stored else pm.NOT_STORED,
            tooltip="" if v.stored else pm.NOT_STORED,
        )))
    return _group(rows)


def footer_text(model: PickerModel, column: str, body: str | None = None, shown: int = 3) -> str:
    """Easy footer: "+N in Advanced: a, b, c ..." from the model (§3.3)."""
    if model.level != pm.EASY:
        return ""
    if column == "fact" and body is None:
        return ""
    n, names = model.extra_in_advanced(column, body)
    if not n:
        return ""
    short = ", ".join(names[:shown]) + (" ..." if n > shown else "")
    return f"+{n} in Advanced: {short}"


def set_line(model: PickerModel, body: str | None) -> tuple[str, str, str]:
    """(pill, counts, dim) of the set line."""
    nb = len(model.bodies())
    nf = len(model.facts(body or pm.ANY_PLANET))
    if model.level == pm.ADVANCED:
        return ("FULL SET", f"{nb} placements · {nf} attributes · targets · Option",
                "Same picker as Easy. ADV marks what Easy leaves out.")
    return ("EASY SET", f"{nb} placements · {nf} attributes · targets", "")


def _label_of(groups: Groups, key) -> str | None:
    return next((r.label for _h, rows in groups for r in rows if r.key == key), None)


def detail_summary(model: PickerModel, sel: Selection) -> str:
    """The detail crumb: each picked slot's label, "Any" when none."""
    parts = []
    for slot in model.details(sel):
        if slot.selected is OMITTED:
            continue
        label = next((i.label for i in slot.items
                      if isinstance(i, ValueItem) and i.pick == slot.selected), "")
        if label:
            parts.append(label)
    return ", ".join(parts) if parts else ANY


def clamp_easy(model: PickerModel, sel: Selection) -> Selection:
    """Easy keeps only Easy picks and no Detail (D1, pada any)."""
    body, fact, value = sel.body, sel.fact, sel.value
    if body is not None and body not in pm.EASY_SUBJECTS:
        body = fact = value = None
    if body is not None and fact is not None and fact not in {x.key for x in model.facts(body)}:
        fact = value = None
    return Selection(body, fact, value, ())


def carry(model: PickerModel, sel: Selection) -> Selection:
    """Keep each pick while the (new) model still offers it, else reset it and
    what follows (§3.3 Detail: "keeps later picks while still offered")."""
    body, fact, value = sel.body, sel.fact, sel.value
    if body is not None and body not in {b.key for b in model.all_bodies()}:
        return Selection()
    if body is None:
        return Selection()
    if fact is not None and fact not in {x.key for x in model.all_facts(body)}:
        return Selection(body)
    if fact is None:
        return Selection(body)
    if value is not None and value not in {v.pick for v in model.values(body, fact, keep=value)}:
        return Selection(body, fact)
    return Selection(body, fact, value, sel.details)


def preview_text(model: PickerModel, sel: Selection) -> str:
    f = model.filter(sel)
    if f is None:
        return EMPTY_PREVIEW
    try:
        return pm.chip_text(model, f)
    except Exception:  # noqa: BLE001 - the preview never raises
        return str(f)


# ------------------------------------------------------------------ painting

ROLE_ROW = Qt.ItemDataRole.UserRole + 1
ROLE_HEADER = Qt.ItemDataRole.UserRole + 2


def _item_fs() -> float:
    return kit.area_fs("info_text")


def _row_h() -> int:
    return round(23 * _item_fs())


class _Delegate(QStyledItemDelegate):
    """Header rows (uppercase, muted) and item rows: label, muted sub text,
    ADV tag, amber dot, chevron; the picked row in the accent."""

    def __init__(self, column: PickerColumn):
        super().__init__(column)
        self._column = column

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        fs = _item_fs()
        if index.data(ROLE_HEADER):
            return QSize(10, round(22 * kit.area_fs("panel_titles")))
        return QSize(10, round(23 * fs))

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        t = kit.tokens()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        base_font = QFont(option.font)
        rect = QRectF(option.rect)
        header = index.data(ROLE_HEADER)
        if header:
            fs = kit.area_fs("panel_titles")
            font = QFont(base_font)
            font.setPixelSize(max(6, round(9.5 * fs)))
            font.setWeight(QFont.DemiBold)
            font.setLetterSpacing(QFont.PercentageSpacing, 110)
            p.setFont(font)
            p.setPen(t["muted"])
            p.drawText(rect.adjusted(8 * fs, 0, -4, -2), Qt.AlignLeft | Qt.AlignBottom,
                       str(header).upper())
            p.restore()
            return
        row: Row = index.data(ROLE_ROW)
        fs = _item_fs()
        box = rect.adjusted(4 * fs, 0, -4 * fs, 0)
        on = row.key == self._column.selected_key
        hover = bool(option.state & QStyle.State_MouseOver)
        if on:
            p.setPen(Qt.NoPen)
            p.setBrush(t["primary"])
            p.drawRoundedRect(box, 5 * fs, 5 * fs)
        elif hover:
            p.setPen(Qt.NoPen)
            p.setBrush(t["ctl_h"])
            p.drawRoundedRect(box, 5 * fs, 5 * fs)
        current = (self._column.view.hasFocus() and self._column.view.currentIndex() == index)
        if current and not on:
            p.setPen(t["ring"])
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 5 * fs, 5 * fs)
        fg = t["fg_on_accent"] if on else (t["secondary_text"] if row.any else t["primary_text"])
        muted = kit._alpha(t["fg_on_accent"], 0.75) if on else t["muted"]
        # right side, painted right to left
        x_right = box.right() - 8 * fs
        if self._column.chevrons:
            d = 8 * fs
            kit.draw_icon(p, "fc_chevr", QRectF(x_right - d, box.center().y() - d / 2, d, d),
                          kit._alpha(fg, 0.5))
            x_right -= d + 6 * fs
        if row.dot:
            d = 6 * fs
            p.setPen(Qt.NoPen)
            p.setBrush(t["gold"])
            p.drawEllipse(QRectF(x_right - d, box.center().y() - d / 2, d, d))
            x_right -= d + 6 * fs
        if row.adv:
            tag_font = QFont(base_font)
            tag_font.setPixelSize(max(5, round(8.5 * fs)))
            tag_font.setWeight(QFont.Bold)
            tm = QFontMetrics(tag_font)
            w = tm.horizontalAdvance("ADV") + 8 * fs
            tag = QRectF(x_right - w, box.center().y() - 6.5 * fs, w, 13 * fs)
            p.setPen(muted)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(tag.adjusted(0.5, 0.5, -0.5, -0.5), 3 * fs, 3 * fs)
            p.setFont(tag_font)
            p.drawText(tag, Qt.AlignCenter, "ADV")
            x_right -= w + 6 * fs
        font = QFont(base_font)
        font.setPixelSize(max(6, round(12 * fs)))
        font.setItalic(row.any)
        fm = QFontMetrics(font)
        left = box.left() + 8 * fs
        avail = max(0.0, x_right - left)
        label = fm.elidedText(row.label, Qt.ElideRight, int(avail))
        p.setFont(font)
        p.setPen(fg)
        p.drawText(QRectF(left, box.top(), avail, box.height()), Qt.AlignVCenter | Qt.AlignLeft, label)
        used = fm.horizontalAdvance(label)
        if row.sub and used + 10 * fs < avail:
            sub_font = QFont(font)
            sub_font.setItalic(False)
            sub_font.setPixelSize(max(5, round(10.5 * fs)))
            sm = QFontMetrics(sub_font)
            room = avail - used - 5 * fs
            p.setFont(sub_font)
            p.setPen(muted)
            p.drawText(QRectF(left + used + 5 * fs, box.top(), room, box.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, sm.elidedText(row.sub, Qt.ElideRight, int(room)))
        p.restore()


class _ListView(QListView):
    """A column's list: Up/Down within, Left/Right to the next column, Enter
    picks, typing filters; Esc clears the typed filter, else goes up."""

    nav = Signal(int)
    enter = Signal(QModelIndex)
    typed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_text = ""

    def keyPressEvent(self, e):  # noqa: N802
        key = e.key()
        if key in (Qt.Key_Left, Qt.Key_Right):
            self.nav.emit(-1 if key == Qt.Key_Left else 1)
            e.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.enter.emit(self.currentIndex())
            e.accept()
            return
        if key == Qt.Key_Escape:
            if self.filter_text:
                self.filter_text = ""
                self.typed.emit("")
                e.accept()
                return
            e.ignore()
            return
        if key == Qt.Key_Backspace and self.filter_text:
            self.filter_text = self.filter_text[:-1]
            self.typed.emit(self.filter_text)
            e.accept()
            return
        text = e.text()
        if text and text.isprintable() and not (e.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            self.filter_text += text
            self.typed.emit(self.filter_text)
            e.accept()
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):  # noqa: N802
        super().focusInEvent(e)
        self.viewport().update()

    def focusOutEvent(self, e):  # noqa: N802
        super().focusOutEvent(e)
        self.viewport().update()


def _label_css(color_key: str, area: str, scale: float = 1.0, weight: int = 400) -> str:
    t = kit.tokens()
    px = max(6, round(scaled_area_px(area) * scale))
    return (f"color: {t[color_key].name()}; font-size: {px}px; font-weight: {weight};"
            " background: transparent;")


class PickerColumn(QWidget):
    """One list column: caption + count, the painted list, the footer."""

    picked = Signal(object)
    activated = Signal(object)

    def __init__(self, index: int, chevrons: bool = True, parent=None):
        super().__init__(parent)
        self.index = index
        self.chevrons = chevrons
        self.selected_key: object = None
        self.caption = kit.SectionHeader(TITLES[index])
        self.count = QLabel()
        self.view = _ListView(self)
        self.view.setObjectName(f"fc_picker_col{index}")
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setMouseTracking(True)
        self.view.setAttribute(Qt.WA_Hover, True)
        self.view.setSelectionMode(QAbstractItemView.NoSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setUniformItemSizes(False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._model = QStandardItemModel(self)
        self.view.setModel(self._model)
        self.view.setItemDelegate(_Delegate(self))
        self.footer = QLabel()
        self.footer.setObjectName(f"fc_picker_foot{index}")
        self.footer.setWordWrap(False)
        self.footer.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        head = QHBoxLayout()
        head.setContentsMargins(10, 7, 10, 5)
        head.addWidget(self.caption)
        head.addStretch(1)
        head.addWidget(self.count)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(head)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.footer)
        self._count_text = ""
        self.view.clicked.connect(self._on_clicked)
        self.view.doubleClicked.connect(self._on_double)
        self.view.enter.connect(self._on_enter)
        self.view.typed.connect(self._apply_filter)
        self.refresh_theme()

    # -- content ------------------------------------------------------------
    def set_groups(self, groups: Groups, selected, count_text: str = "") -> None:
        self.selected_key = selected
        self._count_text = count_text
        if getattr(self, "_groups", None) == groups:
            # Preserve indexes between the first and second mouse clicks.
            # Clearing this model on selection prevents QListView from
            # recognizing the subsequent double-click.
            current = QModelIndex()
            for i in range(self._model.rowCount()):
                index = self._model.index(i, 0)
                row = index.data(ROLE_ROW)
                if row is not None and row.key == selected:
                    current = index
                    break
            self.view.setCurrentIndex(current)
            if not current.isValid():
                self.view.clearSelection()
            self.count.setText(count_text)
            self.view.viewport().update()
            return
        self._groups = groups
        self._model.clear()
        current = None
        for header, rows in groups:
            if header:
                h = QStandardItem()
                h.setData(header, ROLE_HEADER)
                h.setFlags(Qt.NoItemFlags)
                self._model.appendRow(h)
            for row in rows:
                item = QStandardItem(row.label)
                item.setData(row, ROLE_ROW)
                item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if row.tooltip:
                    item.setToolTip(row.tooltip)
                self._model.appendRow(item)
                if row.key == selected:
                    current = item.index()
        self.view.filter_text = ""
        self._apply_filter("")
        if current is not None:
            self.view.setCurrentIndex(current)
            self.view.scrollTo(current)

    def set_footer(self, text: str) -> None:
        self.footer.setText(text)
        self.footer.setToolTip(text)
        self.footer.setVisible(bool(text))

    def rows(self) -> list[Row]:
        return [self._model.item(i).data(ROLE_ROW) for i in range(self._model.rowCount())
                if self._model.item(i).data(ROLE_ROW) is not None]

    def headers(self) -> list[str]:
        return [self._model.item(i).data(ROLE_HEADER) for i in range(self._model.rowCount())
                if self._model.item(i).data(ROLE_HEADER)]

    def visible_rows(self) -> list[Row]:
        return [self._model.item(i).data(ROLE_ROW) for i in range(self._model.rowCount())
                if self._model.item(i).data(ROLE_ROW) is not None and not self.view.isRowHidden(i)]

    def _apply_filter(self, text: str) -> None:
        needle = text.casefold()
        header_row = None
        header_has = False
        for i in range(self._model.rowCount()):
            item = self._model.item(i)
            if item.data(ROLE_HEADER):
                if header_row is not None:
                    self.view.setRowHidden(header_row, not header_has)
                header_row, header_has = i, False
                continue
            show = not needle or needle in item.data(ROLE_ROW).label.casefold()
            self.view.setRowHidden(i, not show)
            header_has = header_has or show
        if header_row is not None:
            self.view.setRowHidden(header_row, not header_has)
        self.count.setText(f"Typed: {text}" if text else self._count_text)
        if needle:
            first = next((self._model.index(i, 0) for i in range(self._model.rowCount())
                          if not self.view.isRowHidden(i) and self._model.item(i).data(ROLE_ROW)), None)
            if first is not None:
                self.view.setCurrentIndex(first)

    # -- events -------------------------------------------------------------
    def _row_at(self, index: QModelIndex) -> Row | None:
        return index.data(ROLE_ROW) if index.isValid() else None

    def _on_clicked(self, index: QModelIndex) -> None:
        row = self._row_at(index)
        if row is not None:
            self.picked.emit(row.key)

    def _on_double(self, index: QModelIndex) -> None:
        row = self._row_at(index)
        if row is not None:
            self.activated.emit(row.key)

    def _on_enter(self, index: QModelIndex) -> None:
        row = self._row_at(index)
        if row is not None:
            self.picked.emit(row.key)
            self.activated.emit(row.key)

    # -- style --------------------------------------------------------------
    def refresh_theme(self) -> None:
        t = kit.tokens()
        self.caption.refresh_theme()
        self.count.setStyleSheet(_label_css("muted", "info_text", 0.85))
        self.footer.setStyleSheet(
            _label_css("muted", "info_text", 0.88)
            + f" padding: 5px 10px 6px 10px;"
            f" border-top: 1px solid {t['hair_soft'].name(QColor.HexArgb)};"
        )
        handle = t["hair"].name(QColor.HexArgb)
        self.view.setStyleSheet(
            "QListView { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }"
            f"QScrollBar::handle:vertical {{ background: {handle}; border-radius: 3px; min-height: 20px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )
        self.view.viewport().update()

    def refresh_metrics(self) -> None:
        self.refresh_theme()
        self._model.layoutChanged.emit()
        self.view.doItemsLayout()


class DetailColumn(QWidget):
    """4 · OPTION: one labelled combo per slot; ``changed(key, pick)``."""

    changed = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.caption = kit.SectionHeader(TITLES[DETAIL])
        self.note = QLabel(NO_DETAIL)
        self._box = QVBoxLayout()
        self._box.setContentsMargins(0, 0, 0, 0)
        self._box.setSpacing(9)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 6)
        lay.setSpacing(6)
        lay.addWidget(self.caption)
        lay.addLayout(self._box)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.combos: dict[str, ReadableCombo] = {}
        self.labels: list[QLabel] = []
        self._items: dict[str, tuple] = {}
        self.refresh_theme()

    def set_slots(self, slots) -> None:
        while self._box.count():
            w = self._box.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.combos.clear()
        self.labels.clear()
        self._items.clear()
        for slot in slots:
            key = slot.facet.key
            label = QLabel(slot.label)
            combo = ReadableCombo()
            combo.setObjectName(f"fc_picker_detail_{key}")
            combo.setAccessibleName(slot.label)
            items = tuple(slot.items)
            for i, item in enumerate(items):
                if item is OMITTED:
                    combo.addItem(ANY)
                else:
                    combo.addItem(item.label if item.stored else f"{item.label} · {pm.NOT_STORED}")
                    if not item.stored:
                        combo.setItemData(i, pm.NOT_STORED, Qt.ToolTipRole)
                if (item is OMITTED and slot.selected is OMITTED) or (
                        item is not OMITTED and item.pick == slot.selected):
                    combo.setCurrentIndex(i)
            combo.currentIndexChanged.connect(lambda i, k=key: self._on_changed(k, i))
            kit.restyle_combo(combo)
            self._box.addWidget(label)
            self._box.addWidget(combo)
            self.labels.append(label)
            self.combos[key] = combo
            self._items[key] = items
        self.note.setVisible(not slots)
        self.refresh_theme()

    def _on_changed(self, key: str, index: int) -> None:
        items = self._items.get(key, ())
        if 0 <= index < len(items):
            item = items[index]
            self.changed.emit(key, OMITTED if item is OMITTED else item.pick)

    def refresh_theme(self) -> None:
        self.caption.refresh_theme()
        self.note.setStyleSheet(_label_css("muted", "info_text", 0.92))
        for label in self.labels:
            label.setStyleSheet(_label_css("muted", "info_text", 0.85, 600))
        for combo in self.combos.values():
            kit.restyle_combo(combo)

    def refresh_metrics(self) -> None:
        self.refresh_theme()


class LockRail(QWidget):
    """Easy's slim rail where column 4 would be (§3.3 Easy set)."""

    advanced_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fc_picker_rail")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.caption = kit.SectionHeader(TITLES[DETAIL])
        self.locks: list[tuple[_LockIcon, QLabel]] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 7, 12, 10)
        lay.setSpacing(7)
        lay.addWidget(self.caption)
        for text in RAIL_LOCKS:
            row = QHBoxLayout()
            row.setSpacing(6)
            icon = _LockIcon()
            label = QLabel(text)
            row.addWidget(icon)
            row.addWidget(label, 1)
            lay.addLayout(row)
            self.locks.append((icon, label))
        lay.addStretch(1)
        self.why = QLabel(RAIL_WHY)
        self.why.setWordWrap(True)
        self.link = _LinkButton("Open it in Advanced")
        self.link.clicked.connect(self.advanced_clicked)
        lay.addWidget(self.why)
        lay.addWidget(self.link)
        self.refresh_metrics()

    def texts(self) -> list[str]:
        return [label.text() for _i, label in self.locks]

    def refresh_theme(self) -> None:
        t = kit.tokens()
        self.setStyleSheet(
            f"#fc_picker_rail {{ background: {t['secondary'].name()};"
            f" border-left: 1px solid {t['hair_soft'].name(QColor.HexArgb)}; }}"
        )
        self.caption.refresh_theme()
        for icon, label in self.locks:
            label.setStyleSheet(_label_css("secondary_text", "info_text", 0.96))
            icon.update()
        self.why.setStyleSheet(_label_css("muted", "info_text", 0.88))
        self.link.refresh_theme()

    def refresh_metrics(self) -> None:
        self.setFixedWidth(round(168 * kit.area_fs("info_text")))
        for icon, _label in self.locks:
            icon.updateGeometry()
        self.refresh_theme()


class _LockIcon(QWidget):
    def sizeHint(self) -> QSize:  # noqa: N802
        d = round(10 * kit.area_fs("info_text"))
        return QSize(d, d)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        d = min(self.width(), self.height())
        kit.draw_icon(p, "fc_lock", QRectF(0, (self.height() - d) / 2, d, d), kit.tokens()["muted"])
        p.end()


class _LinkButton(QPushButton):
    """A flat text link in the accent (the set line and rail links). It may
    shrink below its text, elided (round 9: the open picker must fit 390 px
    with large fonts); the full text stays in the tooltip."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setFlat(True)
        self.setCursor(Qt.ArrowCursor)
        # Shrinkable: layouts may give it less than its text (it elides).
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.refresh_theme()

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        super().setText(text)
        self._elide_to(self.width())

    def full_text(self) -> str:
        return self._full

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), round(24 * kit.area_fs("info_text"))), hint.height())

    def sizeHint(self) -> QSize:  # noqa: N802
        self.ensurePolished()
        width = self.fontMetrics().horizontalAdvance(self._full) + 8
        return QSize(width, super().sizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide_to(event.size().width())

    def _elide_to(self, width: int) -> None:
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(0, width - 6))
        if shown != super().text():
            super().setText(shown)

    def refresh_theme(self) -> None:
        t = kit.tokens()
        px = scaled_area_px("info_text")
        self.setStyleSheet(
            f"QPushButton {{ color: {t['primary'].name()}; background: transparent; border: none;"
            f" padding: 0px 2px; font-size: {px}px; text-align: left; }}"
            f"QPushButton:hover {{ text-decoration: underline; }}"
        )
        self.updateGeometry()


class _Crumb(_LinkButton):
    """One breadcrumb step: shrinks and elides like the links (round 9)."""

    def __init__(self, text: str, on: bool, parent=None):
        self.on = on
        super().__init__(text, parent)
        self.setToolTip(text)

    def refresh_theme(self) -> None:
        t = kit.tokens()
        px = scaled_area_px("info_text")
        color = t["primary"] if self.on else t["secondary_text"]
        self.setStyleSheet(
            f"QPushButton {{ color: {color.name()}; background: transparent; border: none;"
            f" border-radius: 4px; padding: 2px 5px; font-size: {px}px;"
            f" font-weight: {600 if self.on else 400}; }}"
            f"QPushButton:hover {{ background: {t['ctl_h'].name(QColor.HexArgb)}; }}"
        )
        self.updateGeometry()


# ------------------------------------------------------------------ the picker


class FilterPicker(QWidget):
    filter_added = Signal(object)
    filter_saved = Signal(object, object)
    edit_cancelled = Signal()
    edit_refused = Signal(object, str)
    level_requested = Signal(str)

    def __init__(self, level: str, system: SearchSystem, naming: Naming,
                 narrow: Callable | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("fc_picker")
        self._model = PickerModel(level, system, naming, narrow)
        self._sel = Selection()
        self._editing: Filter | None = None
        self._pre_edit: Selection | None = None
        self._not_computed: frozenset[str] = frozenset()
        self._drill = False
        self._step = 0
        self._system_text = ""
        m = kit.metrics()

        # set line
        self.set_pill = QLabel()
        self.set_pill.setObjectName("fc_picker_setpill")
        self.set_counts = QLabel()
        self.set_dim = QLabel()
        for label in (self.set_counts, self.set_dim):  # wrap at 390 px (round 9)
            label.setWordWrap(True)
        self.set_link = _LinkButton("")
        self.set_link.clicked.connect(self._on_set_link)
        # Both lines wrap at narrow widths (review r6: phone width).
        self.set_line = QWidget()
        set_row = kit.FlowLayout(self.set_line, 10, 4)
        for w in (self.set_pill, self.set_counts, self.set_dim, self.set_link):
            set_row.addWidget(w)

        # the card: drill bar + browser
        self.card = QFrame()
        self.card.setObjectName("fc_picker_card")
        self.card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        card_lay = QVBoxLayout(self.card)
        card_lay.setContentsMargins(1, 1, 1, 1)
        card_lay.setSpacing(0)
        self.drill_bar = QWidget()
        self.drill_bar.setObjectName("fc_picker_drill")
        self.drill_bar.setAttribute(Qt.WA_StyledBackground, True)
        drill_lay = QHBoxLayout(self.drill_bar)
        drill_lay.setContentsMargins(8, 6, 8, 6)
        drill_lay.setSpacing(8)
        self.back = kit.KitSegment("picker_back", "BACK", m, icon="fc_back", tooltip="Previous column")
        self.back.clicked.connect(self._on_back)
        self.back_cluster = kit.kit_cluster([self.back], m)
        self._crumb_box = QHBoxLayout()
        self._crumb_box.setSpacing(2)
        self._crumbs: list[_Crumb] = []
        self._crumb_seps: list[QLabel] = []
        self.step_label = QLabel()
        self.step_label.setWordWrap(True)  # "Step 1 of 3" wraps at 390 px (round 9)
        drill_lay.addWidget(self.back_cluster)
        drill_lay.addLayout(self._crumb_box, 1)
        drill_lay.addWidget(self.step_label)
        card_lay.addWidget(self.drill_bar)

        self.browser = QWidget()
        browser_lay = QHBoxLayout(self.browser)
        browser_lay.setContentsMargins(0, 0, 0, 0)
        browser_lay.setSpacing(0)
        self.columns = [PickerColumn(BODY), PickerColumn(FACT), PickerColumn(VALUE)]
        self.detail = DetailColumn()
        self.rail = LockRail()
        self.rail.advanced_clicked.connect(lambda: self.level_requested.emit(pm.ADVANCED))
        for col, stretch in zip(self.columns, (20, 23, 23), strict=True):
            browser_lay.addWidget(col, stretch)
        browser_lay.addWidget(self.detail, 20)
        browser_lay.addWidget(self.rail)
        card_lay.addWidget(self.browser, 1)
        for col in self.columns:
            col.picked.connect(lambda key, c=col.index: self._on_picked(c, key))
            col.activated.connect(lambda key, c=col.index: self._on_activated(c, key))
            col.view.nav.connect(lambda d, c=col.index: self._on_nav(c, d))
        self.detail.changed.connect(self._on_detail)

        # preview line
        self.preview_caption = kit.SectionHeader("Preview")
        self.preview = kit.Chip(EMPTY_PREVIEW)
        self.preview.setObjectName("fc_picker_preview")
        self.preview.set_elide(True)
        self.preview.setFocusPolicy(Qt.NoFocus)
        self.preview.setToolTip("Preview only. Double-click a value or choose Add Filter to apply it.")
        self.add = kit.KitSegment("picker_add", "ADD FILTER", m, role=Role.PRIMARY, icon="fc_add",
                                  tooltip="Add this filter")
        self.add.clicked.connect(self.commit)
        self.add_cluster = kit.kit_cluster([self.add], m)
        self.cancel = kit.IconButton("x", "Cancel editing (keeps the filter)")
        self.cancel.clicked.connect(self.cancel_edit)
        self.cancel.setVisible(False)
        self.sugg_caption = kit.SectionHeader("Try")
        self.suggestions: list[kit.Chip] = []
        self.preview_line = QWidget()
        prev_row = QHBoxLayout(self.preview_line)
        prev_row.setContentsMargins(0, 0, 0, 0)
        prev_row.setSpacing(10)
        prev_row.addWidget(self.preview_caption)
        prev_row.addWidget(self.preview, 1)
        prev_row.addWidget(self.cancel)
        prev_row.addWidget(self.add_cluster)
        self.suggestion_line = QWidget()
        self._sugg_row = kit.FlowLayout(self.suggestion_line, 10, 6)
        self._sugg_row.addWidget(self.sugg_caption)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(9)
        lay.addWidget(self.set_line)
        lay.addWidget(self.card)
        lay.addWidget(self.preview_line)
        lay.addWidget(self.suggestion_line)
        self.set_line.hide()
        self._build_suggestions()
        self.refresh_metrics()
        self._rebuild()

    # ------------------------------------------------------------ public API
    def model(self) -> PickerModel:
        return self._model

    def selection(self) -> Selection:
        return self._sel

    def set_selection(self, sel: Selection) -> None:
        self._sel = carry(self._model, sel)
        if self._model.level == pm.EASY:
            self._sel = clamp_easy(self._model, self._sel)
        self._rebuild()

    def current_filter(self) -> Filter | None:
        if self._model.needs_detail(self._sel):
            return None
        return self._model.filter(self._sel)

    def is_editing(self) -> bool:
        return self._editing is not None

    def step(self) -> int:
        return self._step

    def last_step(self) -> int:
        return DETAIL if self._model.level == pm.ADVANCED else VALUE

    def set_level(self, level: str) -> None:
        if level == self._model.level:
            return
        self._model.level = level
        if level == pm.EASY:
            self._sel = clamp_easy(self._model, self._sel)
        self._step = min(self._step, self.last_step())
        self._build_suggestions()
        self._rebuild()

    def set_context(self, system: SearchSystem, naming: Naming, narrow: Callable | None = None) -> None:
        if self._model.system == system and self._model.naming == naming:
            # Keep the static body/fact catalogue. Store-backed values must
            # still use the current reader after an index or scope change.
            self._model.narrow = narrow
        else:
            # Easy and Advanced may use different naming even in the same
            # zodiac. Retain the previous context as well as the current one.
            previous = getattr(self, "_previous_model", None)
            current = self._model
            if previous is not None and previous.system == system and previous.naming == naming:
                self._model = previous
                self._model.level = current.level
                self._model.narrow = narrow
            else:
                self._model = PickerModel(current.level, system, naming, narrow)
            self._previous_model = current
        self._sel = carry(self._model, self._sel)
        if self._pre_edit is not None:
            self._pre_edit = carry(self._model, self._pre_edit)
        self._build_suggestions()
        self._rebuild()

    def set_system_text(self, text: str) -> None:
        self._system_text = text
        self._sync_set_line()

    def set_not_computed(self, fact_keys: Iterable[str]) -> None:
        keys = frozenset(fact_keys)
        if keys == self._not_computed:
            return
        self._not_computed = keys
        self._rebuild()

    def set_drill_down(self, on: bool) -> None:
        self._drill = bool(on)
        self._step = min(self._step, self.last_step())
        self._sync_columns()

    def is_drill_down(self) -> bool:
        return self._drill

    def go_to_step(self, step: int) -> None:
        self._step = max(0, min(step, self.last_step()))
        self._sync_columns()
        self._focus_step()

    def load_filter(self, f: Filter, fact_hint: str | None = None) -> bool:
        """Load a chip for editing; False (``edit_refused``) leaves every state
        as it was."""
        model = self._model
        try:
            sel = model.load(f, fact_hint)
        except (ValueError, BadFilterError):
            self.edit_refused.emit(f, REFUSED_REASON)
            return False
        if model.level == pm.EASY and not pm.is_easy(f):
            model.level = pm.ADVANCED
            self._build_suggestions()
            self.level_requested.emit(pm.ADVANCED)
        if self._editing is None:
            self._pre_edit = self._sel
        self._editing = f
        self._sel = sel
        self._step = 0
        self._rebuild()
        return True

    def cancel_edit(self) -> None:
        if self._editing is None:
            return
        self._sel = self._pre_edit if self._pre_edit is not None else Selection()
        self._editing = None
        self._pre_edit = None
        self._rebuild()
        self.edit_cancelled.emit()

    def commit(self) -> None:
        """ADD FILTER / SAVE FILTER."""
        f = self.current_filter()
        if f is None:
            return
        if self._editing is not None:
            old = self._editing
            self._editing = None
            self._pre_edit = None
            self._rebuild()
            self.filter_saved.emit(old, f)
            return
        if self._drill:
            self._step = 0
            self._sync_columns()
        self.filter_added.emit(f)

    def add_text(self) -> str:
        """The ADD button's label ("ADD FILTER" / "SAVE FILTER")."""
        return self.add._spec.labels[0]

    def crumbs(self) -> list[str]:
        return [c.text() for c in self._crumbs]

    def suggestion_texts(self) -> list[str]:
        return [c.text() for c in self.suggestions]

    def click_suggestion(self, index: int) -> None:
        self.filter_added.emit(pm.SUGGESTIONS[index])

    # ------------------------------------------------------------ handlers
    def _on_picked(self, column: int, key) -> None:
        sel = self._sel
        if column == BODY:
            sel = carry(self._model, replace(sel, body=key))
        elif column == FACT:
            sel = carry(self._model, replace(sel, fact=key, value=None))
        elif column == VALUE:
            sel = replace(sel, value=key)
        self._sel = sel
        if self._drill:
            self._step = min(column + 1, self.last_step())
        self._rebuild()
        if self._drill:
            self._focus_step()

    def _on_activated(self, column: int, key) -> None:
        if column == VALUE and self.current_filter() is not None:
            self.commit()

    def _on_detail(self, key: str, pick) -> None:
        self._sel = self._sel.with_detail(key, pick)
        self._rebuild()

    def _on_nav(self, column: int, delta: int) -> None:
        if self._drill:
            self.go_to_step(self._step + delta)
            return
        target = column + delta
        if 0 <= target < len(self.columns):
            self.columns[target].view.setFocus()
        elif target == DETAIL and self._model.level == pm.ADVANCED and self.detail.combos:
            next(iter(self.detail.combos.values())).setFocus()

    def _on_back(self) -> None:
        self.go_to_step(self._step - 1)

    def _on_set_link(self) -> None:
        self.level_requested.emit(pm.EASY if self._model.level == pm.ADVANCED else pm.ADVANCED)

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key_Escape and self._editing is not None:
            self.cancel_edit()
            e.accept()
            return
        super().keyPressEvent(e)

    # ------------------------------------------------------------ rebuild
    def _build_suggestions(self) -> None:
        key = (self._model.system, self._model.naming)
        if getattr(self, "_suggestions_key", None) == key:
            self._sync_suggestions()
            return
        self._suggestions_key = key
        for chip in self.suggestions:
            self._sugg_row.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self.suggestions = []
        for i, f in enumerate(pm.SUGGESTIONS):
            try:
                text = pm.suggestion_labels(self._model.system, self._model.naming)[i]
            except Exception:  # noqa: BLE001 - a suggestion never breaks the picker
                continue
            chip = kit.Chip(text, tooltip="Add this filter")
            chip.setObjectName(f"fc_picker_sugg{i}")
            chip.clicked.connect(lambda _c=False, i=i: self.click_suggestion(i))
            self._sugg_row.addWidget(chip)
            self.suggestions.append(chip)
        self._sync_suggestions()

    def _sync_suggestions(self) -> None:
        # Examples belong in help, not in the main filter controls.
        self.suggestion_line.hide()
        self.sugg_caption.hide()
        for chip in self.suggestions:
            chip.hide()

    def _rebuild(self) -> None:
        model, sel = self._model, self._sel
        bodies = body_groups(model)
        self.columns[BODY].set_groups(bodies, sel.body, f"{len(model.bodies())} placements")
        facts = fact_groups(model, sel.body, self._not_computed)
        self.columns[FACT].set_groups(facts, sel.fact,
                                      f"{sum(len(r) for _h, r in facts)} attributes" if facts else "")
        values = value_groups(model, sel)
        n_values = sum(1 for _h, rows in values for r in rows if not r.any)
        self.columns[VALUE].set_groups(values, sel.value, f"{n_values} targets" if n_values else "")
        self.columns[BODY].set_footer("")
        self.columns[FACT].set_footer("")
        self.columns[VALUE].set_footer("")
        slots = model.details(sel) if model.level == pm.ADVANCED else ()
        self.detail.set_slots(slots)
        # preview + add
        self.preview.setText(preview_text(model, sel))
        self.add.setEnabled(self.current_filter() is not None)
        label = "SAVE FILTER" if self._editing is not None else "ADD FILTER"
        self.add.compact_label(label)
        self.add.setToolTip("Replace the filter" if self._editing is not None else "Add this filter")
        self.cancel.setVisible(self._editing is not None)
        self._sync_suggestions()
        self._sync_set_line()
        self._sync_crumbs(bodies, facts, values)
        self._sync_columns()

    def _sync_set_line(self) -> None:
        self.set_line.hide()

    def _sync_crumbs(self, bodies: Groups, facts: Groups, values: Groups) -> None:
        sel = self._sel
        parts = [
            _label_of(bodies, sel.body) or CRUMB_BLANKS[BODY],
            _label_of(facts, sel.fact) or CRUMB_BLANKS[FACT],
            _label_of(values, sel.value) or CRUMB_BLANKS[VALUE],
        ]
        if self._model.level == pm.ADVANCED:
            parts.append(detail_summary(self._model, sel) if sel.value is not None else CRUMB_BLANKS[DETAIL])
        self._step = min(self._step, len(parts) - 1)
        while self._crumb_box.count():
            w = self._crumb_box.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._crumbs, self._crumb_seps = [], []
        for i, text in enumerate(parts):
            if i:
                sep = QLabel("›")
                sep.setStyleSheet(_label_css("muted", "info_text", 0.92))
                self._crumb_box.addWidget(sep)
                self._crumb_seps.append(sep)
            crumb = _Crumb(text, i == self._step)
            crumb.clicked.connect(lambda _c=False, i=i: self.go_to_step(i))
            self._crumb_box.addWidget(crumb)
            self._crumbs.append(crumb)
        self._crumb_box.addStretch(1)

    def _sync_columns(self) -> None:
        adv = self._model.level == pm.ADVANCED
        last = self.last_step()
        self._step = min(self._step, last)
        self.drill_bar.setVisible(self._drill)
        if self._drill:
            for col in self.columns:
                col.setVisible(col.index == self._step)
            self.detail.setVisible(adv and self._step == DETAIL)
            self.rail.setVisible(False)
        else:
            for col in self.columns:
                col.setVisible(True)
            self.detail.setVisible(adv)
            self.rail.hide()
        self.step_label.setText(f"Step {self._step + 1} of {last + 1}")
        self.back.setVisible(self._step > 0)
        for i, crumb in enumerate(self._crumbs):
            if crumb.on != (i == self._step):
                crumb.on = i == self._step
                crumb.refresh_theme()

    def _focus_step(self) -> None:
        if self._step < len(self.columns):
            self.columns[self._step].view.setFocus()

    # ------------------------------------------------------------ style
    def _style_pill(self) -> None:
        t = kit.tokens()
        full = self._model.level == pm.ADVANCED
        px = max(6, round(scaled_area_px("info_text") * 0.8))
        fill = kit._alpha(t["primary"], 0.14) if full else t["ctl"]
        fg = t["primary"] if full else t["secondary_text"]
        self.set_pill.setStyleSheet(
            f"#fc_picker_setpill {{ background: {fill.name(QColor.HexArgb)}; color: {fg.name()};"
            f" border: 1px solid {t['hair_soft'].name(QColor.HexArgb)}; border-radius: 5px;"
            f" padding: 1px 7px; font-size: {px}px; font-weight: 700; letter-spacing: 0.1em; }}"
        )

    def refresh_theme(self) -> None:
        t = kit.tokens()
        self.card.setStyleSheet(
            f"#fc_picker_card {{ background: {t['secondary_light'].name()};"
            f" border: 1px solid {t['hair_soft'].name(QColor.HexArgb)}; border-radius: 8px; }}"
        )
        self.drill_bar.setStyleSheet(
            f"#fc_picker_drill {{ background: {t['secondary'].name()};"
            f" border-bottom: 1px solid {t['hair_soft'].name(QColor.HexArgb)}; }}"
        )
        self._style_pill()
        self.set_counts.setStyleSheet(_label_css("primary_text", "info_text", 0.96, 600))
        self.set_dim.setStyleSheet(_label_css("muted", "info_text", 0.96))
        self.set_link.refresh_theme()
        self.step_label.setStyleSheet(_label_css("muted", "info_text", 0.84))
        for w in (self.preview_caption, self.sugg_caption):
            w.refresh_theme()
        for col in self.columns:
            col.refresh_theme()
        self.detail.refresh_theme()
        self.rail.refresh_theme()
        for crumb in self._crumbs:
            crumb.refresh_theme()
        for sep in self._crumb_seps:
            sep.setStyleSheet(_label_css("muted", "info_text", 0.92))
        for chip in (self.preview, *self.suggestions):
            chip.update()
        for w in (self.add, self.back, self.cancel):
            w.update()

    def refresh_metrics(self) -> None:
        m = kit.metrics()
        for cluster in (self.add_cluster, self.back_cluster):
            cluster.set_metrics(m)
        self.browser.setFixedHeight(round(240 * kit.area_fs("info_text")))
        for col in self.columns:
            col.refresh_metrics()
        self.detail.refresh_metrics()
        self.rail.refresh_metrics()
        for chip in (self.preview, *self.suggestions):
            chip.refresh_metrics()
        self.cancel.updateGeometry()
        self.refresh_theme()


__all__ = (
    "FilterPicker", "PickerColumn", "DetailColumn", "LockRail", "Row",
    "body_groups", "fact_groups", "value_groups", "footer_text", "set_line",
    "detail_summary", "clamp_easy", "carry", "preview_text",
    "NOT_COMPUTED_TIP", "REFUSED_REASON",
)
