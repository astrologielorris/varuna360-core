# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Edit CHTK Sub-tab - Complete CHTK file editor

This sub-tab provides access to edit all sections of a CHTK file:
- Birth Data (Lines 1-14): Core birth information
- Notes Section: Variable length, ends with ~end of notes~
- Muhurtas Section: Variable length, ends with ~end of muhurtas~
- Secondary Residence: Location data for current residence

CHTK Format (UTF-16 encoded):
- Line 1: Name
- Lines 2-7: Year, Month, Day, Hour, Minute, Second
- Line 8: Gender (1=Male, 2=Female)
- Lines 9-10: Country, City
- Lines 11-12: Longitude, Latitude (DMS format)
- Line 13: Timezone offset (±HH:MM:SS) - INVERTED sign from UTC!
- Line 14: Time change flag (0=Standard, 1=DST, 2=War time)
- Lines 15+: Notes section (variable), ends with ~end of notes~
- After notes: Muhurtas section, ends with ~end of muhurtas~
- After muhurtas: Secondary residence (8 lines)
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QLabel, QPushButton, QScrollArea, QFrame,
    QMessageBox, QFileDialog, QTextEdit, QGroupBox, QSplitter
)
from PySide6.QtCore import Signal, Slot, Qt
from PySide6.QtGui import QFont

# Theme imports - use dynamic colors for proper light/dark support
from ui.qt_theme import get_theme_colors

# Canonical timezone helpers (SPEC-TZ-001)
from core.time_utils import format_offset, invert_chtk_timezone, resolve_total_offset


def iana_to_chtk_tz(iana_name, year, month, day, hour, minute):
    """Resolve an IANA zone at a local instant to (chtk_tz, dst_flag).

    CHTK field = inverted STANDARD offset (seconds preserved for LMT-era
    instants); dst flag carried separately. std + flag*3600s == total.

    The flag comes from canonical resolve_total_offset so negative-DST
    zones match the other writers (Dublin summer: std +1, flag 0 — raw
    ZoneInfo.dst() would report +1h there and flip both values). The
    offset seconds stay on ZoneInfo because resolve_total_offset (pytz)
    works in whole minutes and would drop LMT-era seconds (Paris 1880
    -00:09:21 rounds to -00:09:00 in pytz). ZoneInfo seconds are kept only
    when the two totals agree to the minute: a bigger gap means a
    fold-overlap divergence (ZoneInfo fold=0 picks the pre-transition
    side, resolve_total_offset picks standard) and mixing the systems
    would break std + flag == total, so the pytz total wins there.
    """
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    std_hours, dst = resolve_total_offset(iana_name, year, month, day, hour, minute)
    total_sec = int(round((std_hours + dst) * 3600))
    try:
        local_dt = _dt(year, month, day, hour, minute, tzinfo=ZoneInfo(iana_name))
        utc_off = local_dt.utcoffset()
        zi_total_sec = int(utc_off.total_seconds()) if utc_off is not None else 0
        if abs(zi_total_sec - total_sec) < 60:
            total_sec = zi_total_sec   # LMT-era seconds precision
    except Exception:
        pass   # zone known to pytz but not zoneinfo: whole-minute total is fine
    std_sec = total_sec - dst * 3600   # STANDARD component, seconds preserved
    chtk_total = -std_sec              # invert for CHTK
    sign_char = '+' if chtk_total >= 0 else '-'
    a = abs(chtk_total)
    h, rem = divmod(a, 3600)
    m, s = divmod(rem, 60)
    return f"{sign_char}{h:02d}:{m:02d}:{s:02d}", dst


# CHTK Birth Data Line descriptions (first 14 lines)
CHTK_BIRTH_DATA_INFO = [
    ("1", "Name", "Person's full name"),
    ("2", "Year", "Birth year (e.g., 1991)"),
    ("3", "Month", "Birth month (1-12)"),
    ("4", "Day", "Birth day (1-31)"),
    ("5", "Hour", "Birth hour (0-23, local time)"),
    ("6", "Minute", "Birth minute (0-59)"),
    ("7", "Second", "Birth second (0-59)"),
    ("8", "Gender", "1 = Male, 2 = Female"),
    ("9", "Country", "Birth country name"),
    ("10", "City", "City name (with ', 0' suffix for non-USA)"),
    ("11", "Longitude", "DMS: DDDEMMʹSS or DDDWMMʹSS"),
    ("12", "Latitude", "DMS: DDNMMʹSS or DDSMMʹSS"),
    ("13", "Timezone", "±HH:MM:SS (INVERTED: +01:00 = UTC-1)"),
    ("14", "DST Flag", "0 = Standard, 1 = DST, 2 = War time"),
]

