# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Find Chart panel: the host (design.md §4.9, SPEC-FIND-004).

``FindChartPanel`` keeps the attributes the Pro edition drives at runtime
(pro-boundary.md Appendix A.2): ``cache`` (a non-None ``ChartIndexCache``),
``_load_cached_index``, ``sort_combo`` (``SortKey`` item data, ``findData``),
``search_entry``, ``search_timer``, ``_refresh_results``, ``results_table``
(columns 0, 1, 4, 5), ``tree_filepath_map`` (row -> path, ``""`` for a chart
with no file; ``tree_entry_map`` is its row -> entry twin) and
``chart_selected.emit(path)``. A chart with no file opens through
``session_chart_selected.emit(entry_id)`` (D11, ``find_chart/opening.py``).

The search UI lives in ``panels/find_chart/``: the toolbar, trail, picker and
chips, results bar, cards, inspector, the Library sheet (folders, index,
coverage) and the status bar (SPEC-FIND-005), plus web lookup, CHTK creation,
the sort and trash.

Index work follows SPEC-FIND-003: a folder scan only through
``_build_index_async(_user_initiated=True)``, a compute only through
``_start_compute(plan, _consented=True)`` (§5.1).
"""

from __future__ import annotations

import os
from dataclasses import replace
import sqlite3
import time
from concurrent.futures import Future

from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cache.chart_index_cache import ChartIndexCache
from core.chart_search import compute, compute_process, facets, facts, sync, taxonomy, terms
from core.chart_search.compute import ComputePlan
from core.chart_search.errors import (
    BadFilterError,
    ChartSearchError,
    NoIndexError,
    StoreBusyError,
)
from core.chart_search.extractors import positions, registry
from core.chart_search.search import (
    EVERYTHING,
    Query,
    ResultEntry,
    Scope,
    SearchResult,
    Sources,
    SortKey,
    candidates,
    coverage_moments,
    coverage_snapshot,
    needed,
    resolve,
    result_labels,
    search,
)
from core.chart_search.sources import EntryKind, kind_field
from core.chart_search.store import StoreReader
from core.chart_search.system import FIELD_SETTINGS, Field
from core.chart_search.taxonomy import search_naming
from core.settings_registry import default as registry_default
from managers import find_chart_sync
from managers.settings_manager import get_settings

from panels.find_chart import consent, kit, opening, responsive, results
from panels.find_chart import context as fc_context
from panels.find_chart.context import FolderRef, QuerySnapshot, SearchContext
from panels.find_chart.choices import FilterChoices
from panels.find_chart.combos import ReadableCombo
from panels.find_chart import states
from panels.find_chart.states import extractor_label, progress_text
from panels.find_chart.status_bar import StatusBar
from panels.find_chart.notice_host import NOTICE_RETRY, NoticeHostMixin
from core.edition_features import ai_features as _ai_features
# Sort with AI, Pro and up; Lite's panel has the notice host alone (SPEC-EDN-002 P4).
SortWithAIMixin = _ai_features().sort_mixin() if _ai_features() is not None else NoticeHostMixin
from panels.find_chart.check_host import ChartCheckMixin
from panels.find_chart import result_columns
from panels.find_chart.cards import ResultCards
from panels.find_chart.table import ResultDelegate
from panels.find_chart.chips import FilterChips
from panels.find_chart.inspector import Inspector, copy_text
from panels.find_chart.results_bar import ResultsBar
from panels.find_chart.picker import FilterPicker
from panels.find_chart.folders import FolderListMixin
from panels.find_chart.index_menu import IndexMenuMixin
from panels.find_chart.scope_bar import ScopeBar
from panels.find_chart.toolbar import Toolbar
from panels.find_chart.trail import Trail, trail_text
from panels.find_chart.sign_names import SignNamesCombo
from panels.find_chart.system_bar import (
    MORE_FIELDS,
    SystemBar,
    field_items,
    field_value,
)
from panels.find_chart.trash import TrashMixin
from panels.find_chart.web_lookup import WebLookupMixin
from panels.find_chart import workers as fc_workers
from panels.find_chart.workers import ComputeWorker, FolderSyncWorker
from ui.qt_theme import (
    STATUS,
    desat_hex,
    get_primary_button_style,
    get_theme_colors,
    scaled_area_font,
    scaled_area_px,
)

#: The CPU share a background compute keeps to.
CPU_PERCENT_KEY = compute_process.CPU_PERCENT_KEY


NO_INDEX_TEXT = states.no_index().text  # §3.7 states
BUSY_TEXT = "The index is busy, retrying"
BUSY_GAVE_UP_TEXT = "Index busy: try again"
ALREADY_RUNNING_TEXT = "A compute is already running."
INDEX_UPDATING_TEXT = "The index is updating: try again when it is done."
EVERYTHING_DONE_TEXT = "Everything is computed in this system."
COVERAGE_CHANGED_TEXT = "The coverage changed: check the counts and try again."
BUSY_IDLE_TEXT = states.store_busy(False).text
NOTHING_TO_RETRY_TEXT = "Nothing left to retry: those charts are computed."
#: ``_read_store`` could not read (the state is already on screen).
_NOT_READ = object()
#: Store busy: retries after BUSY_RETRY_MS, BUSY_RETRIES times (§3.7).
BUSY_RETRY_MS = 1000
BUSY_RETRIES = 3
#: Table rows filled per event-loop turn when a background read lands
#: (``_fill_step``): about 40 ms each on a 5,380-chart library.
FILL_STEP = 400


def _item_label(field, system):
    """``system``'s value of ``field`` as the system bar names it."""
    value = field_value(system, field)
    return next((label for label, v in field_items(field) if v == value), str(value))


def _fm_min_height(area, pad=8):
    """Vertical floor for a migrated text widget at the CURRENT font size
    (td-2o8u). Under qt-material the QSS-driven sizeHint().height() tracks the
    font px (~38 at composed max), still below fontMetrics().height() (~50), so
    the reliable floor is an explicit fm-derived minimumHeight, re-derived on
    every live font change (see _refresh_geometry)."""
    f = QFont()
    f.setPixelSize(scaled_area_px(area))
    return QFontMetrics(f).height() + pad


