# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Chart Manager - Handles chart file operations and loading

This module manages:
- Opening CHTK files via file dialog
- Loading and parsing CHTK charts
- Reloading current chart
- Closing/removing charts from memory
- Taking chart screenshots

Extracted from core_gui_qt.py to reduce complexity and improve maintainability.
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QApplication
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import Qt

from utils.debug import debug_print

# Project root is one level up from this managers/ directory.
_MANAGERS_DIR = Path(__file__).parent
PROJECT_ROOT = _MANAGERS_DIR.parent

def _format_chart_title(chart, aditya_mode="aditya", chart_data=None, timezone_str=None):
    """Build window title from Chart object.

    Full format: Name | Date Time TZ | City, Country | Asc: Sign Deg°Min'
    Minimal format (no chart_data): Name | Asc: Sign Deg°Min'
    """
    from libaditya.objects.context import Circle

    person_name = chart.context.name or "Unknown"
    rashi = chart.rashi()
    try:
        asc_cusp = rashi.cusps()[1]
    except (KeyError, IndexError, TypeError):
        return f"{person_name} | Asc: Unknown"

    sign_idx = asc_cusp.sign()
    if chart.context.circle == Circle.ADITYA:
        from core.varga_codes import ADITYA_SIGNS
        asc_sign = ADITYA_SIGNS[sign_idx]
    else:
        asc_sign = asc_cusp.sign_name()

    asc_deg = int(asc_cusp.real_in_sign_longitude())
    asc_min = int((asc_cusp.real_in_sign_longitude() % 1) * 60)
    asc_str = f"Asc: {asc_sign} {asc_deg}°{asc_min:02d}'"

    if not chart_data:
        return f"{person_name} | {asc_str}"

    year = chart_data['local_year'] if 'local_year' in chart_data else chart_data.get('year', 1900)
    month = chart_data['local_month'] if 'local_month' in chart_data else chart_data.get('month', 1)
    day = chart_data['local_day'] if 'local_day' in chart_data else chart_data.get('day', 1)
    hour = chart_data['local_hour'] if 'local_hour' in chart_data else chart_data.get('hour', 0)
    minute = chart_data['local_minute'] if 'local_minute' in chart_data else chart_data.get('minute', 0)
    date_str = f"{month:02d}/{day:02d}/{year}"
    time_str = f"{hour:02d}:{minute:02d}"

    tz_part = ""
    try:
        if timezone_str and timezone_str != "UTC":
            try:
                from zoneinfo import ZoneInfo
                from datetime import datetime as dt_module, timezone as dt_tz
                tz = ZoneInfo(timezone_str)
                dt = dt_module(year, month, day, hour, minute, tzinfo=tz)
                offset = dt.utcoffset()
                if offset is not None:
                    total_secs = int(offset.total_seconds())
                    off_h = int(total_secs / 3600)
                    off_m = abs(total_secs - off_h * 3600) // 60
                    tz_offset = f"UTC{off_h:+d}:{off_m:02d}" if off_m else f"UTC{off_h:+d}"
                    tz_abbrev = dt.strftime('%Z')
                    if tz_abbrev and not tz_abbrev.startswith(('+', '-')):
                        tz_part = f"{tz_abbrev} ({tz_offset})"
                    else:
                        tz_part = tz_offset
                else:
                    tz_part = timezone_str
            except Exception:
                tz_part = timezone_str
        else:
            tz_part = "UTC"
    except Exception:
        tz_part = timezone_str if timezone_str else "UTC"

    city = chart_data.get('city', '').strip().rstrip(',')
    country = chart_data.get('country', '').strip().rstrip(',')
    if city and city.endswith(', 0'):
        city = city[:-3].strip()
    if city and country and city.lower() == country.lower():
        location_str = city
    else:
        location_str = f"{city}, {country}" if city and country else (city or country or "")

    parts = [person_name, f"{date_str} {time_str} {tz_part}"]
    if location_str:
        parts.append(location_str)
    parts.append(asc_str)
    return " | ".join(parts)


