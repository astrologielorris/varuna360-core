#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Time Adjust Widget
Time adjustment buttons for birth time or transit time navigation.

Displays two columns of buttons overlaid on the chart center:
- Left column: Time decrements (red buttons)
- Right column: Time increments (green buttons)

Time adjustments range from ±1 second to ±50 years.

NOTE: This widget is overlaid ON TOP of the chart view (not embedded in scene)
to avoid ownership conflicts when the chart is redrawn.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGridLayout, QFrame, QLabel
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import QFont, QIcon
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Import centralized theme
from ui.qt_theme import (
    get_theme_colors, scaled_area_px
)

# Time increment definitions: (label, timedelta_kwargs)
TIME_INCREMENTS = [
    ("1s", {"seconds": 1}),
    ("10s", {"seconds": 10}),
    ("1m", {"minutes": 1}),
    ("10m", {"minutes": 10}),
    ("30m", {"minutes": 30}),
    ("1h", {"hours": 1}),
    ("1d", {"days": 1}),
    ("1w", {"weeks": 1}),
    ("1mo", {"days": 30}),  # Approximate month
    ("1y", {"days": 365}),  # Approximate year
    ("10y", {"days": 3650}),  # Approximate 10 years
    ("50y", {"days": 18250}),  # Approximate 50 years
]

