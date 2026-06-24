# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Add Chart Dialog (Qt) - Birth Chart Creation from natural language input.
PySide6 dialog — uses offline regex parser (text_to_chtk) + geocoding.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFrame, QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor

from ui.qt_theme import (
    SURFACE, BG, BORDER, TEXT_PRIMARY, TEXT_SECONDARY,
    STATUS, HOVER, get_theme_colors, scaled_area_font
)
# Issue 8b-R: Chart-Everywhere — uses core.chart_factory directly.


class AddChartDialog(QDialog):
    """Dialog for creating charts from natural language input (offline regex parser)."""

    # Class-level memory: persists between dialog opens within same app session
    _last_input_text = ""

    def __init__(self, parent=None, on_chart_loaded_callback=None):
        super().__init__(parent)
        self.on_chart_loaded_callback = on_chart_loaded_callback
        self._setup_ui()

    def _setup_ui(self):
        """Build the dialog UI."""
        self.setWindowTitle("Add New Chart")
        self.setFixedSize(750, 400)
        self.setModal(True)

        # Dialog background
        self.setStyleSheet(f"QDialog {{ background-color: {SURFACE}; }}")

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(12)

        # Text input (plain text only — strips formatting on paste)
        self.text_input = QPlainTextEdit()
        self.text_input.setMinimumHeight(220)
        self.text_input.setFont(scaled_area_font('tables'))
        self.text_input.setPlaceholderText(
            "Name, Date, Time, Location\n"
            "(e.g. John Doe, January 15 1990, 10:30am, New York)"
        )
        self.text_input.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {BG};
                color: {TEXT_PRIMARY};
                border: 2px solid {BORDER};
                border-radius: 5px;
                padding: 8px;
            }}
            QPlainTextEdit:focus {{
                border-color: {STATUS["success"]};
            }}
        """)
        layout.addWidget(self.text_input)

        # Restore previous input if any
        if AddChartDialog._last_input_text:
            self.text_input.setPlainText(AddChartDialog._last_input_text)
            self.text_input.selectAll()

        # Compact examples hint
        hint_label = QLabel(
            "Examples: John Doe, January 15 1990, 10:30am, New York  \u2014  "
            "Pierre Martin, 25/12/1975 23h15, Toulouse"
        )
        hint_label.setFont(scaled_area_font('buttons'))
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(hint_label)

        # Status label
        self.status_label = QLabel("Enter birth information and click 'Generate Chart'")
        self.status_label.setFont(scaled_area_font('buttons'))
        self.status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(self.status_label)

        # Auto-confirm checkbox (fast mode: warnings non-blocking)
        self.auto_confirm_checkbox = QCheckBox("Auto-confirm (skip warning popups)")
        self.auto_confirm_checkbox.setChecked(False)
        self.auto_confirm_checkbox.setFont(scaled_area_font('buttons'))
        self.auto_confirm_checkbox.setStyleSheet(
            f"QCheckBox {{ color: {TEXT_SECONDARY}; background: transparent; }}"
        )
        layout.addWidget(self.auto_confirm_checkbox)

        # Stretch to push buttons to bottom
        layout.addStretch()

        # Button frame
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Generate button
        self.generate_btn = QPushButton("Generate Chart")
        self.generate_btn.setFont(scaled_area_font('buttons', bold=True))
        self.generate_btn.setFixedSize(150, 35)
        self.generate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.generate_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {STATUS["success"]};
                color: {TEXT_PRIMARY};
                border: none;
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: {HOVER};
            }}
            QPushButton:pressed {{
                background-color: {BG};
            }}
            QPushButton:disabled {{
                background-color: {BORDER};
                color: {TEXT_SECONDARY};
            }}
        """)
        self.generate_btn.clicked.connect(self._on_generate)
        button_layout.addWidget(self.generate_btn)

        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(scaled_area_font('buttons'))
        cancel_btn.setFixedSize(120, 35)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BG};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 5px;
            }}
            QPushButton:hover {{
                background-color: {HOVER};
            }}
        """)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

        # Focus on text input
        self.text_input.setFocus()

    def _set_status(self, text: str, status_type: str = "info"):
        """Update status label with colored message."""
        color_map = {
            "info": STATUS["info"],
            "success": STATUS["success"],
            "error": STATUS["error"],
            "warning": STATUS["warning"]
        }
        color = color_map.get(status_type, TEXT_SECONDARY)
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color}; background: transparent;")

    def _on_generate(self):
        """Handle Generate Chart button click — offline regex parser + geocoding."""
        user_input = self.text_input.toPlainText().strip()

        # Save input to class-level memory (persists for next open)
        AddChartDialog._last_input_text = user_input

        # Validate input
        if not user_input:
            QMessageBox.warning(
                self, "Empty Input",
                "Please enter birth information in the format:\nName Date Time Location"
            )
            return

        # Show parsing status
        self._set_status("Parsing birth data...", "info")
        self.generate_btn.setEnabled(False)
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            # Step 1: Parse text with offline regex parser
            from AI_tools.AI_main_function.text_to_chtk import parse_birth_text, resolve_location

            parsed = parse_birth_text(user_input)

            name = parsed.get('name', '') or 'Unknown'
            city = parsed['city']
            country = parsed.get('country', '')

            # Show date ambiguity warning if applicable
            if parsed.get('date_warning'):
                if self.auto_confirm_checkbox.isChecked():
                    self._set_status(f"Warning: {parsed['date_warning']}", "warning")
                else:
                    QMessageBox.warning(
                        self, "Date Ambiguity",
                        parsed['date_warning']
                    )

            if not parsed['has_time']:
                if self.auto_confirm_checkbox.isChecked():
                    self._set_status("Warning: No time found, defaulting to 12:00 (noon)", "warning")
                else:
                    QMessageBox.warning(
                        self, "No Time Found",
                        "No birth time was found in the text.\n"
                        "Defaulting to 12:00 (noon). Edit the chart afterwards to set the correct time."
                    )

            # Step 2: Geocode city and get timezone
            self._set_status("Looking up location...", "info")
            QApplication.processEvents()

            loc = resolve_location(city, country,
                                   parsed['year'], parsed['month'], parsed['day'])

            if loc.get('geocode_failed'):
                if self.auto_confirm_checkbox.isChecked():
                    self._set_status(f"Warning: Could not geocode '{city}, {country}' — using fallback", "warning")
                else:
                    QMessageBox.warning(
                        self, "Geocoding Failed",
                        f"Could not find coordinates for '{city}, {country}'.\n"
                        "Using (0, 0) / UTC as fallback. The chart will be inaccurate.\n\n"
                        "Edit the chart afterwards to set correct coordinates."
                    )

            lat = loc['lat']
            lon = loc['lon']
            tz_name = loc['tz_name']


            # Step 3: Calculate planetary positions
            self._set_status("Calculating planetary positions...", "info")
            QApplication.processEvents()

            # Issue 8b-R: build a Chart via chart_factory, then project to dict.
            # The callback takes Chart as primary arg; planets_data carries
            # local-time metadata for display (title bar, edit panel).
            from core.chart_factory import build_chart_from_params
            from libaditya import swe
            from datetime import datetime, timedelta
            from zoneinfo import ZoneInfo

            # Convert the parsed local time + tz_name to UTC for the Chart.
            utc_offset_hours = 0.0
            try:
                from core.time_utils import lmt_corrected_offset
                utc_offset_hours = lmt_corrected_offset(
                    tz_name, parsed['year'], parsed['month'], parsed['day'],
                    parsed['hour'], parsed['minute'], parsed.get('second', 0),
                    lon
                )
                local_dt = datetime(
                    parsed['year'], parsed['month'], parsed['day'],
                    parsed['hour'], parsed['minute'], parsed.get('second', 0),
                )
                utc_dt = local_dt - timedelta(hours=utc_offset_hours)
            except Exception:
                utc_dt = datetime(
                    parsed['year'], parsed['month'], parsed['day'],
                    parsed['hour'], parsed['minute'], parsed.get('second', 0),
                )
            hour_decimal = utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0
            jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, hour_decimal)

            # Mode comes from the parent GUI's current state, defaulting to 'zodiac'
            mode = 'zodiac'
            parent_gui = self.parent()
            if parent_gui is not None and hasattr(parent_gui, 'state'):
                mode = parent_gui.state.aditya_mode

            ayanamsa_id = 1
            if parent_gui is not None and hasattr(parent_gui, 'chart_sidereal_ayanamsa_id'):
                ayanamsa_id = parent_gui.chart_sidereal_ayanamsa_id
            chart = build_chart_from_params(
                jd=jd, lat=lat, lon=lon, mode=mode, name=name, ayanamsa=ayanamsa_id,
                utcoffset=utc_offset_hours,
            )
            location = f"{city}, {country}" if country else city
            planets_data = {
                'julian_day': jd,
                'name': name,
                'person_name': name,
                'city': city,
                'country': country or 'Unknown',
                'year': parsed['year'],
                'month': parsed['month'],
                'day': parsed['day'],
                'hour': parsed['hour'],
                'minute': parsed['minute'],
                'second': parsed.get('second', 0),
                'latitude': lat,
                'longitude': lon,
                'timezone': tz_name,
                'gender': parsed.get('gender', 'Unknown'),
            }

            # Step 4: Call the callback to load chart into GUI
            self._set_status("Loading chart...", "info")
            QApplication.processEvents()

            if self.on_chart_loaded_callback:
                try:
                    self.on_chart_loaded_callback(chart, name, location, planets_data=planets_data)
                except Exception as callback_error:
                    import traceback
                    traceback.print_exc()
                    self._set_status(f"Error loading chart: {str(callback_error)}", "error")
                    self.generate_btn.setEnabled(True)
                    QMessageBox.critical(
                        self, "Chart Loading Error",
                        f"Chart was generated but failed to load:\n\n{str(callback_error)}"
                    )
                    return

            # Success - close dialog
            self.accept()
            QMessageBox.information(
                self.parent(), "Success",
                f"Chart successfully generated for:\n{name}\n{location}"
            )

        except ValueError as e:
            # parse_birth_text raises ValueError when no date found / input invalid
            error_msg = str(e)
            self._set_status(f"Could not parse: {error_msg}", "error")
            self.generate_btn.setEnabled(True)
            QMessageBox.critical(
                self, "Parse Error",
                f"Could not parse birth data:\n\n{error_msg}\n\n"
                "Please include at least a date (e.g. 'January 15, 1990')."
            )

        except Exception as e:
            error_msg = str(e)
            import traceback
            traceback.print_exc()
            if len(error_msg) > 150:
                error_msg = error_msg[:150] + "..."
            self._set_status(f"Error: {error_msg}", "error")
            self.generate_btn.setEnabled(True)
            QMessageBox.critical(
                self, "Chart Generation Error",
                f"Failed to generate chart:\n\n{error_msg}"
            )


def show_add_chart_dialog(parent, on_chart_loaded_callback):
    """
    Show the Add Chart dialog.

    Args:
        parent: Parent QWidget
        on_chart_loaded_callback: Callback function(planets_data, name, location)
    """
    dialog = AddChartDialog(parent, on_chart_loaded_callback)
    dialog.exec()
