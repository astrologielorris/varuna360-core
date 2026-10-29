# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The inspector of the selected result (SPEC-FIND-005 §3.6, §4.7, INV-3, INV-6).

Ported from the round 2 mockup's "Library Triptych" inspector: header
(initials badge, name, "<Kind> chart · <Country>", birth date and time,
place), OPEN CHART and a "..." menu, the Ascendant / Sun / Moon tray, the
collapsible sections filled from a ``facts.ChartFacts`` (stored rows only,
never a compute), File & source, and a foot line with the search system.

Each section lists its owners (the extractors it reads) that are not
computed, in owner order: missing -> "<Owner> not computed" + COMPUTE; failed
-> "<Owner> could not be computed" + RETRY (failure text in the tooltip);
stale -> "<Owner> computed by an older version" + RECOMPUTE. A section with
no rows whose owners all have rows stored reads "Nothing stored". The
header dot follows ``FactSection.state`` (partial, missing, stale = amber;
failed = red). Stored rows always show.

API
- ``Inspector()`` (a QScrollArea)
- signals: ``closed()``, ``open_requested(str entry_id)``,
  ``copy_requested(str entry_id)``, ``show_in_folder_requested(str)``,
  ``trash_requested(str)``, ``compute_requested(str extractor_id,
  object moment_id, str kind)`` with kind in compute / retry / recompute
- ``show_entry(entry, chart_facts, context_token, system_text, has_file)``:
  ``chart_facts`` may be ``None`` (the facts are read later); the binding
  is ``(entry.entry_id, context_token)``, ``context_token`` opaque
- ``fill_facts(entry_id, context_token, chart_facts) -> bool``: applied only
  when still current (late fills dropped)
- ``is_current(entry_id, context_token)``, ``current_entry_id()``,
  ``clear()``, ``open_sections()``, ``set_tier(t)``, ``docked_width()``,
  ``build_menu()``, ``refresh_theme()``, ``refresh_metrics()``
- Qt-free: ``copy_text(entry)`` (Copy birth data, D-17), ``initials``,
  ``kind_line``, ``menu_actions(has_file)``, ``owner_notices(section)``,
  ``section_dot(state)``