class FindChartPanel(
    FolderListMixin,
    IndexMenuMixin,
    WebLookupMixin,
    SortWithAIMixin,
    ChartCheckMixin,
    TrashMixin,
    QWidget,
):
    """Find Chart tab: the chart store's search, with the folder list."""

    chart_selected = Signal(str)  # Emitted when chart is double-clicked (filepath)
    #: A loaded chart of the current session opened (D11): its session entry
    #: id, ``session:{profile}:{session_id}``.
    session_chart_selected = Signal(str)
    #: A store job of the app's sync finished (emitted from its thread).
    _store_job_done = Signal()
    #: A no-scan folder forget finished: (its removed roots, succeeded).
    _folders_forgotten = Signal(object, object)  # owed roots, True / False / None
    #: ASK AI with the search text (SPEC-FIND-005 §4.2; shown only with a
    #: provider, ``set_ask_ai_provider``).
    ask_ai_requested = Signal(str)

    def __init__(self, gui):
        super().__init__()
        self.setObjectName("fc_find_chart")
        self.gui = gui
        # A handle on the store; touches no file (pro-boundary.md A.2: Pro
        # checks it for None before _load_cached_index).
        self.cache = ChartIndexCache()

        # State tracking
        self.folder_entries = []  # List of QLineEdit widgets
        self.folder_checkboxes = []  # List of QCheckBox widgets
        self.folder_frames = []  # List of QWidget frames
        self.folder_containers = []  # List of container widgets
        self.tree_filepath_map = {}  # row_index -> filepath ("" without a file)
        self.tree_entry_map = {}  # row_index -> search.ResultEntry
        self.sort_reverse = False  # Toggle for ascending/descending

        # Search debouncing
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)  # 150ms debounce
        self.search_timer.timeout.connect(self._on_search_timer)
        # INV-3: display-only events bump the generation and refresh quietly;
        # a pending debounce restarted by one of them stays quiet.
        self._search_generation = 0
        self._timer_quiet = False
        # Every search bumps the token: a background read (``_refresh_in_
        # background``) lands only while its token is still the latest.
        self._search_token = 0
        self._search_worker = None  # the StoreReadWorker whose read may land
        self._fill = None  # (token, the _fill_rows steps) of a landed read
        self._fill_timer = QTimer(self)
        self._fill_timer.setSingleShot(True)
        self._fill_timer.setInterval(0)
        self._fill_timer.timeout.connect(self._fill_step)
        # §3.7 synchronous contract (Pro): None after a successful search,
        # else "busy", "no_index" or the ChartSearchError's error_type.
        self.last_search_error = None
        self._busy_retries = 0
        self._busy_timer = QTimer(self)
        self._busy_timer.setSingleShot(True)
        self._busy_timer.setInterval(BUSY_RETRY_MS)
        self._busy_timer.timeout.connect(self._retry_busy)
        self._level = fc_context.level_of(
            get_settings().get(fc_context.LEVEL_KEY, registry_default(fc_context.LEVEL_KEY))
        )

        # Worker thread state
        self._web_worker = None
        self._web_token = 0  # bumps per web job and at shutdown (review r12)
        self._closing = False  # shut down: no job starts until shown again (r13)
        self._inspector_moment = None  # (entry id, exact Moment) shown (r15)
        #: Each shown entry's (moment id, exact Moment), read in the search's
        #: own snapshot: the inspector shows an entry only while the store
        #: still holds exactly this (review r15).
        self._shown_moments = {}
        self._rendered_rows_key = None
        self._row_cells = {}
        self._store_revision = None  # the store revision the caches follow
        self._search_cache = {}  # two queries and exact moments, revision-bound
        self._column_values_cache = {}  # at most two display contexts, revision-bound
        self._coverage_reads = {}
        self._quit = False  # the app is quitting: terminal (review r14)
        # A parked writer of an earlier panel ended: this panel's caches and
        # owed forget catch up (review r14).
        fc_workers.notifier().store_released.connect(self._on_store_released)
        self._sort_worker = None
        self._index_worker = None  # FolderSyncWorker (REBUILD INDEX)
        self._compute_worker = None  # ComputeWorker
        self._store_file_worker = None  # StoreFileWorker (Index menu)
        self._rebuild_compute = False  # the running compute is REBUILD INDEX's
        self._compute_done = {}  # extractor id -> moments done in the running compute
        # Plans the user declined or cancelled: not offered again until the
        # query changes (consent.PlanKey).
        self._declined = set()
        self._tokens = ()  # (token, Filter) of the search box
        # The caches go only when the job really wrote (``_follow_revision``,
        # first step of the search): the session sync of every tab switch
        # usually writes nothing, and a cleared cache costs a full search of
        # the library (td-lb44b.8 follow-up, 2026-10-29), read off the GUI
        # thread when it did write (td-reeow).
        self._store_job_done.connect(self._refresh_in_background)
        self._folders_forgotten.connect(self._on_folders_forgotten)
        chart_folders = get_settings().get_chart_folders()
        self._database_path = chart_folders[0] if chart_folders else os.path.expanduser(
            "~/Documents/Kala/Charts"
        )
        self._unsorted_dir = os.path.join(self._database_path, "celebrity_unsorted")
        self._cached_unsorted_count = -1  # -1 = not yet counted

        # Widgets to store for theme refresh
        self.search_entry = None
        self.sort_combo = None
        self.group_combo = None
        self.index_status = None
        self.results_table = None
        self.add_folder_btn = None
        self.rebuild_btn = None
        self.index_btn = None
        self.folders_container = None
        self.fileless_checkbox = None
        self.web_download_widget = None
        # Migrated-font widgets that _refresh_fonts replays on a live font change
        # (this panel is persistent, not rebuilt per open).
        self._folder_path_labels = []
        self._remove_buttons = []
        self._browse_buttons = []      # td-2o8u: geometry floors re-derived live
        self.toolbar = None
        self.trail = None
        self._ask_ai_provider = None
        self._candidates = {}  # Scope -> candidate count (cleared on store change)
        self.query_revision = 0  # SPEC-FIND-006 §5.1
        self._row_ids = []  # stable ids of the chips, in order
        self._filter_counter = 0
        self._editing_index = None
        self._fact_dots_cache = (None, frozenset())
        self._uncomputed_cache = (None, frozenset())
        self.filter_group = None
        self.results_group = None
        self.status_bar = None
        self._store_epoch = 0  # bumped whenever the store may have changed
        self._coverage_key = None  # (system, scope, epoch) of the snapshot shown
        self._coverage_snapshot = ()
        self._partial_ids = ()  # extractors the trail's COMPUTE plans
        # What the status bar's RETRY / RESUME may run (review r8 #3, #7):
        # (mode, system, {extractor id: the moments that run planned}).
        self._retry_binding = None

        # Build UI
        self._create_ui()

        # Load saved folder paths
        self._load_folder_paths()
        self.refresh_unsorted_downloads(force_recount=True)

        # The app's zodiac frame or sign names changed: the system bar follows
        # the app where it is not pinned, labels follow the naming.
        if hasattr(gui, "aditya_mode_changed"):
            gui.aditya_mode_changed.connect(self._on_aditya_mode_changed)
        # SPEC-MODE-001: also refresh on a names-only change (zodiac system
        # unchanged, labels flipped). Same lightweight relabel as a mode change.
        if hasattr(gui, 'sign_names_changed'):
            gui.sign_names_changed.connect(self._on_aditya_mode_changed)

    def _create_ui(self):
        """Build the UI (SPEC-FIND-005 §3.1): toolbar, trail, folders, scope
        and system (Advanced), filters, results."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(4)

        # The status bar first: everything below reports to index_status.
        self._create_status_bar()

        # 1. Toolbar (hosts search_entry) and the search trail
        self._create_search_section(layout)

        # 2. The Library sheet (folders, index, coverage): over the panel
        self.controls_scroll = QScrollArea()
        self.controls_scroll.setFrameShape(QFrame.NoFrame)
        self.controls_scroll.setWidgetResizable(True)
        self.controls_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.controls_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._controls_content = QWidget()
        body = QVBoxLayout(self._controls_content)
        body.setContentsMargins(14, 0, 14, 0)
        self.controls_scroll.setWidget(self._controls_content)
        layout.addWidget(self.controls_scroll)
        self._create_folder_section(body)
        self._create_sort_section()
        self._create_rate_section()
        self._create_check_section()

        # 3. Scope and independent system controls (Advanced), picker and chips
        self._create_filter_section(body)

        # 4. Sort/Group Controls
        self._create_controls_section(layout)

        # 5. Results Table
        results_box = QVBoxLayout()
        results_box.setContentsMargins(14, 0, 14, 0)
        layout.addLayout(results_box, 1)
        self._create_results_section(results_box)

        # 6. Status bar (§3.7), always visible
        layout.addWidget(self.status_bar)

        # Responsive tiers (§4.8): from the panel's own width only.
        self.responsive = responsive.ResponsiveController(self)
        self.responsive.tier_changed.connect(self._on_tier_changed)
        self._on_tier_changed(self.responsive.tier)

        # Apply initial theme
        self.refresh_theme()
        self._apply_level()
        self._controls_timer = QTimer(self)
        self._controls_timer.setSingleShot(True)
        self._controls_timer.timeout.connect(self._fit_controls)
        self._controls_content.installEventFilter(self)
        self._fit_controls()

    def _create_filter_section(self, parent_layout):
        """System bar, sources, the picker and the chips."""
        self.filter_group = QGroupBox("")
        self.filter_group.setStyleSheet(self._group_title_css())
        box = QVBoxLayout(self.filter_group)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)

        self.system_bar = SystemBar(find_chart_sync.default_system, inline=True)
        # The labels follow the search system's mode (search_naming).
        self.system_bar.changed.connect(self._relabel)
        # varuna/47: this panel's own sign names, never the app's naming.
        self.sign_names_combo = SignNamesCombo()
        self.sign_names_combo.currentIndexChanged.connect(self._relabel)
        self.system_bar.add_trailing(self.sign_names_combo, "Sign names:")
        # Advanced exposes every independent system field directly.
        self.advanced_region = QWidget()
        advanced = QVBoxLayout(self.advanced_region)
        advanced.setContentsMargins(0, 0, 0, 0)
        advanced.setSpacing(4)
        self.scope_bar = ScopeBar()
        # A scope change is a context change: display only (INV-3).
        self.scope_bar.changed.connect(self._on_scope_changed)
        advanced.addWidget(self.scope_bar)
        advanced.addWidget(self.system_bar)
        box.addWidget(self.advanced_region)

        # The picker and the active-filter chips (§3.3, §3.4, W6).
        ctx = self.search_context()
        self.picker = FilterPicker(ctx.level, ctx.system, ctx.naming, self._filter_choices())
        self.picker.filter_added.connect(self._on_filter_added)
        self.picker.filter_saved.connect(self._on_filter_saved)
        self.picker.edit_cancelled.connect(self._on_edit_cancelled)
        self.picker.edit_refused.connect(self._on_edit_refused)
        self.picker.level_requested.connect(self._on_picker_level)
        box.addWidget(self.picker)
        self.chips = FilterChips(self.picker.model())
        self.chips.removed.connect(self._on_chip_removed)
        self.chips.cleared.connect(self._on_chips_cleared)
        self.chips.changed.connect(self._on_chips_changed)
        self.chips.edit_requested.connect(self._on_chip_edit)
        box.addWidget(self.chips)

        parent_layout.addWidget(self.filter_group)

    # -- font style builders (single source: construction AND _refresh_fonts) --
    # This panel is PERSISTENT (not rebuilt per open), so a LIVE font-setting
    # change must re-compose every migrated widget's QSS. Each builder reads
    # scaled_area_px live; construction and the _refresh_fonts replay share them
    # so the two paint paths cannot drift.

    @staticmethod
    def _entry_font_css():
        """Line-edit / search-entry / icon font-size."""
        return f"font-size: {scaled_area_px('tables')}px;"

    @staticmethod
    def _plain_combo_css():
        """Sort/group combos (no highlight)."""
        return f"QComboBox {{ font-size: {scaled_area_px('buttons')}px; }}"

    @staticmethod
    def _group_title_css():
        """QGroupBox title (Search / Results)."""
        return (f"QGroupBox {{ font-size: {scaled_area_px('panel_titles')}px; "
                f"font-weight: bold; }}")

    @staticmethod
    def _table_font_css():
        t = kit.tokens()
        bg = t['secondary_light'].name()
        alt = kit._alpha(t['primary_text'], .025).name(QColor.HexArgb)
        selected = kit._alpha(t['primary'], .18).name(QColor.HexArgb)
        hair = t['hair_soft'].name(QColor.HexArgb)
        return (
            f"QTableWidget {{ font-size: {scaled_area_px('tables')}px; background: {bg};"
            f" alternate-background-color: {alt}; color: {t['primary_text'].name()};"
            f" selection-background-color: {selected}; selection-color: {t['primary_text'].name()};"
            f" border: 1px solid {hair}; border-radius: 8px; }}"
            "QTableWidget::item { border: none; padding: 0 10px; }"
            f"QHeaderView {{ background: {bg}; }}"
            f"QHeaderView::section {{ font-size: {scaled_area_px('table_headers')}px;"
            f" background: {bg}; color: {t['secondary_text'].name()};"
            f" border: none; border-bottom: 1px solid {hair}; padding: 0 10px; font-weight: 600; }}"
        )

    # Legacy fixed dimensions (find_chart construction, pre-td-2o8u). Floors are
    # max(legacy, fm): at default areas/scale the fm term is below these, so the
    # panel renders EXACTLY as pristine (GLM default-parity law); growth engages
    # only when the metric exceeds the legacy value.
    _LEGACY_SORTGROUP_COMBO_H = 26  # sort/group combo.setFixedHeight(26)
    _LEGACY_WEB_SEARCH_W = 200  # web_search_btn.setFixedWidth(200)

    def _refresh_fonts(self):
        """Re-compose the font QSS of every migrated widget from the live
        settings. Called from refresh_theme so a font-size change propagates into
        this persistent panel without a rebuild. The theme-coloured widgets
        (add-folder / browse buttons, index-status, results-count) carry the
        font-size in the colour QSS re-applied by refresh_theme."""
        if self.results_table is not None:
            self.results_table.setStyleSheet(self._table_font_css())
            self.results_table.verticalHeader().setDefaultSectionSize(round(28 * kit.area_fs("tables")))
            self.results_table.horizontalHeader().setFixedHeight(round(30 * kit.area_fs("table_headers")))
        for grp in (self.filter_group, self.results_group):
            if grp is not None:
                grp.setStyleSheet(self._group_title_css())
        for widget in (
            self.sign_names_combo,
            self.system_bar,
            self.scope_bar,
        ):
            widget.refresh_style()
        self.toolbar.refresh_metrics()
        self.trail.refresh_metrics()
        for widget in (self.picker, self.chips, self.results_bar, self.cards, self.inspector):
            widget.refresh_theme()
            widget.refresh_metrics()
        self.inspector_sheet.refresh_metrics()
        for widget in (self.library, self.status_bar, self.unsorted_section, self.sort_flow):
            if widget is not None:  # Sort with AI's are None in Lite
                widget.refresh_theme()
                widget.refresh_metrics()
        self.library_sheet.refresh_metrics()
        if self.sort_sheet is not None:
            self.sort_sheet.refresh_metrics()
        self.check_sheet.refresh_metrics()
        self.no_index_rebuild.set_metrics(kit.metrics())
        self.no_index_label.setStyleSheet(
            f"color: {get_theme_colors()['secondary_text']}; "
            f"font-size: {scaled_area_px('info_text')}px;")

    def _refresh_geometry(self):
        """td-2o8u: re-derive geometry floors as max(legacy, fm) for every
        migrated widget that shipped with a fixed height or width (the folder
        widgets are the Library's, sized by its own metrics). Called from
        refresh_theme (after _refresh_fonts), so
        floors track every live Font-Size area x Display Scale while never
        dropping below the pristine default size."""
        sgh = max(self._LEGACY_SORTGROUP_COMBO_H, _fm_min_height("buttons"))
        for combo in (self.sort_combo, self.group_combo):
            if combo is not None:
                combo.setFixedHeight(sgh)

        # Widths are CAPPED with setFixedWidth, measured with each widget's OWN
        # fontMetrics (the QSS/qt-material font is Roboto). +pad covers padding.
        def _cap_w(widget, legacy, pad):
            adv = widget.fontMetrics().horizontalAdvance(widget.text()) + pad
            widget.setFixedWidth(max(legacy, adv))

        if getattr(self, "web_search_btn", None) is not None:
            _cap_w(self.web_search_btn, self._LEGACY_WEB_SEARCH_W, 24)

    # ------------------------------------------------------------ search box
    def _create_search_section(self, parent_layout):
        """The toolbar (§4.2: level switch, search well with ``search_entry``,
        ASK AI / SEARCH WEB, FILTERS, LIBRARY) and the search trail (§4.3)."""
        self.search_entry = QLineEdit()  # styled by the SearchWell (info_text)
        self.search_entry.textChanged.connect(self._on_search_changed)
        self.toolbar = Toolbar(self.search_entry)
        self.toolbar.level_requested.connect(self.set_search_level)
        self.toolbar.search_web_requested.connect(self._on_web_search_clicked)
        self.toolbar.ask_ai_requested.connect(self.ask_ai_requested.emit)
        self.toolbar.filters_toggled.connect(self._on_filters_toggled)
        self.toolbar.library_requested.connect(self._on_library_requested)
        self.toolbar.well.token_removed.connect(self._remove_token)
        # web_lookup disables it while a lookup runs.
        self.web_search_inline_btn = self.toolbar.search_web
        parent_layout.addWidget(self.toolbar)
        self.trail = Trail()
        self.trail.action_clicked.connect(self._on_trail_action)
        parent_layout.addWidget(self.trail)

    def set_ask_ai_provider(self, provider):
        """Register the Find Chart AI search (its plan owns the behaviour);
        ASK AI shows only while one is registered (§4.2)."""
        self._ask_ai_provider = provider
        self.toolbar.set_ask_ai_visible(provider is not None)

    def _on_filters_toggled(self, on):
        """FILTERS shows or hides the picker (open by default); the active
        chips and the Advanced controls stay (review r7 #9)."""
        self.picker.setVisible(on)

    def _open_picker(self):
        """A chip edit opens the picker and lights FILTERS again."""
        self.picker.show()
        self.toolbar.set_filters_open(True)

    def _on_library_requested(self):
        """LIBRARY (§3.7) and the status bar's coverage: the Library sheet,
        or the Sort with AI sheet when a sort result arrived while it was
        closed (§4.9)."""
        if self._sort_pending:
            self._open_sort_sheet()
            return
        self.rate_sort.refresh()
        self.library_sheet.open_sheet()

    def _create_status_bar(self):
        """The status bar (§3.7): ``index_status`` is its status line, the
        QLabel core_gui calls ``setText`` on (INV-1)."""
        self.status_bar = StatusBar()
        self.index_status = self.status_bar.index_status
        self.status_bar.set_database(str(self.cache.path))
        self.status_bar.cancel_requested.connect(self._on_status_cancel)
        self.status_bar.coverage_clicked.connect(self._on_library_requested)
        self.status_bar.notice_action.connect(self._on_notice_action)

    def _on_status_cancel(self):
        """CANCEL stops the running job: the folder sync (after its commit
        point it only skips the computation) or the compute."""
        if self._index_worker is not None:
            self._index_worker.cancel()
        elif self._compute_worker is not None:
            self._cancel_compute()

    def _on_notice_action(self):
        """The notice's action: RETRY / RESUME (§3.7, bounded to the run that
        failed) or SORT WITH AI (§4.9: only shown while the feature is on)."""
        if self._notice_kind != NOTICE_RETRY:
            self._start_sort_request()
            return
        if self._compute_running() or self._index_running():
            self.status_bar.set_state(ALREADY_RUNNING_TEXT)
            return
        binding = self._retry_binding
        if binding is None:
            self._clear_retry_notice()
            return
        plan = self._read_store(lambda store: self._retry_plan(store, binding))
        if plan is _NOT_READ:
            return  # the notice stays: nothing ran
        self._retry_binding = None
        self._clear_retry_notice()
        if plan is None:
            self.status_bar.set_state(NOTHING_TO_RETRY_TEXT)
            self._store_changed()
            self._refresh_quietly()
            return
        self._start_compute(plan, _consented=True)

    @staticmethod
    def _retry_plan(store, binding):
        """The bound run's moments that still need it, in that run's system
        (never the current context's other moments): RETRY takes the ones
        that failed, RESUME also the ones that run never reached. Planned
        per extractor, each with its OWN set (round 9: one shared ``among``
        would let one extractor's set schedule another's moments)."""
        mode, system, moments, bound = binding
        # Only the very moments that run was for (review r15): an id now
        # naming another birth never qualifies.
        ids = frozenset().union(*moments.values()) if moments else frozenset()
        now = store.moments(ids)
        same = frozenset(mid for mid in ids if mid in bound and now.get(mid) == bound[mid])
        items = []
        expected = []
        for eid, planned in moments.items():
            extractor = registry.get(eid)
            state = coverage_moments(store, system, EVERYTHING, extractor)
            wanted = state.failed if mode == "retry" else state.failed | state.missing
            todo = frozenset(planned) & wanted & same
            if not todo:
                continue
            plan = compute.plan(
                store, system, (extractor,), EVERYTHING,
                among=todo, retry_failed=True, recompute_stale=False,
            )
            items.extend(item for item in plan.items if item.missing)
            expected.extend(plan.expected)
        if not items:
            return None
        return compute.ComputePlan(system, tuple(items), tuple(sorted(set(expected))))

    def _bind_retry(self, mode, plan, extractor_ids=None):
        """Remember what RETRY / RESUME may run: this plan's moments."""
        self._retry_binding = (
            mode,
            plan.system,
            {
                item.extractor.id: frozenset(item.missing)
                for item in plan.items
                if extractor_ids is None or item.extractor.id in extractor_ids
            },
            dict(plan.expected),  # the exact moments (review r15)
        )

    def _read_store(self, read):
        """Open the index and run ``read(store)`` inside ONE handler (review
        r8 #6: a busy store mid-read is the same state as at the open). No
        index: the no-index state; busy or locked: "Index busy: try again";
        another database error: shown as a failure. ``_NOT_READ`` then."""
        try:
            with self.cache.reader() as store:
                return read(store)
        except NoIndexError:
            self._show_no_index()
        except StoreBusyError:
            self.status_bar.show_state(states.store_busy(False))
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc) or "busy" in str(exc):
                self.status_bar.show_state(states.store_busy(False))
            else:
                self.status_bar.set_state(f"Index error: {exc}", states.ERROR)
        except sqlite3.DatabaseError as exc:
            self.status_bar.set_state(f"Index error: {exc}", states.ERROR)
        return _NOT_READ

    def _clear_retry_notice(self):
        if self._notice_kind == NOTICE_RETRY:
            self._set_notice(None)
            self.refresh_unsorted_downloads()

    def _open_compute_settings(self):
        """The Library's "change in Settings" link: the Settings tab."""
        from apps.widgets.hd.hd_frame_notice import open_settings

        if not open_settings(self.gui):
            self.status_bar.set_state("Open Settings to change the CPU share")

    def _apply_level(self):
        """Easy follows the app; Advanced exposes scope and system fields."""
        easy = self._level == fc_context.EASY
        self.toolbar.set_level(self._level)
        self.advanced_region.setVisible(not easy)

    def _on_tier_changed(self, tier):
        """Layout tier (§4.8): the toolbar's label row; regions follow in
        their waves. Display only, never a search."""
        self._display_changed()
        self.toolbar.set_layout_tier(tier)
        self.picker.set_drill_down(tier >= responsive.T3)
        self.results_bar.set_tier(tier)
        cards = tier >= responsive.T4
        self.results_table.setVisible(not cards)  # still filled: Pro reads it
        self.cards.setVisible(cards)
        self.inspector.set_tier(tier)
        self._place_inspector(tier <= responsive.T1)
        self.inspector_sheet.set_full_page(tier >= responsive.T4)
        self.library_sheet.set_full_page(tier >= responsive.T4)
        if self.sort_sheet is not None:
            self.sort_sheet.set_full_page(tier >= responsive.T4)
        self.status_bar.set_tier(tier)

    def _display_changed(self):
        """A display-only event (resize, tier, theme, fonts, columns): bump
        the generation so an older worker completion stays quiet, and keep a
        pending debounce quiet. Never searches itself (INV-3, review r5 #5)."""
        self._search_generation += 1
        if self.search_timer is not None and self.search_timer.isActive():
            self._timer_quiet = True

    def showEvent(self, event):
        """Panel shown: the unsorted folder is counted again (§4.9). A panel
        shown again after a close starts a new lifecycle (old relays stay
        void); never after app quit (review r14)."""
        super().showEvent(event)
        if self._closing and not self._quit:
            self._closing = False
            self._reconcile_jobs()
        if getattr(self, "unsorted_section", None) is not None:
            self.refresh_unsorted_downloads(force_recount=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "search_timer", None) is not None:
            self._display_changed()
        if getattr(self, "_controls_timer", None) is not None:
            self._controls_timer.start()

    def eventFilter(self, watched, event):
        if (watched is getattr(self, "_controls_content", None)
                and event.type() == QEvent.LayoutRequest):
            # Do not change fixed heights while Qt is assigning geometry:
            # that leaves siblings using the previous height until resize.
            self._controls_timer.start()
        return super().eventFilter(watched, event)

    def _fit_controls(self):
        """Keep results and the status line reachable in short windows.

        Only the controls scroll when their natural height would otherwise
        squeeze the results off the bottom (including enlarged fonts).
        """
        layout = self._controls_content.layout()
        width = max(1, self.controls_scroll.viewport().width())
        natural = (layout.totalHeightForWidth(width) if layout.hasHeightForWidth()
                   else layout.sizeHint().height())
        reserve = self.toolbar.sizeHint().height() + self.trail.sizeHint().height()
        reserve += (self.results_bar.heightForWidth(self.width())
                    if self.results_bar.hasHeightForWidth()
                    else self.results_bar.sizeHint().height())
        reserve += self.status_bar.sizeHint().height() + round(240 * kit.area_fs("tables")) + 50
        available = max(100, self.height() - reserve)
        fs = kit.area_fs("info_text")
        browser_height = max(round(120 * fs), min(round(240 * fs),
                             self.picker.browser.height() + available - natural))
        if self.picker.browser.height() != browser_height:
            self.picker.browser.setFixedHeight(browser_height)
            # Qt propagates child size hints on deferred LayoutRequests. The
            # card, picker and group can still report the OLD browser height
            # here; feeding that stale total into the next fit makes Advanced
            # oscillate indefinitely. Invalidate the complete ancestor chain
            # bottom-up before measuring the new total, only after a change.
            ancestor = self.picker.browser.parentWidget()
            while ancestor is not None:
                if ancestor.layout() is not None:
                    ancestor.layout().invalidate()
                ancestor.updateGeometry()
                if ancestor is self._controls_content:
                    break
                ancestor = ancestor.parentWidget()
            natural = (layout.totalHeightForWidth(width) if layout.hasHeightForWidth()
                       else layout.sizeHint().height())
        other_minimum = self.layout().minimumSize().height() - self.controls_scroll.minimumHeight()
        height = min(natural, available, max(0, self.height() - other_minimum - 2))
        if self.controls_scroll.height() != height:
            self.controls_scroll.setFixedHeight(height)
            # QScrollArea has its own delayed LayoutRequest. Recompute the
            # outer layout now so its siblings use the new fixed height.
            self.layout().invalidate()
            self.layout().activate()

    def _on_search_changed(self, text: str = ""):
        """Handle search text change with debouncing (a user search)."""
        self._bump_revision()  # a pending debounce counts as a change
        self._timer_quiet = False
        self.search_timer.stop()
        self.search_timer.start()
        self.toolbar.well.set_busy(True)  # the searching hairline (§4.1)

    def _on_search_timer(self):
        """The debounce fired: a user search, unless a display-only event
        restarted it since (INV-3)."""
        quiet, self._timer_quiet = self._timer_quiet, False
        if quiet:
            self._run_search(auto_compute=False)
        else:
            self._refresh_results()

    def _remove_token(self, token):
        """A token pill's x: take the token out of the search box."""
        text = self.search_entry.text().replace(token, " ", 1)
        self.search_entry.setText(" ".join(text.split()))

    def _search_tokens(self):
        """The search box's legacy ``body:label`` tokens, each with its filter
        (``terms.parse_term``, the CLI's translator)."""
        tokens = []
        for match in terms.TOKEN.finditer(self.search_entry.text()):
            parsed = terms.parse_term(match.group(0))
            if parsed.filters:
                tokens.append((match.group(0), parsed.filters[0]))
        return tuple(tokens)

    # -------------------------------------------------------------- controls
    def _create_controls_section(self, parent_layout):
        """The results bar (§3.5, §4.6): count, SORT, GROUP, PLACEMENTS and
        the column-group chips. ``sort_combo`` / ``group_combo`` stay the
        panel's (Pro A.2 selects with findData); the bar only lays them out."""
        self.sort_combo = ReadableCombo()
        # Each item carries its SortKey in itemData (SPEC-LOC-002 INV-3; Pro
        # selects with findData).
        for key in SortKey:
            self.sort_combo.addItem(key.value, key.value)
        # td-2o8u: keep pristine fixed width (elides); height via _refresh_geometry.
        self.sort_combo.setFixedWidth(120)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_dropdown_changed)

        self.group_combo = ReadableCombo()
        # Each item carries its group key in itemData; 'none' = no grouping.
        for key in results.GROUPS:
            self.group_combo.addItem(key, key)
        self.group_combo.setFixedWidth(120)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)

        self.results_bar = ResultsBar(self.sort_combo, self.group_combo)
        all_placements, groups = result_columns.load_columns_setting(
            get_settings().get(result_columns.SETTING_KEY)
        )
        self.results_bar.set_columns(all_placements, groups)
        self._column_model = result_columns.model(all_placements, groups)
        self.results_bar.reverse_toggled.connect(self._on_reverse_toggled)
        self.results_bar.placements_changed.connect(self._on_columns_changed)
        self.results_bar.groups_changed.connect(self._on_columns_changed)
        parent_layout.addWidget(self.results_bar)

    def _on_sort_dropdown_changed(self, text: str = ""):
        """Handle sort dropdown change - reset to ascending order."""
        self.sort_reverse = False
        self.results_bar.set_reverse(False)
        self._bump_revision()  # the sort is part of the query
        self._refresh_quietly()

    def _on_group_changed(self, *_):
        self._refresh_quietly()

    def _on_reverse_toggled(self, on):
        self.sort_reverse = bool(on)
        self._bump_revision()
        self._refresh_quietly()

    def _on_columns_changed(self, *_):
        """PLACEMENTS or a column group: saved, re-laid, shown quietly; the
        columns read stored rows only, never a compute (§3.5, INV-3)."""
        bar = self.results_bar
        get_settings().set(
            result_columns.SETTING_KEY,
            result_columns.dump_columns_setting(bar.all_placements(), bar.groups()),
        )
        self._column_model = result_columns.model(bar.all_placements(), bar.groups())
        self._apply_columns()
        self._display_changed()
        self._refresh_quietly()

    def _apply_columns(self):
        """Logical 0-9 never move (INV-1); extras appended at 10 and up and
        the ALL placements moved visually after Moon."""
        model = self._column_model
        table = self.results_table
        self._row_cells = {}
        self._rendered_rows_key = None
        table.setColumnCount(model.column_count)
        for i, header in zip(model.logical, model.headers, strict=True):
            table.setHorizontalHeaderItem(i, QTableWidgetItem(header))
            table.setColumnWidth(i, 90)
        result_columns.apply_visual_order(table.horizontalHeader(), model.visual_order)

    # --------------------------------------------------------------- results
    def _create_results_section(self, parent_layout):
        """Create the results table (QTableWidget)."""
        # §3.7 no index: an empty area with REBUILD INDEX (a consented scan).
        self.no_index_widget = QWidget()
        no_index = QVBoxLayout(self.no_index_widget)
        no_index.setContentsMargins(0, 24, 0, 24)
        self.no_index_label = QLabel(states.TRAIL_NO_INDEX)
        self.no_index_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_index_rebuild = kit.KitSegment(
            "fc_no_index_rebuild", "REBUILD INDEX", kit.metrics(),
            icon="fc_rebuild", tooltip="Read the chart folders and build the index")
        self.no_index_rebuild.clicked.connect(self._rebuild_index)
        no_index.addWidget(self.no_index_label)
        no_index.addWidget(self.no_index_rebuild, 0, Qt.AlignmentFlag.AlignHCenter)
        self.no_index_widget.hide()
        parent_layout.addWidget(self.no_index_widget)
        theme = get_theme_colors()

        results_group = QGroupBox("")
        self.results_group = results_group
        results_group.setStyleSheet(self._group_title_css())
        results_layout = QVBoxLayout(results_group)
        results_layout.setContentsMargins(0, 0, 0, 0)

        self.results_table = QTableWidget()
        self.results_table.setItemDelegate(ResultDelegate(self.results_table))
        self.results_table.setMouseTracking(True)
        self.results_table.setColumnCount(len(results.COLUMNS))
        self.results_table.setHorizontalHeaderLabels(list(results.COLUMNS))
        # font-size in the table's own QSS (setFont is the O-6 class under
        # qt-material). Replayed live via _refresh_fonts.
        self.results_table.setStyleSheet(self._table_font_css())
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setShowGrid(False)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)

        for column, width in enumerate((180, 90, 90, 90, 120, 100, 130, 100, 180, 160)):
            self.results_table.setColumnWidth(column, width)
        header = self.results_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        self.results_table.cellDoubleClicked.connect(self._on_chart_double_clicked)
        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(
            self._on_results_context_menu
        )
        header.sectionClicked.connect(self._on_header_clicked)
        self.results_table.itemSelectionChanged.connect(self._on_table_selection)
        self.results_table.cellClicked.connect(self._on_cell_clicked)
        self._apply_columns()

        # Cards at phone width (T4): the table stays filled (Pro reads it).
        self.cards = ResultCards()
        self.cards.entry_activated.connect(self._on_card_activated)
        self.cards.entry_opened.connect(self._on_card_opened)
        self.cards.hide()
        # The inspector: docked at T0/T1, a sheet below (§3.6, §4.7).
        self.inspector = Inspector()
        self.inspector.closed.connect(self._close_inspector)
        self.inspector.open_requested.connect(self._open_entry_id)
        self.inspector.copy_requested.connect(self._copy_entry)
        self.inspector.show_in_folder_requested.connect(self._show_entry_in_folder)
        self.inspector.trash_requested.connect(self._trash_entry)
        self.inspector.compute_requested.connect(self._on_inspector_compute)
        self.inspector.hide()
        self.inspector_sheet = kit.Sheet(self, "Chart", width=kit.INSPECTOR_W, chrome=False)
        self.inspector_sheet.closed.connect(self._close_inspector)
        self._inspector_docked = True
        self._selected_entry_id = None
        self._results_row = QHBoxLayout()
        self._results_row.setContentsMargins(0, 0, 0, 0)
        self._results_row.setSpacing(8)
        self._results_row.addWidget(self.results_table, 1)
        self._results_row.addWidget(self.cards, 1)
        self._results_row.addWidget(self.inspector)
        results_layout.addLayout(self._results_row, 1)

        # === WEB DOWNLOAD SECTION (visible when 0 results + query) ===
        self._create_web_download_section(results_layout, theme)

        parent_layout.addWidget(results_group, 1)  # Stretch to fill
        self.results_hint = QLabel("Click a chart to inspect it. Double click opens it. Right click for more.")
        self.results_hint.setWordWrap(True)
        parent_layout.addWidget(self.results_hint)



    def _on_header_clicked(self, logical_index):
        """Column header click: sort by it, again to reverse (not Path, Source)."""
        sort_key = results.COLUMN_SORTS.get(logical_index)
        if sort_key is None:
            return
        if self.sort_combo.currentData() == sort_key.value:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_reverse = False
        self.sort_combo.blockSignals(True)
        self.sort_combo.setCurrentIndex(self.sort_combo.findData(sort_key.value))
        self.sort_combo.blockSignals(False)
        self.results_bar.set_reverse(self.sort_reverse)
        self._bump_revision()
        self._refresh_quietly()


    def _on_chart_double_clicked(self, row, column):
        self._open_row(row)

    def _row_menu(self, row):
        """The result's menu (§3.5): Load chart; for a chart file Show in
        folder and Move to trash. Returns the menu and its actions."""
        filepath = self.tree_filepath_map.get(row)
        menu = kit.style_menu(QMenu(self))
        actions = {"load": menu.addAction("Load chart")}
        if filepath:
            actions["folder"] = menu.addAction("Show in folder")
            menu.addSeparator()
            actions["trash"] = menu.addAction("Move to trash")
        return menu, actions

    def _row_menu_texts(self, row):
        menu, _actions = self._row_menu(row)
        texts = [a.text() for a in menu.actions() if a.text()]
        menu.deleteLater()
        return texts

    def _on_results_context_menu(self, position):
        """Load any result; show in folder or trash only a chart file."""
        row = self.results_table.rowAt(position.y())
        if row not in self.tree_entry_map:
            return
        filepath = self.tree_filepath_map.get(row)
        entry = self.tree_entry_map[row]
        menu, actions = self._row_menu(row)
        self.results_table.selectRow(row)
        action = menu.exec(self.results_table.viewport().mapToGlobal(position))
        if action is None:
            return
        if action == actions["load"]:
            self._open_row(row)
        elif action == actions.get("folder"):
            self._show_entry_in_folder(entry.entry_id)
        elif action == actions.get("trash"):
            self._move_chart_to_trash(filepath)

    # -------------------------------------------------------------- opening
    def _open_row(self, row):
        """Open a result in the search system (D11, ``find_chart/opening.py``):
        a file by its path; a loaded chart of this session by its entry id;
        another profile's chart copied into this session first. An entry
        with unsaved changes is a session entry: its session version opens."""
        entry = self.tree_entry_map.get(row)
        if entry is None:
            return
        filepath = self.tree_filepath_map.get(row)
        if filepath:
            note = self._match_app_system()
            self.chart_selected.emit(filepath)
            self._open_note(note)
            return
        ref = opening.session_ref(entry.entry_id)
        memory_panel = getattr(self.gui, "memory_panel", None)
        session_manager = getattr(self.gui, "session_manager", None)
        if ref is None or memory_panel is None or session_manager is None:
            return
        current = session_manager.current_profile
        if ref.profile == current:
            if opening.memory_index(memory_panel.charts, ref.session_id) < 0:
                self.index_status.setText(
                    f"{entry.name} is no longer loaded in this profile."
                )
                return
            note = self._match_app_system()
            self.session_chart_selected.emit(entry.entry_id)
            self._open_note(note)
            return
        chart = opening.read_profile_chart(sync.profiles_dir(), ref)
        if chart is None:
            self.index_status.setText(
                f"{entry.name} is no longer in profile {ref.profile}."
            )
            return
        note = self._match_app_system()
        index = memory_panel.add_chart(
            chart["recipe"],
            chtk_path=chart.get("chtk_path") or None,
            is_transit=bool(chart.get("is_transit")),
            **kind_field(chart),
        )
        session_id = memory_panel.charts[index]["id"]
        self.session_chart_selected.emit(opening.session_entry_id(current, session_id))
        self._open_note(f"Copied from profile {ref.profile}. {note}".strip())

    def _match_app_system(self):
        """Put the app on the search's mode, ayanamsa and house system (the
        result matched there) through its runtime zodiac controls; the note
        that says so, and what the app keeps of its own ("" when nothing)."""
        zodiac = getattr(self.gui, "zodiac_settings", None)
        if zodiac is None:
            return ""
        ctx = self.search_context()
        target = ctx.system
        app = opening.AppFrame(
            mode=self.gui.state.aditya_mode,
            ayanamsa_id=self.gui.chart_sidereal_ayanamsa_id,
            nakshatra_coords=self.gui.nakshatra_coords,
            house_system=self.gui.state.house_system,
        )
        changes = opening.frame_changes(target, app)
        settings = get_settings()

        def app_setting(field):
            key = FIELD_SETTINGS[field]
            return settings.get(key, registry_default(key))

        kept = opening.kept_fields(
            target,
            app,
            changes,
            self.system_bar.pinned if ctx.level == fc_context.ADVANCED else {},
            cot_order=app_setting(Field.COT_PLANET_ORDER),
            hd_level=app_setting(Field.HD_FRAME),
        )
        for key in opening.APPLY_ORDER:
            if key == opening.MODE_KEY and key in changes:
                zodiac.set_mode(changes[key])
            elif key in changes:
                zodiac.set_runtime(key, changes[key])
        parts = []
        if changes:
            named = [
                _item_label(field, target)
                for field in (Field.MODE, Field.AYANAMSA_ID, Field.HOUSE_SYSTEM)
                if FIELD_SETTINGS[field] in changes
            ]
            parts.append(f"The app now uses the search system: {', '.join(named)}.")
        if kept:
            names = [
                "nakshatra coordinates"
                if item == opening.NAKSHATRA_COORDS
                else MORE_FIELDS[item][0].rstrip(":")
                for item in kept
            ]
            parts.append(
                f"It keeps its own {', '.join(names)} (Settings), "
                "which the search pinned otherwise."
            )
        return " ".join(parts)

    def _open_note(self, note):
        if note:
            self.index_status.setText(note)

    # ------------------------------------------------------ filters (W6)
    def _new_filter_id(self):
        self._filter_counter += 1
        return f"r{self._filter_counter}"

    def _bump_revision(self):
        """Every change of the effective query bumps the revision at once
        (SPEC-FIND-006 §5.1): an edit, a pin, an app frame change, a level
        switch, a scope or folder change, an applied query."""
        self.query_revision += 1

    def _token_filters(self):
        """The search box's resolving tokens: ``(token, filter, offset)``."""
        found = []
        for match in terms.TOKEN.finditer(self.search_entry.text()):
            parsed = terms.parse_term(match.group(0))
            if not parsed.filters:
                continue
            try:
                resolve(parsed.filters[0])
            except BadFilterError:
                continue
            found.append((match.group(0), parsed.filters[0], match.start()))
        return found

    def _set_chips(self, filters, ids):
        """Chips and their ids together, silently (no search)."""
        self.chips.set_filters(filters)
        self._row_ids = list(ids)
        self._sync_filter_count()

    def _sync_filter_count(self):
        self.toolbar.set_filter_count(len(self.chips.filters()) + len(self._token_filters()))
        if hasattr(self, "inspector"):
            self.inspector.set_first_filter(self._first_filter())

    def _first_filter(self):
        """The funnel's first filter (SPEC-FIND-007 §2.1): the first chip,
        else the search box's first resolved token."""
        chips = self.chips.filters()
        if chips:
            return chips[0]
        tokens = self._token_filters()
        return tokens[0][1] if tokens else None

    def _on_filter_added(self, flt):
        self._set_chips((*self.chips.filters(), flt), (*self._row_ids, self._new_filter_id()))
        self._bump_revision()
        self._refresh_results()

    def _on_filter_saved(self, old, new):
        filters = list(self.chips.filters())
        index = self._editing_index
        if index is None or index >= len(filters) or filters[index] != old:
            index = filters.index(old) if old in filters else None
        self._editing_index = None
        if index is None:  # the edited chip went meanwhile: a new filter
            self._on_filter_added(new)
            return
        filters[index] = new
        self._set_chips(filters, self._row_ids)  # the id stays
        self._bump_revision()
        self._refresh_results()

    def _on_edit_cancelled(self):
        self._editing_index = None

    def _on_edit_refused(self, _flt, reason):
        self._editing_index = None
        self.trail.set_state(f"This filter cannot be edited in the picker: {reason}", "warn")

    def _on_chip_edit(self, index, flt):
        self._open_picker()
        self._edit_chip(index, flt)

    def _edit_chip(self, index, flt):
        self._editing_index = index
        was = self._level
        if not self.picker.load_filter(flt):
            return
        if self._level != was:
            self.trail.set_state("Switched to Advanced to edit this filter")

    def _on_picker_level(self, level):
        """The picker's links, or an Advanced filter loaded in Easy (the
        picker has already switched itself)."""
        self.set_search_level(level)

    def _on_chip_removed(self, index):
        if 0 <= index < len(self._row_ids):
            del self._row_ids[index]
        if self._editing_index is not None:
            if self._editing_index == index:
                self.picker.cancel_edit()
                self._editing_index = None
            elif self._editing_index > index:
                self._editing_index -= 1

    def _on_chips_cleared(self):
        self._row_ids = []
        if self._editing_index is not None:
            self.picker.cancel_edit()
            self._editing_index = None

    def _on_chips_changed(self):
        self._row_ids = self._row_ids[: len(self.chips.filters())]
        self._sync_filter_count()
        self._bump_revision()
        self._refresh_results()

    def _uncomputed(self, store, ctx):
        """Extractors with nothing computed in this system at the running
        version (§3.3 "Not computed"): read per system and store epoch,
        never computed (review r7 #10)."""
        key = (ctx.system, self._store_epoch)
        if self._uncomputed_cache[0] != key:
            none = set()
            for extractor in registry.EXTRACTORS:
                pid = store.projection_id(extractor.projection(ctx.system))
                if pid is None or not store.any_computed(pid, extractor.version):
                    none.add(extractor.id)
            self._uncomputed_cache = (key, frozenset(none))
        return self._uncomputed_cache[1]

    def _show_filter_state(self, query, result, uncomputed=frozenset()):
        """The FILTERS count, the amber "not computed" dots on chips (this
        search's gaps) and on the picker's FACT items (nothing computed in
        this system, whatever the query) (§3.3, §3.4, §4.5)."""
        self._sync_filter_count()
        lacking = {c.extractor_id: c for c in result.coverage if not c.complete}
        dots = {}
        for index, flt in enumerate(self.chips.filters()):
            try:
                owner = taxonomy.owner(flt.property)
            except BadFilterError:
                continue
            cov = lacking.get(owner)
            if cov is not None:
                missing = max(cov.in_scope - cov.computed, 0)
                noun = "chart" if missing == 1 else "charts"
                dots[index] = f"Not computed yet for {missing:,} {noun} in this search"
        self.chips.set_not_computed(dots)
        self.picker.set_not_computed(self._lacking_fact_keys(frozenset(uncomputed)))

    def _lacking_fact_keys(self, lacking):
        if not lacking:
            return frozenset()
        # Availability belongs to properties, not to a particular body's
        # possible values. Do not enumerate every body/value combination.
        if self._fact_dots_cache[0] != lacking:
            keys = set()
            for facet in facets.FACETS:
                if facet.slot is not facets.Slot.VALUE:
                    continue
                for prop in facet.properties:
                    if taxonomy.owner(prop) in lacking:
                        keys.add(facet.key)
                        keys.add(f"{facet.key}:{prop}")
            self._fact_dots_cache = (lacking, frozenset(keys))
        return self._fact_dots_cache[1]

    # ------------------------------------------------- Ask AI API (W6)
    def query_snapshot(self):
        """The whole effective query at this revision (SPEC-FIND-006 §5.1)."""
        ctx = self.search_context()
        query = self._query(ctx)
        tokens = self._token_filters()
        ids = (*self._row_ids, *(f"t{at}" for _t, _f, at in tokens))
        origins = (
            *(fc_context.ROW for _ in self._row_ids),
            *(fc_context.TOKEN for _ in tokens),
        )
        unchecked = set(self._get_unchecked_folders())
        folders = []
        paths = [e.text().strip() for e in self.folder_entries if e.text().strip()]
        try:
            with self.cache.reader() as store:
                for path in paths:
                    scope = Scope(sources=Sources.FOLDERS, folders=(path,),
                                  include_fileless=False, kinds=frozenset(EntryKind))
                    folders.append(FolderRef(path, path not in unchecked,
                                             len(candidates(store, scope))))
        except (NoIndexError, StoreBusyError, sqlite3.OperationalError):
            folders = [FolderRef(p, p not in unchecked, 0) for p in paths]
        return QuerySnapshot(
            query=query,
            filter_ids=ids,
            origins=origins,
            folders=tuple(folders),
            pinned=dict(self.system_bar.pinned) if ctx.level == fc_context.ADVANCED else {},
            level=ctx.level,
            revision=self.query_revision,
        )

    def _validate_filters(self, filters):
        for flt in filters:
            resolve(flt)  # raises BadFilterError, nothing changed yet

    def add_filters(self, filters):
        """Add several filters atomically (remote control, Ask AI): all
        validated first (``BadFilterError``, nothing changed), one chip each,
        ONE search through the consent rule."""
        filters = tuple(filters)
        self._validate_filters(filters)
        if not filters:
            return
        self._set_chips(
            (*self.chips.filters(), *filters),
            (*self._row_ids, *(self._new_filter_id() for _ in filters)),
        )
        self._bump_revision()
        self._refresh_results()

    def apply_query(self, query, filter_ids, origins):
        """Apply a whole effective query in one step (SPEC-FIND-006 §7.3,
        SPEC-FIND-005 §4.2): ``query.filters`` with a parallel id (``None``:
        a new row) and origin each. Every field is validated before anything
        changes (``BadFilterError``; ``ValueError`` with a reason): lengths,
        duplicate ids, origins; a token filter must still be what its token
        parses to ("token_changed"); ``query.system`` must be the context's
        ("system_change_unsupported"); ``query.limit`` must be None
        ("limit_unsupported"); in Easy the scope must be the context's
        ("needs_advanced"); in Advanced it must be what the scope bar and
        the folder ticks can express ("unrepresentable_scope"); ``query.text``
        must be plain free text the box keeps as itself, no ``key:value``
        token and no edge punctuation the box strips
        ("unrepresentable_text"). Then the
        box, the chips, the sort, the scope and the ticks are set silently
        and ONE search runs, computing only through the consent rule."""
        filters = tuple(query.filters)
        filter_ids, origins = tuple(filter_ids), tuple(origins)
        if not len(filters) == len(filter_ids) == len(origins):
            raise ValueError("filters, ids and origins differ in length")
        given = [fid for fid in filter_ids if fid is not None]
        if len(given) != len(set(given)):
            raise ValueError("duplicate filter ids")
        self._validate_filters(filters)
        ctx = self.search_context()
        if query.system != ctx.system:
            raise ValueError("system_change_unsupported")
        if query.limit is not None:
            raise ValueError("limit_unsupported")
        sort = SortKey(query.sort)
        if ctx.level == fc_context.EASY and query.scope != ctx.scope:
            raise ValueError("needs_advanced")
        ticks = None
        if ctx.level == fc_context.ADVANCED and query.scope != ctx.scope:
            ticks = self._ticks_for(query.scope)  # raises before any change
        current_tokens = {
            f"t{at}": (token, flt) for token, flt, at in self._token_filters()
        }
        kept_tokens = []
        rows, row_ids = [], []
        for flt, fid, origin in zip(filters, filter_ids, origins, strict=True):
            if origin == fc_context.TOKEN:
                if fid not in current_tokens:
                    raise ValueError(f"unknown token id {fid!r}")
                token, current = current_tokens[fid]
                if flt != current:
                    raise ValueError(f"token_changed {fid!r}")
                kept_tokens.append(token)
            elif origin == fc_context.ROW:
                rows.append(flt)
                row_ids.append(fid if fid in self._row_ids else None)
            else:
                raise ValueError(f"unknown origin {origin!r}")
        # The box parses its text into tokens and free text: the text given
        # must come back as exactly itself, never as an added, dropped or
        # changed filter (review r8 #3).
        residual = " ".join((query.text or "").split())
        text = " ".join([*kept_tokens, *residual.split()])
        if terms.TOKEN.search(residual) or terms.parse_term(text).text != residual or [
            m.group(0) for m in terms.TOKEN.finditer(text)
        ] != kept_tokens:
            raise ValueError("unrepresentable_text")
        # Validated: from here on nothing raises before the one search.
        row_ids = [fid if fid is not None else self._new_filter_id() for fid in row_ids]
        self.search_entry.blockSignals(True)
        try:
            self.search_entry.setText(text)
        finally:
            self.search_entry.blockSignals(False)
        self.search_timer.stop()
        self.toolbar.well._sync_clear()
        self.sort_combo.blockSignals(True)
        try:
            self.sort_combo.setCurrentIndex(self.sort_combo.findData(sort.value))
        finally:
            self.sort_combo.blockSignals(False)
        self.sort_reverse = bool(query.reverse)
        self.results_bar.set_reverse(self.sort_reverse)
        if ticks is not None:
            self._apply_scope_silently(query.scope, ticks)
        if self._editing_index is not None:
            self.picker.cancel_edit()
            self._editing_index = None
        self._set_chips(rows, row_ids)
        self._bump_revision()
        self._refresh_results()

    def _ticks_for(self, scope):
        """The folder ticks that make the scope bar express ``scope``
        (Advanced), or ``ValueError("unrepresentable_scope")``: kinds birth
        only or all, folders and hidden among the Library's own folders.
        Checked by rebuilding the scope from them."""
        if scope.kinds not in (frozenset({EntryKind.BIRTH}), frozenset(EntryKind)):
            raise ValueError("unrepresentable_scope")
        live = self.search_context().scope
        if (scope.forgetting, scope.retained) != (live.forgetting, live.retained):
            # Removed folders still owed a forget are the panel's own state
            # (review r11): a caller can neither add nor drop one.
            raise ValueError("unrepresentable_scope")
        norm = os.path.normpath
        paths = [norm(e.text().strip()) for e in self.folder_entries]
        known = {p for p in paths if p != "."}
        wanted = {norm(f) for f in scope.folders}
        hidden = {norm(f) for f in scope.hidden}
        if not (wanted <= known and hidden <= known):
            raise ValueError("unrepresentable_scope")
        current = [c.isChecked() for c in self.folder_checkboxes]
        if scope.sources is Sources.FOLDERS:
            ticks = [p in wanted for p in paths]
        elif scope.sources is Sources.ALL:
            ticks = [p not in hidden for p in paths]
        else:
            ticks = current
        checked = [p for p, t in zip(paths, ticks) if t and p in known]
        unchecked = [p for p, t in zip(paths, ticks) if not t and p in known]
        rebuilt = fc_context.advanced_scope(
            scope.sources, scope.kinds, checked, unchecked, scope.include_fileless,
            live.forgetting,  # removed folders still in the index, not a tick
            live.retained,
        )
        if rebuilt != Scope(
            sources=scope.sources,
            folders=tuple(norm(f) for f in scope.folders),
            include_fileless=scope.include_fileless,
            hidden=tuple(norm(f) for f in scope.hidden),
            kinds=scope.kinds,
            forgetting=scope.forgetting,
            retained=scope.retained,
        ):
            raise ValueError("unrepresentable_scope")
        return ticks

    def _apply_scope_silently(self, scope, ticks):
        """Sources, kinds, the folder ticks and the file-less tick from
        ``scope`` without a search each."""
        bar = self.scope_bar
        bar.blockSignals(True)
        try:
            bar.buttons[scope.sources].setChecked(True)
            bar.kinds_check.setChecked(scope.kinds != frozenset({EntryKind.BIRTH}))
        finally:
            bar.blockSignals(False)
        for check, tick in zip(self.folder_checkboxes, ticks):
            check.blockSignals(True)
            check.setChecked(tick)
            check.blockSignals(False)
            check.update()
        self.fileless_checkbox.blockSignals(True)
        self.fileless_checkbox.setChecked(scope.include_fileless)
        self.fileless_checkbox.blockSignals(False)
        self.fileless_checkbox.update()

    # ---------------------------------------------------------------- search
    # ------------------------------------------------------- search context
    def search_level(self):
        """``"easy"`` or ``"advanced"`` (``ui.find_chart_search_level``)."""
        return self._level

    def set_search_level(self, level):
        """Switch Easy / Advanced: persisted, display only (INV-3)."""
        level = fc_context.level_of(level)
        if level == self._level:
            return
        self._level = level
        get_settings().set(fc_context.LEVEL_KEY, level)
        self._apply_level()
        self._relabel()

    def search_context(self) -> SearchContext:
        """The one effective frame, naming and scope (§3.2, INV-4). Easy: the
        app's frame and naming and the Easy scope, whatever is pinned or
        saved; Advanced: the pins, the panel's sign names, the scope bar."""
        include_fileless = self.fileless_checkbox.isChecked()
        if self._level == fc_context.EASY:
            system = self.system_bar.app_system()
            return SearchContext(
                fc_context.EASY,
                system,
                fc_context.app_naming(
                    getattr(self.gui, "use_western_names", False),
                    getattr(self.gui, "sign_language", "en"),
                ),
                fc_context.easy_scope(
                    self._get_unchecked_folders(),
                    include_fileless,
                    self._forgetting(),
                    self._configured_folders(),
                ),
            )
        system = self.system_bar.system()
        return SearchContext(
            fc_context.ADVANCED,
            system,
            self._naming(system),
            fc_context.advanced_scope(
                self.scope_bar.sources(),
                self.scope_bar.kinds(),
                self._get_checked_folders(),
                self._get_unchecked_folders(),
                include_fileless,
                self._forgetting(),
                self._configured_folders(),
            ),
        )

    def _naming(self, system):
        """Advanced labels for a search in ``system`` (varuna/47): the
        switcher's pick, never the app's use_western_names (the system may be
        pinned). Easy reads the app's naming (``search_context``)."""
        return search_naming(
            system.mode,
            self.sign_names_combo.sign_names(),
            getattr(self.gui, "sign_language", "en") or "en",
        )

    def _filter_choices(self):
        """Value narrowing in the current context (the picker's VALUE
        column keeps what the store holds)."""
        ctx = self.search_context()
        return FilterChoices(ctx.system, ctx.naming, self.cache.reader)

    def _scope(self):
        return self.search_context().scope

    def _query(self, ctx: SearchContext):
        """The search: free text, filter rows and the box's tokens that resolve
        (one that does not is shown in red on its row and left out)."""
        token_filters = [flt for _token, flt, _at in self._token_filters()]
        return Query(
            system=ctx.system,
            text=terms.parse_term(self.search_entry.text()).text,
            scope=ctx.scope,
            filters=(*self.chips.filters(), *token_filters),
            sort=SortKey(self.sort_combo.currentData()),
            reverse=self.sort_reverse,
        )

    def _sync_token_pills(self):
        """The pills follow the whole parse (recognised AND ignored tokens),
        rebuilt whenever either changes (review r6 #3)."""
        tokens = self._search_tokens()
        signature = (tokens, terms.parse_term(self.search_entry.text()).ignored)
        if signature != self._tokens:
            self._tokens = signature
            self._show_token_pills(tokens)

    def _show_token_pills(self, tokens):
        """The search box's tokens as pills in the SearchWell (§3.4): a
        resolving token plain, a bad value or an unknown key red with the
        reason in its tooltip (and not searched)."""
        pills = []
        for token, flt in tokens:
            try:
                resolve(flt)
            except BadFilterError as exc:
                pills.append((token, token, False, str(exc)))
            else:
                pills.append((token, token, True, ""))
        for token in terms.parse_term(self.search_entry.text()).ignored:
            key = token.split(":", 1)[0]
            pills.append((token, token, False, f"Unknown key {key!r}: not searched"))
        self.toolbar.well.set_tokens(pills)

    def _on_scope_changed(self, *_):
        """Sources, kinds, a folder tick or the file-less tick: a query
        change (revision), shown quietly, never a compute (INV-3)."""
        self._bump_revision()
        self._refresh_quietly()

    def _refresh_results(self):
        """Run the search and show it; then compute what it lacks, with the
        user's consent (SPEC-FIND-003 §3.6)."""
        self._run_search(auto_compute=True)

    def _refresh_quietly(self):
        """Run the search and show it; never compute (startup preload, panel
        load, a sync job finishing: SPEC-FIND-004 §5.2 item 6; every
        display-only change, INV-3). Bumps the generation, so an older
        search or worker completion never turns into a compute request, and
        keeps a pending debounce quiet."""
        self._search_generation += 1
        if self.search_timer.isActive():
            self._timer_quiet = True
            self.search_timer.start()
        self._run_search(auto_compute=False)

    def _refresh_in_background(self):
        """``_refresh_quietly`` for the loads and a sync job's end (startup
        preload, the tab shown, a session sync): when the caches miss (the
        first search, or the store changed), the store reads run in a
        ``StoreReadWorker`` behind the searching hairline, then land in the
        caches and ``_run_search`` shows them from there: the same code, so
        the same rows in the same order. Only the latest read lands; any
        search meanwhile voids it. On a 5,380-chart library the first
        search held the window 1.4 s (td-reeow, 2026-10-29)."""
        self._search_generation += 1
        if self.search_timer.isActive():
            self._timer_quiet = True
            self.search_timer.start()
        if self.cache is None or self.search_entry is None:
            return
        read = None if self._closing else self._search_read_needed()
        if read is None and self._fill is not None and self._fill[0] == self._search_token:
            return  # the latest read is filling: its search shows this
        if read is None:
            self._run_search(auto_compute=False)
            return
        self._search_token += 1
        token = self._search_token
        worker = fc_workers.StoreReadWorker(self.cache.path, read)
        relay = fc_workers.relay_for(
            worker, lambda w=worker: self._search_worker is w and not self._closing, self
        )
        relay.bind(worker.done, lambda got, t=token: self._on_search_read(t, got))
        relay.bind(worker.error, lambda _msg, t=token: self._on_search_read(t, None))
        self._search_worker = worker
        self._sync_token_pills()
        self.toolbar.well.set_busy(True)  # the searching hairline (§4.1)
        fc_workers.start_read(worker)

    def _search_read_needed(self):
        """The background read for this context, or ``None`` when the
        caches already hold it (the store revision unchanged, the query
        searched) or the store cannot be read (``_run_search`` says why)."""
        try:
            with self.cache.reader() as store:
                revision = store.revision()
        except (NoIndexError, StoreBusyError, sqlite3.OperationalError):
            return None
        ctx = self.search_context()
        query = self._query(ctx)
        if revision == self._store_revision and query in self._search_cache:
            return None
        model, read = self._column_model, type(self)._read_search
        return lambda store: read(store, ctx, query, model)

    @classmethod
    def _read_search(cls, store, ctx, query, model):
        """What ``_run_search`` reads from the store for (ctx, query), on
        the worker's thread: pure reads, no panel state."""
        result = search(store, query)
        moments = frozenset(e.moment_id for e in result.entries if e.moment_id is not None)
        return {
            "revision": store.revision(),
            "ctx": ctx,
            "query": query,
            "search": (result, cls._moments_of(store, result.entries)),
            "scope": ctx.scope,
            "in_scope": len(candidates(store, ctx.scope)),
            "columns": ((ctx.system, ctx.naming, model, moments),
                        cls._read_column_values(store, ctx, model, moments)),
            "coverage": ((ctx.system, ctx.scope),
                         (coverage_snapshot(store, ctx.system, ctx.scope), store.status())),
        }

    def _on_search_read(self, token, read):
        """The background read landed (``None``: it failed). A newer search
        voided it; else the caches take it, its rows fill in steps and the
        search shows the rest (a failure searches here, where every store
        state has its message)."""
        self._search_worker = None
        if token != self._search_token:
            return
        if read is None:
            self._run_search(auto_compute=False)
            return
        if read["revision"] != self._store_revision:
            self._store_revision = read["revision"]
            self._store_changed()
        _remember(self._search_cache, read["query"], read["search"])
        self._candidates[read["scope"]] = read["in_scope"]
        _remember(self._column_values_cache, *read["columns"])
        key, value = read["coverage"]
        _remember(self._coverage_reads, (*key, self._store_epoch), value)
        values = read["columns"][1][0]
        self._extra_values = values
        if self._fill is not None:
            self._fill[1].close()
        self._fill = (token, self._fill_rows(read["search"][0], read["ctx"], values))
        self._fill_timer.start()

    def _fill_step(self):
        """``FILL_STEP`` more rows of the landed read per event-loop turn,
        while it is the latest search; then ``_run_search`` shows it from
        the caches (the rows key matches: nothing is filled twice)."""
        fill, self._fill = self._fill, None
        if fill is None:
            return
        token, steps = fill
        if token != self._search_token or self._closing:
            steps.close()
            return
        done = object()
        self.results_table.blockSignals(True)
        try:
            more = next(steps, done) is not done
        finally:
            self.results_table.blockSignals(False)
        if more:
            self._fill = fill
            self._fill_timer.start()
            return
        self._run_search(auto_compute=False)

    def _run_search(self, *, auto_compute, retry=False):
        self._search_token += 1  # a background read still running is void
        if self.cache is None or self.search_entry is None:
            return
        if not retry:
            self._busy_timer.stop()
            self._busy_retries = 0
        self._sync_token_pills()  # needs no store: shown even when busy
        generation = self._search_generation
        started = time.perf_counter()
        if not self.search_timer.isActive():
            self.toolbar.well.set_busy(False)
        try:
            with self.cache.reader() as store:
                self._follow_revision(store)
                ctx = self.search_context()
                query = self._query(ctx)
                cached = self._search_cache.get(query)
                if cached is None:
                    result = search(store, query)
                    shown = self._moments_of(store, result.entries)
                    _remember(self._search_cache, query, (result, shown))
                else:
                    result, shown = cached
                in_scope = self._candidate_count(store, ctx.scope)
                extra = self._read_extras(store, ctx, result)
                coverage, status = self._coverage_for(store, ctx)
                uncomputed = self._uncomputed(store, ctx)
                partial = self._partial_plan(store, query, result)
                ask = (
                    self._auto_compute(store, query, result)
                    if auto_compute and generation == self._search_generation
                    else None
                )
        except NoIndexError:
            self._show_no_index()
            return
        except StoreBusyError:
            self._show_busy()
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) and "busy" not in str(exc):
                raise
            self._show_busy()
            return
        except ChartSearchError as exc:
            self._clear_results()
            self.last_search_error = exc.error_type
            self.status_bar.set_state(str(exc), states.ERROR)
            return
        was_busy = self.last_search_error == "busy"
        self.last_search_error = None
        if was_busy and self.index_status.text() in (BUSY_TEXT, BUSY_IDLE_TEXT):
            # The busy message was the search's own: recovered (review r8
            # #11); a job, a rebuild outcome or a notice is never touched.
            self.status_bar.set_state(self._store_status_text() or "")
        self._shown_moments = shown
        self._show_result(query, result, ctx, extra)
        self._show_filter_state(query, result, uncomputed)
        self._show_trail(ctx, result, in_scope, (time.perf_counter() - started) * 1000)
        self._show_coverage(coverage, status)
        self._show_partial(partial)
        if ask is not None and generation == self._search_generation:
            self._ask_to_compute(*ask)  # asked once this search is on screen

    def _candidate_count(self, store, scope):
        """The entries the scope holds before text and filters (the scope
        pill, the trail, "N of M"); cached until the store changes."""
        if scope not in self._candidates:
            self._candidates[scope] = len(candidates(store, scope))
        return self._candidates[scope]

    def _on_store_released(self):
        """A worker an earlier panel parked ended: the store may hold its
        writes. The caches go, the view refreshes quietly, and a forget owed
        meanwhile is asked now (no compute)."""
        if self._closing:
            return
        self._reconcile_jobs()
        self._after_index_writer()

    def _reconcile_jobs(self):
        """The job presentation follows the store operations that really
        run (review r15): a panel reopened, or a parked worker ended, with
        no slot of its own and no parked worker left shows no job any more
        (no "Updating" line, Library buttons working). The caches go and
        the view refreshes quietly (no compute)."""
        if not (self._index_running() or self._compute_running()
                or self._store_file_running()):
            self._end_job()
        self._store_changed()
        self._refresh_quietly()

    def _store_changed(self):
        """The store may hold new rows: cached counts and coverage go."""
        self._candidates.clear()
        self._search_cache.clear()
        self._column_values_cache.clear()
        self._coverage_reads.clear()
        self._store_epoch += 1

    def _follow_revision(self, store):
        """Another writer (the CLI, an import, another app instance)
        committed since the caches were filled (review r16): they go. One
        meta read per search, never a recount per keystroke."""
        revision = store.revision()
        if revision != self._store_revision:
            self._store_revision = revision
            self._store_changed()

    def _coverage_for(self, store, ctx):
        """The coverage snapshot and the store status for this context
        (§3.7): read again after a sync, a compute, a scope, level or system
        change (the key), never per keystroke. ``None`` when unchanged."""
        key = (ctx.system, ctx.scope, self._store_epoch)
        if key == self._coverage_key:
            return None, None
        if key not in self._coverage_reads:
            _remember(self._coverage_reads, key,
                      (coverage_snapshot(store, ctx.system, ctx.scope), store.status()))
        snapshot, status = self._coverage_reads[key]
        return (key, snapshot), status

    def _show_coverage(self, coverage, status):
        if coverage is None:
            return
        self._coverage_key, self._coverage_snapshot = coverage
        self.status_bar.set_coverage(self._coverage_snapshot)
        self.library.set_coverage(self._coverage_snapshot)
        if status is not None:
            self.status_bar.set_counts(status.entries, status.moments)
            self.library.set_index_count(status.entries)
        self.library.set_cpu_percent(
            int(get_settings().get(CPU_PERCENT_KEY, registry_default(CPU_PERCENT_KEY)))
        )

    def _partial_plan(self, store, query, result):
        """§3.7 partial: what the filtered extractors still lack over the
        search scope (never failed moments: RETRY covers those). Planned,
        never run here."""
        if self._compute_running() or self._index_running():
            return None
        lacking = tuple(
            c.extractor_id
            for c in result.coverage
            if self._filtered(query, c) and not c.complete
        )
        if not lacking:
            return None
        plan = compute.plan(
            store, query.system, tuple(registry.get(eid) for eid in lacking), query.scope
        )
        return None if plan.empty else plan

    def _show_partial(self, plan):
        """The trail's amber partial line with its COMPUTE (about T)."""
        if plan is None:
            self._partial_ids = ()
            return
        items = [item for item in plan.items if item.missing]
        self._partial_ids = tuple(item.extractor.id for item in items)
        names = ", ".join(extractor_label(eid) for eid in self._partial_ids)
        missing = max(len(item.missing) for item in items)
        self.trail.set_state(
            states.partial_text(names, missing),
            "warn",
            states.partial_action(_duration(plan.estimate_s)),
        )

    def _on_trail_action(self):
        """The trail's COMPUTE: those extractors over the search scope, a
        direct action (consented, INV-2)."""
        ids = self._partial_ids
        if ids:
            self._plan_and_start(ids)

    def _on_coverage_action(self, extractor_id, kind):
        """A Library row's COMPUTE n / RETRY n / RECOMPUTE n (§3.7): plans
        exactly that state's moments of that extractor in the current
        context; a set that no longer matches the count shown refreshes the
        row instead of running."""
        if self._compute_running() or self._index_running():
            self.status_bar.set_state(ALREADY_RUNNING_TEXT)
            return
        attr = {"compute": "missing", "retry": "failed", "recompute": "stale"}.get(kind)
        if attr is None:
            return
        extractor = registry.get(extractor_id)
        ctx = self.search_context()

        def read(store):
            among = getattr(coverage_moments(store, ctx.system, ctx.scope, extractor), attr)
            return among, compute.plan(
                store,
                ctx.system,
                (extractor,),
                ctx.scope,
                among=among,
                retry_failed=kind != "compute",
                recompute_stale=kind == "recompute",
            )

        got = self._read_store(read)
        if got is _NOT_READ:
            return
        among, plan = got
        shown = next(
            (c for c in self._coverage_snapshot if c.extractor_id == extractor_id), None
        )
        if shown is None or getattr(shown, attr) != len(among):
            self._store_changed()
            self.status_bar.set_state(COVERAGE_CHANGED_TEXT, states.WARN)
            self._refresh_quietly()
            return
        planned = frozenset(m for item in plan.items for m in item.missing)
        if not planned or not planned <= among:
            return
        self._start_compute(plan, _consented=True)

    def _system_text(self, system):
        parts = [_item_label(Field.MODE, system)]
        if system.mode.value == "sidereal":
            parts.append(_item_label(Field.AYANAMSA_ID, system))
        parts.append(_item_label(Field.HOUSE_SYSTEM, system))
        return ", ".join(parts)

    def _show_trail(self, ctx, result, in_scope, ms):
        self.results_bar.set_count(result.total, in_scope, getattr(self, "_partial", False))
        sources = ctx.scope.sources
        self.toolbar.well.set_scope(f"{sources.value.upper()} · {in_scope:,}", f"{in_scope:,}")
        self.trail.set_search(
            trail_text(
                sources,
                in_scope,
                self._system_text(ctx.system),
                result.total,
                ctx.level == fc_context.EASY,
            ),
            ms,
        )

    def _clear_results(self):
        """No result on screen nor in the row maps (never an earlier query's
        rows: Pro reads them synchronously, D-14)."""
        self.results_table.setRowCount(0)
        self.results_table.setUpdatesEnabled(True)  # after a fill closed halfway
        self.tree_filepath_map.clear()
        self.tree_entry_map.clear()
        self.results_bar.set_count(0, 0, False)
        self.cards.set_entries((), lambda e: {})
        self._shown_moments = {}
        self._rendered_rows_key = None
        self._row_cells = {}
        # No result backs a selection any more (review r7 #6).
        self._selected_entry_id = None
        self.inspector.clear()
        self._close_inspector()

    def _show_busy(self):
        """Store busy (§3.7 states): emptied, typed, retried 3 times."""
        self._clear_results()
        self.last_search_error = "busy"
        if self._busy_retries < BUSY_RETRIES:
            self._busy_retries += 1
            self.status_bar.show_state(states.store_busy(True))
            self.trail.set_state(BUSY_TEXT, "warn")
            self._busy_timer.start()
        else:
            self.status_bar.show_state(states.store_busy(False))
            self.trail.set_state(BUSY_GAVE_UP_TEXT, "warn")

    def _retry_busy(self):
        self._run_search(auto_compute=False, retry=True)

    def _show_no_index(self):
        """§3.7 no index: the trail, the status bar and the results area
        say so; REBUILD INDEX is the action (a consented scan)."""
        self._clear_results()
        self.last_search_error = "no_index"
        self.trail.set_state(states.TRAIL_NO_INDEX, "warn")
        self._coverage_key = None
        self._coverage_snapshot = ()
        self.status_bar.set_coverage(())
        self.status_bar.set_counts(0, 0)
        self.library.set_coverage(())
        self.library.set_index_count(0)
        folders = [e.text() for e in self.folder_entries if e.text().strip()]
        if folders:
            self.status_bar.show_state(states.no_index())
        else:
            self.status_bar.set_state("No folders configured", states.WARN)
        self.no_index_widget.show()

    def _read_extras(self, store, ctx, result):
        """What the result shows besides its own fields, from stored rows
        only (never a compute): the extra column cells, each group's missing
        moments, and the selected chart's facts for the inspector."""
        model = self._column_model
        moments = frozenset(e.moment_id for e in result.entries if e.moment_id is not None)
        key = (ctx.system, ctx.naming, model, moments)
        cached = self._column_values_cache.get(key)
        if cached is None:
            cached = self._read_column_values(store, ctx, model, moments)
            _remember(self._column_values_cache, key, cached)
        values, missing = cached
        chosen = next(
            (e for e in result.entries if e.entry_id == self._selected_entry_id), None
        )
        chart = (
            facts.chart_facts(store, ctx.system, ctx.naming, chosen.moment_id)
            if chosen is not None and chosen.moment_id is not None
            else None
        )
        return values, missing, chosen, chart

    @staticmethod
    def _read_column_values(store, ctx, model, moments):
        values = (
            facts.column_values(
                store, ctx.system, ctx.naming, moments, model.groups, model.all_placements
            )
            if model.columns
            else {}
        )
        missing = (
            facts.group_missing_moments(store, ctx.system, moments, model.groups)
            if model.groups
            else {}
        )
        return values, missing

    def _labeler(self, result, naming):
        """The sign labels of an entry, computed once per distinct triple."""
        cache_labels = {}

        def labels(entry: ResultEntry):
            key = (entry.ascendant, entry.sun, entry.moon)
            if key not in cache_labels:
                cache_labels[key] = result_labels(
                    entry, result.system, naming
                )
            return cache_labels[key]

        return labels

    def _fill_rows(self, result, ctx, values):
        """Fill the table rows and the cards with ``result``, unless they
        show it already (the rows key). A generator: it pauses after every
        ``FILL_STEP`` rows, so ``_fill_step`` spreads a large fill over
        event-loop turns; a search runs it through in one go. The table
        repaints only once it is done, and the row maps (what a click opens)
        follow the rows painted: they change at the end, all at once. A
        fill closed halfway (a newer search took over) leaves the table
        unpainted until that search fills or clears it."""
        labels = self._labeler(result, ctx.naming)
        group_by = self.group_combo.currentData()
        rows_key = (result.entries, ctx.system, ctx.naming, group_by,
                    self._column_model, values)
        if rows_key == self._rendered_rows_key:
            return
        self._rendered_rows_key = None  # cells change from here on
        maps = ({}, {})  # the new tree_filepath_map, tree_entry_map
        filled = 0  # rows since the last pause
        self.results_table.setUpdatesEnabled(False)
        try:
            self._row_cells = {r: c for r, c in self._row_cells.items()
                               if r < len(result.entries)}
            theme = get_theme_colors()
            color_odd = QColor(theme["secondary"])
            color_even = QColor(theme["secondary_dark"])
            color_group = QColor(theme["secondary_light"])
            row_idx = 0
            ordered = list(result.entries)  # the display order, table and cards
            if group_by and group_by != "none":
                ordered = []
                groups = results.grouped(result.entries, group_by, labels)
                self.results_table.setRowCount(len(result.entries) + len(groups))
                for group_name, entries in groups.items():
                    self._row_cells.pop(row_idx, None)
                    group_item = QTableWidgetItem(f"── {group_name} ({len(entries)}) ──")
                    group_item.setFont(scaled_area_font("table_headers", bold=True))
                    group_item.setBackground(color_group)
                    group_item.setForeground(QColor(theme["secondary_text"]))
                    group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    self.results_table.setItem(row_idx, 0, group_item)
                    for col in range(1, self.results_table.columnCount()):
                        empty_item = QTableWidgetItem("")
                        empty_item.setBackground(color_group)
                        empty_item.setFlags(empty_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                        self.results_table.setItem(row_idx, col, empty_item)
                    row_idx += 1
                    filled += 1
                    if filled >= FILL_STEP:
                        filled = 0
                        yield
                    ordered.extend(entries)
                    for entry in entries:
                        self._insert_entry(
                            entry,
                            labels(entry),
                            row_idx,
                            color_odd if row_idx % 2 == 1 else color_even,
                            maps,
                        )
                        row_idx += 1
                        filled += 1
                        if filled >= FILL_STEP:
                            filled = 0
                            yield
            else:
                self.results_table.setRowCount(len(result.entries))
                for row_idx, entry in enumerate(result.entries):
                    self._insert_entry(
                        entry,
                        labels(entry),
                        row_idx,
                        color_odd if row_idx % 2 == 1 else color_even,
                        maps,
                    )
                    filled += 1
                    if filled >= FILL_STEP:
                        filled = 0
                        yield

            for shown, new in zip((self.tree_filepath_map, self.tree_entry_map), maps):
                shown.clear()
                shown.update(new)
            self.cards.set_entries(tuple(ordered), labels)
            self._rendered_rows_key = rows_key
        except GeneratorExit:
            raise  # half filled: no repaint of mixed rows (the maps are the old ones)
        except BaseException:
            self.results_table.setUpdatesEnabled(True)
            raise
        self.results_table.setUpdatesEnabled(True)

    def _show_result(self, query, result: SearchResult, ctx: SearchContext, extra=None):
        """Fill the table, the cards, the count, the coverage strip, the web
        section, and keep the selection by entry id (§3.6)."""
        values, missing, chosen, chart = extra or ({}, {}, None, None)
        self._extra_values = values
        self.results_table.blockSignals(True)
        for _step in self._fill_rows(result, ctx, values):
            pass

        count = result.total
        partial = any(
            not c.complete for c in result.coverage if self._filtered(query, c)
        )
        self._partial = partial
        self.results_bar.set_group_dots(
            result_columns.group_missing_counts(result.entries, missing)
        )
        self._reselect(chosen, chart, ctx)
        self.results_table.blockSignals(False)
        self.no_index_widget.hide()

        # Show/hide web download section
        search_query = self.search_entry.text().strip()
        if self.web_download_widget:
            if count == 0 and len(search_query) >= 3 and not query.filters:
                self.no_results_label.setText(
                    f'No local charts found for "{search_query}"'
                )
                self.web_download_widget.show()
                self.web_result_label.hide()
                self.web_status_label.setText("Click to search the web for birth data")
            else:
                self.web_download_widget.hide()

        # The unsorted count, badge and notice (cached: no listdir here)
        self.refresh_unsorted_downloads()

    @staticmethod
    def _filtered(query, coverage):
        """Whether an extractor's gaps can hide matches (it owns a filter);
        Positions for the columns alone only leaves cells empty."""
        return any(
            taxonomy.owner(f.property) == coverage.extractor_id for f in query.filters
        )

    def _insert_entry(self, entry: ResultEntry, labels, row_index, bg_color, maps):
        """Update a preallocated row, retaining unchanged cells on refresh;
        ``maps`` take its path and entry (``_fill_rows`` shows them)."""
        cells = results.row_values(entry, labels)
        cells += result_columns.cell_texts(entry, self._extra_values, self._column_model)
        previous = self._row_cells.get(row_index, ())
        for col, value in enumerate(cells):
            if col < len(previous) and previous[col] == value:
                continue
            item = self.results_table.item(row_index, col)
            if item is None or not previous:
                item = QTableWidgetItem(value)
                self.results_table.setItem(row_index, col, item)
            else:
                item.setText(value)
        self._row_cells[row_index] = cells
        maps[0][row_index] = results.openable_path(entry)
        maps[1][row_index] = entry

    # ------------------------------------------------- selection, inspector
    def _row_of(self, entry_id):
        for row, entry in self.tree_entry_map.items():
            if entry.entry_id == entry_id:
                return row
        return None

    def _entry_of(self, entry_id):
        row = self._row_of(entry_id)
        return None if row is None else self.tree_entry_map[row]

    def _context_token(self, ctx, moment_id=None):
        """The inspector's binding with the entry id: the moment and the
        context (a late fill for another moment of the same entry, or from
        another frame or naming, is dropped; review r6 #8)."""
        return (moment_id, ctx.system, ctx.naming)

    def _on_table_selection(self):
        rows = {i.row() for i in self.results_table.selectedItems()}
        entry = self.tree_entry_map.get(next(iter(rows))) if len(rows) == 1 else None
        if entry is None:
            return
        self._inspect(entry)

    def _on_card_activated(self, entry_id):
        row = self._row_of(entry_id)
        if row is None:
            return
        if entry_id == self._selected_entry_id:
            self._inspect(self.tree_entry_map[row])  # reopens a closed inspector
        else:
            self.results_table.selectRow(row)  # -> _on_table_selection

    def _on_cell_clicked(self, row, _column):
        """A click on the selected row reopens a closed inspector (a new
        row is shown by the selection change)."""
        entry = self.tree_entry_map.get(row)
        if entry is not None and not self._inspector_visible():
            self._inspect(entry)

    def _inspector_visible(self):
        if self._inspector_docked:
            return not self.inspector.isHidden()
        return self.inspector_sheet.is_open()

    def _on_card_opened(self, entry_id):
        self._open_entry_id(entry_id)

    def _open_entry_id(self, entry_id):
        row = self._row_of(entry_id)
        if row is not None:
            self._open_row(row)

    def _inspect(self, entry):
        """Select ``entry`` (by id) and show it: its stored facts read now,
        never computed. Display only: a pending debounce turns quiet first
        (INV-3, review r7 #5). The entry is resolved again by id in one
        read snapshot (review r15): gone, moved to another moment, or its
        moment changed since the search, the view refreshes instead and no
        stale fact is shown."""
        self._display_changed()
        self._selected_entry_id = entry.entry_id
        self.cards.select(entry.entry_id)
        ctx = self.search_context()
        chart = None
        self._inspector_moment = None
        if entry.moment_id is not None:
            try:
                with self.cache.reader() as store:
                    if not self._still_shown(store, entry):
                        stale = True
                    else:
                        stale = False
                        chart = facts.chart_facts(store, ctx.system, ctx.naming, entry.moment_id)
                        self._bind_inspector(store, entry)
            except (NoIndexError, StoreBusyError, sqlite3.OperationalError):
                stale, chart = False, None
            if stale:
                self._store_changed()
                self._refresh_quietly()  # reselects or closes (§3.6)
                return
        self.inspector.set_glance_context(ctx.system, ctx.naming, self._first_filter())
        self.inspector.show_entry(
            entry, chart, self._context_token(ctx, entry.moment_id),
            self._system_text(ctx.system),
            bool(results.openable_path(entry)),
        )
        self._show_inspector()
        self._compute_snapshot_positions(chart, entry.moment_id)

    def _compute_snapshot_positions(self, chart, moment_id):
        """SPEC-FIND-007 v1.0: the snapshot follows every zodiac system. The
        stored signs are per system, so the shown chart, selected or kept
        selected across a system change, gets its missing Positions now, for
        this one chart (the selection is the consent, the plan is bounded to
        its moment); never while another compute runs. A failed compute is
        FAILED, not MISSING, so this never loops."""
        if chart is None or moment_id is None or self._compute_running():
            return
        owner = chart.owner_states.get("positions")
        if owner is not None and owner.state == facts.MISSING:
            self._on_inspector_compute("positions", moment_id, "compute")

    @staticmethod
    def _moments_of(store, entries):
        """Each entry's (moment id, exact Moment) in this snapshot."""
        ids = frozenset(e.moment_id for e in entries if e.moment_id is not None)
        stored = store.moments(ids) if ids else {}
        return {
            e.entry_id: (e.moment_id, stored.get(e.moment_id))
            for e in entries
            if e.moment_id is not None
        }

    def _still_shown(self, store, entry):
        """The store holds ``entry`` at exactly the moment the search showed."""
        shown = self._shown_moments.get(entry.entry_id)
        if shown is None or shown[1] is None or shown[0] != entry.moment_id:
            return False
        if store.moment_of(entry.entry_id) != entry.moment_id:
            return False
        return store.moments(frozenset({entry.moment_id})).get(entry.moment_id) == shown[1]

    def _bind_inspector(self, store, entry):
        """The exact stored moment the inspector shows (review r15): its
        actions run only while the store still holds exactly it."""
        moment = store.moments(frozenset({entry.moment_id})).get(entry.moment_id)
        self._inspector_moment = (entry.entry_id, moment) if moment else None

    def _reselect(self, chosen, chart, ctx):
        """After a refresh: the same entry selected again, its facts
        refilled; gone from the result, the inspector closes (§3.6)."""
        if self._selected_entry_id is None:
            return
        row = self._row_of(self._selected_entry_id)
        if row is None or chosen is None:
            self._selected_entry_id = None
            self.results_table.clearSelection()
            self.cards.select(None)
            self.inspector.clear()
            self._close_inspector()
            return
        self.results_table.selectRow(row)
        if chosen.moment_id is not None:
            try:
                with self.cache.reader() as store:
                    if self._still_shown(store, chosen):
                        self._bind_inspector(store, chosen)
                    else:
                        self._inspector_moment = None
            except (NoIndexError, StoreBusyError, sqlite3.OperationalError):
                self._inspector_moment = None
        token = self._context_token(ctx, chosen.moment_id)
        self.inspector.set_glance_context(ctx.system, ctx.naming, self._first_filter())
        # Changed metadata (name, birth data, file) rebinds the whole entry
        # (review r7 #6); otherwise only the facts refill.
        if self.inspector.current_entry() != chosen or not self.inspector.fill_facts(
            chosen.entry_id, token, chart
        ):
            self.inspector.show_entry(
                chosen, chart, token, self._system_text(ctx.system),
                bool(results.openable_path(chosen)),
            )
        # A system change keeps the chart selected: its snapshot computes the
        # new system's Positions as a fresh selection would (Lorris, Sidereal).
        self._compute_snapshot_positions(chart, chosen.moment_id)

    def _place_inspector(self, docked):
        """Docked beside the results (T0/T1) or in its sheet (T2 and below)."""
        if docked == self._inspector_docked:
            return
        self._inspector_docked = docked
        showing = self._selected_entry_id is not None and (
            not self.inspector.isHidden() or self.inspector_sheet.is_open()
        )
        if docked:
            self.inspector_sheet.close_sheet()
            self._results_row.addWidget(self.inspector)
        else:
            self.inspector_sheet.content_layout.addWidget(self.inspector)
        self.inspector.setVisible(showing or not docked)
        if showing:
            self._show_inspector()

    def _show_inspector(self):
        if self._inspector_docked:
            self.inspector.show()
        else:
            self.inspector.show()
            self.inspector_sheet.open_sheet()

    def _close_inspector(self):
        """The inspector's close or back: hidden, the selection stays."""
        if self._inspector_docked:
            self.inspector.hide()
        else:
            self.inspector_sheet.close_sheet()

    def _copy_entry(self, entry_id):
        entry = self._entry_of(entry_id)
        if entry is not None:
            QApplication.clipboard().setText(copy_text(entry))

    def _show_entry_in_folder(self, entry_id):
        entry = self._entry_of(entry_id)
        path = results.openable_path(entry) if entry is not None else ""
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _trash_entry(self, entry_id):
        entry = self._entry_of(entry_id)
        path = results.openable_path(entry) if entry is not None else ""
        if path:
            self._move_chart_to_trash(path)

    def _on_inspector_compute(self, extractor_id, moment_id, kind):
        """COMPUTE / RETRY / RECOMPUTE for one chart: the click is the
        consent, the plan is bounded to that moment (among), and its
        completion refreshes quietly (INV-2, INV-3). The shown entry is
        resolved again first (review r14): another writer may have rebuilt
        the index and reused its moment id for another birth, so an entry
        gone or moved refreshes the view instead of computing."""
        entry = self.inspector.current_entry()
        bound = self._inspector_moment
        ctx = self.search_context()

        def read(store):  # one snapshot: the binding check and the plan
            current = store.moment_of(entry.entry_id)
            if current != moment_id or bound is None or bound[0] != entry.entry_id:
                return None
            moment = store.moments(frozenset({moment_id})).get(moment_id)
            if moment != bound[1]:
                return None  # same ids, another birth (review r15)
            plan = compute.plan(
                store,
                ctx.system,
                (registry.get(extractor_id),),
                ctx.scope,
                among=frozenset({moment_id}),
                retry_failed=kind != "compute",
                recompute_stale=kind == "recompute",
            )
            return replace(plan, expected=((moment_id, moment),))

        plan = None if entry is None else self._read_store(read)
        if plan is _NOT_READ:
            return
        if plan is None:
            self._store_changed()
            self._refresh_quietly()
            return
        if not plan.empty:
            self._start_compute(plan, _consented=True)

    # --------------------------------------------------------------- compute
    def _auto_compute(self, store: StoreReader, query: Query, result: SearchResult):
        """Plan what the search lacks; run it when consented (consent.decide).
        Returns ``(plan, key)`` when the user is to be asked, else None."""
        if self._compute_running() or self._index_running():
            return None
        if all(c.complete for c in result.coverage):
            return None
        # What the visible query matches by text first (design.md §4.6).
        visible = (
            frozenset(
                row.moment_id for row in candidates(store, query.scope, query.text)
            )
            if query.text
            else frozenset()
        )
        plan = compute.plan(
            store, query.system, needed(query), query.scope, priority=visible
        )
        key = consent.key_of(plan, query.scope)
        decision = consent.decide(
            plan,
            requested=frozenset(taxonomy.owner(f.property) for f in query.filters),
            dont_ask=bool(get_settings().get(consent.DONT_ASK_KEY, False)),
            declined=key in self._declined,
        )
        if decision is consent.Decision.RUN:
            self._start_compute(plan, _consented=True)
        elif decision is consent.Decision.ASK:
            return plan, key
        return None

    def _ask_to_compute(self, plan: ComputePlan, key):
        """SPEC-FIND-003 §3.6: above the threshold, ask, with "Don't ask again"."""
        if self._compute_running() or key in self._declined:
            return
        names = ", ".join(extractor_label(item.extractor.id) for item in plan.items)
        widest = max(plan.items, key=lambda item: len(item.missing))
        box = kit.style_dialog(QMessageBox(self))
        box.setWindowTitle("Compute for this search")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            f"This search needs {names} for {len(widest.missing):,} charts that "
            f"do not have it yet ({widest.already:,} already do). That takes "
            f"about {_duration(plan.estimate_s)}.\n\n"
            "Compute it now? You can keep working while it runs, and cancel it."
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        dont_ask = QCheckBox("Don't ask again")
        box.setCheckBox(dont_ask)
        answer = box.exec()
        if answer != QMessageBox.StandardButton.Yes:
            self._declined.add(key)
            return
        if dont_ask.isChecked():
            get_settings().set(consent.DONT_ASK_KEY, True)
        self._start_compute(plan, _consented=True)

    def _on_compute_clicked(self, extractor_ids):
        """COMPUTE for these extractors over the search scope: a direct
        action (FIND-003 §3.1)."""
        self._plan_and_start(extractor_ids)

    def _on_recompute_clicked(self, extractor_ids):
        """RECOMPUTE: failures and other app versions."""
        self._plan_and_start(extractor_ids, retry=True)

    def _plan_and_start(self, extractor_ids, *, retry=False, stale=None):
        if self._compute_running() or self._index_running():
            return
        ctx = self.search_context()
        plan = self._read_store(lambda store: compute.plan(
            store,
            ctx.system,
            tuple(registry.get(eid) for eid in extractor_ids),
            ctx.scope,
            retry_failed=retry,
            recompute_stale=retry if stale is None else stale,
        ))
        if plan is not _NOT_READ and not plan.empty:
            self._start_compute(plan, _consented=True)

    def _on_compute_everything(self):
        """ "Compute everything": every extractor over every entry, in the
        system the bar shows (varuna/43). Another system is another run, or
        computes on demand. A direct action, so consent (FIND-003 §3.1); the
        dialog only says how long it takes."""
        if self._compute_running() or self._index_running():
            self.status_bar.set_state(ALREADY_RUNNING_TEXT)
            return
        system = self.search_context().system
        plan = self._read_store(
            lambda store: compute.plan(store, system, registry.EXTRACTORS, EVERYTHING)
        )
        if plan is _NOT_READ:
            return
        if plan.empty:
            self.status_bar.set_state(EVERYTHING_DONE_TEXT)
            return
        if self._confirm_everything(plan):
            self._start_compute(plan, _consented=True)

    def _confirm_everything(self, plan: ComputePlan):
        charts = max(item.in_scope for item in plan.items)
        lines = "\n".join(
            f"  {extractor_label(item.extractor.id)}: {len(item.missing):,} to "
            f"compute, {item.already:,} already done"
            for item in plan.items
        )
        box = kit.style_dialog(QMessageBox(self))
        box.setWindowTitle("Compute everything")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            f"Compute every domain for the {charts:,} charts in the index, in "
            f"the system shown above:\n\n{lines}\n\n"
            f"That takes about {_duration(plan.estimate_s)}. You can keep "
            "working while it runs, and cancel it; what is done is kept.\n\n"
            "Another system (a different ayanamsa, say) needs its own run, or "
            "computes when a search needs it."
        )
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _start_compute(self, plan: ComputePlan, *, _consented=False, rebuild=False):
        """The panel's only entry to ``compute.run`` (SPEC-FIND-003 §5.1)."""
        if not _consented:
            print(
                "[FIND_CHART] WARNING: _start_compute() called without "
                "_consented=True. This is a SPEC-FIND-003 violation. Ignoring call."
            )
            return
        if self._compute_running() or plan.empty or self._closing:
            return
        if self._index_running() or self._store_file_running():
            # One writer at a time (round 9 #7, an import too: round 11, a
            # parked one from an earlier panel too: round 13): a rebuild may recreate the
            # tables and reuse moment ids, so no plan read before it may run
            # during it. REBUILD INDEX's own Positions starts after release.
            self.status_bar.set_state(INDEX_UPDATING_TEXT, states.WARN)
            return
        self._rebuild_compute = rebuild
        self._compute_done = {}
        worker = ComputeWorker(
            plan,
            int(get_settings().get(CPU_PERCENT_KEY, registry_default(CPU_PERCENT_KEY))),
        )
        relay = fc_workers.relay_for(worker, lambda w=worker: self._compute_worker is w, self)
        relay.bind(worker.progress, self._on_compute_progress)
        relay.bind(worker.done, self._on_compute_done)
        relay.bind(worker.error, self._on_compute_error)
        self._compute_worker = worker  # owned until its result is delivered
        self._retry_binding = None
        self._clear_retry_notice()
        self.status_bar.set_job(
            f"Computing {', '.join(extractor_label(i.extractor.id) for i in plan.items)}...",
            0,
            sum(len(item.missing) for item in plan.items),
        )
        self._set_running(plan.items[0].extractor.id if plan.items else None)
        self.library.set_busy(True)
        # No window overlay: the compute runs in the background and the app
        # stays usable; progress and CANCEL live in the status bar.
        worker.start()

    def _on_compute_progress(self, extractor_id, done, total):
        worker = self._compute_worker
        if worker is None or not self._from(worker):
            return
        self._compute_done[extractor_id] = done
        text = self._progress_text(worker.plan)
        self.status_bar.set_job(
            text,
            sum(self._compute_done.values()),
            sum(len(item.missing) for item in worker.plan.items),
        )
        self._set_running(extractor_id)

    def _progress_text(self, plan: ComputePlan):
        """One extractor: its own count. Several (moment-major, they advance
        together): one count over all of them."""
        items = plan.items
        if len(items) == 1:
            what = extractor_label(items[0].extractor.id)
        else:
            what = f"{len(items)} domains"
        return progress_text(
            what,
            sum(self._compute_done.values()),
            sum(len(item.missing) for item in items),
            sum(item.already for item in items),
        )

    def _on_compute_done(self, report):
        if not self._from(self._compute_worker):
            return
        worker = self._release_compute_worker()
        if report.cancelled and worker is not None:
            self._declined.add(consent.key_of(worker.plan, self._scope()))
        failed = sum(item.failed for item in report.items)
        self._end_job()
        if report.cancelled and self._rebuild_compute:
            self.status_bar.show_state(states.computation_cancelled())
        else:
            text = "Compute cancelled" if report.cancelled else "Compute done"
            if failed:
                text += f" ({failed:,} failed)"
            self.status_bar.set_state(text)
        if failed and worker is not None:
            self._bind_retry(
                "retry", worker.plan, {i.extractor_id for i in report.items if i.failed}
            )
            self._set_notice(NOTICE_RETRY, *states.COMPUTE_FAILED_NOTICE)
        self._rebuild_compute = False
        self._store_changed()
        # Completion always refreshes quietly (review r5 #2): a search's plan
        # already held every extractor it needed, and a bounded job (one
        # moment from the inspector, one state from the Library) must never
        # chain into work over unrelated moments (INV-2/INV-3).
        self._refresh_quietly()

    def _on_compute_error(self, message):
        """The compute stopped on an error (review r8 #7): batches written
        before it are kept, so the caches go and the view refreshes quietly
        (the message stays); RESUME runs only what this compute had left,
        never an index-wide plan, and nothing follows on its own."""
        if not self._from(self._compute_worker):
            return
        worker = self._release_compute_worker()
        if worker is not None:
            self._declined.add(consent.key_of(worker.plan, self._scope()))
        print(f"[FIND_CHART] Compute error: {message}")
        self._end_job()
        self._rebuild_compute = False
        if worker is not None and not worker.plan.empty:
            self._bind_retry("resume", worker.plan)
            self._set_notice(NOTICE_RETRY, *states.COMPUTE_STOPPED_NOTICE)
        self._store_changed()
        self._refresh_quietly()
        self.status_bar.set_state(f"Compute failed: {message}", states.ERROR)

    def _release_compute_worker(self):
        worker = self._compute_worker
        self._compute_worker = None
        if worker is not None:
            worker.wait()
            worker.deleteLater()
        return worker

    def _set_running(self, extractor_id):
        """The extractor a compute is running for: its ring and Library row."""
        self.status_bar.set_running(extractor_id)
        self.library.set_running(extractor_id)

    def _end_job(self):
        """A sync or compute ended: the status line comes back, the Library
        buttons work again."""
        self.status_bar.clear_job()
        self._set_running(None)
        self.library.set_busy(False)

    def _cancel_compute(self):
        if self._compute_worker is not None:
            self._compute_worker.cancel()

    def _compute_running(self):
        """A compute owns the slot from its start until its result is
        delivered, not only while its thread runs (review r10: a finished
        worker with a queued result still owns it)."""
        return self._compute_worker is not None or fc_workers.parked(ComputeWorker)

    def _index_running(self):
        """As ``_compute_running``, for the folder sync. A worker an earlier
        panel parked still owns the store (review r13): every panel waits."""
        return self._index_worker is not None or fc_workers.parked(FolderSyncWorker)

    def _from(self, current):
        """Whether the signal being delivered comes from ``current`` (the
        slot's worker); a direct call counts as it. A delivery from any other
        worker is dropped: it never releases, reads or cancels the slot's."""
        sender = self.sender()
        return sender is None or sender is current

    # ------------------------------------------------------------ app events
    def _on_aditya_mode_changed(self, mode):
        """The app's frame or sign names changed: follow it, relabel, search."""
        self.system_bar.follow_app()
        self._relabel()

    def _relabel(self):
        """The search system, the naming or the level changed: relabel and
        refresh, display only (INV-3: never a compute)."""
        self._bump_revision()
        self._display_changed()  # before anything that can fail (r6 #7)
        ctx = self.search_context()
        self.picker.set_level(ctx.level)
        self.picker.set_context(ctx.system, ctx.naming, self._filter_choices())
        self.picker.set_system_text(self._system_text(ctx.system))
        self.chips.relabel(self.picker.model())
        self._tokens = ()  # token pills relabel too
        self._refresh_quietly()

    def _refresh_when_done(self, job: Future | None):
        """Refresh once a job of the app's sync has written the store."""
        if job is None:
            return
        job.add_done_callback(lambda _job: self._store_job_done.emit())

    # ------------------------------------------------------------ index load
    def _store_status_text(self):
        try:
            store = self.cache.reader()
            with store:
                status = store.status()
        except NoIndexError:
            return None
        except (StoreBusyError, sqlite3.OperationalError):
            return BUSY_TEXT  # contention, never "no index" (review r5 #3)
        noun = "chart" if status.entries == 1 else "charts"
        text = f"{status.entries:,} {noun} in the index"
        if status.unreadable:
            text += f" ({len(status.unreadable):,} files could not be read)"
        return text

    def _load_cache_only(self):
        """Startup preload: show what the store holds. No sync, no scan, no
        compute (SPEC-FIND-003 §5.2 item 6)."""
        if self._closing:
            return
        text = self._store_status_text()
        if text is None:
            self.status_bar.show_state(states.no_index())
            print("[FIND_CHART] Preload: no index, nothing built")
            return
        self.index_status.setText(text)
        self._refresh_in_background()

    def _load_cached_index(self):
        """Open the store, sync the session, refresh. SPEC-FIND-003: no folder
        scan; the session sync is JSON only (design.md §4.6). Pro calls this."""
        if self._closing:
            return  # a delayed load after a close or a quit (reviews r14, r15)
        self.system_bar.follow_app()
        text = self._store_status_text()
        self.index_status.setText(
            text
            if text is not None
            else (
                NO_INDEX_TEXT
                if any(e.text().strip() for e in self.folder_entries)
                else "No folders configured"
            )
        )
        app_sync = find_chart_sync.current()
        if app_sync is not None:
            self._refresh_when_done(app_sync.panel_shown(self._current_session()))
            self._ask_forget_owed(app_sync)
        self._refresh_in_background()

    def _current_session(self):
        """The running profile's charts from memory (None: read it from disk)."""
        session_manager = getattr(self.gui, "session_manager", None)
        return (
            session_manager.current_session() if session_manager is not None else None
        )

    def _build_index_async(self, *, _user_initiated=False, _discard=False):
        """Folder sync, then Positions for the current system (REBUILD INDEX).
        SPEC-FIND-003: user consent required."""
        if not _user_initiated:
            print("[FIND_CHART] WARNING: _build_index_async() called without "
                  "_user_initiated=True. SPEC-FIND-003 violation. Ignoring.")
            return

        if self._closing:
            return
        if self._index_running() or self._compute_running() or self._store_file_running():
            self.index_status.setText("The index is busy, try again after.")
            return

        if (hasattr(self, 'gui') and hasattr(self.gui, 'chart_manager')
                and getattr(self.gui.chart_manager, '_loading_chart', False)):
            self.index_status.setText("Chart is loading, try again after.")
            return

        folder_paths = [e.text() for e in self.folder_entries if e.text()]
        if not folder_paths:
            self.index_status.setText("No folders configured")
            return

        from pathlib import Path

        filtered_paths = [
            Path(p) for p in self._filter_redundant_subfolders(folder_paths)
        ]
        current = self._current_session()

        # In the background, no window overlay: the app stays usable while the
        # folders are read and Positions computed (Lorris, 2026-10-18).
        self.status_bar.show_state(states.syncing(0, 0))
        self._clear_retry_notice()
        self.library.set_busy(True)

        worker = FolderSyncWorker(
            filtered_paths, sync.profiles_dir(), current, discard=_discard
        )
        relay = fc_workers.relay_for(worker, lambda w=worker: self._index_worker is w, self)
        relay.bind(worker.synced, self._on_index_finished)
        relay.bind(worker.error, self._on_index_error)
        relay.bind(worker.progress, self._on_sync_progress)
        relay.bind(worker.committing, self._on_sync_committing)
        relay.bind(worker.cancelled, self._on_sync_cancelled)
        self._index_worker = worker
        worker.start()

    def _on_sync_progress(self, done, total):
        if self._index_worker is None or self._index_worker.cancel_after_commit:
            return
        if not self._from(self._index_worker):
            return
        state = states.syncing(done, total)
        self.status_bar.set_job(state.text, done, total, state.cancel_label)

    def _on_sync_committing(self):
        """The commit point: the writes finish whatever happens; CANCEL now
        only skips the computation that follows (§3.7 sync writing)."""
        if not self._from(self._index_worker):
            return
        self.status_bar.show_state(states.sync_writing())

    def _on_sync_cancelled(self):
        """Cancelled during the scan: nothing was written."""
        if not self._from(self._index_worker):
            return
        self._release_index_worker()
        self._end_job()
        self.status_bar.show_state(states.sync_cancelled())
        self._after_index_writer()

    def _release_index_worker(self):
        worker = self._index_worker
        self._index_worker = None
        if worker is not None:
            worker.wait()
            worker.deleteLater()
        return worker

    def _on_index_finished(self, folder_sync):
        """Folders read: compute Positions for the current system (REBUILD
        INDEX's meaning, design.md §4.6), then show the result."""
        if not self._from(self._index_worker):
            return
        worker = self._release_index_worker()
        self._store_changed()
        self._end_job()
        if self._forgetting():
            # A folder left the list while this sync ran: it was cancelled
            # (no compute) and the owed forget runs now (review r11).
            self._after_index_writer()
        if worker is not None and worker.cancel_after_commit:
            # CANCEL after the commit point: the index is refreshed, no
            # computation starts (§3.7 sync writing).
            self.status_bar.show_state(states.computation_cancelled())
            self._declined.clear()
            self._refresh_quietly()
            return
        text = f"Indexed {folder_sync.updated:,} new or changed files"
        if folder_sync.removed:
            text += f", {folder_sync.removed:,} removed"
        if folder_sync.unreadable:
            text += f", {len(folder_sync.unreadable):,} unreadable"
        self.status_bar.set_state(text)
        self._sort_index_rebuilt()
        self.rate_sort.refresh()  # an open Library sheet shows the new counts
        print(f"[FIND_CHART] Folder sync complete: {text}")
        self._declined.clear()
        system = self.search_context().system
        plan = self._read_store(lambda store: compute.plan(
            store, system, (positions.EXTRACTOR,), EVERYTHING
        ))
        self._refresh_quietly()
        if plan is _NOT_READ:
            return  # busy or no index: shown; REBUILD INDEX again computes
        # The user clicked REBUILD INDEX: consent by direct action (§3.1).
        self._start_compute(plan, _consented=True, rebuild=True)

    def _on_index_error(self, error_msg):
        """Handle index build error (main thread)."""
        if not self._from(self._index_worker):
            return
        self._release_index_worker()
        self._end_job()
        self._after_index_writer()
        # Writes before the failure may have landed (a Full Rebuild's own
        # commit is one transaction, so it never empties the index): the
        # caches go and the view shows what the store holds (review r8 #5).
        self._store_changed()
        self._refresh_quietly()
        self.status_bar.show_state(states.sync_failed(error_msg))
        print(f"[FIND_CHART] Index build error: {error_msg}")

    def _rebuild_index(self):
        """Refresh the index: unchanged files are kept, new and changed read."""
        self._save_folder_paths()
        self._build_index_async(_user_initiated=True)

    def _show_rebuild_context_menu(self, pos):
        """The Library's index menu (Refresh index, Full rebuild)."""
        self.library.index_menu.exec(self.rebuild_btn.mapToGlobal(pos))

    def _full_rebuild_index(self):
        """Empty the store and rebuild from the sources (context menu only)."""
        self._save_folder_paths()
        self._build_index_async(_user_initiated=True, _discard=True)

    def closeEvent(self, event):
        """Stop all background workers on close to prevent crashes."""
        self.stop_background_work()
        super().closeEvent(event)

    def stop_background_work(self, *, app_quit=False):
        """Cancel the compute and join every worker thread (the panel closing,
        the app quitting): a QThread destroyed while it runs aborts the app.
        ``app_quit`` (the app's close handler, SPEC-FIND-005 §4.9): a sort
        that is moving files finishes its current file and journal write
        before the app goes; on a panel close it is detached instead."""
        # Phase 1, before anything can process events (review r13: the sort's
        # finishing repaint drains the queue): timers off, every result relay
        # and the web load token void, so a queued result does nothing.
        self._closing = True
        self._quit = self._quit or app_quit
        self._search_token += 1  # a background read lands nowhere
        self._search_worker = None
        self._fill_timer.stop()
        if self._fill is not None:
            self._fill[1].close()
            self._fill = None
        self._busy_timer.stop()
        if getattr(self, "search_timer", None) is not None:
            self.search_timer.stop()  # no search (and its compute) after close
        self._web_token += 1  # a deferred chart load from before is void
        for worker in (self._web_worker, self._index_worker, self._compute_worker,
                       self._store_file_worker):
            if worker is not None:
                fc_workers.invalidate(worker)
        # Phase 2: the sort finishes or detaches, then the rest is joined.
        self._stop_sort_worker(app_quit=app_quit)
        self._stop_check_worker(app_quit=app_quit)
        self.rate_sort.stop(app_quit=app_quit)
        if app_quit:  # workers an earlier panel close parked join too (r11)
            fc_workers.join_parked()
        # The index and compute workers: cancelled (a scan stops before its
        # commit; after it the writes finish), their results disconnected so
        # nothing follows (no compute after a sync), then joined; on app quit
        # with no time cap (review r10: ``quit()`` does not stop a ``run()``
        # without an event loop, and a thread destroyed running aborts the
        # app). A panel close waits 3 s, then parks the worker until it ends.
        # Search Web runs on a daemon thread (it never aborts the exit):
        # cancelled, so it writes no file, then left to end on its own; a
        # file write in progress is waited for (review r11).
        web = self._web_worker
        if web is not None:
            fc_workers.disconnect_web(web)
            self._web_worker = None
            web.cancel()
            web.wait(0)
        for attr in ("_index_worker", "_compute_worker", "_store_file_worker"):
            worker = getattr(self, attr)
            if worker is None:
                continue
            if hasattr(worker, "cancel"):
                worker.cancel()
            fc_workers.disconnect_results(worker)
            setattr(self, attr, None)
            worker.quit()
            if app_quit:  # local writes: they finish, the app waits
                worker.wait()
            elif not worker.wait(3000):
                fc_workers.park(worker)
                continue
            worker.deleteLater()

    def _recolor_group_rows(self, theme):
        """Group header rows keep the brushes they were built with (the
        delegate hands them to the standard painter), and the row cache does
        not rebuild them on a theme switch: recolor them in place (review
        2026-10-23). Result rows are painted from live tokens already."""
        table = getattr(self, "results_table", None)
        if table is None:
            return
        bg, fg = QColor(theme["secondary_light"]), QColor(theme["secondary_text"])
        for row in range(table.rowCount()):
            first = table.item(row, 0)
            if first is None or first.flags() & Qt.ItemFlag.ItemIsSelectable:
                continue
            first.setForeground(fg)
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item is not None:
                    item.setBackground(bg)

    def refresh_theme(self):
        """Update all colors when theme changes."""
        if getattr(self, "search_timer", None) is not None:
            self._display_changed()
        theme = get_theme_colors()
        self._recolor_group_rows(theme)

        # Main widget background
        self.setStyleSheet(f"""
            QWidget {{ background: transparent; color: {theme['secondary_text']}; }}
            QWidget#fc_find_chart {{ background: {theme['secondary']}; }}
            QGroupBox {{ border: none; margin: 0; padding: 0; }}
            QLineEdit {{
                background: {theme['secondary_light']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 4px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border-color: {theme['primary']}; }}
        """)
        self.results_hint.setStyleSheet(
            f"color: {kit.tokens()['muted'].name()}; font-size: {scaled_area_px('info_text')}px;"
            "padding: 4px 0; background: transparent;"
        )

        # Web download section: styled once at construction, so a live
        # theme switch re-applies it here (td-v21r).
        if self.toolbar is not None:
            self.toolbar.refresh_theme()
        if getattr(self, "web_download_widget", None) is not None:
            self.no_results_label.setStyleSheet(
                f"color: {theme['secondary_text']}; "
                f"font-size: {scaled_area_px('status')}px;")
            self.web_search_btn.setStyleSheet(get_primary_button_style())
            self.web_status_label.setStyleSheet(
                f"color: {theme['secondary_text']}; "
                f"font-size: {scaled_area_px('status')}px; font-style: italic;")
            self.web_result_label.setStyleSheet(
                f"color: {desat_hex(STATUS['success'])}; "
                f"font-size: {scaled_area_px('status')}px; font-weight: bold;")
            self.web_download_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: {theme['secondary']};
                    border: 1px solid {theme['primary']};
                    border-radius: 6px;
                }}
            """)

        # Persistent-surface live-replay: this panel is not rebuilt when the font
        # settings change, so re-compose every migrated widget's font QSS from the
        # live values. Runs last so nothing it sets is overwritten.
        self._refresh_fonts()
        # td-2o8u: re-derive fm-based geometry floors so migrated widgets that
        # kept setFixedHeight/setFixedWidth do not clip at large fonts.
        self._refresh_geometry()


def _remember(cache, key, value):
    """``cache[key] = value``, keeping the two latest keys (the search,
    column and coverage caches: a query and the one before it)."""
    if key not in cache and len(cache) >= 2:
        cache.pop(next(iter(cache)))
    cache[key] = value


def _duration(seconds):
    if seconds < 90:
        return f"{max(1, round(seconds))} seconds"
    return f"{round(seconds / 60)} minutes"
