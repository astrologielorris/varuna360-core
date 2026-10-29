# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The Find Chart status bar (SPEC-FIND-005 §3.7, §4.8 T3/T4).

Always visible, left to right: the database short path, "N charts · M
moments", the status line (a state dot and ``index_status``, the QLabel
``core_gui_qt`` calls ``setText`` on), while a job runs its text, a
``kit.ProgressLine`` and CANCEL in place of the status line, a notice with an
optional action, and "COVERAGE k/9" with one ring per extractor (ring =
computed / in_scope, empty grey for an empty scope, a small dot when stale);
a click on the coverage group opens the Library.

Signals: ``cancel_requested()``, ``coverage_clicked()``, ``notice_action()``.

Methods: ``set_database(path)``, ``set_counts(charts, moments)``,
``set_state(text, tone)`` / ``show_state(StatusState)`` (§3.7 States rows,
``panels.find_chart.states``), ``set_job(text, done, total,
cancel_label="CANCEL")`` (total 0 = indeterminate), ``clear_job()``,
``set_notice(text, action_label=None)``, ``set_coverage(snapshot)``,
``set_running(extractor_id | None)``, ``set_tier(t)`` (T3: no path; T4:
counts, progress and "COVERAGE k/9" only), ``refresh_theme()``,
``refresh_metrics()``.

Host wiring: ``self.status_bar = StatusBar(); self.index_status =
self.status_bar.index_status``; ``cancel_requested`` -> cancel the running
``FolderSyncWorker`` / ``ComputeWorker`` (after the commit point:
``cancel_after_commit``); ``coverage_clicked`` -> open the Library sheet;
``notice_action`` -> the notice's own action (RETRY: ``retry_failed`` plan
through ``_start_compute(plan, _consented=True)``).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QWidget

from apps.widgets.action_bar.bar_types import BarMetrics
from core.chart_search.search import Coverage
from panels.find_chart import kit, responsive, states
from panels.find_chart.library import ElidedLabel, StaleRing, StateDot
from ui.qt_theme import scaled_area_px


def status_metrics() -> BarMetrics:
    """Status bar buttons size from the ``status`` font area (INV-10)."""
    return BarMetrics(kit.area_fs("status"))