Host wiring: on row/card selection ``show_entry(entry, facts.chart_facts(
store, ctx.system, ctx.naming, entry.moment_id), token, trail_system_text,
bool(results.openable_path(entry)))`` (or ``None`` then ``fill_facts`` from
a worker, dropped when ``not is_current``); ``open_requested`` -> the
``_open_row`` logic; ``copy_requested`` -> ``QApplication.clipboard().setText(
inspector.copy_text(entry))``; ``compute_requested`` -> ``compute.plan(...,
among=frozenset({moment_id}), retry_failed=kind != "compute",
recompute_stale=kind == "recompute")`` checked, then ``_start_compute(plan,
_consented=True)``; ``closed`` -> hide or close the sheet (selection stays).
"""

from __future__ import annotations

import datetime
import html

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from apps.widgets.action_bar.bar_types import Role, draw_bar_text
from core.chart_search import facts
from core.chart_search.extractors import registry
from core.chart_search.search import ResultEntry
from panels.find_chart import kit, responsive
from panels.find_chart.glance_chart import GlanceChart
from panels.find_chart.results import source_text
from ui.qt_theme import scaled_area_px

AREA = "info_text"  # the inspector's text (INV-10); section titles: panel_titles
FILE_SECTION = "file_source"
NOTHING_STORED = "Nothing stored"
EMPTY_TEXT = "Select a chart in the results to see everything stored for it."
LOADING_TEXT = "Reading stored facts"
FOOT_NOTE = "Stored facts for this birth moment."

COMPUTE, RETRY, RECOMPUTE = "compute", "retry", "recompute"

#: SPEC-FIND-007 §3: the Glance Chart replaces the inspector body; the tray
#: and the fact sections are set aside (not deleted) behind this switch.
SHOW_FACT_SECTIONS = False
#: The identity block (badge, name, kind, date, place) is set aside too
#: (Lorris 2026-10-25): the results table already shows it; the panel is the
#: chart, then OPEN CHART and "...". True brings the block back above the chart.
SHOW_IDENTITY = False
#: The panel title (was "Inspector" + "Selected chart").
TITLE = "Chart snapshot"
POSITIONS_NOTICE = {
    facts.MISSING: ("Positions not computed", "COMPUTE", COMPUTE),
    facts.FAILED: ("Positions could not be computed", "RETRY", RETRY),
    facts.STALE: ("Positions computed by an older version", "RECOMPUTE", RECOMPUTE),
}


def positions_notice(chart_facts) -> tuple[str, str, str] | None:
    """The single muted line under the Glance Chart (§3): ``(text, button,
    kind)`` when the positions owner is missing, failed or stale."""
    if chart_facts is None:
        return None
    owner = chart_facts.owner_states.get("positions")
    if owner is None:
        return None
    return POSITIONS_NOTICE.get(owner.state)

#: Default titles (before a fill) of the sections, in the spec's order.
TITLES = {
    "placements": "Placements",
    "navamsa": "Navamsa",
    "nakshatras": "Nakshatras",
    "dignity": "Dignity",
    "avasthas": "Avasthas",
    "shayanadi": "Shayanadi",
    "retinue": "Retinue beings",
    "cards_of_truth": "Cards of Truth",
    "human_design": "Human Design",
    FILE_SECTION: "File & source",
}
SECTION_KEYS: tuple[str, ...] = (*facts.SECTION_ORDER, FILE_SECTION)
DEFAULT_OPEN = frozenset({"placements"})


# ------------------------------------------------------------------ Qt-free


def copy_text(entry: ResultEntry) -> str:
    """Copy birth data (§3.6, D-17): ``Name, YYYY-MM-DD HH:MM:SS, Place,
    Country`` from the entry alone (``birth_local`` as stored, no offset, no
    coordinates); an empty field is left out with its comma."""
    parts = (entry.name, entry.birth_local, entry.place, entry.country)
    return ", ".join(p.strip() for p in parts if p and p.strip())


def initials(name: str) -> str:
    words = [w for w in name.split() if w[:1].isalnum()]
    return "".join(w[0].upper() for w in words[:2]) or "?"


def kind_line(entry: ResultEntry) -> str:
    """"Birth chart · France"."""
    kind = str(getattr(entry.kind, "value", entry.kind) or "birth")
    text = f"{kind[:1].upper()}{kind[1:]} chart"
    return f"{text} · {entry.country}" if entry.country else text


def birth_line(entry: ResultEntry) -> str:
    """"1977-12-21 · 10:40"."""
    date, _, time = entry.birth_local.partition(" ")
    return f"{date} · {time[:5]}" if time else date


def place_line(entry: ResultEntry) -> str:
    return ", ".join(p for p in (entry.place, entry.country) if p)


def menu_actions(has_file: bool) -> tuple[tuple[str, str], ...]:
    """The "..." menu: file actions only when the entry has a file."""
    items = (("open", "Open chart"), ("copy", "Copy birth data"))
    if has_file:
        items += (("folder", "Show in folder"), ("trash", "Move to trash"))
    return items


def section_dot(state: str) -> str:
    if state == facts.COMPUTED:
        return ""
    return "red" if state == facts.FAILED else "amber"


def owner_notices(section: facts.FactSection) -> list[tuple[str, str, str, str, str]]:
    """``(extractor_id, text, button, kind, tooltip)`` per owner not
    computed, in owner order."""
    out = []
    for owner in section.owners:
        name = registry.label(owner.extractor_id)
        if owner.state == facts.MISSING:
            out.append((owner.extractor_id, f"{name} not computed", "COMPUTE", COMPUTE,
                        f"Compute {name} for this chart"))
        elif owner.state == facts.FAILED:
            out.append((owner.extractor_id, f"{name} could not be computed", "RETRY", RETRY,
                        owner.error or "The computation failed"))
        elif owner.state == facts.STALE:
            out.append((owner.extractor_id, f"{name} computed by an older version", "RECOMPUTE",
                        RECOMPUTE, f"Compute {name} again with this version"))
    return out


def file_rows(entry: ResultEntry, has_file: bool) -> tuple[facts.FactRow, ...]:
    modified = (
        datetime.datetime.fromtimestamp(entry.file_modified).strftime("%Y-%m-%d")
        if entry.file_modified is not None
        else ""
    )
    rows = [facts.FactRow(("Source", source_text(entry)))]
    rows.append(facts.FactRow(("Path", entry.path if has_file and entry.path else "No file")))
    if modified:
        rows.append(facts.FactRow(("Modified", modified)))
    return tuple(rows)


# ------------------------------------------------------------------ widgets


class _Badge(QWidget):
    """The initials badge (mockup ``.mono``)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""
        self.refresh_metrics()

    def set_text(self, text: str) -> None:
        self._text = text
        self.update()

    def text(self) -> str:
        return self._text

    def refresh_metrics(self) -> None:
        fs = kit.area_fs(AREA)
        self.setFixedSize(round(38 * fs), round(40 * fs))
        self.update()

    def paintEvent(self, _e):
        t = kit.tokens()
        fs = kit.area_fs(AREA)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(t["hair_soft"])
        p.setBrush(t["well"])
        p.drawRoundedRect(r, 7 * fs, 7 * fs)
        p.setPen(t["gold_hi"])
        draw_bar_text(p, r, Qt.AlignCenter, self._text, 15, 520, 0.02, fs)
        p.end()