class ChartManager:
    """
    Manages chart file operations - loading, saving, and switching charts.

    This class handles:
    - File dialogs for opening CHTK files
    - Parsing CHTK format and timezone conversion
    - Loading charts into the GUI
    - Closing/removing charts
    - Taking screenshots

    Heavy GUI operations are delegated back to the main window via self.gui reference.
    """

    def __init__(self, gui):
        """
        Initialize the chart manager.

        Args:
            gui: The main ChartGUI instance (QMainWindow)
        """
        self.gui = gui
        self.state = gui.state

    # =========================================================================
    # FILE DIALOG
    # =========================================================================

    def open_file_dialog(self):
        """Show file dialog to open CHTK file."""
        from utils.path_translator import translate_path
        from managers.settings_manager import get_settings
        # Read default folder from SettingsManager
        start_dir = str(PROJECT_ROOT)  # Fallback

        try:
            _sm = get_settings()
            default_folder = _sm.get("paths.default_folder", "")
            # Translate path for cross-OS compatibility
            default_folder = translate_path(default_folder) if default_folder else ''
            if default_folder and Path(default_folder).exists():
                start_dir = default_folder
            else:
                # Fallback to ~/Charts if it exists
                charts_dir = Path.home() / "Charts"
                if charts_dir.exists():
                    start_dir = str(charts_dir)
        except Exception:
            # Use ~/Charts fallback
            charts_dir = Path.home() / "Charts"
            if charts_dir.exists():
                start_dir = str(charts_dir)

        file_path, _ = QFileDialog.getOpenFileName(
            self.gui,
            "Open CHTK Chart File",
            start_dir,
            "CHTK Files (*.chtk);;All Files (*)"
        )

        if file_path:
            self.load_chart(Path(file_path))

    # =========================================================================
    # CHART LOADING
    # =========================================================================

    def reload_current(self):
        """Reload the currently loaded chart."""
        if self.gui.current_chart_path:
            self.load_chart(self.gui.current_chart_path)
            from pathlib import Path
            self.gui.statusBar().showMessage(f"Reloaded: {Path(self.gui.current_chart_path).name}")
        else:
            self.gui.statusBar().showMessage("No chart loaded to reload")

    def load_chart(self, chtk_path):
        """Load CHTK file and display chart."""
        if getattr(self, '_loading_chart', False):
            return
        from core.chart_factory import make_source_params
        from managers.birth_data_manager import BirthDataManager

        self._loading_chart = True
        try:
            # Show loading overlay immediately
            self.gui.loading_manager.start("Loading chart...")

            chtk_path = Path(chtk_path) if isinstance(chtk_path, str) else chtk_path

            # === CREATE CANONICAL BIRTH_DATA FIRST ===
            # This is the Single Source of Truth for all UI components
            birth_data = BirthDataManager.create_birth_data_from_chtk(str(chtk_path))

            # Validate and surface warnings (SPEC-TZ-001 8a, non-blocking).
            # Console [TZ-CHECK] lines now; status bar message merged into the
            # final Loaded message below so it is the LAST showMessage of the load.
            _tz_warns = BirthDataManager.report_tz_warnings(
                BirthDataManager.validate_birth_data(birth_data))

            # Log birth data for DAI tracing (after validation)

            # Extract values from canonical birth_data
            latitude = birth_data.get('latitude', 0)
            longitude = birth_data.get('longitude', 0)

            # UTC time for calculations (already converted in BirthDataManager)
            # Note: We use individual values instead of datetime to support BCE dates
            utc_year = birth_data['utc_year']
            utc_month = birth_data['utc_month']
            utc_day = birth_data['utc_day']
            utc_hour = birth_data['utc_hour']
            utc_minute = birth_data['utc_minute']
            utc_second = birth_data['utc_second']

            # Calculate Julian Day for mode switching
            from core.time_utils import julday
            hour_decimal = utc_hour + utc_minute / 60.0 + utc_second / 3600.0
            birth_jd = julday(utc_year, utc_month, utc_day, hour_decimal)

            # Store birth parameters for mode switching
            self.gui.birth_jd = birth_jd
            self.gui.birth_lat = latitude
            self.gui.birth_lon = longitude
            self.gui.is_human_design = False  # Reset HD mode on new chart load

            # Build libaditya Chart from pre-computed JD and coordinates
            self.gui.loading_manager.update("Calculating positions...")
            from core.chart_factory import build_chart_from_params
            mode = self.state.aditya_mode
            _chart = build_chart_from_params(
                jd=birth_jd,
                lat=latitude,
                lon=longitude,
                mode=mode,
                name=birth_data.get('name', ''),
                utcoffset=birth_data.get('utc_offset_hours', 0.0),
                ayanamsa=getattr(self.gui, 'chart_sidereal_ayanamsa_id', 1),
                hsys=self.state.house_system_code,
            )

            # Dispatch to Layer B state container
            from state.events import SetActiveChart
            self.gui.state.dispatch(SetActiveChart(
                chart=_chart,
                source_params=make_source_params(
                    chtk_path=str(chtk_path),
                    birth_data=birth_data,
                    mode=mode,
                    ayanamsa=getattr(self.gui, 'chart_sidereal_ayanamsa_id', 1),
                    house_system=self.gui.state.house_system,
                    is_human_design=False,
                )))
            self.gui.current_chart_path = str(chtk_path)

            from core.chart_factory import recipe_from_chart
            _recipe = recipe_from_chart(
                _chart,
                timezone=birth_data.get('iana_timezone', 'UTC'),
                city=birth_data.get('city', ''),
                country=birth_data.get('country', ''),
                gender=birth_data.get('gender', 'Unknown'),
                time_change_flag=birth_data.get('time_change_flag', 0),
            )
            self.gui._current_chart_data = None
            self.gui._current_birth_data = birth_data

            self.gui.person_name = birth_data.get('name', 'Unknown')
            self.gui.birth_country = birth_data.get('country', '')
            self.gui.current_timezone = birth_data.get('iana_timezone', 'UTC')

            # Reset dasha levels for new chart load
            self.gui.dasha_level_vedanga = 1
            self.gui.dasha_level_vimshottari = 1
            self.gui.vedanga_parent_chain = []
            self.gui.vimshottari_parent_chain = []
            self.gui.dasha_cycle_offset_vedanga = 0
            self.gui.dasha_cycle_offset_vimshottari = 0
            if hasattr(self.gui, 'vedanga_level_buttons'):
                for idx, btn in enumerate(self.gui.vedanga_level_buttons):
                    btn.setChecked(idx == 0)
            if hasattr(self.gui, 'vimshottari_level_buttons'):
                for idx, btn in enumerate(self.gui.vimshottari_level_buttons):
                    btn.setChecked(idx == 0)

            # Memory panel BEFORE finalize (dasha lazy-rebuild reads recipe)
            chart_name = birth_data.get('name', 'Unknown')
            if hasattr(self.gui, 'memory_panel'):
                self.gui.memory_panel.add_chart(
                    _recipe,
                    chtk_path=str(chtk_path),
                    chart_obj=_chart,
                )

            # Edit chart panel
            city = birth_data.get('city', '')
            country = birth_data.get('country', '')
            if hasattr(self.gui, 'edit_chart_panel') and self.gui.edit_chart_panel:
                chart_entry = {
                    'planets_data': {},
                    'birth_metadata': birth_data,
                    'person_name': chart_name,
                    'city': city,
                    'country': country,
                    'chtk_path': str(chtk_path),
                    'birth_data': birth_data,
                    'chart_obj': self.gui.state.active_chart,
                    'source_params': self.gui.state.source_params,
                }
                self.gui.edit_chart_panel.load_chart_from_memory(chart_entry)

            self.gui._finalize_chart_load()

            if getattr(self.gui, 'right_dasha_mode', 'vimshottari') == 'nisarga':
                self.gui._configure_right_panel_for_nisarga()
            if _tz_warns:
                _more = f" (+{len(_tz_warns) - 1} more)" if len(_tz_warns) > 1 else ""
                self.gui.statusBar().showMessage(
                    f"Loaded: {chart_name} | {_tz_warns[0]}{_more}")
            else:
                self.gui.statusBar().showMessage(f"Loaded: {chart_name}")

            self.gui.loading_manager.finish()

        except Exception as e:
            self.gui.loading_manager.force_finish()
            self.gui.statusBar().showMessage(f"Error loading chart: {e}")
            print(f"Error loading chart: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._loading_chart = False

    # =========================================================================
    # CHART CLOSING
    # =========================================================================

    def close_current_chart(self):
        """
        Remove current chart from memory panel.
        If other charts remain, select the next one. If no charts remain, show empty state.
        """
        # Check if we have a memory panel with a selected chart
        if not hasattr(self.gui, 'memory_panel') or self.gui.memory_panel.current_index == -1:
            return

        current_index = self.gui.memory_panel.current_index
        chart_name = "Unknown"
        if 0 <= current_index < len(self.gui.memory_panel.charts):
            chart_name = self.gui.memory_panel.charts[current_index].get('person_name', 'Unknown')

        # Remove the chart from memory (this also adjusts current_index and saves session)
        self.gui.memory_panel.remove_chart(current_index)

        # Check if there are charts remaining
        if len(self.gui.memory_panel.charts) > 0:
            # Charts remain - select the chart at the adjusted current_index
            adjusted_index = self.gui.memory_panel.current_index
            self.gui.memory_panel.select_chart(adjusted_index)
        else:
            # No charts remain - clear display and show empty state

            # Clear chart view by drawing empty grid
            if hasattr(self.gui, 'chart_view'):
                self.gui.chart_view.draw_empty_grid()

            # Clear active chart FIRST so fallback cannot resurrect (six-eyes M3)
            from state.events import SetActiveChart, SetVarga
            self.gui.state.dispatch(SetActiveChart(chart=None))
            self.gui.state.dispatch(SetVarga(varga_number=1))
            self.gui.current_chart_path = None
            self.gui.current_chart_data = None
            self.gui.current_birth_data = None

            # Clear panels
            if hasattr(self.gui, 'vedanga_list'):
                self.gui.vedanga_list.clear()
            if hasattr(self.gui, 'vimshottari_list'):
                self.gui.vimshottari_list.clear()
            if hasattr(self.gui, 'karakas_table'):
                self.gui.karakas_table.clearContents()
                self.gui.karakas_table.setRowCount(0)
            if hasattr(self.gui, 'strength_table'):
                self.gui.strength_table.clearContents()
                self.gui.strength_table.setRowCount(0)

            # Update title
            if hasattr(self.gui, 'chart_title_label'):
                self.gui.chart_title_label.setText("No Chart Loaded")

            self.gui.setWindowTitle("Varuna360")
            self.gui.statusBar().showMessage("Chart removed from memory")

        self.gui.statusBar().showMessage(f"Removed '{chart_name}' from memory")

    # =========================================================================
    # SCREENSHOT
    # =========================================================================

    def take_screenshot(self):
        """Capture chart view and save as PNG to screenshot_debug/ folder."""
        # Create screenshot directory if it doesn't exist
        screenshot_dir = PROJECT_ROOT / "screenshot_debug"
        screenshot_dir.mkdir(exist_ok=True)

        # Generate filename with timestamp and chart name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        chart_name = "chart"
        if self.gui.current_chart_data:
            chart_name = self.gui.current_chart_data.get('name', 'chart')
            # Sanitize filename (remove invalid characters)
            chart_name = "".join(c for c in chart_name if c.isalnum() or c in " _-").strip()
            chart_name = chart_name.replace(" ", "_")

        filename = f"{chart_name}_{timestamp}.png"
        filepath = screenshot_dir / filename

        try:
            # Render the chart scene to a pixmap
            scene = self.gui.chart_view.scene
            scene_rect = scene.sceneRect()

            # Create a pixmap with the scene dimensions
            image = QImage(
                int(scene_rect.width()),
                int(scene_rect.height()),
                QImage.Format.Format_ARGB32
            )
            image.fill(Qt.GlobalColor.transparent)

            # Render the scene
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            scene.render(painter)
            painter.end()

            # Save to file
            image.save(str(filepath), "PNG")

            self.gui.statusBar().showMessage(f"Screenshot saved: {filename}")

        except Exception as e:
            self.gui.statusBar().showMessage(f"Screenshot failed: {e}")
            print(f"❌ Screenshot error: {e}")
            import traceback
            traceback.print_exc()
