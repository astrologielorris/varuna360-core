# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart toolbar (SPEC-FIND-005 §4.2, §4.8).

``[EASY|ADVANCED]  [search well ........]  [ASK AI|SEARCH WEB]  [FILTERS n]
[LIBRARY n]`` in the chart action bar's segments. The search well hosts the
panel's ``search_entry`` (a real QLineEdit, Pro A.2).

Labels follow ``responsive.FC_LABELS``: the panel gives the layout tier,
the toolbar picks the first label row whose measured width fits
(``KitSegment.width_for``; measuring never changes the live buttons). In the
last row FILTERS and LIBRARY live in a "..." menu; if even that row does not
fit, the search well takes a second row of its own.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLineEdit, QMenu, QVBoxLayout, QWidget

from apps.widgets.action_bar.bar_types import META_TEXT, Role, draw_bar_text, text_advance
from panels.find_chart import kit, responsive
from panels.find_chart.context import ADVANCED, EASY

PLACEHOLDER = "Name, place, country or notes (sun:Dhata works too)"


class CountBadge(QWidget):
    """A small gold count pill (Sort with AI's promotion on LIBRARY)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_count(self, n: int) -> None:
        self._count = n
        self.setAccessibleName(f"{n} unsorted charts" if n else "")
        self.adjustSize()
        self.update()

    def count(self) -> int:
        return self._count

    def sizeHint(self) -> QSize:  # noqa: N802
        fs = kit.metrics().fs
        w = text_advance(str(self._count), *META_TEXT, fs=fs) + 8 * fs
        h = 13 * fs
        return QSize(round(max(w, h)), round(h))

    def paintEvent(self, _event):
        t = kit.tokens()
        fs = kit.metrics().fs
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(t["gold"])
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setPen(t["fg_on_accent"])
        draw_bar_text(p, r, Qt.AlignCenter, str(self._count), *META_TEXT, fs=fs)
        p.end()


class Toolbar(QWidget):
    level_requested = Signal(str)  # "easy" / "advanced"
    ask_ai_requested = Signal(str)  # the search text
    search_web_requested = Signal()
    filters_toggled = Signal(bool)
    library_requested = Signal()

    def __init__(self, search_entry: QLineEdit, parent=None):
        super().__init__(parent)
        self.search_entry = search_entry
        search_entry.setPlaceholderText(PLACEHOLDER)
        m = kit.metrics()
        self._m = m
        self._layout_tier = responsive.T0
        self._row = 0
        self._two_rows = False
        self._filter_count = 0
        self._library_badge = 0
        self._ask_ai = False

        self.easy = kit.KitSegment(
            "easy", "EASY", m, icon="fc_easy",
            checkable=True, accent_selection=True,
            tooltip="Easy: the common facts, in the app's own zodiac and names",
        )
        self.advanced = kit.KitSegment(
            "advanced", "ADVANCED", m, icon="fc_advanced",
            checkable=True, accent_selection=True,
            tooltip="Advanced: every fact, the sources and a search system of its own",
        )
        self._level_group = QButtonGroup(self)
        self._level_group.setExclusive(True)
        self._level_group.addButton(self.easy)
        self._level_group.addButton(self.advanced)
        self.easy.clicked.connect(lambda: self.level_requested.emit(EASY))
        self.advanced.clicked.connect(lambda: self.level_requested.emit(ADVANCED))
        self.level_cluster = kit.kit_cluster([self.easy, self.advanced], m)

        self.well = kit.SearchWell(search_entry)

        self.ask_ai = kit.KitSegment(
            "ask_ai", "ASK AI", m, icon="fc_sparkle", role=Role.TINT_BLUE,
            tooltip="Ask AI: describe the charts you are looking for",
        )
        self.search_web = kit.KitSegment(
            "search_web", "SEARCH WEB", m, icon="fc_globe",
            tooltip="Search the web for this person's birth data",
        )
        self.ask_ai.clicked.connect(
            lambda: self.ask_ai_requested.emit(self.search_entry.text())
        )
        self.search_web.clicked.connect(self.search_web_requested.emit)
        self.find_cluster = kit.kit_cluster([self.ask_ai, self.search_web], m)
        self.find_cluster.set_button_visible(self.ask_ai, False)

        self.filters = kit.KitSegment(
            "filters", "FILTERS", m, icon="fc_filters", checkable=True,
            tooltip="Show or hide the filter picker",
        )
        self.filters.setChecked(True)
        self.filters.set_lit(True)
        self.filters.toggled.connect(self._on_filters)
        self.library = kit.KitSegment(
            "library", "LIBRARY", m, icon="fc_library",
            tooltip="Library: folders, index, coverage and unsorted downloads",
        )
        self.library.clicked.connect(self.library_requested.emit)
        self.more = kit.KitSegment("more", "", m, icon="fc_more", tooltip="More")
        self.more.clicked.connect(self._show_more)
        self.tail_cluster = kit.kit_cluster([self.filters, self.library, self.more], m)
        self.tail_cluster.set_button_visible(self.more, False)
        self.badge = CountBadge(self)
        self.badge.hide()

        self._top = QHBoxLayout()
        self._top.setSpacing(m.grp_gap)
        self._bottom = QHBoxLayout()
        self._bottom.setContentsMargins(0, 0, 0, 0)
        rows = QVBoxLayout(self)
        rows.setSpacing(round(4 * m.fs))
        rows.addLayout(self._top)
        rows.addLayout(self._bottom)
        self._place_widgets()
        self._apply_margins()
        self.set_level(EASY)

    # ------------------------------------------------------------- state
    def set_level(self, level: str) -> None:
        self.easy.setChecked(level == EASY)
        self.advanced.setChecked(level == ADVANCED)
        self.easy.set_lit(level == EASY)
        self.advanced.set_lit(level == ADVANCED)
        self.level_cluster.notify_state_changed()

    def set_ask_ai_visible(self, visible: bool) -> None:
        """ASK AI shows only with a registered provider (§4.2)."""
        self._ask_ai = visible
        self.find_cluster.set_button_visible(self.ask_ai, visible)
        self.relayout()

    def filter_count(self) -> int:
        return self._filter_count

    def set_filter_count(self, n: int) -> None:
        self._filter_count = n
        self.relayout()  # a longer label may need a narrower row (§4.8)

    def set_filters_open(self, on: bool) -> None:
        self.filters.blockSignals(True)
        self.filters.setChecked(on)
        self.filters.blockSignals(False)
        self.filters.set_lit(on)

    def set_library_badge(self, n: int) -> None:
        """The gold count for Sort with AI (§4.9), painted over the LIBRARY
        segment's corner (it never changes the segment's width); 0 hides it.
        The host sets it only while Sort with AI is on with 5 or more
        charts waiting (INV-8)."""
        self._library_badge = n
        self.badge.set_count(n)
        self._place_badge()
        self.relayout()

    def _on_filters(self, on: bool) -> None:
        self.filters.set_lit(on)
        self.filters_toggled.emit(on)

    def _show_more(self) -> None:
        menu = kit.style_menu(QMenu(self))
        n = self._filter_count
        filters = menu.addAction(f"Filters ({n})" if n else "Filters")
        filters.setCheckable(True)
        filters.setChecked(self.filters.isChecked())
        library = menu.addAction(
            f"Library ({self._library_badge})" if self._library_badge else "Library"
        )
        chosen = menu.exec(self.more.mapToGlobal(self.more.rect().bottomLeft()))
        if chosen is filters:
            self.filters.toggle()
        elif chosen is library:
            self.library_requested.emit()

    # ------------------------------------------------------------ labels
    def _label(self, key: str, row: int) -> str | None:
        label = responsive.FC_LABELS[key][row]
        if label is None:
            return None
        if key == "filters" and self._filter_count and label:
            return f"{label} {self._filter_count}"
        return label

    def _segment(self, key: str) -> kit.KitSegment:
        return {
            "easy": self.easy,
            "advanced": self.advanced,
            "ask_ai": self.ask_ai,
            "search_web": self.search_web,
            "filters": self.filters,
            "library": self.library,
            "more": self.more,
        }[key]

    def _present(self) -> tuple[str, ...]:
        return tuple(k for k in responsive.FC_LABELS if k != "ask_ai" or self._ask_ai)

    def row_width(self, row: int) -> float:
        """The toolbar's width at ``row`` with its labels (measured, §4.8)."""
        m = self._m
        clusters = 4
        gaps = (clusters - 1) * m.grp_gap
        margins = 2 * m.side_pad
        total = margins + gaps + self.well.floor_width()
        for key in self._present():
            label = self._label(key, row)
            if label is not None:
                total += self._segment(key).width_for(label)
        return total

    def set_layout_tier(self, tier: int) -> None:
        self._layout_tier = tier
        self.relayout()

    def relayout(self) -> None:
        """Pick the label row for the current width (never from a width the
        row itself changes: the available width is the toolbar's own)."""
        available = self.width() or 10_000
        self._row = responsive.label_row(self._layout_tier, available, self.row_width)
        two = self.row_width(self._row) > available
        self._apply_labels()
        if two != self._two_rows:
            self._two_rows = two
            self._place_widgets()

    def _apply_labels(self) -> None:
        row = self._row
        for key in responsive.FC_LABELS:
            seg = self._segment(key)
            label = self._label(key, row)
            cluster = self._cluster_of(key)
            visible = label is not None and (key != "ask_ai" or self._ask_ai)
            if label is not None:
                seg.compact_label(label)
            if seg.isHidden() == visible:
                cluster.set_button_visible(seg, visible)
        self._place_badge()

    def _cluster_of(self, key: str):
        if key in ("easy", "advanced"):
            return self.level_cluster
        if key in ("ask_ai", "search_web"):
            return self.find_cluster
        return self.tail_cluster

    def label_row(self) -> int:
        return self._row

    def two_rows(self) -> bool:
        return self._two_rows

    # ------------------------------------------------------------ layout
    def _place_widgets(self) -> None:
        for lay in (self._top, self._bottom):
            while lay.count():
                lay.takeAt(0)
        self._top.addWidget(self.level_cluster)
        if self._two_rows:
            self._top.addStretch(1)
            self._top.addWidget(self.find_cluster)
            self._top.addWidget(self.tail_cluster)
            self._bottom.addWidget(self.well, 1)
        else:
            self._top.addWidget(self.well, 1)
            self._top.addWidget(self.find_cluster)
            self._top.addWidget(self.tail_cluster)
        self.setFixedHeight(self._height())

    def _height(self) -> int:
        one = round(kit.TOOLBAR_H * self._m.fs)
        return 2 * one if self._two_rows else one

    def _apply_margins(self) -> None:
        m = self._m
        pad = round(2 * m.fs)
        self.layout().setContentsMargins(m.side_pad, pad, m.side_pad, pad)
        self._top.setSpacing(m.grp_gap)
        self.layout().setSpacing(round(4 * m.fs))

    def _place_badge(self) -> None:
        """The badge on the LIBRARY segment's top right corner, or on "..."
        when LIBRARY sits in the menu."""
        host = self.more if self.library.isHidden() else self.library
        if not self._library_badge or host.isHidden():
            self.badge.hide()
            return
        self.badge.adjustSize()
        corner = host.mapTo(self, host.rect().topRight())
        self.badge.move(corner.x() - self.badge.width() + round(4 * self._m.fs),
                        max(0, corner.y() - round(4 * self._m.fs)))
        self.badge.show()
        self.badge.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.size().width() != e.oldSize().width():
            self.relayout()
        self._place_badge()

    def showEvent(self, e):
        super().showEvent(e)
        self._place_badge()

    def refresh_metrics(self) -> None:
        """A scale or font change: rebox every segment and re-measure."""
        m = kit.metrics()
        self._m = m
        for cluster in (self.level_cluster, self.find_cluster, self.tail_cluster):
            cluster.set_metrics(m)
        self.well.set_metrics(m)
        self._apply_margins()
        self.setFixedHeight(self._height())
        self.relayout()

    def refresh_theme(self) -> None:
        self.well.refresh_theme()
        for cluster in (self.level_cluster, self.find_cluster, self.tail_cluster):
            cluster.update()
            for b in cluster.buttons():
                b.update()