class _TrayCard(QWidget):
    """One of the Ascendant / Sun / Moon cards (mockup ``.trinity``)."""

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.caption = caption
        self.value = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_metrics()

    def set_value(self, value: str) -> None:
        self.value = value
        self.setToolTip(f"{self.caption}: {value}" if value else f"{self.caption}: not stored")
        self.update()

    def refresh_metrics(self) -> None:
        self.setFixedHeight(round(46 * kit.area_fs(AREA)))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(round(80 * kit.area_fs(AREA)), self.height())

    def paintEvent(self, _e):
        t = kit.tokens()
        fs = kit.area_fs(AREA)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(t["hair_soft"])
        p.setBrush(t["ctl"])  # a control surface: dark in dark themes (W10)
        p.drawRoundedRect(r, 6 * fs, 6 * fs)
        p.setPen(t["muted"])
        draw_bar_text(p, QRectF(r.left(), r.top() + 7 * fs, r.width(), 12 * fs), Qt.AlignCenter,
                      self.caption.upper(), 9.5, 620, 0.08, fs)
        p.setPen(t["primary_text"] if self.value else t["muted"])
        draw_bar_text(p, QRectF(r.left(), r.top() + 21 * fs, r.width(), 18 * fs), Qt.AlignCenter,
                      self.value or "·", 12.5, 600, 0, fs)
        p.end()