class CoverageButton(QAbstractButton):
    """"COVERAGE k/9" and one ring per extractor; one click target."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip("Coverage per domain: open Library")
        self.setAccessibleName("Coverage: open Library")
        self.label = QLabel("COVERAGE 0/0", self)
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.rings_box = QWidget(self)
        self.rings_box.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.rings_layout = QHBoxLayout(self.rings_box)
        self.rings_layout.setContentsMargins(0, 0, 0, 0)
        self.rings: list[StaleRing] = []
        lay = QHBoxLayout(self)
        lay.addWidget(self.label)
        lay.addWidget(self.rings_box)
        self.refresh_metrics()

    def set_ring_count(self, n: int) -> None:
        while len(self.rings) > n:
            ring = self.rings.pop()
            self.rings_layout.removeWidget(ring)
            ring.hide()
            ring.deleteLater()
        while len(self.rings) < n:
            ring = StaleRing(11, "status")
            ring.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.rings_layout.addWidget(ring)
            self.rings.append(ring)
        self.updateGeometry()

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.layout().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.layout().minimumSize()

    def refresh_metrics(self) -> None:
        fs = kit.area_fs("status")
        self.layout().setContentsMargins(round(6 * fs), round(3 * fs), round(6 * fs), round(3 * fs))
        self.layout().setSpacing(round(7 * fs))
        self.rings_layout.setSpacing(round(4 * fs))
        for ring in self.rings:
            ring.refresh_metrics()
        self.refresh_theme()
        self.updateGeometry()

    def refresh_theme(self) -> None:
        t = kit.tokens()
        self.label.setStyleSheet(
            f"color: {t['secondary_text'].name()}; font-size: {scaled_area_px('status')}px;"
            " font-weight: 600; letter-spacing: 0.08em; background: transparent;"
        )
        for ring in self.rings:
            ring.update()
        self.update()

    def paintEvent(self, _event):
        if not (self.underMouse() or self.hasFocus()):
            return
        t = kit.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        rad = 6 * kit.area_fs("status")
        if self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(t["ctl_h"])
            p.drawRoundedRect(r, rad, rad)
        if self.hasFocus():
            p.setPen(QPen(t["ring"], 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, rad, rad)
        p.end()


class StatusBar(QWidget):
    cancel_requested = Signal()
    coverage_clicked = Signal()
    notice_action = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("fc_status_bar")
        self._tier = responsive.T0
        self._tone = states.NORMAL
        self._job_active = False
        self._notice_text = ""
        self._notice_action: str | None = None
        self._running: str | None = None
        self._snapshot: tuple[Coverage, ...] = ()
        m = status_metrics()

        self.database = ElidedLabel("", Qt.ElideLeft)
        self.database.setObjectName("fc_status_db")
        self.counts = QLabel("")
        self.counts.setWordWrap(True)
        self.counts.setMinimumWidth(0)
        self.counts.setObjectName("fc_status_counts")

        # status line (idle)
        self.state_dot = StateDot()
        self.index_status = QLabel("")
        self.index_status.setObjectName("fc_status_text")
        self.index_status.setMinimumWidth(0)
        # job (running)
        self.job_text = QLabel("")
        self.job_text.setObjectName("fc_status_job")
        self.progress = kit.JobBar(18)
        self.cancel_button = kit.KitSegment("sb_cancel", states.CANCEL, m,
                                            tooltip="Stop the running job")
        self.cancel_button.clicked.connect(self.cancel_requested)
        # notice
        self.notice_label = QLabel("")
        self.notice_label.setObjectName("fc_status_notice")
        self.notice_button = kit.KitSegment("sb_notice", "", m)
        self.notice_button.clicked.connect(self.notice_action)
        # coverage
        self.coverage = CoverageButton()
        self.coverage.clicked.connect(self.coverage_clicked)

        self.middle = QWidget()
        mid = QHBoxLayout(self.middle)
        mid.setContentsMargins(0, 0, 0, 0)
        self._mid = mid
        for w in (self.state_dot, self.index_status):
            mid.addWidget(w)
        mid.setStretchFactor(self.index_status, 1)
        mid.addWidget(self.job_text)
        mid.addWidget(self.progress, 1)  # the bar takes the free width
        mid.addWidget(self.cancel_button)

        lay = QHBoxLayout(self)
        self._lay = lay
        lay.addWidget(self.database, 2)
        lay.addWidget(self.counts)
        lay.addWidget(self.middle, 6)
        lay.addWidget(self.notice_label)
        lay.addWidget(self.notice_button)
        # Coverage is available in Library; keep its state API for consumers
        # without a second Library entry point in the bottom status line.
        self.coverage.setParent(self)
        self.coverage.hide()
        self.clear_job()
        self.set_notice("")
        self.refresh_metrics()

    # ------------------------------------------------------------ API

    def set_database(self, path: str) -> None:
        self.database.set_full_text(states.short_path(path), tooltip=path)

    def set_counts(self, charts: int, moments: int) -> None:
        self.counts.setText(states.counts_text(charts, moments))

    def set_state(self, text: str, tone: str = states.NORMAL) -> None:
        self._tone = tone
        self.index_status.setText(text)
        self.state_dot.tone = tone
        self._style_status()

    def show_state(self, state: states.StatusState) -> None:
        """One §3.7 States row: a job row (``cancel_label`` set) shows the
        progress line, the others the status line."""
        if state.cancel_label is None:
            self.clear_job()
            self.set_state(state.text, state.tone)
        else:
            self.set_job(state.text, 0, 0, state.cancel_label)

    def set_job(self, text: str, done: int, total: int, cancel_label: str = states.CANCEL) -> None:
        self._job_active = True
        self.job_text.setText(text)
        self.job_text.setToolTip(text)
        self.progress.set_progress(done, total)
        self.cancel_button.compact_label(cancel_label)
        self.cancel_button.setToolTip(cancel_label if cancel_label != states.CANCEL
                                      else "Stop the running job")
        self._apply_visibility()

    def clear_job(self) -> None:
        self._job_active = False
        self.job_text.setText("")
        self.progress.set_progress(0, 1)
        self.cancel_button.compact_label(states.CANCEL)
        self._apply_visibility()

    def job_active(self) -> bool:
        return self._job_active

    def set_notice(self, text: str, action_label: str | None = None) -> None:
        self._notice_text = text or ""
        self.notice_label.setText(self._notice_text)
        self.notice_label.setToolTip(self._notice_text)
        self._notice_action = action_label if self._notice_text else None
        if self._notice_action:
            self.notice_button.compact_label(self._notice_action)
            self.notice_button.setToolTip(self._notice_action)
            self.notice_button.setAccessibleName(self._notice_action)
        self._apply_visibility()

    def set_coverage(self, snapshot: tuple[Coverage, ...]) -> None:
        self._snapshot = tuple(snapshot)
        self.coverage.set_ring_count(len(self._snapshot))
        self.coverage.label.setText(states.coverage_counter(self._snapshot))
        for ring, c in zip(self.coverage.rings, self._snapshot):
            row = states.coverage_row(c)
            ring.set_coverage(row.fraction, empty=row.empty, stale=row.stale,
                              running=c.extractor_id == self._running)
            ring.setToolTip(row.tooltip)
        self.coverage.refresh_theme()

    def set_running(self, extractor_id: str | None) -> None:
        self._running = extractor_id
        if self._snapshot:
            self.set_coverage(self._snapshot)

    def set_tier(self, tier: int) -> None:
        self._tier = tier
        self._apply_visibility()

    def tier(self) -> int:
        return self._tier

    # ------------------------------------------------------------ layout

    def _apply_visibility(self) -> None:
        t3 = self._tier >= responsive.T3
        t4 = self._tier >= responsive.T4
        self.counts.setWordWrap(t4)
        job = self._job_active
        self.database.setVisible(not t3)
        # T4 with a job: the counts give way to progress and CANCEL (r8 #9).
        self.counts.setVisible(not (t4 and job))
        self.state_dot.setVisible(not job and not t4)
        self.index_status.setVisible(not job and not t4)
        self.job_text.setVisible(job and not t4)
        self.progress.setVisible(job)
        self.cancel_button.setVisible(job)
        notice = bool(self._notice_text) and not t4
        self.notice_label.setVisible(notice)
        self.notice_button.setVisible(notice and bool(self._notice_action))
        self.coverage.rings_box.setVisible(not t4)
        self.coverage.updateGeometry()

    def _style_status(self) -> None:
        t = kit.tokens()
        px = scaled_area_px("status")
        if self._tone == states.ERROR:
            color = t["red"]
        elif self._tone == states.WARN:
            color = t["gold"]
        else:
            color = t["muted"]
        self.index_status.setStyleSheet(
            f"color: {color.name()}; font-size: {px}px; background: transparent;"
        )
        self.state_dot.update()

    def refresh_theme(self) -> None:
        t = kit.tokens()
        px = scaled_area_px("status")
        plain = f"color: {t['secondary_text'].name()}; font-size: {px}px; background: transparent;"
        self.database.setStyleSheet(plain)
        self.database.refresh()
        self.counts.setStyleSheet(plain)
        self.job_text.setStyleSheet(plain)
        self.notice_label.setStyleSheet(plain)
        self._style_status()
        self.coverage.refresh_theme()
        for w in (self.cancel_button, self.notice_button, self.progress):
            w.update()
        self.update()

    def refresh_metrics(self) -> None:
        fs = kit.area_fs("status")
        m = status_metrics()
        self._lay.setContentsMargins(round(12 * fs), 0, round(10 * fs), 0)
        self._lay.setSpacing(round(12 * fs))
        self._mid.setSpacing(round(8 * fs))
        self.setFixedHeight(max(round(36 * fs), m.ctl_h + round(8 * fs)))
        self.progress.setFixedHeight(round(20 * fs))
        # It shrinks to a floor so a job fits a phone-width panel (review r8
        # #9), and otherwise fills the status bar (Lorris 2026-10-25: the
        # 180 px line went unnoticed).
        self.progress.setMinimumWidth(round(80 * fs))
        self.progress.setMaximumWidth(16777215)
        self.cancel_button.set_metrics(m)
        self.notice_button.set_metrics(m)
        self.state_dot.refresh_metrics()
        self.coverage.refresh_metrics()
        self.refresh_theme()

    def paintEvent(self, _event):
        t = kit.tokens()
        p = QPainter(self)
        p.fillRect(self.rect(), t["bar_b"])
        p.setPen(QPen(t["hair"], 1))
        p.drawLine(QPointF(0, 0.5), QPointF(self.width(), 0.5))
        p.end()
