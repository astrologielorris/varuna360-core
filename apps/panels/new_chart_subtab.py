# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
New Chart Sub-tab - Form for creating charts from scratch

This sub-tab provides a form for entering birth data to create a new chart:
- Name and Gender
- Date (MM/DD/YYYY)
- Time with Local/UTC toggle
- Location (City, Country)
- Coordinates (Latitude, Longitude with cardinal directions)
- Timezone and DST settings

Creates a new chart by calculating planetary positions and adding to memory panel.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QLineEdit, QRadioButton, QButtonGroup, QPushButton, QLabel,
    QScrollArea, QFrame, QGroupBox, QSpacerItem, QSizePolicy,
    QMessageBox, QApplication
)
from PySide6.QtCore import Signal, Slot, Qt
from PySide6.QtGui import QIntValidator, QDoubleValidator

# Theme imports - use dynamic colors for proper light/dark support
from ui.qt_theme import get_theme_colors, scaled_area_px

# Time conversion utilities (extracted to core/)
from core.time_utils import local_to_utc, utc_to_local, invert_chtk_timezone
HAS_TIME_UTILS = True

class NewChartSubTab(QWidget):
    """
    Form for creating new charts from scratch.

    Signals:
        chart_created(object): Emitted when a new chart is successfully created.
            Carries a libaditya Chart object (Chart-Everywhere Issue 8b-R).
        data_changed(): Emitted when any field changes
    """

    chart_created = Signal(object)  # carries a libaditya Chart (Issue 8b-R)
    data_changed = Signal()
    map_view_requested = Signal()  # Request switch to Map View

    def __init__(self, parent_panel):
        super().__init__()

        self.parent_panel = parent_panel
        self.gui = parent_panel.gui if hasattr(parent_panel, 'gui') else None
        self.time_mode = "Local"  # "Local" or "UTC"
        self._syncing = False  # Prevent recursive sync
        self._group_frames = []  # Store group frames for theme refresh
        self._group_labels = []  # Store group labels for theme refresh

        self._create_ui()
        self._setup_validators()
        self._setup_bindings()

    def _create_ui(self):
        """Create the form UI"""
        # Get dynamic theme colors
        theme = get_theme_colors()
        bg = theme['secondary_dark']

        # Main layout with scroll
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {bg}; }}")
        self._scroll = scroll  # Store for theme refresh

        # Content widget
        content = QWidget()
        content.setStyleSheet(f"background: {bg};")
        self._content = content  # Store for theme refresh
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(15)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # === Title + Clear Form row ===
        title_row = QHBoxLayout()
        self._title_label = QLabel("Create New Chart")
        self._title_label.setStyleSheet(f"""
            font-size: {scaled_area_px('panel_titles')}px;
            font-weight: bold;
            color: {theme['secondary_text']};
            padding: 10px 0;
        """)
        title_row.addWidget(self._title_label)
        title_row.addStretch()

        self.clear_btn = QPushButton("Clear Form")
        self.clear_btn.setToolTip("Reset all fields")
        self._style_button(self.clear_btn, accent=False)
        title_row.addWidget(self.clear_btn)

        content_layout.addLayout(title_row)

        # === Name Section ===
        name_group = self._create_group("Full Name:")
        name_layout = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter person's name")
        self._style_input(self.name_input)
        name_layout.addWidget(self.name_input)
        name_group.layout().addLayout(name_layout)
        content_layout.addWidget(name_group)

        # === Gender Section ===
        gender_group = self._create_group("Gender:")
        gender_layout = QHBoxLayout()
        self.gender_group = QButtonGroup(self)
        self.male_radio = QRadioButton("Male")
        self.female_radio = QRadioButton("Female")
        self._style_radio(self.male_radio)
        self._style_radio(self.female_radio)
        self.gender_group.addButton(self.male_radio, 1)
        self.gender_group.addButton(self.female_radio, 2)
        gender_layout.addWidget(self.male_radio)
        gender_layout.addWidget(self.female_radio)
        gender_layout.addStretch()
        gender_group.layout().addLayout(gender_layout)
        content_layout.addWidget(gender_group)

        # === Date Section ===
        date_group = self._create_group("Date (month/day/year):")
        date_layout = QHBoxLayout()

        self.date_month = QLineEdit()
        self.date_month.setPlaceholderText("MM")
        self.date_month.setMaximumWidth(60)
        self._style_input(self.date_month)

        self.date_day = QLineEdit()
        self.date_day.setPlaceholderText("DD")
        self.date_day.setMaximumWidth(60)
        self._style_input(self.date_day)

        self.date_year = QLineEdit()
        self.date_year.setPlaceholderText("YYYY")
        self.date_year.setMaximumWidth(80)
        self._style_input(self.date_year)

        date_layout.addWidget(self.date_month)
        date_layout.addWidget(QLabel("/"))
        date_layout.addWidget(self.date_day)
        date_layout.addWidget(QLabel("/"))
        date_layout.addWidget(self.date_year)

        format_label = QLabel("(MM/DD/YYYY)")
        format_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px; opacity: 0.7;")
        date_layout.addWidget(format_label)
        date_layout.addStretch()

        date_group.layout().addLayout(date_layout)
        content_layout.addWidget(date_group)

        # === Time Format Toggle ===
        time_toggle_group = self._create_group("Time Format:")
        time_toggle_layout = QHBoxLayout()

        self.time_mode_group = QButtonGroup(self)
        self.local_radio = QRadioButton("Local Time")
        self.utc_radio = QRadioButton("UTC Time")
        self.local_radio.setChecked(True)

        self._style_radio(self.local_radio)
        self._style_radio(self.utc_radio)

        self.time_mode_group.addButton(self.local_radio, 0)
        self.time_mode_group.addButton(self.utc_radio, 1)

        time_toggle_layout.addWidget(self.local_radio)
        time_toggle_layout.addWidget(self.utc_radio)
        time_toggle_layout.addStretch()

        time_toggle_group.layout().addLayout(time_toggle_layout)
        content_layout.addWidget(time_toggle_group)

        # === Local Time Section ===
        local_group = self._create_group("Local Time:")
        local_layout = QHBoxLayout()

        self.local_hour = QLineEdit()
        self.local_hour.setPlaceholderText("HH")
        self.local_hour.setMaximumWidth(50)
        self._style_input(self.local_hour)

        self.local_minute = QLineEdit()
        self.local_minute.setPlaceholderText("MM")
        self.local_minute.setMaximumWidth(50)
        self._style_input(self.local_minute)

        self.local_second = QLineEdit()
        self.local_second.setPlaceholderText("SS")
        self.local_second.setMaximumWidth(50)
        self._style_input(self.local_second)

        local_layout.addWidget(self.local_hour)
        local_layout.addWidget(QLabel(":"))
        local_layout.addWidget(self.local_minute)
        local_layout.addWidget(QLabel(":"))
        local_layout.addWidget(self.local_second)

        local_format = QLabel("(HH:MM:SS)")
        local_format.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('info_text')}px; opacity: 0.7;")
        local_layout.addWidget(local_format)
        local_layout.addStretch()

        local_group.layout().addLayout(local_layout)
        self.local_time_group = local_group
        content_layout.addWidget(local_group)

        # === UTC Time Section ===
        utc_group = self._create_group("UTC Time:")
        utc_layout = QHBoxLayout()

        self.utc_hour = QLineEdit()
        self.utc_hour.setPlaceholderText("HH")
        self.utc_hour.setMaximumWidth(50)
        self._style_input(self.utc_hour, readonly=True)

        self.utc_minute = QLineEdit()
        self.utc_minute.setPlaceholderText("MM")
        self.utc_minute.setMaximumWidth(50)
        self._style_input(self.utc_minute, readonly=True)

        self.utc_second = QLineEdit()
        self.utc_second.setPlaceholderText("SS")
        self.utc_second.setMaximumWidth(50)
        self._style_input(self.utc_second, readonly=True)

        utc_layout.addWidget(self.utc_hour)
        utc_layout.addWidget(QLabel(":"))
        utc_layout.addWidget(self.utc_minute)
        utc_layout.addWidget(QLabel(":"))
        utc_layout.addWidget(self.utc_second)

        self.utc_day_offset = QLabel("")
        self.utc_day_offset.setStyleSheet(f"color: {theme['primary']}; font-weight: bold;")
        utc_layout.addWidget(self.utc_day_offset)
        utc_layout.addStretch()

        utc_group.layout().addLayout(utc_layout)
        self.utc_time_group = utc_group
        content_layout.addWidget(utc_group)

        # === Location Section ===
        location_group = self._create_group("Location:")

        # Hidden inputs for data storage (set by map, read by chart creation)
        self.city_input = QLineEdit()
        self.city_input.setVisible(False)
        self.country_input = QLineEdit()
        self.country_input.setVisible(False)

        # Location display label (shows selected city, country)
        self.location_display_label = QLabel("No location selected")
        self.location_display_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('tables')}px; padding: 4px;")
        location_group.layout().addWidget(self.location_display_label)

        # Button row: Use Map + Help
        btn_row = QHBoxLayout()

        self.use_map_btn = QPushButton("Use Map")
        self.use_map_btn.setToolTip("Pick a location on the interactive map")
        self._style_button(self.use_map_btn, accent=True)

        self.help_btn = QPushButton("?  Help")
        self.help_btn.setFixedWidth(80)
        self.help_btn.setToolTip("How to use this form")
        self._style_button(self.help_btn, accent=False)

        btn_row.addWidget(self.use_map_btn)
        btn_row.addWidget(self.help_btn)
        location_group.layout().addLayout(btn_row)

        content_layout.addWidget(location_group)

        # === Coordinates Section ===
        coords_group = self._create_group("Coordinates:")
        coords_layout = QGridLayout()

        coords_layout.addWidget(QLabel("Latitude:"), 0, 0)
        self.latitude_input = QLineEdit()
        self.latitude_input.setPlaceholderText("e.g. 48.8566")
        self._style_input(self.latitude_input)
        coords_layout.addWidget(self.latitude_input, 0, 1)

        self.lat_dir_group = QButtonGroup(self)
        self.lat_n = QRadioButton("N")
        self.lat_s = QRadioButton("S")
        self.lat_n.setChecked(True)
        self._style_radio(self.lat_n)
        self._style_radio(self.lat_s)
        self.lat_dir_group.addButton(self.lat_n, 0)
        self.lat_dir_group.addButton(self.lat_s, 1)

        lat_dir_layout = QHBoxLayout()
        lat_dir_layout.addWidget(self.lat_n)
        lat_dir_layout.addWidget(self.lat_s)
        coords_layout.addLayout(lat_dir_layout, 0, 2)

        coords_layout.addWidget(QLabel("Longitude:"), 1, 0)
        self.longitude_input = QLineEdit()
        self.longitude_input.setPlaceholderText("e.g. 2.3522")
        self._style_input(self.longitude_input)
        coords_layout.addWidget(self.longitude_input, 1, 1)

        self.lon_dir_group = QButtonGroup(self)
        self.lon_e = QRadioButton("E")
        self.lon_w = QRadioButton("W")
        self.lon_e.setChecked(True)
        self._style_radio(self.lon_e)
        self._style_radio(self.lon_w)
        self.lon_dir_group.addButton(self.lon_e, 0)
        self.lon_dir_group.addButton(self.lon_w, 1)

        lon_dir_layout = QHBoxLayout()
        lon_dir_layout.addWidget(self.lon_e)
        lon_dir_layout.addWidget(self.lon_w)
        coords_layout.addLayout(lon_dir_layout, 1, 2)

        coords_group.layout().addLayout(coords_layout)
        content_layout.addWidget(coords_group)

        # === Timezone Section ===
        tz_group = self._create_group("Timezone:")
        tz_layout = QGridLayout()

        tz_layout.addWidget(QLabel("UTC Offset:"), 0, 0)
        self.timezone_input = QLineEdit()
        self.timezone_input.setPlaceholderText("+01:00")
        self._style_input(self.timezone_input)
        tz_layout.addWidget(self.timezone_input, 0, 1)

        tz_layout.addWidget(QLabel("(e.g. +05:30 for India, -05:00 for New York)"), 1, 0, 1, 2)

        tz_group.layout().addLayout(tz_layout)
        content_layout.addWidget(tz_group)

        # === DST Section ===
        dst_group = self._create_group("Daylight Saving Time:")
        dst_layout = QHBoxLayout()

        self.dst_group = QButtonGroup(self)
        self.dst_none = QRadioButton("None (Standard)")
        self.dst_yes = QRadioButton("DST Active")
        self.dst_war = QRadioButton("War Time")
        self.dst_none.setChecked(True)

        self._style_radio(self.dst_none)
        self._style_radio(self.dst_yes)
        self._style_radio(self.dst_war)

        self.dst_group.addButton(self.dst_none, 0)
        self.dst_group.addButton(self.dst_yes, 1)
        self.dst_group.addButton(self.dst_war, 2)

        dst_layout.addWidget(self.dst_none)
        dst_layout.addWidget(self.dst_yes)
        dst_layout.addWidget(self.dst_war)
        dst_layout.addStretch()

        dst_group.layout().addLayout(dst_layout)
        content_layout.addWidget(dst_group)

        # === Action Buttons ===
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)

        self.create_btn = QPushButton("Create Chart")
        self.create_btn.setToolTip("Calculate planets and create new chart")
        self._style_button(self.create_btn, accent=True)

        button_layout.addStretch()
        button_layout.addWidget(self.create_btn)

        content_layout.addLayout(button_layout)

        # Add spacer at bottom
        content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _create_group(self, title: str) -> QFrame:
        """Create a styled group frame with dynamic theme colors"""
        from PySide6.QtWidgets import QFrame
        theme = get_theme_colors()
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        self._group_frames.append(frame)  # Store for theme refresh

        layout = QVBoxLayout(frame)
        layout.setSpacing(8)

        label = QLabel(title)
        label.setStyleSheet(f"color: {theme['secondary_text']}; font-weight: bold; border: none;")
        self._group_labels.append(label)  # Store for theme refresh
        layout.addWidget(label)

        return frame

    def _style_input(self, widget: QLineEdit, readonly: bool = False):
        """Apply consistent styling to input fields with dynamic theme"""
        theme = get_theme_colors()
        # For readonly, use a lighter shade
        bg = theme['secondary_light'] if readonly else theme['secondary']
        text_color = theme['secondary_text']

        widget.setStyleSheet(f"""
            QLineEdit {{
                background-color: {bg};
                color: {text_color};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 4px;
                padding: 8px;
                font-size: {scaled_area_px('tables')}px;
            }}
            QLineEdit:focus {{
                border-color: {theme['primary']};
            }}
            QLineEdit:read-only {{
                background-color: {theme['secondary_light']};
                color: {text_color};
                opacity: 0.7;
            }}
        """)
        if readonly:
            widget.setReadOnly(True)

    def _style_radio(self, radio: QRadioButton):
        """Apply consistent styling to radio buttons"""
        theme = get_theme_colors()
        radio.setStyleSheet(f"""
            QRadioButton {{
                color: {theme['secondary_text']};
                spacing: 8px;
                padding: 5px;
            }}
            QRadioButton::indicator {{
                width: 16px;
                height: 16px;
            }}
        """)

    def _style_button(self, button: QPushButton, accent: bool = False):
        """Apply consistent styling to buttons"""
        theme = get_theme_colors()
        if accent:
            button.setStyleSheet(f"""
                QPushButton {{
                    background: {theme['primary']};
                    color: white;
                    border: none;
                    border-radius: 5px;
                    padding: 12px 24px;
                    font-size: {scaled_area_px('buttons')}px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background: {theme['primary_light']};
                }}
                QPushButton:pressed {{
                    background: {theme['primary_dark']};
                }}
            """)
        else:
            button.setStyleSheet(f"""
                QPushButton {{
                    background: {theme['secondary_dark']};
                    color: {theme['secondary_text']};
                    border: 1px solid {theme['secondary_dark']};
                    border-radius: 5px;
                    padding: 10px 20px;
                    font-size: {scaled_area_px('buttons')}px;
                }}
                QPushButton:hover {{
                    background: {theme['secondary_light']};
                    border-color: {theme['primary']};
                }}
            """)

    def _setup_validators(self):
        """Set up input validators"""
        # Date validators
        self.date_month.setValidator(QIntValidator(1, 12))
        self.date_day.setValidator(QIntValidator(1, 31))
        self.date_year.setValidator(QIntValidator(1, 2100))

        # Time validators
        self.local_hour.setValidator(QIntValidator(0, 23))
        self.local_minute.setValidator(QIntValidator(0, 59))
        self.local_second.setValidator(QIntValidator(0, 59))
        self.utc_hour.setValidator(QIntValidator(0, 23))
        self.utc_minute.setValidator(QIntValidator(0, 59))
        self.utc_second.setValidator(QIntValidator(0, 59))

        # Coordinate validators
        self.latitude_input.setValidator(QDoubleValidator(0, 90, 6))
        self.longitude_input.setValidator(QDoubleValidator(0, 180, 6))

    def _setup_bindings(self):
        """Set up signal connections"""
        # Time mode toggle
        self.local_radio.toggled.connect(self._on_time_mode_changed)
        self.utc_radio.toggled.connect(self._on_time_mode_changed)

        # Local time changes -> sync to UTC
        self.local_hour.textChanged.connect(self._sync_utc_from_local)
        self.local_minute.textChanged.connect(self._sync_utc_from_local)
        self.local_second.textChanged.connect(self._sync_utc_from_local)

        # UTC time changes -> sync to local
        self.utc_hour.textChanged.connect(self._sync_local_from_utc)
        self.utc_minute.textChanged.connect(self._sync_local_from_utc)
        self.utc_second.textChanged.connect(self._sync_local_from_utc)

        # Timezone/DST changes
        self.timezone_input.textChanged.connect(self._on_timezone_changed)
        self.dst_group.buttonToggled.connect(self._on_dst_changed)

        # Date changes affect UTC conversion
        self.date_year.textChanged.connect(self._sync_utc_from_local)
        self.date_month.textChanged.connect(self._sync_utc_from_local)
        self.date_day.textChanged.connect(self._sync_utc_from_local)

        # All field changes -> mark modified
        for widget in [self.name_input, self.date_month, self.date_day, self.date_year,
                       self.local_hour, self.local_minute, self.local_second,
                       self.country_input, self.city_input,
                       self.latitude_input, self.longitude_input, self.timezone_input]:
            widget.textChanged.connect(lambda: self.data_changed.emit())

        # Button connections
        self.create_btn.clicked.connect(self._on_create_chart)
        self.clear_btn.clicked.connect(self.clear_form)
        self.use_map_btn.clicked.connect(lambda: self.map_view_requested.emit())
        self.help_btn.clicked.connect(self._on_help)

    # =========================================================================
    # TIME MODE HANDLING
    # =========================================================================

    @Slot(bool)
    def _on_time_mode_changed(self, checked: bool):
        """Handle Local/UTC toggle"""
        if not checked:  # Only process when becoming checked
            return

        is_local = self.local_radio.isChecked()
        self.time_mode = "Local" if is_local else "UTC"

        # Update field states
        self._update_time_field_states()

        # Trigger sync
        if is_local:
            self._sync_utc_from_local()
        else:
            self._sync_local_from_utc()

    def _update_time_field_states(self):
        """Update which time fields are editable based on mode"""
        is_local = self.time_mode == "Local"

        # Local fields
        for widget in [self.local_hour, self.local_minute, self.local_second]:
            widget.setReadOnly(not is_local)
            self._style_input(widget, readonly=not is_local)

        # UTC fields
        for widget in [self.utc_hour, self.utc_minute, self.utc_second]:
            widget.setReadOnly(is_local)
            self._style_input(widget, readonly=is_local)

        # DST is only relevant in Local mode
        theme = get_theme_colors()
        for btn in [self.dst_none, self.dst_yes, self.dst_war]:
            btn.setEnabled(is_local)
            if not is_local:
                btn.setStyleSheet(f"""
                    QRadioButton {{
                        color: {theme['secondary_text']};
                        spacing: 8px;
                        padding: 5px;
                        opacity: 0.5;
                    }}
                """)
            else:
                self._style_radio(btn)

        # Timezone is only relevant in Local mode
        self.timezone_input.setEnabled(is_local)
        self._style_input(self.timezone_input, readonly=not is_local)

    # =========================================================================
    # TIME SYNCHRONIZATION
    # =========================================================================

    @Slot()
    def _sync_utc_from_local(self):
        """Convert local time to UTC and update UTC fields"""
        if self._syncing or self.time_mode != "Local":
            return

        if not HAS_TIME_UTILS:
            return

        self._syncing = True
        try:
            # Get local time
            hour = int(self.local_hour.text() or 0)
            minute = int(self.local_minute.text() or 0)
            second = int(self.local_second.text() or 0)

            # Get date
            year = int(self.date_year.text() or 2000)
            month = int(self.date_month.text() or 1)
            day = int(self.date_day.text() or 1)

            # Get timezone
            tz_str = self.timezone_input.text().strip() or "+00:00"

            # Get DST flag as int (0/1/2), not bool
            dst_flag = self.dst_group.checkedId()
            if dst_flag < 0:
                dst_flag = 0

            # Convert
            utc_result = local_to_utc(year, month, day, hour, minute, second, tz_str, dst_flag)

            # Update UTC fields
            self.utc_hour.setText(f"{utc_result[3]:02d}")
            self.utc_minute.setText(f"{utc_result[4]:02d}")
            self.utc_second.setText(f"{utc_result[5]:02d}")

            # Check for date rollover
            from datetime import date
            local_date = date(year, month, day)
            utc_date = date(utc_result[0], utc_result[1], utc_result[2])
            day_diff = (utc_date - local_date).days

            if day_diff == -1:
                self.utc_day_offset.setText("(-1d)")
            elif day_diff == 1:
                self.utc_day_offset.setText("(+1d)")
            elif day_diff != 0:
                self.utc_day_offset.setText(f"({day_diff:+d}d)")
            else:
                self.utc_day_offset.setText("")

        except (ValueError, TypeError):
            pass  # Silently ignore invalid input during typing
        finally:
            self._syncing = False

    @Slot()
    def _sync_local_from_utc(self):
        """Convert UTC time to local and update local fields"""
        if self._syncing or self.time_mode != "UTC":
            return

        if not HAS_TIME_UTILS:
            return

        self._syncing = True
        try:
            # Get UTC time
            hour = int(self.utc_hour.text() or 0)
            minute = int(self.utc_minute.text() or 0)
            second = int(self.utc_second.text() or 0)

            # Get date
            year = int(self.date_year.text() or 2000)
            month = int(self.date_month.text() or 1)
            day = int(self.date_day.text() or 1)

            # Get timezone
            tz_str = self.timezone_input.text().strip() or "+00:00"

            # Get DST flag as int (0/1/2), not bool
            dst_flag = self.dst_group.checkedId()
            if dst_flag < 0:
                dst_flag = 0

            # Convert
            local_result = utc_to_local(year, month, day, hour, minute, second, tz_str, dst_flag)

            # Update local fields
            self.local_hour.setText(f"{local_result[3]:02d}")
            self.local_minute.setText(f"{local_result[4]:02d}")
            self.local_second.setText(f"{local_result[5]:02d}")

        except (ValueError, TypeError):
            pass
        finally:
            self._syncing = False

    @Slot()
    def _on_timezone_changed(self, text: str = ""):
        """Re-sync when timezone changes"""
        if self.time_mode == "Local":
            self._sync_utc_from_local()
        self.data_changed.emit()

    @Slot()
    def _on_dst_changed(self, button=None, checked: bool = False):
        """Re-sync when DST changes"""
        if self.time_mode == "Local":
            self._sync_utc_from_local()
        self.data_changed.emit()

    # =========================================================================
    # COORDINATE LOOKUP
    # =========================================================================

    # _on_search_location removed: location is now set exclusively via Map View (commit 7a192916).

    # =========================================================================
    # PUBLIC SETTERS (matching EditInfoSubTab API)
    # =========================================================================

    def set_coordinates(self, lat: float, lon: float):
        """Set coordinates from external source (e.g., map)"""
        self._syncing = True
        try:
            self.latitude_input.setText(f"{abs(lat):.6f}")
            self.longitude_input.setText(f"{abs(lon):.6f}")
            if lat >= 0:
                self.lat_n.setChecked(True)
            else:
                self.lat_s.setChecked(True)
            if lon >= 0:
                self.lon_e.setChecked(True)
            else:
                self.lon_w.setChecked(True)
        finally:
            self._syncing = False

    def set_city(self, city: str):
        """Set city from external source"""
        self.city_input.setText(city)
        self._update_location_display()

    def set_country(self, country: str):
        """Set country from external source"""
        self.country_input.setText(country)
        self._update_location_display()

    def _update_location_display(self):
        """Update the visible location label from hidden city/country fields."""
        city = self.city_input.text().strip()
        country = self.country_input.text().strip()
        if city and country:
            self.location_display_label.setText(f"{city}, {country}")
        elif city:
            self.location_display_label.setText(city)
        elif country:
            self.location_display_label.setText(country)
        else:
            self.location_display_label.setText("No location selected")

    def set_timezone(self, tz_str: str):
        """Set timezone from external source (IANA name or offset string)"""
        self._syncing = True
        try:
            if '/' in tz_str:
                try:
                    from datetime import datetime
                    try:
                        birth_dt = datetime(
                            int(self.date_year.text() or 2000),
                            int(self.date_month.text() or 1),
                            int(self.date_day.text() or 1),
                            int(self.local_hour.text() or 0),
                            int(self.local_minute.text() or 0),
                        )
                    except Exception:
                        birth_dt = datetime(2000, 1, 1)
                    # SPEC-TZ-001 5g: canonical resolver decomposes the TOTAL
                    # offset at the birth instant into std + dst flag. War
                    # radio is never auto-set (user-asserted only).
                    from core.time_utils import resolve_total_offset, format_offset
                    std_hours, dst_flag = resolve_total_offset(
                        tz_str, birth_dt.year, birth_dt.month, birth_dt.day,
                        birth_dt.hour, birth_dt.minute)
                    self.timezone_input.setText(format_offset(0, int(round(std_hours * 60))))
                    if dst_flag == 1:
                        self.dst_yes.setChecked(True)
                    else:
                        self.dst_none.setChecked(True)
                except Exception:
                    pass
            else:
                self.timezone_input.setText(tz_str)
        finally:
            self._syncing = False
        self._sync_utc_from_local()

    # =========================================================================
    # HELP DIALOG
    # =========================================================================

    @Slot()
    def _on_help(self):
        """Show comprehensive help dialog about creating charts and time reliability"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QDialogButtonBox
        from PySide6.QtCore import QSize

        dialog = QDialog(self)
        dialog.setWindowTitle("New Chart — Help")
        dialog.setMinimumSize(QSize(620, 520))
        layout = QVBoxLayout(dialog)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        theme = get_theme_colors()
        browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                border: none;
                font-size: {scaled_area_px('info_text')}px;
                padding: 12px;
            }}
        """)
        browser.setHtml(f"""
        <h2 style="color: {theme['primary']};">Creating a New Chart</h2>

        <p><b>Name & Date:</b> Enter birth name, gender, and date (MM/DD/YYYY).</p>

        <h3 style="color: {theme['primary']};">Time Format</h3>

        <p><b>Local Time</b> (recommended): Just enter the clock time at the birth location.
        The software handles everything automatically — timezone and DST are detected
        when you search for a location.</p>

        <p><b>UTC Time</b>: This is what the software actually needs to calculate a chart.
        UTC mode is more complex because you need to already know the UTC time yourself.
        Daylight Saving Time rules are notoriously hard to track — every country has different
        rules, and those rules have changed many times throughout history. Some birth times
        are unreliable precisely because of this administrative chaos.
        <b>Use UTC when you have a verified UTC time, or for births before 1970</b> where
        the timezone database is less reliable.</p>

        <h3 style="color: {theme['primary']};">Location</h3>
        <ul>
        <li><b>Search Location</b>: Type a city name, click Search — fills city, country,
            coordinates, and timezone automatically.</li>
        <li><b>Use Map</b>: Click on the map to pick a location visually.</li>
        <li>You can also enter coordinates manually if you have them.</li>
        </ul>

        <h3 style="color: {theme['primary']};">A Note on Birth Time Accuracy</h3>

        <p>Even though the astrology community rarely discusses this openly, <b>birth time
        remains one of the most unreliable pieces of data we work with</b>. This is not the
        fault of astrologers or of the software — it is a limitation of how humans have
        recorded time across different eras.</p>

        <p>For most of history, precise timekeeping simply did not exist. Pocket watches
        only became common in the 16th century, and even then they were imprecise and owned
        by few. Wristwatches spread during World War I (1910s). Quartz accuracy arrived
        in 1969. Today we carry phones that sync to atomic clocks — so <i>now</i> we know
        when things happen. Or at least we should.</p>

        <p>But even in the 2000s, and even in 2025, <b>birth times are still recorded
        without seconds</b>. The minutes themselves are often rounded — how many birth
        certificates say ":30" when the real time was :31 or :28? To most people, the
        difference is trivial. To an astrologer, it is not.</p>

        <p>Consider twins: their birth times are usually recorded a few minutes apart —
        "I was born first at :31, my sibling came 6 minutes later." Yet even here, no one
        records the seconds. This matters because this software calculates <b>Varga charts
        (divisional charts)</b>, where even a one-minute difference can shift a planet
        into a different division.</p>

        <p><b>This is perhaps the main reason astrology as a science is still emerging</b>,
        despite enormous strides in calculation software. The further back in time you go,
        the less reliable the recorded birth time becomes. We are limited not by our
        understanding of the cosmos, but by how carefully humanity has chosen to record
        the moment of birth.</p>
        """)

        layout.addWidget(browser)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(dialog.accept)
        button_box.setStyleSheet(f"""
            QPushButton {{
                background: {theme['primary']};
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 24px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(button_box)

        dialog.exec()

    # =========================================================================
    # DATA COLLECTION
    # =========================================================================

    def collect_data(self) -> dict:
        """
        Gather all form values into a dictionary.

        Returns:
            Dict with all form data
        """
        try:
            # Get latitude with direction
            lat = float(self.latitude_input.text() or 0)
            if self.lat_s.isChecked():
                lat = -lat

            # Get longitude with direction
            lon = float(self.longitude_input.text() or 0)
            if self.lon_w.isChecked():
                lon = -lon

            if self.time_mode == "UTC":
                hour = int(self.utc_hour.text() or 0)
                minute = int(self.utc_minute.text() or 0)
                second = int(self.utc_second.text() or 0)
            else:
                hour = int(self.local_hour.text() or 0)
                minute = int(self.local_minute.text() or 0)
                second = int(self.local_second.text() or 0)

            data = {
                'name': self.name_input.text().strip(),
                'year': int(self.date_year.text() or 0),
                'month': int(self.date_month.text() or 0),
                'day': int(self.date_day.text() or 0),
                'hour': hour,
                'minute': minute,
                'second': second,
                'gender': 'Male' if self.male_radio.isChecked() else 'Female' if self.female_radio.isChecked() else '',
                'country': self.country_input.text().strip(),
                'city': self.city_input.text().strip(),
                'latitude': lat,
                'longitude': lon,
                'timezone': self.timezone_input.text().strip() or '+00:00',
                'dst': self.dst_group.checkedId(),
                'time_mode': self.time_mode,
            }
            return data
        except ValueError as e:
            print(f"Error collecting form data: {e}")
            return {}

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def _validate_data(self, data: dict) -> bool:
        """Validate form data before creating chart"""
        errors = []

        if not data.get('name'):
            errors.append("Name is required")

        year = data.get('year', 0)
        if not (1 <= year <= 2100):
            errors.append("Year must be between 1 and 2100")

        month = data.get('month', 0)
        if not (1 <= month <= 12):
            errors.append("Month must be 1-12")

        day = data.get('day', 0)
        if 1 <= month <= 12 and 1 <= year:
            import calendar
            max_day = calendar.monthrange(max(year, 1), month)[1]
            if not (1 <= day <= max_day):
                errors.append(f"Day must be 1-{max_day} for month {month}")
        elif not (1 <= day <= 31):
            errors.append("Day must be 1-31")

        hour = data.get('hour', 0)
        if not (0 <= hour <= 23):
            errors.append("Hour must be 0-23")

        minute = data.get('minute', 0)
        if not (0 <= minute <= 59):
            errors.append("Minute must be 0-59")

        second = data.get('second', 0)
        if not (0 <= second <= 59):
            errors.append("Second must be 0-59")

        lat = data.get('latitude', 0)
        lon = data.get('longitude', 0)
        if not self.latitude_input.text().strip() and not self.longitude_input.text().strip():
            errors.append("Coordinates are required (use the map to select a location)")
        else:
            if not (-90 <= lat <= 90):
                errors.append("Latitude must be -90 to 90")
            if not (-180 <= lon <= 180):
                errors.append("Longitude must be -180 to 180")

        if errors:
            QMessageBox.warning(self, "Validation Error", "\n".join(errors))
            return False

        return True

    # =========================================================================
    # CREATE CHART
    # =========================================================================

    @Slot()
    def _on_create_chart(self):
        """Create new chart from form data"""
        # Collect data
        data = self.collect_data()
        if not data:
            QMessageBox.warning(self, "Error", "Could not collect form data")
            return

        # Validate
        if not self._validate_data(data):
            return

        # Calculate planets — returns (Chart, dict) pair (Issue 8b-R).
        # Chart is the new pipeline; dict is kept for memory_panel legacy use.
        result = self._calculate_planets(data)
        if not result:
            return
        chart, _recipe = result

        self._add_to_memory_panel(data, _recipe, chart)

        self.chart_created.emit(chart)
        self.clear_form()

    def _calculate_planets(self, data: dict):
        """Calculate planetary positions from form data.

        Issue 8b-R: builds a libaditya Chart via chart_factory and projects
        to a renderer dict for legacy memory_panel consumption. Returns
        (Chart, dict) tuple, or None on error.
        """
        try:
            from core.chart_factory import build_chart_from_params
            from libaditya import swe
        except ImportError as e:
            QMessageBox.critical(self, "Error", f"Could not import chart_factory: {e}")
            return None

        try:
            if self.gui and hasattr(self.gui, 'loading_manager'):
                self.gui.loading_manager.start("Creating chart...")

            # Determine time mode
            is_utc = data.get('time_mode') == 'UTC'

            from managers.birth_data_manager import BirthDataManager

            form_data = {
                'name': data.get('name', ''),
                'year': data.get('year'),
                'month': data.get('month'),
                'day': data.get('day'),
                'hour': data.get('hour'),
                'minute': data.get('minute'),
                'second': data.get('second'),
                'timezone': data.get('timezone', '+00:00'),
                'dst': data.get('dst', 0),
                'time_mode': 'UTC' if is_utc else 'Local',
                'latitude': data.get('latitude', 0.0),
                'longitude': data.get('longitude', 0.0),
                'city': data.get('city', ''),
                'country': data.get('country', ''),
                'gender': data.get('gender', ''),
                'iana_timezone': data.get('iana_timezone', ''),
            }
            bd = BirthDataManager.create_from_form_data(form_data)

            # SPEC-TZ-001 8a: surface timezone warnings, non-blocking
            BirthDataManager.report_tz_warnings(
                BirthDataManager.validate_birth_data(bd),
                status_bar=self.gui.statusBar() if self.gui else None,
                context="New Chart")

            utc_year = bd['utc_year']
            utc_month = bd['utc_month']
            utc_day = bd['utc_day']
            utc_hour = bd['utc_hour']
            utc_minute = bd['utc_minute']
            utc_second = bd['utc_second']
            _utcoffset = bd['utc_offset_hours']

            hour_decimal = utc_hour + utc_minute / 60.0 + utc_second / 3600.0
            jd = swe.julday(utc_year, utc_month, utc_day, hour_decimal)
            _has_state = bool(self.gui and hasattr(self.gui, 'state'))
            mode = self.gui.state.aditya_mode if _has_state else 'aditya'
            _hsys = self.gui.state.house_system_code if _has_state else 'C'
            chart = build_chart_from_params(
                jd=jd,
                lat=data.get('latitude'),
                lon=data.get('longitude'),
                mode=mode,
                name=data.get('name', ''),
                ayanamsa=getattr(self.gui, 'chart_sidereal_ayanamsa_id', 1),
                utcoffset=_utcoffset,
                hsys=_hsys,
            )
            from core.chart_factory import make_recipe
            _local_h = bd.get('local_hour', 0)
            _local_m = bd.get('local_minute', 0)
            _local_s = bd.get('local_second', 0)
            _recipe = make_recipe(
                name=data.get('name', ''),
                year=bd.get('local_year', data.get('year')),
                month=bd.get('local_month', data.get('month')),
                day=bd.get('local_day', data.get('day')),
                timedec=_local_h + _local_m / 60.0 + _local_s / 3600.0,
                utcoffset=_utcoffset,
                timezone=data.get('timezone', 'UTC'),
                lat=data.get('latitude', 0.0), lon=data.get('longitude', 0.0),
                city=data.get('city', ''), country=data.get('country', ''),
                gender=data.get('gender', 'Unknown'),
                time_change_flag=data.get('dst', 0),
                house_system=self.gui.state.house_system if _has_state else 'campanus',
            )

            QApplication.processEvents()
            if self.gui and hasattr(self.gui, 'loading_manager'):
                self.gui.loading_manager.finish()
            return chart, _recipe

        except Exception as e:
            if self.gui and hasattr(self.gui, 'loading_manager'):
                self.gui.loading_manager.force_finish()
            QMessageBox.critical(self, "Calculation Error", f"Error calculating planets: {e}")
            return None

    def _add_to_memory_panel(self, data: dict, recipe: dict, chart=None):
        """Add the new chart to the memory panel and display it."""
        if not self.gui:
            return

        memory_panel = getattr(self.gui, 'memory_panel', None)
        if not memory_panel:
            return

        chart_index = memory_panel.add_chart(
            recipe,
            chtk_path=data.get('chtk_path', ''),
            chart_obj=chart,
        )

        # Select the newly added chart - this triggers proper loading into the app
        memory_panel.select_chart(chart_index)

        # Switch to the Chart tab so user sees the result
        main_tabs = getattr(self.gui, 'main_tabs', None)
        if main_tabs:
            for i in range(main_tabs.count()):
                tab_text = main_tabs.tabText(i)
                if "Chart" in tab_text and "Edit" not in tab_text:
                    main_tabs.setCurrentIndex(i)
                    break

    # =========================================================================
    # CLEAR FORM
    # =========================================================================

    @Slot()
    def clear_form(self):
        """Reset all form fields to empty/default values"""
        self._syncing = True
        try:
            self.name_input.clear()
            self.date_month.clear()
            self.date_day.clear()
            self.date_year.clear()

            self.local_hour.clear()
            self.local_minute.clear()
            self.local_second.clear()
            self.utc_hour.clear()
            self.utc_minute.clear()
            self.utc_second.clear()
            self.utc_day_offset.clear()

            self.city_input.clear()
            self.country_input.clear()
            self._update_location_display()
            self.latitude_input.clear()
            self.longitude_input.clear()
            self.timezone_input.clear()

            self.male_radio.setAutoExclusive(False)
            self.female_radio.setAutoExclusive(False)
            self.male_radio.setChecked(False)
            self.female_radio.setChecked(False)
            self.male_radio.setAutoExclusive(True)
            self.female_radio.setAutoExclusive(True)

            self.local_radio.setChecked(True)
            self.dst_none.setChecked(True)
            self.lat_n.setChecked(True)
            self.lon_e.setChecked(True)

            self.time_mode = "Local"
            self._update_time_field_states()
        finally:
            self._syncing = False

    # =========================================================================
    # THEME SUPPORT
    # =========================================================================

    def refresh_theme(self):
        """Update colors after theme change"""
        theme = get_theme_colors()
        bg = theme['secondary_dark']

        # Update scroll area and content backgrounds
        if hasattr(self, '_scroll'):
            self._scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {bg}; }}")
        if hasattr(self, '_content'):
            self._content.setStyleSheet(f"background: {bg};")

        # Re-style title label
        if hasattr(self, '_title_label'):
            self._title_label.setStyleSheet(f"font-size: {scaled_area_px('panel_titles')}px; font-weight: bold; color: {theme['secondary_text']}; padding: 10px 0;")

        # Re-style group frames and their labels
        group_style = f"QFrame {{ background-color: {theme['secondary']}; border: 1px solid {theme['secondary_dark']}; border-radius: 8px; padding: 10px; }}"
        for frame in getattr(self, '_group_frames', []):
            frame.setStyleSheet(group_style)
        for label in getattr(self, '_group_labels', []):
            label.setStyleSheet(f"color: {theme['secondary_text']}; font-weight: bold; border: none;")

        # Re-style all inputs
        for widget in [self.name_input, self.date_month, self.date_day, self.date_year,
                       self.country_input, self.city_input, self.latitude_input,
                       self.longitude_input, self.timezone_input]:
            self._style_input(widget)

        # Re-style time fields based on mode
        self._update_time_field_states()

        # Re-style radio buttons
        for btn in [self.local_radio, self.utc_radio, self.male_radio, self.female_radio,
                    self.lat_n, self.lat_s, self.lon_e, self.lon_w]:
            self._style_radio(btn)

        # Re-style DST buttons
        is_local = self.time_mode == "Local"
        for btn in [self.dst_none, self.dst_yes, self.dst_war]:
            if is_local:
                self._style_radio(btn)

        # Re-style location display label
        if hasattr(self, 'location_display_label'):
            self.location_display_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('tables')}px; padding: 4px;")

        # Re-style buttons
        self._style_button(self.create_btn, accent=True)
        self._style_button(self.clear_btn, accent=False)
        self._style_button(self.use_map_btn, accent=True)
        self._style_button(self.help_btn, accent=False)