class Inspector(QScrollArea):
    closed = Signal()
    open_requested = Signal(str)
    copy_requested = Signal(str)
    show_in_folder_requested = Signal(str)
    trash_requested = Signal(str)
    compute_requested = Signal(str, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAccessibleName("Selected chart inspector")
        self._entry: ResultEntry | None = None
        self._token = None
        self._facts: facts.ChartFacts | None = None
        self._has_file = False
        self._tier = responsive.T0
        self._open: set[str] = set(DEFAULT_OPEN)
        self._filling = False
        #: (label, role) pairs restyled by refresh_theme (no rebuild).
        self._styled: list[tuple[QLabel, str]] = []
        self.notice_buttons: dict[str, list[tuple[str, str, kit.KitSegment]]] = {}
        m = kit.metrics()

        content = QWidget()
        content.setObjectName("fc_inspector_content")
        self._lay = QVBoxLayout(content)

        head = QHBoxLayout()
        self.back_button = kit.KitSegment("insp_back", "RESULTS", m, icon="fc_back",
                                          tooltip="Back to the results")
        self.back_button.clicked.connect(self._close)
        self.back_button.hide()
        self.title_label = self._label(TITLE, "title")
        self.sub_label = self._label("Selected chart", "muted")
        self.close_button = kit.IconButton("x", "Close the chart snapshot", size=18)
        self.close_button.clicked.connect(self._close)
        for label in (self.title_label, self.sub_label):
            label.setWordWrap(True)  # the header fits 390 px at large fonts (round 9)
        head.addWidget(self.back_button)
        head.addWidget(self.title_label)
        head.addStretch(1)
        head.addWidget(self.sub_label)
        self.sub_label.setVisible(SHOW_IDENTITY)
        head.addWidget(self.close_button)
        self._lay.addLayout(head)

        self.empty_label = self._label(EMPTY_TEXT, "muted")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self._lay.addWidget(self.empty_label)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        self._body_lay = body
        self.identity = QWidget()
        identity = QVBoxLayout(self.identity)
        identity.setContentsMargins(0, 0, 0, 0)
        person = QHBoxLayout()
        self.badge = _Badge()
        who = QVBoxLayout()
        who.setSpacing(2)
        self.name_label = self._label("", "name")
        self.name_label.setWordWrap(True)
        self.kind_label = self._label("", "secondary")
        self.kind_label.setWordWrap(True)
        who.addWidget(self.name_label)
        who.addWidget(self.kind_label)
        person.addWidget(self.badge)
        person.addLayout(who, 1)
        identity.addLayout(person)
        self.when_label = self._label("", "secondary")
        self.when_label.setWordWrap(True)
        self.place_label = self._label("", "secondary")
        self.place_label.setWordWrap(True)
        identity.addWidget(self.when_label)
        identity.addWidget(self.place_label)
        body.addWidget(self.identity)
        self.identity.setVisible(SHOW_IDENTITY)


        self.glance = GlanceChart()
        self.glance.clicked.connect(lambda: self._emit_entry(self.open_requested))
        body.addWidget(self.glance)
        self._glance_system = None
        self._glance_naming = None
        self._first_filter = None
        self.glance_notice = QWidget()
        nl = QHBoxLayout(self.glance_notice)
        nl.setContentsMargins(0, 0, 0, 0)
        self.glance_notice_label = self._label("", "muted")
        self.glance_notice_label.setWordWrap(True)
        self.glance_notice_button = kit.KitSegment("insp_glance_compute", "COMPUTE", m,
                                                   tooltip="Compute Positions for this chart")
        self._glance_notice_kind = COMPUTE
        self.glance_notice_button.clicked.connect(
            lambda: self._request_compute("positions", self._glance_notice_kind))
        nl.addWidget(self.glance_notice_label, 1)
        nl.addWidget(self.glance_notice_button)
        self.glance_notice.hide()
        body.addWidget(self.glance_notice)
        # OPEN CHART and "..." sit under the chart: the chart is the first view.
        actions = QHBoxLayout()
        self.open_button = kit.KitSegment("insp_open", "OPEN CHART", m, icon="fc_open",
                                          role=Role.PRIMARY, tooltip="Open this chart")
        self.open_button.clicked.connect(lambda: self._emit_entry(self.open_requested))
        self.more_button = kit.KitSegment("insp_more", "", m, icon="fc_more",
                                          tooltip="More actions")
        self.more_button.clicked.connect(self._show_menu)
        self.open_cluster = kit.kit_cluster([self.open_button], m)
        self.more_cluster = kit.kit_cluster([self.more_button], m)
        actions.addWidget(self.open_cluster, 1)
        actions.addWidget(self.more_cluster)
        body.addLayout(actions)

        self.tray_widget = QWidget()
        tray = QHBoxLayout(self.tray_widget)
        tray.setContentsMargins(0, 0, 0, 0)
        tray.setSpacing(3)
        self.tray_cards = tuple(_TrayCard(c) for c in ("Ascendant", "Sun", "Moon"))
        for card in self.tray_cards:
            tray.addWidget(card)
        self.tray_widget.setVisible(SHOW_FACT_SECTIONS)
        body.addWidget(self.tray_widget)

        self.loading_label = self._label(LOADING_TEXT, "muted")
        body.addWidget(self.loading_label)

        self.sections: dict[str, kit.CollapsibleSection] = {}
        for key in SECTION_KEYS:
            section = kit.CollapsibleSection(TITLES[key], open_=key in self._open)
            section.setProperty("sentence_case", True)
            section.toggled.connect(lambda on, k=key: self._on_section_toggled(k, on))
            self.sections[key] = section
            body.addWidget(section)

        self.foot_label = self._label("", "muted")
        self.foot_label.setWordWrap(True)
        self.foot_label.setVisible(SHOW_FACT_SECTIONS)
        body.addWidget(self.foot_label)
        self._lay.addWidget(self.body)
        self._lay.addStretch(1)
        self.setWidget(content)
        self.clear()
        self.refresh_metrics()

    # ------------------------------------------------------------ helpers
    def _label(self, text: str, role: str) -> QLabel:
        label = QLabel(text)
        self._styled.append((label, role))
        label.setStyleSheet(self._style(role))
        return label

    def _style(self, role: str) -> str:
        t = kit.tokens()
        px = scaled_area_px(AREA)
        color = {
            "title": t["primary_text"],
            "name": t["primary_text"],
            "cell": t["primary_text"],
            "secondary": t["secondary_text"],
            "first": t["secondary_text"],
            "muted": t["muted"],
            "head": t["muted"],
        }.get(role, t["primary_text"])
        size = {"name": px + 5, "title": px + 1, "head": max(8, px - 2)}.get(role, px)
        extra = {
            "name": " font-weight: 620;",
            "title": " font-weight: 650;",
            "head": " font-weight: 650; letter-spacing: 0.09em;",
        }.get(role, "")
        return f"color: {color.name()}; font-size: {size}px; background: transparent;{extra}"

    def _retro_html(self, body: str) -> str:
        red = kit.tokens()["red"].name()
        return (f"{html.escape(body)} <span style='color:{red}; font-weight:650;'"
                f" title='Retrograde'>R</span>")

    def _emit_entry(self, signal) -> None:
        if self._entry is not None:
            signal.emit(self._entry.entry_id)

    def _close(self) -> None:
        self.closed.emit()

    def _on_section_toggled(self, key: str, on: bool) -> None:
        if self._filling:
            return
        if on:
            self._open.add(key)
        else:
            self._open.discard(key)

    # -------------------------------------------------------------- binding
    def current_entry_id(self):
        return self._entry.entry_id if self._entry is not None else None

    def current_entry(self) -> ResultEntry | None:
        """The entry shown (the host compares it after a refresh)."""
        return self._entry

    def is_current(self, entry_id, context_token) -> bool:
        return (
            self._entry is not None
            and self._entry.entry_id == entry_id
            and self._token == context_token
        )

    def clear(self) -> None:
        """No selection: the empty state."""
        self._entry = None
        self._token = None
        self._facts = None
        self.empty_label.show()
        self.body.hide()

    def show_entry(
        self,
        entry: ResultEntry,
        chart_facts: facts.ChartFacts | None,
        context_token,
        system_text: str,
        has_file: bool,
    ) -> None:
        self._entry = entry
        self._token = context_token
        self._has_file = bool(has_file)
        self.empty_label.hide()
        self.body.show()
        self.badge.set_text(initials(entry.name))
        self.name_label.setText(entry.name)
        self.kind_label.setText(kind_line(entry))
        self.when_label.setText(birth_line(entry))
        self.place_label.setText(place_line(entry))
        self.place_label.setVisible(bool(self.place_label.text()))
        self.foot_label.setText(f"{system_text}\n{FOOT_NOTE}" if system_text else FOOT_NOTE)
        if SHOW_FACT_SECTIONS:  # hidden sections are not built (review r1 #2)
            self._fill_section(FILE_SECTION, None, ("Field", "Value"), file_rows(entry, has_file))
        self.sections[FILE_SECTION].set_subtitle("File" if has_file else "No file")
        self.sections[FILE_SECTION].setVisible(SHOW_FACT_SECTIONS)
        self._apply_facts(chart_facts)

    def fill_facts(self, entry_id, context_token, chart_facts: facts.ChartFacts) -> bool:
        """A late fill: applied only for the current selection and context."""
        if not self.is_current(entry_id, context_token):
            return False
        self._apply_facts(chart_facts)
        return True

    # ----------------------------------------------------------- glance
    def set_glance_context(self, system, naming, first_filter) -> None:
        """The search system and naming (the 12 labels, even with no facts)
        and the first funnel filter (the centre, §2.1). Repaints the centre
        from the facts already held: no facts re-read (T11)."""
        changed = (system, naming) != (self._glance_system, self._glance_naming)
        self._glance_system, self._glance_naming = system, naming
        self._first_filter = first_filter
        if changed and system is not None and naming is not None:
            self.glance.set_labels(facts.sign_labels(system, naming))
        self._update_centre()

    def set_first_filter(self, first_filter) -> None:
        self._first_filter = first_filter
        self._update_centre()

    def _update_centre(self) -> None:
        if self._glance_system is None or self._glance_naming is None:
            self.glance.set_centre(None)
            return
        self.glance.set_centre(facts.resolve_centre(
            self._facts, self._first_filter, self._glance_system, self._glance_naming))

    def _apply_glance(self, chart_facts) -> None:
        self.glance.set_chart(chart_facts.glance if chart_facts is not None else None)
        if chart_facts is not None and chart_facts.sign_labels:
            self.glance.set_labels(chart_facts.sign_labels)
        self._update_centre()
        notice = positions_notice(chart_facts)
        self.glance_notice.setVisible(notice is not None)
        if notice is not None:
            text, button, kind = notice
            self.glance_notice_label.setText(text)
            self.glance_notice_button.setText(button)
            self._glance_notice_kind = kind

    def _apply_facts(self, chart_facts: facts.ChartFacts | None) -> None:
        self._facts = chart_facts
        self._apply_glance(chart_facts)
        self.loading_label.setVisible(chart_facts is None and SHOW_FACT_SECTIONS)
        cards = dict(chart_facts.cards) if chart_facts is not None else {}
        for card, body in zip(self.tray_cards, facts.DEFAULT_PLACEMENTS):
            card.set_value(cards.get(body, ""))
        for key in facts.SECTION_ORDER:
            section = self.sections[key]
            section.setVisible(chart_facts is not None and SHOW_FACT_SECTIONS)
            if chart_facts is None:
                continue
            fs_ = chart_facts.section(key)
            section.set_subtitle(fs_.subtitle)
            section.set_dot(section_dot(fs_.state))
            if SHOW_FACT_SECTIONS:
                self._fill_section(key, fs_, fs_.columns, fs_.rows)
        self._filling = True
        for key, section in self.sections.items():
            section.set_open(key in self._open)
        self._filling = False

    def _clear_body(self, section: kit.CollapsibleSection) -> None:
        lay = section.body_layout
        dead = set()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                dead.add(id(w))
                for child in w.findChildren(QLabel):
                    dead.add(id(child))
                w.hide()  # gone from the screen now, not at the next event loop
                w.deleteLater()
        self._styled = [(lbl, r) for lbl, r in self._styled if id(lbl) not in dead]

    def _fill_section(self, key, section: facts.FactSection | None, columns, rows) -> None:
        widget = self.sections[key]
        self._clear_body(widget)
        m = kit.metrics()
        buttons = []
        if section is not None:
            for eid, text, button_text, kind, tip in owner_notices(section):
                line = QWidget()
                hl = QHBoxLayout(line)
                hl.setContentsMargins(0, 0, 0, 0)
                label = self._label(text, "secondary")
                label.setWordWrap(True)
                label.setToolTip(tip)
                button = kit.KitSegment(f"insp_{kind}_{eid}", button_text, m, tooltip=tip)
                button.clicked.connect(
                    lambda _c=False, e=eid, k=kind: self._request_compute(e, k)
                )
                hl.addWidget(label, 1)
                hl.addWidget(button)
                widget.body_layout.addWidget(line)
                buttons.append((eid, kind, button))
        self.notice_buttons[key] = buttons
        if not rows:
            if section is None or section.computed:
                widget.body_layout.addWidget(self._label(NOTHING_STORED, "muted"))
            return
        table = QWidget()
        grid = QGridLayout(table)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(round(8 * kit.area_fs(AREA)))
        grid.setVerticalSpacing(0)
        for c, header in enumerate(columns):
            label = self._label(header.upper(), "head")
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            if c:
                label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(label, 0, c)
            grid.setColumnStretch(c, 2 if c < 2 else 1)
        for r, row in enumerate(rows, start=1):
            grid.setRowMinimumHeight(r, round(26 * kit.area_fs(AREA)))
            tip = "\n".join(row.details)
            for c, cell in enumerate(row.cells):
                role = "first" if c == 0 else "cell"
                if c == 0 and columns[0] == "Body":
                    cell = next((name for name, short in facts.SHORT_BODY.items()
                                 if short == cell and short != "Asc"), cell)
                if c == 0 and row.retrograde:
                    label = self._label("", "first")
                    label.setTextFormat(Qt.RichText)
                    label.setProperty("fc_retro_body", cell)
                    label.setText(self._retro_html(cell))
                else:
                    label = self._label(cell, role)
                    label.setTextFormat(Qt.PlainText)
                label.setWordWrap(True)
                label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
                if c:
                    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if tip:
                    label.setToolTip(tip)
                grid.addWidget(label, r, c)
        widget.body_layout.addWidget(table)

    def _request_compute(self, extractor_id: str, kind: str) -> None:
        if self._entry is None:
            return
        self.compute_requested.emit(extractor_id, self._entry.moment_id, kind)

    def open_sections(self) -> frozenset[str]:
        return frozenset(self._open)

    def current_facts(self) -> facts.ChartFacts | None:
        return self._facts

    # ----------------------------------------------------------------- menu
    def build_menu(self) -> QMenu:
        menu = QMenu(self)
        kit.style_menu(menu)
        signals = {
            "open": self.open_requested,
            "copy": self.copy_requested,
            "folder": self.show_in_folder_requested,
            "trash": self.trash_requested,
        }
        for key, text in menu_actions(self._has_file):
            if key == "folder":
                menu.addSeparator()
            action = menu.addAction(text)
            action.setData(key)
            action.triggered.connect(lambda _c=False, s=signals[key]: self._emit_entry(s))
        return menu

    def _show_menu(self) -> None:
        if self._entry is None:
            return
        menu = self.build_menu()
        menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))
        menu.deleteLater()

    # ---------------------------------------------------------- responsive
    def docked_width(self) -> int:
        return round(kit.INSPECTOR_W * kit.metrics().fs)

    def set_tier(self, tier: int) -> None:
        """T0/T1 docked at ``INSPECTOR_W`` x fs; T2/T3 in a sheet; T4 full
        page with a RESULTS back button."""
        self._tier = tier
        full = tier >= responsive.T4
        self.back_button.setVisible(full)
        self.close_button.setVisible(not full)
        # Full page: RESULTS + the title only, so the header fits 390 px.
        self.sub_label.setVisible(SHOW_IDENTITY and not full)
        if tier <= responsive.T1:
            self.setFixedWidth(self.docked_width())
        else:
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)

    # ------------------------------------------------------- theme, fonts
    def refresh_metrics(self) -> None:
        m = kit.metrics()
        fs = kit.area_fs(AREA)
        # Side margins grow with the font only to 1.25x: with large fonts at
        # 390 px the text needs the width more than the gutter (round 9).
        side = round(16 * min(fs, 1.25))
        self._lay.setContentsMargins(side, round(12 * fs), side, round(4 * fs))
        self._lay.setSpacing(round(10 * fs))
        self._body_lay.setSpacing(round(8 * fs))
        for seg in (self.back_button, self.open_button, self.more_button):
            seg.set_metrics(m)
        self.open_cluster.set_metrics(m)
        self.more_cluster.set_metrics(m)
        for buttons in self.notice_buttons.values():
            for _eid, _kind, button in buttons:
                button.set_metrics(m)
        self.badge.refresh_metrics()
        self.glance_notice_button.set_metrics(m)
        self.glance.refresh_metrics()
        for card in self.tray_cards:
            card.refresh_metrics()
        for section in self.sections.values():
            section.refresh_metrics()
        self.set_tier(self._tier)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        t = kit.tokens()
        self.widget().setStyleSheet(
            "QWidget { background: transparent; }"
            f"QWidget#fc_inspector_content {{ background: {t['secondary_light'].name()}; }}"
        )
        self.setStyleSheet(
            f"QScrollArea {{ background: {t['secondary_light'].name()}; border: none; }}"
        )
        for label, role in self._styled:
            label.setStyleSheet(self._style(role))
            body = label.property("fc_retro_body")
            if body:
                label.setText(self._retro_html(body))
        self.glance.refresh_theme()
        for w in (self.badge, *self.tray_cards, self.close_button, self.back_button,
                  self.open_button, self.more_button):
            w.update()
        for section in self.sections.values():
            section.header.update()
