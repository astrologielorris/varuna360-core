# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""ChartSideFrame: one chart side (SI / Wheel / NI stacked) with its chrome.

SPEC-DUAL-001 D-2 (td-1mgk7): extracted from ``DualChartWidget`` so the Chart
tab's chart B and the Transit / Solar Return pages share ONE construction of a
chart side (frame style, themed background, element pies off, chart-host
registration). ``DualChartWidget`` composes two of these and keeps its public
``left_*`` / ``right_*`` attributes as aliases of the side attributes.

The frame is display-only: its views are not connected to the GUI (no planet
clicks, no dialogs).

Render API (used by chart B; DualChartWidget keeps its own per-side render
bookkeeping on top of the same views):
- ``update_from_chart`` renders all three stacked views;
- ``update_visible_only`` renders only the on-screen view and marks the other
  two dirty; ``flush_dirty(index)`` renders a dirty view before it is shown;
- ``set_view_index`` flushes then reveals; ``clear`` empties every view.
"""

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout,
    QWidget,
)

from apps.widgets.chart_host_registry import register_chart_host
from core.i18n import t
from apps.widgets.north_indian_view import NorthIndianView
from apps.widgets.south_indian_vector_view import create_south_indian_view
from apps.widgets.wheel_view import WheelView
from ui.qt_theme import (
    get_frame_style,
    get_theme_colors,
    scaled_area_px,
    themed_chart_background,
)
from ui.themed_style import ThemedStyleMixin


def _header_style():
    theme = get_theme_colors()
    return (f"font-size: {scaled_area_px('table_headers')}px; font-weight: bold; "
            f"color: {theme['secondary_text']};")


def _name_style():
    theme = get_theme_colors()
    return (f"color: {theme['secondary_text']}; font-size: {scaled_area_px('tables')}px; "
            f"font-weight: bold;")


def _info_style():
    theme = get_theme_colors()
    return f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;"


class ChartSideFrame(ThemedStyleMixin, QFrame):
    """One chart side: chrome (header row + name / info labels) above a stack
    of three chart views (0 South Indian, 1 Wheel, 2 North Indian)."""

    VIEW_NAMES = ("south_indian", "wheel", "north_indian")

    def __init__(self, title: str = "", empty_name: str = "",
                 min_size: int = 400, margins: int = 8, parent=None):
        super().__init__(parent)
        # Frame background (Wave G): registered so refresh_theme replays it.
        self._register_themed(self, get_frame_style)
        self._chart = None
        self._kwargs = None
        self._dirty = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(margins, margins, margins, margins)
        layout.setSpacing(4)

        # SPEC-FSV-001 §3.7: chrome wrapper (hidden by fullscreen in one call).
        self.chrome = QWidget()
        chrome_layout = QVBoxLayout(self.chrome)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(4)

        self.header_row = QHBoxLayout()
        self.header_label = QLabel(title)
        self.header_label.setStyleSheet(_header_style())
        self.header_row.addWidget(self.header_label)
        self.header_row.addStretch()
        self.header_widget_slot = QHBoxLayout()
        self.header_row.addLayout(self.header_widget_slot)
        chrome_layout.addLayout(self.header_row)

        self.name_label = QLabel(empty_name)
        self.name_label.setStyleSheet(_name_style())
        chrome_layout.addWidget(self.name_label)
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(_info_style())
        chrome_layout.addWidget(self.info_label)
        layout.addWidget(self.chrome)

        self.stack = QStackedWidget()
        if min_size:
            self.stack.setMinimumSize(min_size, min_size)
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.south = create_south_indian_view()
        self.wheel = WheelView()
        # td-u53i: element pies are a MAIN-TAB feature; every side wheel is
        # born with them OFF and nothing here re-enables them.
        self.wheel.show_element_pies = False
        self.north = NorthIndianView()
        # td-iqjb.8 (Wave H): theme-locked background at construction.
        self.south.set_background(themed_chart_background())

        self.stack.addWidget(self.south)   # 0
        self.stack.addWidget(self.wheel)   # 1
        self.stack.addWidget(self.north)   # 2
        layout.addWidget(self.stack, 1)

    def register_hosts(self):
        """td-iaqm.5 CP7d: register the Wheel / NI views so a live sign-display
        flip redraws them (the SI view rides its own live registry)."""
        register_chart_host(self.wheel)
        register_chart_host(self.north)

    # ------------------------------------------------------------------ views
    def views(self):
        """The three views in stack order (0 South, 1 Wheel, 2 North)."""
        return (self.south, self.wheel, self.north)

    def current_view(self):
        return self.stack.currentWidget()

    @property
    def chart(self):
        return self._chart

    # ----------------------------------------------------------------- render
    @staticmethod
    def _resolve_mode(chart, aditya_mode):
        if aditya_mode is not None:
            return aditya_mode
        from libaditya.objects.context import Circle
        return "aditya" if chart.context.circle == Circle.ADITYA else "tropical_classic"

    def _commit(self, chart, name, info, use_western_names, varga_code, aditya_mode):
        self._chart = chart
        self._kwargs = dict(varga_code=varga_code, use_western_names=use_western_names,
                            aditya_mode=aditya_mode)
        self.name_label.setText(name if name else t("chart.side.loaded", "Chart loaded"))
        self.info_label.setText(info if info else "")

    def update_from_chart(self, chart, name="", info="", use_western_names=False,
                          varga_code=None, aditya_mode=None):
        """Render ALL three stacked views from ``chart``."""
        aditya_mode = self._resolve_mode(chart, aditya_mode)
        self._commit(chart, name, info, use_western_names, varga_code, aditya_mode)
        for view in self.views():
            view.update_from_chart(chart, **self._kwargs)
        self._dirty.clear()

    def update_visible_only(self, chart, name="", info="", use_western_names=False,
                            varga_code=None, aditya_mode=None):
        """Render only the on-screen view; the other two are marked dirty and
        rendered by ``flush_dirty`` before they are revealed (M3, td-n0o9)."""
        aditya_mode = self._resolve_mode(chart, aditya_mode)
        self._commit(chart, name, info, use_western_names, varga_code, aditya_mode)
        views = self.views()
        assert self.stack.count() == len(views), "stacked view count drifted"
        visible = self.stack.currentIndex()
        self._dirty = set(range(self.stack.count())) - {visible}
        views[visible].update_from_chart(chart, **self._kwargs)

    def flush_dirty(self, index):
        """Render a dirty view (no-op when ``index`` is clean)."""
        if index not in self._dirty:
            return
        self._dirty.discard(index)
        if self._chart is None or self._kwargs is None:
            return
        self.views()[index].update_from_chart(self._chart, **self._kwargs)

    def clear(self, name="", info=""):
        """Empty every view (SPEC-SIC-002 §4.1: clear_chart, never the scene)."""
        self._chart = None
        self._kwargs = None
        self._dirty.clear()
        self.name_label.setText(name if name else "")
        self.info_label.setText(info if info else "")
        for view in self.views():
            view.clear_chart()

    def set_view_index(self, index):
        """Flush the target view, then reveal it (flush before show: td-u53i)."""
        index = max(0, min(int(index), self.stack.count() - 1))
        self.flush_dirty(index)
        self.stack.setCurrentIndex(index)

    # ------------------------------------------------------------------ theme
    def refresh_theme(self):
        """Re-apply the frame style, chrome label styles and the themed chart
        background (Wave H), then let each view redraw. Works while hidden: the
        styles are applied now and painted on the next show."""
        self._replay_themed()
        self.header_label.setStyleSheet(_header_style())
        self.name_label.setStyleSheet(_name_style())
        self.info_label.setStyleSheet(_info_style())
        themed_bg = themed_chart_background()
        for v in self.views():
            try:
                if hasattr(v, 'set_background'):
                    v.set_background(themed_bg)
                if hasattr(v, 'refresh_theme'):
                    v.refresh_theme()
                if hasattr(v, 'sync_style'):
                    v.sync_style()
            except Exception:
                # Per-child isolation (eclipse_panel Wave B pattern).
                pass