# Secondary Residence field descriptions
CHTK_RESIDENCE_INFO = [
    ("Identifier", "Residence ID (e.g., 'France, 0' or 'CA1')"),
    ("Country", "Residence country"),
    ("City", "Residence city"),
    ("Longitude", "DMS format"),
    ("Latitude", "DMS format"),
    ("Timezone", "±HH:MM:SS"),
    ("DST Flag", "0 = Standard, 1 = DST"),
    ("Identifier 2", "Same as first identifier"),
]

class EditCHTKSubTab(QWidget):
    """
    Complete CHTK file editor with sections for birth data, notes, muhurtas,
    and secondary residence.

    Signals:
        data_changed(): Emitted when any field changes
        save_requested(): Emitted when Save button clicked
        cancel_requested(): Emitted when Cancel button clicked
    """

    data_changed = Signal()
    save_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent_panel):
        super().__init__()

        self.parent_panel = parent_panel
        self.current_file_path = None
        self._populating = False  # Guard against signal storms during population

        # Storage for line inputs
        self.birth_data_inputs = []  # 14 QLineEdit for birth data
        self.notes_edit = None  # QTextEdit for notes
        self.muhurtas_edit = None  # QTextEdit for muhurtas
        self.residence_inputs = []  # 8 QLineEdit for residence
        self._group_boxes = []  # Store QGroupBox sections for theme refresh

        self._create_ui()
        self._connect_signals()

    def _create_ui(self):
        """Create the CHTK editor UI with collapsible sections"""
        # Get dynamic theme colors
        theme = get_theme_colors()
        bg = theme['secondary_dark']
        surface = theme['secondary']
        text_color = theme['secondary_text']
        border_color = theme['secondary_dark']
        primary_color = theme['primary']

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {bg}; }}")
        self._scroll = scroll

        content = QWidget()
        content.setStyleSheet(f"background: {bg};")
        self._content = content
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(15)
        content_layout.setContentsMargins(20, 20, 20, 20)

        # === Title ===
        self._title_label = QLabel("Complete CHTK File Editor")
        self._title_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: bold;
            color: {text_color};
            padding: 10px 0;
        """)
        content_layout.addWidget(self._title_label)

        # === Info Box ===
        info_frame = self._create_section_frame(
            "CHTK Format",
            "CHTK files contain birth data, notes, muhurtas, and secondary residence.\n"
            "⚠️ Timezone uses INVERTED sign: +01:00 in CHTK = UTC-1 standard",
            theme
        )
        content_layout.addWidget(info_frame)

        # === Section 1: Birth Data (14 lines) ===
        birth_group = self._create_birth_data_section(theme)
        self._group_boxes.append(birth_group)
        content_layout.addWidget(birth_group)

        # === Section 2: Notes ===
        notes_group = self._create_notes_section(theme)
        self._group_boxes.append(notes_group)
        content_layout.addWidget(notes_group)

        # === Section 3: Muhurtas ===
        muhurtas_group = self._create_muhurtas_section(theme)
        self._group_boxes.append(muhurtas_group)
        content_layout.addWidget(muhurtas_group)

        # === Section 4: Secondary Residence ===
        residence_group = self._create_residence_section(theme)
        self._group_boxes.append(residence_group)
        content_layout.addWidget(residence_group)

        # === File Info ===
        self.file_label = QLabel("No file loaded")
        self.file_label.setStyleSheet(f"""
            color: {text_color};
            font-style: italic;
            padding: 10px 0;
            opacity: 0.7;
        """)
        content_layout.addWidget(self.file_label)

        # === Action Buttons ===
        button_layout = self._create_buttons(theme)
        content_layout.addLayout(button_layout)
        content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _create_section_frame(self, title: str, description: str, theme: dict) -> QFrame:
        """Create a styled info frame"""
        frame = QFrame()
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        layout = QVBoxLayout(frame)

        title_label = QLabel(f"<b>{title}</b>")
        title_label.setStyleSheet(f"color: {theme['secondary_text']}; border: none;")
        layout.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setStyleSheet(f"color: {theme['secondary_text']}; border: none; opacity: 0.8;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        return frame

    def _create_birth_data_section(self, theme: dict) -> QGroupBox:
        """Create the birth data section (14 fields)"""
        group = QGroupBox("Birth Data (Lines 1-14)")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)

        grid = QGridLayout(group)
        grid.setSpacing(6)
        grid.setColumnStretch(2, 1)

        # Header
        for col, header in enumerate(["Line", "Field", "Value", "Description"]):
            label = QLabel(header)
            label.setStyleSheet(f"""
                font-weight: bold;
                color: {theme['secondary_text']};
                padding: 3px;
                border: none;
                border-bottom: 1px solid {theme['secondary_dark']};
            """)
            grid.addWidget(label, 0, col)

        # Data rows
        for i, (line_num, field_name, description) in enumerate(CHTK_BIRTH_DATA_INFO):
            row = i + 1

            # Line number
            num_label = QLabel(line_num)
            num_label.setStyleSheet(f"color: {theme['secondary_text']}; padding: 3px; border: none; opacity: 0.7;")
            grid.addWidget(num_label, row, 0)

            # Field name
            name_label = QLabel(field_name)
            name_label.setStyleSheet(f"color: {theme['secondary_text']}; font-weight: bold; padding: 3px; border: none;")
            grid.addWidget(name_label, row, 1)

            # Input
            line_input = QLineEdit()
            line_input.setStyleSheet(self._get_input_style(theme))
            line_input.textChanged.connect(lambda: self.data_changed.emit() if not self._populating else None)
            self.birth_data_inputs.append(line_input)
            grid.addWidget(line_input, row, 2)

            # Description
            desc_label = QLabel(description)
            desc_label.setStyleSheet(f"color: {theme['secondary_text']}; font-style: italic; padding: 3px; border: none; opacity: 0.6;")
            grid.addWidget(desc_label, row, 3)

        return group

    def _create_notes_section(self, theme: dict) -> QGroupBox:
        """Create the notes section (variable length)"""
        group = QGroupBox("Notes Section")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)

        layout = QVBoxLayout(group)

        hint = QLabel("Content between line 15 and ~end of notes~ marker")
        hint.setStyleSheet(f"color: {theme['secondary_text']}; opacity: 0.7; border: none;")
        layout.addWidget(hint)

        self.notes_edit = QTextEdit()
        self.notes_edit.setMinimumHeight(150)
        self.notes_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 4px;
                padding: 8px;
                font-family: monospace;
            }}
        """)
        self.notes_edit.textChanged.connect(lambda: self.data_changed.emit() if not self._populating else None)
        layout.addWidget(self.notes_edit)

        return group

    def _create_muhurtas_section(self, theme: dict) -> QGroupBox:
        """Create the muhurtas section"""
        group = QGroupBox("Muhurtas Section")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)

        layout = QVBoxLayout(group)

        hint = QLabel("Content between ~end of notes~ and ~end of muhurtas~ markers")
        hint.setStyleSheet(f"color: {theme['secondary_text']}; opacity: 0.7; border: none;")
        layout.addWidget(hint)

        self.muhurtas_edit = QTextEdit()
        self.muhurtas_edit.setMinimumHeight(100)
        self.muhurtas_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 4px;
                padding: 8px;
                font-family: monospace;
            }}
        """)
        self.muhurtas_edit.textChanged.connect(lambda: self.data_changed.emit() if not self._populating else None)
        layout.addWidget(self.muhurtas_edit)

        return group

    def _create_residence_section(self, theme: dict) -> QGroupBox:
        """Create the secondary residence section (8 fields)"""
        group = QGroupBox("Secondary Residence")
        group.setStyleSheet(f"""
            QGroupBox {{
                font-weight: bold;
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }}
        """)

        grid = QGridLayout(group)
        grid.setSpacing(6)
        grid.setColumnStretch(1, 1)

        # Header
        for col, header in enumerate(["Field", "Value", "Description"]):
            label = QLabel(header)
            label.setStyleSheet(f"""
                font-weight: bold;
                color: {theme['secondary_text']};
                padding: 3px;
                border: none;
                border-bottom: 1px solid {theme['secondary_dark']};
            """)
            grid.addWidget(label, 0, col)

        # Data rows
        for i, (field_name, description) in enumerate(CHTK_RESIDENCE_INFO):
            row = i + 1

            # Field name
            name_label = QLabel(field_name)
            name_label.setStyleSheet(f"color: {theme['secondary_text']}; font-weight: bold; padding: 3px; border: none;")
            grid.addWidget(name_label, row, 0)

            # Input
            line_input = QLineEdit()
            line_input.setStyleSheet(self._get_input_style(theme))
            line_input.textChanged.connect(lambda: self.data_changed.emit() if not self._populating else None)
            self.residence_inputs.append(line_input)
            grid.addWidget(line_input, row, 1)

            # Description
            desc_label = QLabel(description)
            desc_label.setStyleSheet(f"color: {theme['secondary_text']}; font-style: italic; padding: 3px; border: none; opacity: 0.6;")
            grid.addWidget(desc_label, row, 2)

        return group

    def _get_input_style(self, theme: dict) -> str:
        """Get consistent input field style"""
        return f"""
            QLineEdit {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 4px;
                padding: 6px;
                font-family: monospace;
            }}
            QLineEdit:focus {{
                border-color: {theme['primary']};
            }}
        """

    def _create_buttons(self, theme: dict) -> QHBoxLayout:
        """Create action buttons"""
        primary_color = theme['primary']
        surface = theme['secondary']
        text_color = theme['secondary_text']
        border_color = theme['secondary_dark']
        hover_color = theme['secondary_light']

        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)

        self.save_file_btn = QPushButton("Save to File")
        self.save_file_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary_color};
                color: white;
                padding: 12px 25px;
                border: none;
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)

        self.save_btn = QPushButton("Apply Changes")
        self.save_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {primary_color};
                color: white;
                padding: 12px 25px;
                border: none;
                border-radius: 6px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
        """)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {surface};
                color: {text_color};
                padding: 12px 25px;
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
        """)

        self.load_btn = QPushButton("Load File...")
        self.load_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {surface};
                color: {text_color};
                padding: 12px 25px;
                border: 1px solid {border_color};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
        """)

        button_layout.addWidget(self.save_file_btn)
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.load_btn)

        return button_layout

    def _connect_signals(self):
        """Wire up signal connections"""
        self.save_btn.clicked.connect(self.save_requested.emit)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.save_file_btn.clicked.connect(self._save_to_file)
        self.load_btn.clicked.connect(self._load_file_dialog)

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================

    def load_from_file(self, file_path: str):
        """
        Load CHTK file content into the editor, parsing all sections.

        Args:
            file_path: Path to the CHTK file
        """
        try:
            # Try UTF-16 first (standard CHTK encoding)
            try:
                with open(file_path, 'r', encoding='utf-16') as f:
                    lines = f.read().splitlines()
            except UnicodeDecodeError:
                # Fall back to UTF-8
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = f.read().splitlines()

            # Parse the file into sections
            self._parse_and_populate(lines)

            self.current_file_path = file_path
            self.file_label.setText(f"File: {file_path}")

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load file: {e}")

    def _parse_and_populate(self, lines: list):
        """Parse CHTK lines and populate all sections"""
        self._populating = True
        try:
            self._parse_and_populate_inner(lines)
        finally:
            self._populating = False

    def _parse_and_populate_inner(self, lines: list):
        """Inner population logic (called with _populating=True)."""
        # Find section markers
        end_notes_idx = None
        end_muhurtas_idx = None

        for i, line in enumerate(lines):
            if '~end of notes~' in line:
                end_notes_idx = i
            elif '~end of muhurtas~' in line:
                end_muhurtas_idx = i

        # === Section 1: Birth Data (first 14 lines) ===
        for i, input_widget in enumerate(self.birth_data_inputs):
            if i < len(lines):
                input_widget.setText(lines[i])
            else:
                input_widget.setText("")

        # === Section 2: Notes (lines 15 to ~end of notes~) ===
        if end_notes_idx is not None and end_notes_idx > 14:
            notes_lines = lines[14:end_notes_idx]
            self.notes_edit.setPlainText('\n'.join(notes_lines))
        else:
            self.notes_edit.setPlainText("")

        # === Section 3: Muhurtas (after notes to ~end of muhurtas~) ===
        if end_notes_idx is not None and end_muhurtas_idx is not None:
            muhurtas_start = end_notes_idx + 1
            muhurtas_lines = lines[muhurtas_start:end_muhurtas_idx]
            self.muhurtas_edit.setPlainText('\n'.join(muhurtas_lines))
        else:
            self.muhurtas_edit.setPlainText("")

        # === Section 4: Secondary Residence (after ~end of muhurtas~) ===
        if end_muhurtas_idx is not None:
            residence_start = end_muhurtas_idx + 1
            for i, input_widget in enumerate(self.residence_inputs):
                line_idx = residence_start + i
                if line_idx < len(lines):
                    input_widget.setText(lines[line_idx])
                else:
                    input_widget.setText("")
        else:
            # No residence data found
            for input_widget in self.residence_inputs:
                input_widget.setText("")

    def _load_file_dialog(self):
        """Open file dialog to load a CHTK file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open CHTK File",
            "",
            "CHTK Files (*.chtk);;All Files (*)"
        )
        if file_path:
            self.load_from_file(file_path)

    def _save_to_file(self):
        """Save current content to CHTK file"""
        if not self.current_file_path:
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save CHTK File",
                "",
                "CHTK Files (*.chtk);;All Files (*)"
            )
            if not file_path:
                return
            self.current_file_path = file_path

        try:
            content = self._build_chtk_content()

            # Save as UTF-16-LE with explicit BOM and CRLF (Kala standard)
            with open(self.current_file_path, 'w', encoding='utf-16-le', newline='') as f:
                f.write('\ufeff')  # Explicit BOM
                f.write(content.replace('\n', '\r\n'))

            self.file_label.setText(f"File: {self.current_file_path} (saved)")
            QMessageBox.information(self, "Success", "CHTK file saved successfully!")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file: {e}")

    def _build_chtk_content(self) -> str:
        """Build complete CHTK file content from all sections"""
        lines = []

        # Birth data (14 lines)
        for input_widget in self.birth_data_inputs:
            lines.append(input_widget.text())

        # Notes section
        notes_text = self.notes_edit.toPlainText()
        if notes_text.strip():
            lines.extend(notes_text.split('\n'))
        else:
            lines.append(' ')  # Empty placeholder
        lines.append('~end of notes~')

        # Muhurtas section
        muhurtas_text = self.muhurtas_edit.toPlainText()
        if muhurtas_text.strip():
            lines.extend(muhurtas_text.split('\n'))
        else:
            lines.append(' ')  # Empty placeholder (same pattern as notes)
        lines.append('~end of muhurtas~')

        # Secondary residence (8 lines)
        for input_widget in self.residence_inputs:
            lines.append(input_widget.text())

        return '\n'.join(lines)

    # =========================================================================
    # DATA ACCESS
    # =========================================================================

    def get_chtk_lines(self) -> list:
        """
        Get current content as list of all lines.

        Returns:
            List of strings (line contents)
        """
        return self._build_chtk_content().split('\n')

    def set_chtk_lines(self, lines: list):
        """
        Set all line contents.

        Args:
            lines: List of strings
        """
        self._parse_and_populate(lines)

    def populate_from_metadata(self, birth_metadata: dict):
        """
        Generate CHTK content from birth metadata.

        Args:
            birth_metadata: Dict with birth information
        """
        lines = self._metadata_to_chtk_lines(birth_metadata)
        self._parse_and_populate(lines)
        self.file_label.setText("Generated from chart data (not saved)")

    def populate_from_birth_data(self, birth_data: dict):
        """
        Generate CHTK content from canonical birth_data (Single Source of Truth).

        Args:
            birth_data: Canonical birth_data dict from BirthDataManager
        """
        if not birth_data:
            return

        # Convert birth_data to CHTK lines
        lines = self._birth_data_to_chtk_lines(birth_data)
        self._parse_and_populate(lines)
        self.file_label.setText("Generated from canonical birth data (not saved)")

    def _birth_data_to_chtk_lines(self, birth_data: dict) -> list:
        """Convert canonical birth_data to CHTK lines."""
        # Format coordinates to DMS
        lat = birth_data.get('latitude', 0)
        lon = birth_data.get('longitude', 0)
        lat_dms = self._decimal_to_dms(lat, is_latitude=True)
        lon_dms = self._decimal_to_dms(lon, is_latitude=False)

        # Gender (1=Male, 2=Female per CHTK spec)
        gender = birth_data.get('gender', '')
        if str(gender).lower() in ('male', 'm', '1'):
            gender_code = '1'
        elif str(gender).lower() in ('female', 'f', '2'):
            gender_code = '2'
        else:
            gender_code = ''

        # City (add ', 0' suffix for non-USA)
        city = birth_data.get('city', '')
        country = birth_data.get('country', '')
        if country.lower() not in ('usa', 'united states', 'us'):
            # Only add ', 0' if not already present
            if city and not city.endswith(', 0'):
                city = f"{city}, 0"

        # Timezone - use chtk_timezone if available, else convert offset
        chtk_tz = birth_data.get('chtk_timezone', '')
        if not chtk_tz:
            # Convert UTC offset to RAW CHTK (inverted sign): UTC+5 = CHTK
            # "-05:00:00". NOTE: utc_offset_hours is TOTAL (std + flag), so
            # this rarely-hit fallback can bake DST into the field, the same
            # td-q9bw double-count family as the IANA branch below. Behavior
            # preserved from before the sweep.
            offset = birth_data.get('utc_offset_hours', 0)
            # int() truncation toward zero on total minutes replicates the old
            # per-field int() math, EXCEPT for 0 < offset < 1h where the old
            # code lost the inversion (UTC+00:30 wrongly emitted '+00:30:00',
            # which readers re-invert to UTC-00:30). format_offset on signed
            # total minutes fixes that sign bug.
            tm = int(-offset * 60)
            sign = 1 if tm >= 0 else -1
            chtk_tz = format_offset(sign * (abs(tm) // 60), sign * (abs(tm) % 60)) + ":00"

        # DST flag
        dst = birth_data.get('time_change_flag', 0)

        lines = [
            birth_data.get('name', ''),
            str(birth_data.get('local_year', '')),
            str(birth_data.get('local_month', '')),
            str(birth_data.get('local_day', '')),
            str(birth_data.get('local_hour', '')),
            str(birth_data.get('local_minute', '')),
            str(birth_data.get('local_second', 0)),
            gender_code,
            country,
            city,
            lon_dms,
            lat_dms,
            chtk_tz,
            str(dst),
            ' ',  # Notes placeholder
            '~end of notes~',
            '~end of muhurtas~',
        ]
        return lines

    def sync_from_form_data(self, form_data: dict):
        """
        Update CHTK fields from form data (Edit Info tab).

        Args:
            form_data: Dict with form field values
        """
        lines = self._form_data_to_chtk_lines(form_data)
        # Only update birth data, preserve notes/muhurtas/residence
        for i, input_widget in enumerate(self.birth_data_inputs):
            if i < len(lines):
                input_widget.setText(str(lines[i]))

    def _metadata_to_chtk_lines(self, meta: dict) -> list:
        """Convert birth metadata to complete 28-line CHTK content."""
        location = meta.get('location', {})

        # Format coordinates to DMS
        lat = meta.get('latitude', 0)
        lon = meta.get('longitude', 0)
        lat_dms = self._decimal_to_dms(lat, is_latitude=True)
        lon_dms = self._decimal_to_dms(lon, is_latitude=False)

        # Gender (1=Male, 2=Female per CHTK spec)
        gender = meta.get('gender', '')
        if str(gender).lower() in ('male', 'm', '1'):
            gender_code = '1'
        elif str(gender).lower() in ('female', 'f', '2'):
            gender_code = '2'
        else:
            gender_code = ''

        # City (add ', 0' suffix for non-USA)
        city = location.get('city', '') or meta.get('city', '')
        country = location.get('country', '') or meta.get('country', '')
        is_usa = country.lower() in ('usa', 'united states', 'us')
        if not is_usa:
            city = f"{city}, 0" if city else ", 0"

        # Timezone, handle IANA names (e.g. "Asia/Tehran") before inverting.
        # KNOWN falsy-zero `or` chains below, kept as-is (do not replicate in
        # new code; use `is not None` checks instead).
        tz = location.get('timezone', '+00:00') or meta.get('timezone', '+00:00')
        dst = meta.get('dst', 0) or meta.get('time_change_flag', 0)

        if '/' in str(tz) or str(tz) == 'UTC':
            # IANA timezone name — resolve to inverted STANDARD offset and
            # carry the DST flag separately (decompose-from-total).
            try:
                year = int(meta.get('year', 2000))
                month = int(meta.get('month', 1))
                day = int(meta.get('day', 1))
                hour = int(meta.get('hour', 0))
                minute = int(meta.get('minute', 0))
                # CHTK field = inverted STANDARD offset, seconds PRESERVED for
                # LMT-era dates (e.g. Paris pre-1891 -00:09:21); the dst flag is
                # set from the DST component, so std + flag == total (no
                # double-count when readers re-add the flag).
                chtk_tz, auto_dst = iana_to_chtk_tz(str(tz), year, month, day, hour, minute)
                # Preserve user-asserted war time: resolve_total_offset never
                # returns flag 2, so the auto flag would silently downgrade it.
                dst = dst if dst == 2 else auto_dst
            except Exception:
                print(f"[TZ-CHECK] edit_chtk: IANA timezone '{tz}' failed to "
                      f"resolve; falling back to UTC (CHTK '-00:00:00')")
                chtk_tz = self._invert_timezone('+00:00')
        else:
            chtk_tz = self._invert_timezone(tz)

        # Residence identifier (just country for non-USA, state+1 for USA)
        if is_usa:
            city_parts = city.split(',') if city else []
            if len(city_parts) > 1:
                residence_id = city_parts[-1].strip() + '1'
            else:
                residence_id = 'USA1'
        else:
            residence_id = country if country else 'Unknown'

        # Line 27 uses "country, 0" for non-USA
        residence_id_27 = residence_id if is_usa else (
            f"{country}, 0" if country else ", 0"
        )

        lines = [
            meta.get('name', ''),          # Line 1
            str(meta.get('year', '')),      # Line 2
            str(meta.get('month', '')),     # Line 3
            str(meta.get('day', '')),       # Line 4
            str(meta.get('hour', '')),      # Line 5
            str(meta.get('minute', '')),    # Line 6
            str(meta.get('second', '')),    # Line 7
            gender_code,                    # Line 8
            country,                        # Line 9
            city,                           # Line 10
            lon_dms,                        # Line 11
            lat_dms,                        # Line 12
            chtk_tz,                        # Line 13
            str(dst),                       # Line 14
            ' ',                            # Line 15: Notes placeholder
            '~end of notes~',              # Line 16
            ' ',                            # Line 17: Muhurtas placeholder
            '~end of muhurtas~',           # Line 18
            '0',                            # Line 19: Separator
            residence_id,                   # Line 20
            country,                        # Line 21
            city,                           # Line 22
            lon_dms,                        # Line 23
            lat_dms,                        # Line 24
            chtk_tz,                        # Line 25
            str(dst),                       # Line 26
            residence_id_27,                # Line 27
            '',                             # Line 28: Empty end line
        ]
        return lines

    def _form_data_to_chtk_lines(self, data: dict) -> list:
        """Convert form data to CHTK lines"""
        # Format coordinates to DMS
        lat = data.get('latitude', 0)
        lon = data.get('longitude', 0)
        lat_dms = self._decimal_to_dms(lat, is_latitude=True)
        lon_dms = self._decimal_to_dms(lon, is_latitude=False)

        # Gender (1=Male, 2=Female per CHTK spec)
        gender = data.get('gender', '')
        if str(gender).lower() == 'male':
            gender_code = '1'
        elif str(gender).lower() == 'female':
            gender_code = '2'
        else:
            gender_code = ''

        # City (add ', 0' suffix for non-USA)
        city = data.get('city', '')
        country = data.get('country', '')
        if country.lower() not in ('usa', 'united states', 'us'):
            city = f"{city}, 0" if city else ", 0"

        # Timezone (invert for CHTK format)
        tz = data.get('timezone', '+00:00')
        chtk_tz = self._invert_timezone(tz)

        lines = [
            data.get('name', ''),
            str(data.get('year', '')),
            str(data.get('month', '')),
            str(data.get('day', '')),
            str(data.get('hour', '')),
            str(data.get('minute', '')),
            str(data.get('second', '')),
            gender_code,
            country,
            city,
            lon_dms,
            lat_dms,
            chtk_tz,
            str(data.get('dst', 0)),
        ]
        return lines

    def _decimal_to_dms(self, decimal: float, is_latitude: bool) -> str:
        """Convert decimal degrees to DMS format for CHTK."""
        try:
            decimal = float(decimal)
        except (ValueError, TypeError):
            return "00N00'00" if is_latitude else "000E00'00"

        if decimal >= 0:
            direction = 'N' if is_latitude else 'E'
        else:
            direction = 'S' if is_latitude else 'W'
            decimal = abs(decimal)

        degrees = int(decimal)
        minutes = int((decimal - degrees) * 60)
        seconds = int(((decimal - degrees) * 60 - minutes) * 60)

        if is_latitude:
            return f"{degrees:02d}{direction}{minutes:02d}'{seconds:02d}"
        else:
            return f"{degrees:03d}{direction}{minutes:02d}'{seconds:02d}"

    def _invert_timezone(self, tz: str) -> str:
        """Invert timezone sign for CHTK format (delegates to core.time_utils).

        Input convention: STANDARD offset string; output is RAW CHTK (inverted
        sign, HH:MM:SS). Canonical unsigned semantics (td-8rew): an unsigned
        input is a POSITIVE standard offset and maps to a NEGATIVE CHTK value.
        The old body returned '+' for unsigned input, which CHTK readers
        re-invert to a negative standard offset (silent corruption).
        """
        tz = str(tz).strip()
        if not tz:
            return "+00:00:00"

        inverted = invert_chtk_timezone(tz)
        # Pad to HH:MM:SS (invert_chtk_timezone preserves the input's format)
        parts = inverted[1:].split(':')
        while len(parts) < 3:
            parts.append('00')
        return inverted[0] + ':'.join(parts)

    # =========================================================================
    # THEME SUPPORT
    # =========================================================================

    def refresh_theme(self):
        """Update colors after theme change - re-apply all dynamic styles"""
        theme = get_theme_colors()
        bg = theme['secondary_dark']

        # Update scroll area and content backgrounds
        if hasattr(self, '_scroll'):
            self._scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {bg}; }}")
        if hasattr(self, '_content'):
            self._content.setStyleSheet(f"background: {bg};")

        # Re-style title label
        if hasattr(self, '_title_label'):
            self._title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {theme['secondary_text']}; padding: 10px 0;")

        # Re-style QGroupBox sections
        group_style = f"""
            QGroupBox {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 8px;
                margin-top: 10px;
                padding: 15px 10px 10px 10px;
                font-weight: bold;
                color: {theme['secondary_text']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px;
                color: {theme['primary']};
            }}
        """
        for group in getattr(self, '_group_boxes', []):
            group.setStyleSheet(group_style)

        # Re-style birth data inputs
        input_style = self._get_input_style(theme)
        for line_input in self.birth_data_inputs:
            line_input.setStyleSheet(input_style)

        # Re-style residence inputs
        for line_input in self.residence_inputs:
            line_input.setStyleSheet(input_style)

        # Re-style text edits
        text_edit_style = f"""
            QTextEdit {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_dark']};
                border-radius: 4px;
                padding: 8px;
                font-family: monospace;
            }}
        """
        if self.notes_edit:
            self.notes_edit.setStyleSheet(text_edit_style)
        if self.muhurtas_edit:
            self.muhurtas_edit.setStyleSheet(text_edit_style)