class TimeAdjustWidget(QWidget):
    """
    Widget containing time adjustment buttons for birth time or transit navigation.

    This widget is designed to be overlaid ON TOP of the chart view (not embedded
    in the QGraphicsScene) to avoid destruction when the chart is redrawn.
    """

    # Signal emitted when time is adjusted (optional - for external listeners)
    time_adjusted = Signal(int)  # delta_seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gui = None  # Will be set by caller
        self._drag_active = False
        self._drag_offset = QPoint()
        self._setup_ui()

    def set_gui(self, gui):
        """Set reference to main GUI for accessing planets_data and recalculation."""
        self.gui = gui

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle_rect = self._drag_handle.geometry()
            if handle_rect.contains(event.position().toPoint()):
                self._drag_active = True
                self._drag_offset = event.position().toPoint()
                self._drag_handle.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active:
            new_pos = self.mapToParent(event.position().toPoint()) - self._drag_offset
            parent = self.parentWidget()
            if parent:
                pr = parent.rect()
                x = max(0, min(new_pos.x(), pr.width() - self.width()))
                y = max(0, min(new_pos.y(), pr.height() - self.height()))
                self.move(x, y)
            else:
                self.move(new_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_active:
            self._drag_active = False
            self._drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _setup_ui(self):
        """Create the button grid layout."""
        theme = get_theme_colors()

        # Use QFrame for proper rounded corners with clipping
        self.setStyleSheet("""
            TimeAdjustWidget {
                background-color: #1E1E20;
                border-radius: 12px;
                border: 1px solid #555;
            }
        """)

        # Main layout directly on self - compact margins
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(2)

        # Drag handle at the top (3 horizontal bars)
        self._drag_handle = QFrame()
        self._drag_handle.setFixedHeight(22)
        self._drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self._drag_handle.setStyleSheet("""
            QFrame {
                background: transparent;
                border: none;
                border-bottom: 1px solid #444;
            }
        """)
        grip_label = QLabel(self._drag_handle)
        svg_path = Path(__file__).resolve().parents[2] / "img" / "icons" / "drag_grip.svg"
        icon = QIcon(str(svg_path))
        pix = icon.pixmap(100, 16)
        if not pix.isNull():
            grip_label.setPixmap(pix)
        else:
            grip_label.setText("━ ━ ━")
            grip_label.setStyleSheet(f"color: #AAA; font-size: {scaled_area_px('buttons')}px;")
        grip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grip_layout = QHBoxLayout(self._drag_handle)
        grip_layout.setContentsMargins(0, 2, 0, 2)
        grip_layout.addWidget(grip_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._drag_handle)

        # Create grid for buttons - tight spacing
        grid = QGridLayout()
        grid.setSpacing(3)

        # Button styling — red (decrease) / blue (increase) with gradient depth
        minus_style = f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #6B3535, stop:1 #4A2020);
                color: #E8C8C8;
                font-weight: bold;
                font-size: {scaled_area_px('buttons')}px;
                border: 1px solid #7A4040;
                border-bottom: 2px solid #351515;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 55px;
                min-height: 22px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #8B4545, stop:1 #5A3030);
                border-color: #AA5555;
                color: #FFD0D0;
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #351515, stop:1 #4A2020);
                border-bottom: 1px solid #351515;
                padding-top: 5px;
            }}
        """

        plus_style = f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #354A6B, stop:1 #20354A);
                color: #C8D8E8;
                font-weight: bold;
                font-size: {scaled_area_px('buttons')}px;
                border: 1px solid #40557A;
                border-bottom: 2px solid #152035;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 55px;
                min-height: 22px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #456A8B, stop:1 #30455A);
                border-color: #5575AA;
                color: #D0E0FF;
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #152035, stop:1 #20354A);
                border-bottom: 1px solid #152035;
                padding-top: 5px;
            }}
        """

        # Create button pairs for each time increment
        for row, (label, delta_kwargs) in enumerate(TIME_INCREMENTS):
            # Calculate total seconds for this increment
            td = timedelta(**delta_kwargs)
            delta_seconds = int(td.total_seconds())

            # Minus button (left column)
            minus_btn = QPushButton(f"-{label}")
            minus_btn.setStyleSheet(minus_style)
            minus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            # Store delta in button property to avoid lambda closure issues
            minus_btn.setProperty("delta_seconds", -delta_seconds)
            minus_btn.clicked.connect(self._on_button_clicked)
            grid.addWidget(minus_btn, row, 0)

            # Plus button (right column)
            plus_btn = QPushButton(f"+{label}")
            plus_btn.setStyleSheet(plus_style)
            plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            plus_btn.setProperty("delta_seconds", delta_seconds)
            plus_btn.clicked.connect(self._on_button_clicked)
            grid.addWidget(plus_btn, row, 1)

        layout.addLayout(grid)

        # Save button — commits the adjusted time as the chart's new birth time
        save_style = f"""
            QPushButton {{
                background-color: #2A6ACF;
                color: white;
                font-weight: bold;
                font-size: {scaled_area_px('buttons')}px;
                border: none;
                border-radius: 4px;
                padding: 6px 8px;
            }}
            QPushButton:hover {{
                background-color: #3A7ADF;
            }}
            QPushButton:pressed {{
                background-color: #1A5ABF;
            }}
        """
        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet(save_style)
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setToolTip("Save adjusted time as the chart's birth time")
        self.save_btn.clicked.connect(self._save_adjusted_time)
        layout.addWidget(self.save_btn)

        # 12 rows x 28px + save button (32px) + drag handle (26px) + margins + grid spacing
        self.setFixedSize(160, 445)

    def update_save_button_state(self):
        """Disable Save when transit overlay is active (transit time is ephemeral)."""
        mgr = getattr(self.gui, 'transit_overlay_manager', None)
        if mgr and mgr.transit_enabled and self._active_view_has_overlay():
            self.save_btn.setEnabled(False)
            self.save_btn.setToolTip(
                "Cannot save transit time (toggle transit OFF to adjust birth time)"
            )
        else:
            self.save_btn.setEnabled(True)
            self.save_btn.setToolTip("Save adjusted time as the chart's birth time")

    def _on_button_clicked(self):
        """Handle time adjustment button click."""
        sender = self.sender()
        if sender:
            delta_seconds = sender.property("delta_seconds")
            if delta_seconds is not None:
                # Use QTimer to defer the adjustment slightly
                # This prevents issues with signal handling during scene updates
                QTimer.singleShot(10, lambda ds=delta_seconds: self._adjust_time(ds))

    def _active_view_has_overlay(self):
        """True when the active chart view renders a transit overlay."""
        return self.gui.state.chart_view_style in ("wheel", "south_indian", "north_indian")

    def _adjust_time(self, delta_seconds):
        """Adjust birth time (or transit time if overlay active) by delta_seconds."""
        if not self.gui:
            return
        mgr = getattr(self.gui, 'transit_overlay_manager', None)
        if mgr and mgr.transit_enabled and self._active_view_has_overlay():
            mgr.adjust_time(delta_seconds)
            return

        old_chart = self.gui.state.active_chart
        if not old_chart:
            return

        from dataclasses import replace as dc_replace
        from core.chart_factory import make_source_params, timedec_to_hms
        from libaditya.objects.julian_day import JulianDay
        from libaditya.charts.chart import Chart
        from state.events import SetActiveChart

        try:
            ctx = old_chart.context
            old_jd = ctx.timeJD

            # Nudge JD (EphContext is frozen → replace)
            new_jd_float = old_jd.jd + delta_seconds * old_jd.onesecjd
            new_timeJD = JulianDay(new_jd_float, utcoffset=old_jd.utcoffset)
            _chart = Chart(dc_replace(ctx, timeJD=new_timeJD))

            # Update source_params for mode-switch rebuild / session restore
            sp = self.gui.state.source_params or {}
            old_bd = sp.get("birth_data", {})
            njd = _chart.context.timeJD
            hour_float = njd.usrhour()
            h, m, s = timedec_to_hms(hour_float)

            new_bd = dict(old_bd)
            new_bd.update({
                'year': njd.usryear(), 'month': njd.usrmonth(),
                'day': njd.usrday(), 'hour': h, 'minute': m,
                'second': s, 'timedec': hour_float,
                'latitude': ctx.location.lat,
                'longitude': ctx.location.long,
            })
            self.gui.state.dispatch(SetActiveChart(chart=_chart, source_params=make_source_params(
                chtk_path=sp.get("chtk_path"),
                birth_data=new_bd,
                mode=sp.get("mode", self.gui.state.aditya_mode),
                ayanamsa=sp.get("ayanamsa",
                                getattr(self.gui, 'chart_sidereal_ayanamsa_id', 1)),
                house_system=sp.get("house_system", "campanus"),
                is_human_design=sp.get("is_human_design", False),
            )))

            self.gui.birth_jd = new_jd_float

            new_meta = dict(new_bd)
            new_meta.setdefault('timezone', 'UTC')
            for key in ['city', 'country', 'gender']:
                if key in old_bd:
                    new_meta.setdefault(key, old_bd[key])
            self.gui._current_chart_data = None
            self.gui.current_birth_data = new_meta

            if hasattr(self.gui, '_finalize_chart_load'):
                self.gui._finalize_chart_load(
                    skip_varga_reset=True, skip_loading=True)

        except Exception as e:
            print(f"[TIME_ADJUST] Error adjusting time: {e}")
            import traceback
            traceback.print_exc()

    def _update_title_display(self, birth_data):
        """Update the window title bar with adjusted time info.

        birth_data stores time in the timezone it was calculated with
        (often UTC for transit charts). We must convert to the chart's
        display timezone before writing to current_chart_data.
        """
        if not self.gui:
            return

        try:
            year = birth_data.get('year', 0)
            month = birth_data.get('month', 0)
            day = birth_data.get('day', 0)
            hour = birth_data.get('hour', 0)
            minute = birth_data.get('minute', 0)
            second = birth_data.get('second', 0)
            calc_tz_str = birth_data.get('timezone', 'UTC')

            # Get the chart's display timezone from current_chart_data
            chart_data = getattr(self.gui, 'current_chart_data', None)
            if not chart_data:
                return

            display_tz_str = chart_data.get('timezone', 'UTC')

            # Convert from calculation timezone to display timezone if they differ
            if calc_tz_str != display_tz_str:
                try:
                    calc_tz = ZoneInfo(calc_tz_str)
                    display_tz = ZoneInfo(display_tz_str)
                    dt_calc = datetime(year, month, day, hour, minute, second, tzinfo=calc_tz)
                    dt_local = dt_calc.astimezone(display_tz)
                    year, month, day = dt_local.year, dt_local.month, dt_local.day
                    hour, minute, second = dt_local.hour, dt_local.minute, dt_local.second
                except Exception as e:
                    print(f"[TIME_ADJUST] Timezone conversion error: {e}")

            # Update current_chart_data with local time values
            chart_data['year'] = year
            chart_data['month'] = month
            chart_data['day'] = day
            chart_data['hour'] = hour
            chart_data['minute'] = minute
            chart_data['second'] = second

            # Also update current_birth_data (canonical source used by _update_title)
            # Without this, the window title bar shows stale time from initial load
            birth_data = getattr(self.gui, 'current_birth_data', None)
            if birth_data:
                birth_data['local_year'] = year
                birth_data['local_month'] = month
                birth_data['local_day'] = day
                birth_data['local_hour'] = hour
                birth_data['local_minute'] = minute
                birth_data['local_second'] = second

            # Use the standard title update for consistent formatting
            if hasattr(self.gui, '_update_title'):
                self.gui._update_title()

        except Exception as e:
            print(f"[TIME_ADJUST] Error updating title: {e}")

    def _save_adjusted_time(self):
        """Save the current adjusted time as the chart's definitive birth time."""
        if not self.gui:
            return
        active = self.gui.state.active_chart
        if not active:
            return

        njd = active.context.timeJD
        year = njd.usryear()
        month = njd.usrmonth()
        day = njd.usrday()
        timedec = njd.usrhour()

        saved = False
        if hasattr(self.gui, 'chart_memory_panel') and self.gui.chart_memory_panel:
            panel = self.gui.chart_memory_panel
            if 0 <= panel.current_index < len(panel.charts):
                panel.update_current_chart({
                    'year': year,
                    'month': month,
                    'day': day,
                    'timedec': timedec,
                })
                entry = panel.charts[panel.current_index]
                entry['_chart'] = active
                entry['_built_mode'] = self.gui.state.aditya_mode
                entry['_built_ayanamsa'] = getattr(
                    self.gui, 'chart_sidereal_ayanamsa_id', 1
                )
                saved = True

                if hasattr(self.gui, 'edit_chart_panel') and self.gui.edit_chart_panel:
                    self.gui.edit_chart_panel.load_chart_from_memory(entry)

        if hasattr(self.gui, '_update_title'):
            self.gui._update_title()

        if hasattr(self.gui, '_toggle_time_adjust'):
            self.gui._toggle_time_adjust()

        if saved:
            self.gui.statusBar().showMessage("Birth time saved", 3000)
        else:
            self.gui.statusBar().showMessage("No chart selected to save", 3000)

def create_time_adjust_overlay(gui):
    """
    Create and return a TimeAdjustWidget configured for the given GUI.

    Args:
        gui: The main ChartGUI instance

    Returns:
        TimeAdjustWidget instance (as child of chart_view for proper positioning)
    """
    # Create widget as child of chart_stack so it overlays on any chart view
    if hasattr(gui, 'chart_stack') and gui.chart_stack:
        widget = TimeAdjustWidget(gui.chart_stack)
    elif hasattr(gui, 'chart_view') and gui.chart_view:
        widget = TimeAdjustWidget(gui.chart_view)
    else:
        widget = TimeAdjustWidget()

    widget.set_gui(gui)
    widget.hide()  # Start hidden
    return widget
