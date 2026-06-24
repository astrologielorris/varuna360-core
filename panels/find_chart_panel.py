#!/usr/bin/env python3
"""
Find Chart Panel - Search CHTK database with multi-folder support
Migrated from ui/chart_search_tab.py (CustomTkinter → PySide6/Qt6)

Features:
- Multi-folder management (3+ expandable paths with checkboxes)
- 13 planetary position filters (Asc through Pluto)
- Text search with debouncing (150ms)
- Sorting and grouping by multiple criteria
- Results table with 8 columns
- Index caching with progress display
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QCheckBox,
    QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QAbstractItemView,
    QApplication, QMenu, QMessageBox
)
from PySide6.QtCore import Signal, QTimer, Qt, QThread
from PySide6.QtGui import QFont, QColor
import os
import json
import platform
import re

from cache.chart_index_cache import ChartIndexCache

from ui.qt_theme import (
    get_theme_colors, get_primary_button_style,
    get_secondary_button_style, STATUS,
    FONT_PRIMARY,
    scaled_area_px, scaled_area_size, scaled_area_font
)




class IndexBuildWorker(QThread):
    """Background worker to build the chart index without blocking the GUI."""
    finished = Signal(int)        # chart count
    progress = Signal(int, int, str, bool, dict)  # current, total, filepath, is_cached, stats
    error = Signal(str)

    def __init__(self, cache, folder_paths):
        super().__init__()
        self.cache = cache
        self.folder_paths = folder_paths

    def run(self):
        try:
            def _progress_callback(current, total, filepath, is_cached, stats):
                self.progress.emit(current, total, filepath, is_cached, stats)

            self.cache.build_index(self.folder_paths, progress_callback=_progress_callback)
            self.finished.emit(len(self.cache.index))
        except Exception as e:
            import traceback
            self.error.emit(f"{e}\n\n{traceback.format_exc()}")


class WebDownloadWorker(QThread):
    """Background worker to download birth data from the web and create a CHTK file."""
    finished = Signal(object)  # dict with birth_data + chtk_path, or None
    status = Signal(str)       # progress messages

    def __init__(self, name, source, output_dir):
        super().__init__()
        self.name = name
        self.source = source
        self.output_dir = output_dir

    def run(self):
        try:
            from browser_tools.web_birth_data import extract_birth_data
            from core.chtk_writer import create_chtk_from_web_data
            from pathlib import Path

            self.status.emit(f"Searching {self.source}...")
            birth_data = extract_birth_data(self.name, source=self.source, verbose=False)
            if not birth_data:
                self.finished.emit(None)
                return

            self.status.emit("Found! Creating chart file...")
            chtk_path = create_chtk_from_web_data(birth_data, Path(self.output_dir), verbose=False)
            if chtk_path:
                self.finished.emit({"birth_data": birth_data, "chtk_path": str(chtk_path)})
            else:
                self.finished.emit(None)
        except Exception as e:
            self.status.emit(f"Error: {e}")
            self.finished.emit(None)


class ChartSortWorker(QThread):
    """Background worker to categorize unsorted charts via DeepSeek API."""
    finished = Signal(list)    # list of {"name", "folder", "moved": bool}
    status = Signal(str)
    error = Signal(str)

    def __init__(self, unsorted_dir, database_path, api_key):
        super().__init__()
        self.unsorted_dir = unsorted_dir
        self.database_path = database_path
        self.api_key = api_key

    def run(self):
        try:
            self._do_sort()
        except Exception as e:
            self.error.emit(f"Sort failed: {e}")

    def _do_sort(self):
        import shutil
        import requests as req
        from pathlib import Path

        unsorted = Path(self.unsorted_dir)
        chtk_files = list(unsorted.glob("*.chtk"))
        if not chtk_files:
            self.error.emit("No unsorted charts found")
            return

        # 1. Read chart names from CHTK files (line 1 = name, UTF-16-LE)
        chart_info = []
        for f in chtk_files:
            try:
                content = f.read_bytes().decode('utf-16-le', errors='ignore')
                name = content.split('\n')[0].strip().strip('\ufeff')
                chart_info.append({"name": name, "file": str(f), "filename": f.name})
            except Exception:
                chart_info.append({"name": f.stem, "file": str(f), "filename": f.name})

        self.status.emit(f"Read {len(chart_info)} chart names, calling DeepSeek...")

        # 2. Get available category folders
        db_path = Path(self.database_path)
        categories = sorted([
            d.name for d in db_path.iterdir()
            if d.is_dir() and d.name != "celebrity_unsorted"
        ])

        # 3. Call DeepSeek API
        prompt = (
            "Categorize each person into the most appropriate folder from the list.\n"
            f"Available folders: {categories}\n"
            f"People to categorize (name | filename):\n"
            + "\n".join(f"- {c['name']} | {c['filename']}" for c in chart_info)
            + "\n\nReturn ONLY a JSON array like: "
            '[{"filename": "file.chtk", "folder": "Folder Name", "guess": "reason"}]\n'
            "IMPORTANT: use the 'filename' field (not 'name') as the unique key.\n\n"
            "Rules:\n"
            "- Use ONLY folders from the list above when you can identify the person.\n"
            "- If the name looks like a personal/family chart (e.g. 'mother', 'dad', "
            "first name only, nicknames), use folder: \"Personal\"\n"
            "- If you cannot identify the person OR the name is ambiguous/abbreviated, "
            "use folder: \"Unclassified\" and put your best guess in the 'guess' field.\n"
            "- The 'guess' field should briefly explain your reasoning "
            "(e.g. \"unknown person\", \"possibly a YouTuber\", \"personal chart\")."
        )

        try:
            resp = req.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 1.0,
                    "response_format": {"type": "json_object"}
                },
                timeout=60
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if not content or not content.strip():
                self.error.emit("DeepSeek returned empty response (known API quirk), try again")
                return

            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(content)
            assignments = parsed if isinstance(parsed, list) else parsed.get("assignments", parsed.get("results", []))
        except Exception as e:
            self.error.emit(f"DeepSeek API error: {e}")
            return

        if not isinstance(assignments, list):
            self.error.emit(f"DeepSeek returned unexpected format: {type(assignments).__name__}")
            return

        # 4. Move files to assigned folders (with safety checks)
        self.status.emit("Moving files to category folders...")
        results = []
        # Map by filename (unique) for reliable matching
        filename_to_file = {c["filename"]: c["file"] for c in chart_info}
        name_to_file = {c["name"]: c["file"] for c in chart_info}

        # Security: whitelist of allowed folder names (existing + safe defaults)
        allowed_folders = set(categories) | {"Personal", "Unclassified", "Miscellaneous"}
        db_resolved = db_path.resolve()

        # Write sort log BEFORE moving (enables undo/recovery)
        sort_log_path = unsorted / "sort_log.json"
        try:
            existing_log = json.loads(sort_log_path.read_text()) if sort_log_path.exists() else []
        except Exception:
            existing_log = []
        log_entry = {
            "timestamp": __import__('datetime').datetime.now().isoformat(),
            "assignments": assignments,
            "source_files": {c["filename"]: c["file"] for c in chart_info}
        }
        existing_log.append(log_entry)
        try:
            sort_log_path.write_text(json.dumps(existing_log, indent=2))
        except Exception:
            pass  # Non-critical — don't block sorting if log fails

        for item in assignments:
            if not isinstance(item, dict):
                continue
            item_filename = str(item.get("filename", "")).strip()
            person_name = str(item.get("name", "")).strip()
            folder_name = str(item.get("folder", "Miscellaneous")).strip()
            if not folder_name:
                folder_name = "Miscellaneous"

            # SECURITY: reject any folder name not in the whitelist
            if folder_name not in allowed_folders:
                folder_name = "Unclassified"

            # Primary: match by filename (unique, reliable)
            src_path_str = filename_to_file.get(item_filename)

            # Fallback: match by name
            if not src_path_str:
                src_path_str = name_to_file.get(person_name)

            # Last resort: fuzzy match by name substring
            if not src_path_str and len(person_name) > 2:
                for cn, cf in name_to_file.items():
                    if person_name.lower() in cn.lower() or cn.lower() in person_name.lower():
                        src_path_str = cf
                        break

            if not src_path_str:
                results.append({"name": person_name or item_filename, "folder": folder_name, "moved": False})
                continue

            src_path = Path(src_path_str)

            try:
                # SECURITY: resolve path and verify it stays inside database
                dst_dir = (db_path / folder_name).resolve()
                if not dst_dir.is_relative_to(db_resolved):
                    raise ValueError(f"Path escapes database: {dst_dir}")

                dst_dir.mkdir(exist_ok=True)
                dst_path = dst_dir / src_path.name

                # SECURITY: refuse to overwrite existing files
                if dst_path.exists():
                    results.append({"name": person_name, "folder": folder_name,
                                    "moved": False, "error": "destination exists"})
                    continue

                shutil.move(str(src_path), str(dst_path))
                results.append({"name": person_name, "folder": folder_name, "moved": True})
            except Exception as e:
                results.append({"name": person_name, "folder": folder_name,
                                "moved": False, "error": str(e)})

        self.finished.emit(results)



class FindChartPanel(QWidget):
    """Find Chart tab - search CHTK database with multi-folder support."""

    chart_selected = Signal(str)  # Emitted when chart is double-clicked (filepath)

    def __init__(self, gui):
        super().__init__()
        self.gui = gui
        self.cache = None  # Lazy init - created in _build_index_async() to avoid slow startup

        # State tracking
        self.folder_entries = []       # List of QLineEdit widgets
        self.folder_checkboxes = []    # List of QCheckBox widgets
        self.folder_frames = []        # List of QWidget frames
        self.folder_containers = []    # List of container widgets
        self.planet_filters = {}       # planet_key -> QComboBox
        self.planet_labels = {}        # planet_key -> QLabel (for styling)
        self.being_filters = {}        # planet_being_key -> QComboBox
        self.being_labels = {}         # planet_being_key -> QLabel
        self.tree_filepath_map = {}    # row_index -> filepath
        self.sort_reverse = False      # Toggle for ascending/descending

        # Search debouncing
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(150)  # 150ms debounce
        self.search_timer.timeout.connect(self._refresh_results)

        # Rebuild lock - prevents re-entrant _refresh_results during build_index
        self._rebuilding = False

        # Worker thread state
        self._web_worker = None
        self._sort_worker = None
        self._index_worker = None
        from managers.settings_manager import get_settings
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
        self.results_label = None
        self.index_status = None
        self.results_table = None
        self.add_folder_btn = None
        self.rebuild_btn = None
        self.clear_filters_btn = None
        self.folders_container = None
        self.web_download_widget = None
        self.sort_banner = None
        self.sort_count_label = None
        self.sort_btn = None

        # Build UI
        self._create_ui()

        # Load saved folder paths
        self._load_folder_paths()

        # Connect to aditya mode changes for sign name display refresh
        if hasattr(gui, 'aditya_mode_changed'):
            gui.aditya_mode_changed.connect(self._on_aditya_mode_changed)
        # SPEC-MODE-001: also refresh on a names-only change (zodiac system
        # unchanged, labels flipped). Same lightweight relabel as a mode change.
        if hasattr(gui, 'sign_names_changed'):
            gui.sign_names_changed.connect(self._on_aditya_mode_changed)

        # NOTE: Index building is deferred to core_gui_qt._deferred_init_find_chart()
        # This keeps app startup fast - index builds 2s after UI is ready

    def _create_ui(self):
        """Build the UI - 5 main sections."""
        # Main layout with generous spacing
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 1. Folder Paths Section
        self._create_folder_section(layout)

        # 2. Planetary Filters Section
        self._create_planet_filters_section(layout)

        # 2b. Retinue Being Filters Section
        self._create_retinue_filters_section(layout)

        # 3. Search Section
        self._create_search_section(layout)

        # 4. Sort/Group Controls
        self._create_controls_section(layout)

        # 5. Results Table
        self._create_results_section(layout)

        # Apply initial theme
        self.refresh_theme()

    @staticmethod
    def _collapsible_header_style(theme):
        """QSS for a collapsible section header bar, built from the live theme.

        Shared by _make_collapsible (build time) and refresh_theme (theme
        switch) so the headers cannot drift out of sync with the active theme.
        """
        return f"""
            QPushButton {{
                background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                border: none;
                border-bottom: 1px solid {theme['secondary_light']};
                text-align: left;
                padding: 4px 8px;
                font-size: {scaled_area_px('panel_titles')}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {theme['secondary_light']};
            }}
        """

    def _make_collapsible(self, title, parent_layout, collapsed=False):
        """Create a collapsible section with a clickable header bar.

        Returns the content QWidget to populate with child widgets.
        """
        theme = get_theme_colors()

        # Header button with arrow indicator
        header_btn = QPushButton(f"{'▶' if collapsed else '▼'}  {title}")
        header_btn.setStyleSheet(self._collapsible_header_style(theme))
        header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        parent_layout.addWidget(header_btn)

        # header_btn is a local; refresh_theme() can't reach it otherwise, which
        # is why these headers stayed dark on theme switch (td-2pm6).
        if not hasattr(self, "_collapsible_headers"):
            self._collapsible_headers = []
        self._collapsible_headers.append(header_btn)

        content = QWidget()
        parent_layout.addWidget(content)

        def toggle():
            visible = not content.isVisible()
            content.setVisible(visible)
            header_btn.setText(f"{'▼' if visible else '▶'}  {title}")

        header_btn.clicked.connect(toggle)
        if collapsed:
            content.hide()

        return content

    def _create_folder_section(self, parent_layout):
        """Create folder paths section (collapsible, collapsed by default)."""
        theme = get_theme_colors()

        # Collapsible header + content
        folder_content = self._make_collapsible("Folder Paths", parent_layout, collapsed=True)
        folder_layout = QVBoxLayout(folder_content)
        folder_layout.setSpacing(8)
        folder_layout.setContentsMargins(10, 5, 10, 5)

        # Container for dynamic folder entries
        self.folders_container = QWidget()
        folders_container_layout = QVBoxLayout(self.folders_container)
        folders_container_layout.setContentsMargins(0, 0, 0, 0)
        folders_container_layout.setSpacing(5)
        folder_layout.addWidget(self.folders_container)

        # Add initial 3 folder entries
        for i in range(3):
            self._add_folder_entry()

        # Bottom button row
        btn_row = QWidget()
        btn_row_layout = QHBoxLayout(btn_row)
        btn_row_layout.setContentsMargins(0, 10, 0, 0)
        btn_row_layout.setSpacing(10)

        # Add Folder button (left) - hidden, fixed at 3 folder slots
        self.add_folder_btn = QPushButton("+ Add Folder")
        self.add_folder_btn.setFont(scaled_area_font('buttons'))
        self.add_folder_btn.setMinimumHeight(32)
        self.add_folder_btn.clicked.connect(self._add_folder_entry)
        self.add_folder_btn.setVisible(False)
        btn_row_layout.addWidget(self.add_folder_btn)

        # Index status label (center)
        self.index_status = QLabel("")
        self.index_status.setFont(scaled_area_font('status'))
        self.index_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_row_layout.addWidget(self.index_status, 1)  # Stretch

        # Rebuild Index button (right, green)
        self.rebuild_btn = QPushButton("Rebuild Index")
        self.rebuild_btn.setFont(scaled_area_font('buttons', bold=True))
        self.rebuild_btn.setMinimumHeight(32)
        self.rebuild_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #27AE60;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: #229954;
            }}
            QPushButton:pressed {{
                background-color: #1E8449;
            }}
        """)
        self.rebuild_btn.clicked.connect(self._rebuild_index)
        self.rebuild_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.rebuild_btn.customContextMenuRequested.connect(self._show_rebuild_context_menu)
        btn_row_layout.addWidget(self.rebuild_btn)

        folder_layout.addWidget(btn_row)

    def _add_folder_entry(self):
        """Add a new folder path entry (checkbox, label, entry, browse, remove)."""
        theme = get_theme_colors()
        idx = len(self.folder_entries)

        # Container for this folder entry
        entry_widget = QWidget()
        entry_layout = QHBoxLayout(entry_widget)
        entry_layout.setContentsMargins(0, 0, 0, 0)
        entry_layout.setSpacing(5)

        # Checkbox (checked by default)
        checkbox = QCheckBox()
        checkbox.setChecked(True)
        checkbox.setFixedSize(24, 24)
        checkbox.stateChanged.connect(self._refresh_results)
        entry_layout.addWidget(checkbox)

        # Label
        label = QLabel(f"Path {idx + 1}:")
        label.setFont(scaled_area_font('buttons'))
        label.setFixedWidth(50)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        entry_layout.addWidget(label)

        # Entry field
        line_edit = QLineEdit()
        line_edit.setFont(scaled_area_font('tables'))
        line_edit.setMinimumHeight(28)
        line_edit.setPlaceholderText("Browse for folder...")
        entry_layout.addWidget(line_edit, 1)  # Stretch

        # Browse button (blue)
        browse_btn = QPushButton("Browse")
        browse_btn.setFont(scaled_area_font('buttons'))
        browse_btn.setMinimumHeight(28)
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(lambda: self._browse_folder(line_edit))
        entry_layout.addWidget(browse_btn)

        # Remove button (red, only for entries 4+)
        if idx >= 3:
            remove_btn = QPushButton("✕")
            remove_btn.setFont(scaled_area_font('buttons', bold=True))
            remove_btn.setFixedSize(28, 28)
            remove_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {STATUS['error']};
                    color: white;
                    border: none;
                    border-radius: 14px;
                }}
                QPushButton:hover {{
                    background-color: #CC0000;
                }}
            """)
            remove_btn.clicked.connect(lambda: self._remove_folder_entry(entry_widget, line_edit, checkbox))
            entry_layout.addWidget(remove_btn)

        # Store references
        self.folder_entries.append(line_edit)
        self.folder_checkboxes.append(checkbox)
        self.folder_frames.append(entry_widget)
        self.folder_containers.append(entry_widget)

        # Add to container layout
        self.folders_container.layout().addWidget(entry_widget)

    def _remove_folder_entry(self, frame, entry, checkbox):
        """Remove a folder entry."""
        if entry in self.folder_entries:
            self.folder_entries.remove(entry)
        if checkbox in self.folder_checkboxes:
            self.folder_checkboxes.remove(checkbox)
        if frame in self.folder_frames:
            self.folder_frames.remove(frame)
        if frame in self.folder_containers:
            self.folder_containers.remove(frame)

        frame.deleteLater()
        self._refresh_results()

    def _browse_folder(self, entry_widget):
        """Open folder browser dialog."""
        # Determine initial directory
        current_path = entry_widget.text().strip()
        if current_path and os.path.isdir(current_path):
            initial_dir = current_path
        else:
            # Try to use first configured folder, or home directory
            for e in self.folder_entries:
                path = e.text().strip()
                if path and os.path.isdir(path):
                    initial_dir = path
                    break
            else:
                initial_dir = os.path.expanduser("~")

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select CHTK Folder",
            initial_dir,
            QFileDialog.Option.ShowDirsOnly
        )

        if folder:
            entry_widget.setText(folder)
            self._save_folder_paths()
            self._build_index_async()

    def _create_planet_filters_section(self, parent_layout):
        """Create planetary filter dropdowns section (collapsible)."""
        theme = get_theme_colors()

        # Collapsible header + content
        filter_content = self._make_collapsible("Filter by Planetary Position", parent_layout, collapsed=True)
        filter_layout = QVBoxLayout(filter_content)
        filter_layout.setSpacing(8)
        filter_layout.setContentsMargins(10, 5, 10, 5)

        # Define celestial bodies (13 total)
        celestial_bodies = [
            ('Asc', 'ascendant'),
            ('Sun', 'sun'),
            ('Moon', 'moon'),
            ('Mars', 'mars'),
            ('Mercury', 'mercury'),
            ('Jupiter', 'jupiter'),
            ('Venus', 'venus'),
            ('Saturn', 'saturn'),
            ('Rahu', 'rahu'),
            ('Ketu', 'ketu'),
            ('Uranus', 'uranus'),
            ('Neptune', 'neptune'),
            ('Pluto', 'pluto')
        ]

        from core.retinue_constants import ADITYA_SIGN_ORDER
        self._aditya_signs = ADITYA_SIGN_ORDER

        display_signs = ['(Any)'] + [self._convert_sign_name(s) for s in self._aditya_signs]

        # Create 2 rows of dropdowns (7 per row, then 6 + stretch)
        row1_widget = QWidget()
        row1_layout = QHBoxLayout(row1_widget)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(10)

        row2_widget = QWidget()
        row2_layout = QHBoxLayout(row2_widget)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(10)

        for i, (label_text, planet_key) in enumerate(celestial_bodies):
            # Choose row layout
            if i < 7:
                row_layout = row1_layout
            else:
                row_layout = row2_layout

            # Label
            label = QLabel(f"{label_text}:")
            label.setFont(scaled_area_font('buttons', bold=True))
            label.setFixedWidth(60)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            row_layout.addWidget(label)
            self.planet_labels[planet_key] = label

            # Dropdown
            combo = QComboBox()
            combo.addItems(display_signs)
            combo.setFont(scaled_area_font('buttons'))
            combo.setFixedWidth(100)
            combo.setFixedHeight(24)
            combo.currentTextChanged.connect(lambda val, pk=planet_key: self._on_planet_filter_changed(pk))
            row_layout.addWidget(combo)

            self.planet_filters[planet_key] = combo

        # Add stretch to row2 to fill remaining space
        row2_layout.addStretch(1)

        filter_layout.addWidget(row1_widget)
        filter_layout.addWidget(row2_widget)

        # Clear filters button (red, right-aligned)
        button_row = QWidget()
        button_row_layout = QHBoxLayout(button_row)
        button_row_layout.setContentsMargins(0, 5, 0, 0)
        button_row_layout.addStretch(1)

        self.clear_filters_btn = QPushButton("Clear All Filters")
        self.clear_filters_btn.setFont(scaled_area_font('buttons'))
        self.clear_filters_btn.setMinimumHeight(28)
        self.clear_filters_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {STATUS['error']};
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }}
            QPushButton:hover {{
                background-color: #C0392B;
            }}
        """)
        self.clear_filters_btn.clicked.connect(self._clear_planet_filters)
        button_row_layout.addWidget(self.clear_filters_btn)

        filter_layout.addWidget(button_row)

    def _create_retinue_filters_section(self, parent_layout):
        """Create retinue being filter dropdowns section (collapsible)."""
        from AI_tools.AI_main_function.retinue import (
            ALL_BEING_NAMES, BEING_TYPE_FOR_NAME, BEING_SIGN_DEGREES,
            RETINUE_PLANETS,
        )

        filter_content = self._make_collapsible(
            "Filter by Retinue Being", parent_layout, collapsed=True
        )
        filter_layout = QVBoxLayout(filter_content)
        filter_layout.setSpacing(8)
        filter_layout.setContentsMargins(10, 5, 10, 5)

        retinue_bodies = [
            (p if p != 'Ascendant' else 'Asc', f'{p.lower()}_being')
            for p in RETINUE_PLANETS
        ]

        from core.retinue_constants import ADITYA_SIGN_ORDER, TRIMSAMSA_ODD, TRIMSAMSA_EVEN
        from AI_tools.AI_main_function.retinue import ADITYA_RETINUE
        being_items = ['(Any)']
        for sign in ADITYA_SIGN_ORDER:
            data = ADITYA_RETINUE[sign]
            is_odd = data["type"] == "odd"
            if is_odd:
                being_items.append(f"{sign} ({sign} 0-15°)")
                being_items.append(f"{data['naga']} ({sign} 15-30°)")
            else:
                being_items.append(f"{data['naga']} ({sign} 0-15°)")
                being_items.append(f"{sign} ({sign} 15-30°)")
            bounds = TRIMSAMSA_ODD if is_odd else TRIMSAMSA_EVEN
            for _start, _end, _lord, _btype, _elem in bounds:
                being_items.append(f"{data[_btype]} ({sign} {_start}-{_end}°)")

        row1_widget = QWidget()
        row1_layout = QHBoxLayout(row1_widget)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(10)

        row2_widget = QWidget()
        row2_layout = QHBoxLayout(row2_widget)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.setSpacing(10)

        for i, (label_text, being_key) in enumerate(retinue_bodies):
            row_layout = row1_layout if i < 5 else row2_layout

            label = QLabel(f"{label_text}:")
            label.setFont(scaled_area_font('buttons', bold=True))
            label.setFixedWidth(60)
            label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            row_layout.addWidget(label)
            self.being_labels[being_key] = label

            combo = QComboBox()
            combo.addItems(being_items)
            combo.setFont(scaled_area_font('buttons'))
            combo.setFixedWidth(200)
            combo.setFixedHeight(24)
            combo.currentTextChanged.connect(
                lambda val, bk=being_key: self._on_being_filter_changed(bk)
            )
            row_layout.addWidget(combo)
            self.being_filters[being_key] = combo

        row1_layout.addStretch(1)
        row2_layout.addStretch(1)

        filter_layout.addWidget(row1_widget)
        filter_layout.addWidget(row2_widget)

    def _on_being_filter_changed(self, being_key):
        """Handle being filter dropdown change."""
        combo = self.being_filters.get(being_key)
        if not combo:
            return

        selection = combo.currentText()
        theme = get_theme_colors()

        if selection == '(Any)':
            combo.setStyleSheet("")
            self._remove_filter_from_search(being_key)
        else:
            combo.setStyleSheet(f"""
                QComboBox {{
                    background-color: {theme["primary"]};
                    color: {theme["primary_text"]};
                    border: 1px solid {theme["primary_light"]};
                    border-radius: 4px;
                    padding: 2px 4px;
                }}
            """)
            being_name = selection.split(' (')[0]
            self._add_being_filter_to_search(being_key, being_name)

    def _on_planet_filter_changed(self, planet_key):
        """Handle planet filter dropdown change."""
        combo = self.planet_filters.get(planet_key)
        if not combo:
            return

        selection = combo.currentText()
        theme = get_theme_colors()

        # Update dropdown appearance based on selection
        if selection == '(Any)':
            # Reset to default appearance
            combo.setStyleSheet("")
            # Remove this filter from search query
            self._remove_filter_from_search(planet_key)
        else:
            # Highlight active filter with theme primary color (blue)
            combo.setStyleSheet(f"""
                QComboBox {{
                    background-color: {theme["primary"]};
                    color: {theme["primary_text"]};
                    border: 1px solid {theme["primary_light"]};
                    border-radius: 4px;
                    padding: 2px 4px;
                }}
            """)
            # Add/update this filter in search query
            self._add_filter_to_search(planet_key, selection)

    def _add_filter_to_search(self, planet_key, sign):
        """Add or update a planet filter in the search query."""
        current_search = self.search_entry.text()

        # Write the DISPLAYED label into the search box so the search key matches
        # the dropdown and the wheel (e.g. "sun:Aries" in Tropical Classic + Western,
        # "sun:Dhata" in Aditya mode). cache.search resolves both Aditya and Western
        # names to the same ordinal via query_sign_index, so the displayed label
        # always matches correctly in every zodiac mode. SPEC-FIND-001.
        filter_string = f"{planet_key}:{sign}"

        # Check if this planet already has a filter
        pattern = rf'\b{planet_key}:\w+\b'
        if re.search(pattern, current_search):
            # Replace existing filter
            current_search = re.sub(pattern, filter_string, current_search)
        else:
            # Add new filter
            if current_search:
                current_search = f"{current_search} {filter_string}"
            else:
                current_search = filter_string

        self.search_entry.setText(current_search)
        self._refresh_results()

    def _add_being_filter_to_search(self, being_key, being_name):
        """Add or update a being filter in the search query (no sign-name conversion)."""
        current_search = self.search_entry.text()
        filter_string = f"{being_key}:{being_name}"

        pattern = rf'\b{re.escape(being_key)}:\w+\b'
        if re.search(pattern, current_search):
            current_search = re.sub(pattern, filter_string, current_search)
        else:
            if current_search:
                current_search = f"{current_search} {filter_string}"
            else:
                current_search = filter_string

        self.search_entry.setText(current_search)
        self._refresh_results()

    def _remove_filter_from_search(self, planet_key):
        """Remove a planet filter from the search query."""
        current_search = self.search_entry.text()

        # Remove planet:sign pattern
        pattern = rf'\b{planet_key}:\w+\b'
        new_search = re.sub(pattern, '', current_search)

        # Clean up double spaces
        new_search = ' '.join(new_search.split())

        self.search_entry.setText(new_search)
        self._refresh_results()

    def _clear_planet_filters(self):
        """Clear all planet and retinue being filters."""
        for planet_key, combo in self.planet_filters.items():
            combo.setCurrentIndex(0)
            combo.setStyleSheet("")

        for being_key, combo in self.being_filters.items():
            combo.setCurrentIndex(0)
            combo.setStyleSheet("")

        current_search = self.search_entry.text()

        all_keys = list(self.planet_filters.keys()) + list(self.being_filters.keys())
        keys_pattern = '|'.join(re.escape(k) for k in all_keys)
        pattern = rf'\b({keys_pattern}):\w+\b'
        new_search = re.sub(pattern, '', current_search)
        new_search = ' '.join(new_search.split())

        self.search_entry.setText(new_search)
        self._refresh_results()

    def _create_search_section(self, parent_layout):
        """Create the search bar section."""
        theme = get_theme_colors()

        # GroupBox with title
        search_group = QGroupBox("Search")
        search_group.setFont(scaled_area_font('panel_titles', bold=True))
        search_layout = QHBoxLayout(search_group)
        search_layout.setSpacing(10)

        # Search icon (magnifying glass emoji)
        icon_label = QLabel("🔍")
        icon_label.setFont(scaled_area_font('tables'))
        search_layout.addWidget(icon_label)

        # Search entry
        self.search_entry = QLineEdit()
        self.search_entry.setFont(scaled_area_font('tables'))
        self.search_entry.setMinimumHeight(36)
        self.search_entry.setPlaceholderText("Type name, city, or country to search...")
        self.search_entry.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_entry, 1)  # Stretch

        # Persistent "Search Web" button — always available
        self.web_search_inline_btn = QPushButton("Search Web")
        self.web_search_inline_btn.setFont(scaled_area_font('buttons'))
        self.web_search_inline_btn.setMinimumHeight(36)
        self.web_search_inline_btn.setStyleSheet(get_secondary_button_style())
        self.web_search_inline_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.web_search_inline_btn.clicked.connect(self._on_web_search_clicked)
        search_layout.addWidget(self.web_search_inline_btn)

        parent_layout.addWidget(search_group)


    def _on_search_changed(self, text: str = ""):
        """Handle search text change with debouncing."""
        # Cancel previous scheduled search
        self.search_timer.stop()

        # Schedule new search after 150ms
        self.search_timer.start()

    def _create_controls_section(self, parent_layout):
        """Create sort/group controls."""
        theme = get_theme_colors()

        controls_widget = QWidget()
        controls_layout = QHBoxLayout(controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(10)

        # Sort by
        sort_label = QLabel("Sort by:")
        sort_label.setFont(scaled_area_font('buttons', bold=True))
        controls_layout.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(['name', 'ascendant', 'sun', 'moon', 'city', 'country', 'birth_date', 'file_modified'])
        self.sort_combo.setFont(scaled_area_font('buttons'))
        self.sort_combo.setFixedWidth(120)
        self.sort_combo.setFixedHeight(26)
        self.sort_combo.currentTextChanged.connect(self._on_sort_dropdown_changed)
        controls_layout.addWidget(self.sort_combo)

        controls_layout.addSpacing(20)

        # Group by
        group_label = QLabel("Group by:")
        group_label.setFont(scaled_area_font('buttons', bold=True))
        controls_layout.addWidget(group_label)

        self.group_combo = QComboBox()
        self.group_combo.addItems(['none', 'folder', 'ascendant', 'sun', 'moon', 'country', 'city'])
        self.group_combo.setFont(scaled_area_font('buttons'))
        self.group_combo.setFixedWidth(120)
        self.group_combo.setFixedHeight(26)
        self.group_combo.currentTextChanged.connect(lambda: self._refresh_results())
        controls_layout.addWidget(self.group_combo)

        controls_layout.addStretch(1)

        # Results count label (right-aligned)
        self.results_label = QLabel("0 charts")
        self.results_label.setFont(scaled_area_font('status'))
        self.results_label.setStyleSheet("font-style: italic;")
        controls_layout.addWidget(self.results_label)

        parent_layout.addWidget(controls_widget)


    def _on_sort_dropdown_changed(self, text: str = ""):
        """Handle sort dropdown change - reset to ascending order."""
        self.sort_reverse = False
        self._refresh_results()

    def _create_results_section(self, parent_layout):
        """Create the results table (QTableWidget)."""
        theme = get_theme_colors()

        # GroupBox with title
        results_group = QGroupBox("Results")
        results_group.setFont(scaled_area_font('panel_titles', bold=True))
        results_layout = QVBoxLayout(results_group)
        results_layout.setContentsMargins(10, 10, 10, 10)

        # Table widget
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(9)
        self.results_table.setHorizontalHeaderLabels([
            'Name', 'Asc', 'Sun', 'Moon', 'City', 'Country', 'Birth', 'Modified', 'Path'
        ])

        # Table properties
        self.results_table.setFont(scaled_area_font('tables'))
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)

        # Column widths
        self.results_table.setColumnWidth(0, 180)  # Name
        self.results_table.setColumnWidth(1, 90)   # Asc
        self.results_table.setColumnWidth(2, 90)   # Sun
        self.results_table.setColumnWidth(3, 90)   # Moon
        self.results_table.setColumnWidth(4, 120)  # City
        self.results_table.setColumnWidth(5, 100)  # Country
        self.results_table.setColumnWidth(6, 130)  # Birth
        self.results_table.setColumnWidth(7, 100)  # Modified
        self.results_table.setColumnWidth(8, 250)  # Path

        # Resize mode
        header = self.results_table.horizontalHeader()
        header.setStretchLastSection(True)

        # Double-click to load chart
        self.results_table.cellDoubleClicked.connect(self._on_chart_double_clicked)

        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self._on_results_context_menu)

        # Header click to sort
        header.sectionClicked.connect(self._on_header_clicked)

        results_layout.addWidget(self.results_table)

        # === SORT BANNER (visible when unsorted charts >= threshold AND API key set) ===
        from managers.settings_manager import get_settings
        _sort_enabled = bool(get_settings().get_api_key("DEEPSEEK_API_KEY"))
        if _sort_enabled:
            self.sort_banner = QWidget()
            self.sort_banner.hide()
            sort_banner_layout = QHBoxLayout(self.sort_banner)
            sort_banner_layout.setContentsMargins(8, 6, 8, 6)
            self.sort_count_label = QLabel("")
            self.sort_count_label.setStyleSheet(f"color: {STATUS['warning']}; font-weight: bold; font-size: {scaled_area_px('status')}px;")
            self.sort_btn = QPushButton("Sort with DeepSeek")
            self.sort_btn.setStyleSheet(get_primary_button_style())
            self.sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.sort_btn.clicked.connect(self._on_sort_clicked)
            sort_banner_layout.addWidget(self.sort_count_label)
            sort_banner_layout.addStretch()
            sort_banner_layout.addWidget(self.sort_btn)
            self.sort_banner.setStyleSheet(f"""
                QWidget {{
                    background-color: {theme['secondary']};
                    border: 1px solid {STATUS['warning']};
                    border-radius: 4px;
                }}
            """)
            results_layout.addWidget(self.sort_banner)

        # === WEB DOWNLOAD SECTION (visible when 0 results + query) ===
        self.web_download_widget = QWidget()
        self.web_download_widget.hide()
        dl_layout = QVBoxLayout(self.web_download_widget)
        dl_layout.setContentsMargins(10, 15, 10, 10)
        dl_layout.setSpacing(8)

        self.no_results_label = QLabel("")
        self.no_results_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px;")
        dl_layout.addWidget(self.no_results_label)

        # Search button row
        btn_row = QHBoxLayout()
        self.web_search_btn = QPushButton("Search Web")
        self.web_search_btn.setStyleSheet(get_primary_button_style())
        self.web_search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.web_search_btn.setFixedWidth(200)
        self.web_search_btn.clicked.connect(self._on_web_search_clicked)
        btn_row.addWidget(self.web_search_btn)
        btn_row.addStretch()
        dl_layout.addLayout(btn_row)

        self.web_status_label = QLabel("Click to search the web for birth data")
        self.web_status_label.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_area_px('status')}px; font-style: italic;")
        dl_layout.addWidget(self.web_status_label)

        self.web_result_label = QLabel("")
        self.web_result_label.setStyleSheet(f"color: {STATUS['success']}; font-size: {scaled_area_px('status')}px; font-weight: bold;")
        self.web_result_label.hide()
        dl_layout.addWidget(self.web_result_label)

        self.web_download_widget.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['primary']};
                border-radius: 6px;
            }}
        """)
        results_layout.addWidget(self.web_download_widget)

        parent_layout.addWidget(results_group, 1)  # Stretch to fill


    def _on_header_clicked(self, logical_index):
        """Handle column header click for sorting."""
        # Map column index to sort key
        column_map = {
            0: 'name',
            1: 'ascendant',
            2: 'sun',
            3: 'moon',
            4: 'city',
            5: 'country',
            6: 'birth_date',
            7: 'file_modified',
            8: 'filepath'
        }

        sort_key = column_map.get(logical_index, 'name')

        # Toggle direction if clicking same column, else reset to ascending
        if self.sort_combo.currentText() == sort_key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_reverse = False

        self.sort_combo.setCurrentText(sort_key)
        self._refresh_results()


    def _on_chart_double_clicked(self, row, column):
        """Handle chart double-click - emit signal to load chart."""
        filepath = self.tree_filepath_map.get(row)
        if filepath:
            self.chart_selected.emit(filepath)

    def _on_results_context_menu(self, position):
        """Show right-click context menu on results table."""
        row = self.results_table.rowAt(position.y())
        if row < 0:
            return
        filepath = self.tree_filepath_map.get(row)
        if not filepath:
            return

        menu = QMenu(self)
        load_action = menu.addAction("Load chart")
        menu.addSeparator()
        trash_action = menu.addAction("Move to trash")
        self.results_table.selectRow(row)  # Highlight the right-clicked row

        action = menu.exec(self.results_table.viewport().mapToGlobal(position))
        if action == load_action:
            self.chart_selected.emit(filepath)
        elif action == trash_action:
            self._move_chart_to_trash(filepath)

    def _move_chart_to_trash(self, filepath):
        """Move a chart file to the trash folder (no deletion)."""
        import shutil
        from pathlib import Path

        trash_dir = Path(self._database_path) / "trash"
        trash_dir.mkdir(exist_ok=True)

        src = Path(filepath)
        if not src.exists():
            return

        # Unique destination name to avoid collisions
        dst = trash_dir / src.name
        counter = 1
        while dst.exists():
            dst = trash_dir / f"{src.stem}_{counter}{src.suffix}"
            counter += 1

        try:
            shutil.move(str(src), str(dst))
            QMessageBox.information(self, "Moved to Trash",
                                    f"'{src.name}' moved to trash folder.")
            # Refresh results to remove the trashed chart
            QTimer.singleShot(500, lambda: self._build_index_async(silent=True))
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to move to trash: {e}")

    def _get_checked_folders(self):
        """Get list of folder paths that are checked."""
        checked = []
        for entry, checkbox in zip(self.folder_entries, self.folder_checkboxes):
            if checkbox.isChecked():
                path = entry.text().strip()
                if path:
                    checked.append(os.path.normpath(path))
        return checked

    def _is_path_in_folders(self, filepath, folders):
        """Check if filepath is within any of the given folders."""
        if not folders:
            return False  # If no folders checked, show nothing

        filepath_norm = os.path.normpath(filepath)
        for folder in folders:
            if filepath_norm.startswith(folder + os.sep) or filepath_norm == folder:
                return True
        return False

    def _refresh_results(self):
        """Refresh the results table based on current search/sort/group."""
        # Guard: cache not yet initialized (lazy init deferred to 2s after startup)
        if self.cache is None:
            return
        # Guard: don't refresh during rebuild (processEvents can trigger signals)
        if self._rebuilding:
            return

        # Get search query
        query = self.search_entry.text()

        # Get sort/group settings
        sort_by = self.sort_combo.currentText()
        group_by = self.group_combo.currentText()
        if group_by == 'none':
            group_by = None

        # Get checked folders for filtering
        checked_folders = self._get_checked_folders()

        # Search
        results = self.cache.search(
            query, sort_by, group_by, reverse=self.sort_reverse,
            mode=self.gui.state.aditya_mode,
            ayanamsa_offset=getattr(self.gui, 'chart_ayanamsa_offset', 0.0),
        )

        # Filter by checked folders
        if isinstance(results, dict):
            # Grouped results - filter each group
            filtered_results = {}
            for group_name, entries in results.items():
                filtered_entries = [e for e in entries if self._is_path_in_folders(e.get('filepath', ''), checked_folders)]
                if filtered_entries:
                    filtered_results[group_name] = filtered_entries
            results = filtered_results
        else:
            # Flat list
            results = [e for e in results if self._is_path_in_folders(e.get('filepath', ''), checked_folders)]

        # Clear table
        self.results_table.setRowCount(0)
        self.tree_filepath_map.clear()

        # Get theme for alternating colors
        theme = get_theme_colors()
        color_odd = QColor(theme["secondary"])
        color_even = QColor(theme["secondary_dark"])
        color_group = QColor(theme["secondary_light"])

        # Populate results
        if isinstance(results, dict):
            # Grouped results
            count = 0
            row_idx = 0
            for group_name, entries in results.items():
                # Add group header row
                self.results_table.insertRow(row_idx)
                group_item = QTableWidgetItem(f"── {group_name} ({len(entries)}) ──")
                group_item.setFont(scaled_area_font('table_headers', bold=True))
                group_item.setBackground(color_group)
                group_item.setForeground(QColor(theme["secondary_text"]))
                self.results_table.setItem(row_idx, 0, group_item)
                for col in range(1, 9):
                    empty_item = QTableWidgetItem("")
                    empty_item.setBackground(color_group)
                    self.results_table.setItem(row_idx, col, empty_item)
                row_idx += 1

                # Add entries for this group
                for entry in entries:
                    self._insert_entry(entry, row_idx, color_odd if row_idx % 2 == 1 else color_even)
                    row_idx += 1
                    count += 1
        else:
            # Flat list
            count = len(results)
            for row_idx, entry in enumerate(results):
                self._insert_entry(entry, row_idx, color_odd if row_idx % 2 == 1 else color_even)

        # Update count label
        self.results_label.setText(f"{count} charts")

        # Show/hide web download section
        search_query = self.search_entry.text().strip()
        if self.web_download_widget:
            if count == 0 and len(search_query) >= 3:
                self.no_results_label.setText(f'No local charts found for "{search_query}"')
                self.web_download_widget.show()
                self.web_result_label.hide()
                self.web_status_label.setText("Click to search the web for birth data")
            else:
                self.web_download_widget.hide()

        # Show/hide sort banner (check unsorted count)
        self._update_sort_banner()

    def _update_sort_banner(self, force_recount=False):
        """Show sort banner if unsorted charts exceed threshold.

        Uses cached count to avoid blocking os.listdir on every search keystroke.
        Pass force_recount=True after downloads or sorts to refresh.
        """
        if not self.sort_banner:
            return

        if force_recount or self._cached_unsorted_count < 0:
            try:
                if os.path.isdir(self._unsorted_dir):
                    self._cached_unsorted_count = len(
                        [f for f in os.listdir(self._unsorted_dir) if f.endswith('.chtk')]
                    )
                else:
                    self._cached_unsorted_count = 0
            except Exception:
                self._cached_unsorted_count = 0

        threshold = 5
        if self._cached_unsorted_count >= threshold:
            self.sort_count_label.setText(f"{self._cached_unsorted_count} unsorted charts need organizing")
            self.sort_banner.show()
        else:
            self.sort_banner.hide()

    def _on_web_search_clicked(self):
        """Download birth data from web and create CHTK file."""
        query = self.search_entry.text().strip()
        if not query or self._web_worker is not None:
            return

        source = "auto"

        # Ensure output directory exists
        os.makedirs(self._unsorted_dir, exist_ok=True)

        # Disable both buttons (inline + 0-results section)
        self.web_search_inline_btn.setEnabled(False)
        if self.web_search_btn:
            self.web_search_btn.setEnabled(False)
        self.web_status_label.setText(f"Searching {source}...")
        self.web_result_label.hide()

        worker = WebDownloadWorker(query, source, self._unsorted_dir)
        worker.status.connect(self.web_status_label.setText)
        worker.finished.connect(self._on_web_download_finished)
        self._web_worker = worker
        worker.start()

    def _on_web_download_finished(self, result):
        """Handle web download completion."""
        self.web_search_inline_btn.setEnabled(True)
        if self.web_search_btn:
            self.web_search_btn.setEnabled(True)

        # Clean up QThread before dropping reference (prevents C++ destructor deadlock)
        worker = self._web_worker
        self._web_worker = None
        if worker is not None:
            try:
                worker.finished.disconnect(self._on_web_download_finished)
                worker.status.disconnect(self.web_status_label.setText)
            except RuntimeError:
                pass
            worker.wait()
            worker.deleteLater()

        if result is None:
            self.web_status_label.setText("Not found on the web. Try a different spelling.")
            return

        bd = result["birth_data"]
        chtk_path = result["chtk_path"]
        has_time = bd.get("hasBirthTime", False)
        time_str = f"{bd.get('hour', 12):02d}:{bd.get('minute', 0):02d}" if has_time else "noon (unknown)"

        self.web_status_label.setText("Chart saved and loaded!")
        self.web_result_label.setText(
            f"{bd.get('name', '?')} — {bd.get('day', '?')}/{bd.get('month', '?')}/{bd.get('year', '?')} "
            f"{time_str} — {bd.get('city', '?')}, {bd.get('country', '?')}"
        )
        self.web_result_label.show()

        # Defer chart loading to next event loop iteration so QThread
        # cleanup completes fully before heavy chart computation begins.
        # Without this, processEvents() inside load_chart can process
        # thread teardown events mid-computation, causing a freeze.
        QTimer.singleShot(0, lambda p=chtk_path: self.chart_selected.emit(p))

        # Update sort banner (new unsorted file — force recount)
        self._update_sort_banner(force_recount=True)

        # Incremental update so the new chart appears in future searches
        QTimer.singleShot(1500, lambda: self._build_index_async(silent=True))

    def _on_sort_clicked(self):
        """Start batch sorting of unsorted charts via DeepSeek."""
        if self._sort_worker is not None:
            return

        # Get DeepSeek API key via canonical SettingsManager
        from managers.settings_manager import get_settings
        api_key = get_settings().get_api_key("DEEPSEEK_API_KEY")

        if not api_key:
            self.sort_count_label.setText("DeepSeek API key not found! Set DEEPSEEK_API_KEY in .env")
            return

        self.sort_btn.setEnabled(False)
        self.sort_count_label.setText("Sorting with DeepSeek...")

        self._sort_worker = ChartSortWorker(
            self._unsorted_dir, self._database_path, api_key
        )
        self._sort_worker.status.connect(self.sort_count_label.setText)
        self._sort_worker.error.connect(self._on_sort_error)
        self._sort_worker.finished.connect(self._on_sort_finished)
        self._sort_worker.start()

    def _on_sort_error(self, error_msg):
        """Handle sort worker error."""
        self.sort_btn.setEnabled(True)
        self.sort_count_label.setText(f"Sort failed: {error_msg}")
        self._sort_worker = None

    def _on_sort_finished(self, results):
        """Handle sort worker completion."""
        self.sort_btn.setEnabled(True)
        self._sort_worker = None

        moved = sum(1 for r in results if r.get("moved"))
        failed = len(results) - moved
        summary = f"Sorted {moved} charts"
        if failed > 0:
            summary += f" ({failed} could not be moved)"
        self.sort_count_label.setText(summary)

        # Refresh after a moment to update banner
        QTimer.singleShot(2000, lambda: self._update_sort_banner(force_recount=True))

        # Incremental update to reflect moved files
        QTimer.singleShot(1500, lambda: self._build_index_async(silent=True))

    def _on_aditya_mode_changed(self, mode):
        """Refresh filter dropdowns and results table when mode/names change."""
        self._update_filter_dropdowns()
        self._refresh_results()

    def _update_filter_dropdowns(self):
        """Update filter dropdown items to show mode-appropriate sign names."""
        new_names = ['(Any)'] + [self._convert_sign_name(s) for s in self._aditya_signs]
        for planet_key, combo in self.planet_filters.items():
            current_idx = combo.currentIndex()
            combo.blockSignals(True)  # Don't trigger filter changes during update
            combo.clear()
            combo.addItems(new_names)
            combo.setCurrentIndex(current_idx)
            combo.blockSignals(False)

    def _convert_sign_name(self, aditya_circle_name):
        """Return the display label for an Aditya Circle name, using the SAME
        rule as the main chart wheel (core.aditya_mode.displayed_sign_name, the
        single source of truth). The displayed label set depends on BOTH the
        zodiac mode and use_western_names (SPEC-FIND-001): aditya mode shows
        Aditya names by default; tropical_classic and sidereal show Western names
        by default; use_western_names flips each. Callers pass an Aditya Circle
        name in (the ordinal anchor).
        """
        from core.aditya_mode import ADITYA_NAMES, displayed_sign_name
        if aditya_circle_name not in ADITYA_NAMES:
            return aditya_circle_name
        idx = ADITYA_NAMES.index(aditya_circle_name)
        mode = getattr(getattr(self.gui, 'state', None), 'aditya_mode', 'aditya')
        use_western = getattr(self.gui, 'use_western_names', False)
        sign_language = getattr(self.gui, 'sign_language', 'en')
        return displayed_sign_name(idx, mode, use_western, sign_language)

    def _entry_sign_display(self, entry, planet_key):
        """Display sign for a cached planet, computed in the current zodiac mode.

        Uses the stored tropical longitude so the column matches the wheel and the
        search filter in every mode. Falls back to the legacy Aditya-name relabel
        for pre-v3 cache entries that lack longitudes.
        """
        from cache.chart_index_cache import sign_index_in_mode
        from core.aditya_mode import ADITYA_NAMES
        lon = entry.get(f'{planet_key}_lon')
        if lon is None:
            return self._convert_sign_name(entry.get(planet_key, ''))
        idx = sign_index_in_mode(
            lon, self.gui.state.aditya_mode,
            getattr(self.gui, 'chart_ayanamsa_offset', 0.0),
        )
        return self._convert_sign_name(ADITYA_NAMES[idx])

    def _insert_entry(self, entry, row_index, bg_color):
        """Insert a single entry into the table."""
        theme = get_theme_colors()

        # Format modified date
        modified = entry.get('file_modified', '')
        if modified:
            modified = modified[:10]  # Just the date part

        # Format birth date+time
        birth_date = entry.get('birth_date', '')
        birth_time = entry.get('birth_time', '')
        birth = f"{birth_date} {birth_time}" if birth_date else ''

        # Insert row
        self.results_table.insertRow(row_index)

        # Get folder name from filepath for the Path column
        filepath = entry.get('filepath', '')
        folder_name = os.path.basename(os.path.dirname(filepath)) if filepath else ''

        # Show each sign computed in the CURRENT zodiac mode (from longitude),
        # so the table matches the wheel and the search filter in every mode.
        values = [
            entry.get('name', ''),
            self._entry_sign_display(entry, 'ascendant'),
            self._entry_sign_display(entry, 'sun'),
            self._entry_sign_display(entry, 'moon'),
            entry.get('city', ''),
            entry.get('country', ''),
            birth,
            modified,
            folder_name
        ]

        # Set items with background color
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setBackground(bg_color)
            item.setForeground(QColor(theme["secondary_text"]))
            self.results_table.setItem(row_index, col, item)

        # Store filepath mapping
        self.tree_filepath_map[row_index] = entry.get('filepath', '')

    def _filter_redundant_subfolders(self, folder_paths):
        """
        Filter out folders that are subfolders of other folders in the list.
        This prevents redundant indexing when one path contains another.
        """
        if not folder_paths:
            return []

        # Normalize all paths
        normalized = [(os.path.normpath(p), p) for p in folder_paths if p]
        if not normalized:
            return []

        # Sort by path length (shortest first = parent folders first)
        normalized.sort(key=lambda x: len(x[0]))

        # Keep only folders that are not subfolders of others
        root_folders = []
        for norm_path, orig_path in normalized:
            is_subfolder = False
            for root in root_folders:
                # Check if norm_path is inside root
                if norm_path.startswith(root + os.sep) or norm_path == root:
                    is_subfolder = True
                    break
            if not is_subfolder:
                root_folders.append(norm_path)

        # Return original paths for the root folders
        result = []
        for norm_path, orig_path in normalized:
            if norm_path in root_folders:
                result.append(orig_path)
        return result

    def _load_cache_only(self):
        """Load index from disk cache only — no auto-build if empty.

        Used during tab preloading to avoid blocking startup with a
        multi-minute index build.
        """
        if self.cache is None:
            self.cache = ChartIndexCache()
        count = len(self.cache.index)
        if count > 0:
            self.index_status.setText(f"Loaded {count} charts from cache")
            print(f"[FIND_CHART] Preload: loaded {count} charts from cache")
            self._refresh_results()
        else:
            self.index_status.setText("Index not built yet")
            print("[FIND_CHART] Preload: no cache, skipping build")

    def _load_cached_index(self):
        """Load index from disk cache, then silently refresh in the background."""
        if self.cache is None:
            print("[FIND_CHART] Loading cached index from disk...")
            self.cache = ChartIndexCache()

        count = len(self.cache.index)
        if count > 0:
            self.index_status.setText(f"Loaded {count} charts from cache")
            print(f"[FIND_CHART] Loaded {count} charts from cache")
            self._refresh_results()
            QTimer.singleShot(3000, lambda: self._build_index_async(silent=True))
        else:
            folders = [e.text() for e in self.folder_entries if e.text().strip()]
            if folders:
                print("[FIND_CHART] No cached index, auto-building...")
                self.index_status.setText("Building index...")
                self._build_index_async(silent=False)
            else:
                self.index_status.setText("No folders configured")
                print("[FIND_CHART] No cached index and no folders configured")

    def _build_index_async(self, silent=False):
        """Build index in a background thread.

        Args:
            silent: If True, don't show loading overlay (for automatic rebuilds).
        """
        if self._index_worker is not None and self._index_worker.isRunning():
            return

        # Don't start index rebuild while a chart is loading: processEvents()
        # during chart load would process thousands of index progress signals,
        # causing the UI to freeze.
        if (hasattr(self, 'gui') and hasattr(self.gui, 'chart_manager')
                and getattr(self.gui.chart_manager, '_loading_chart', False)):
            QTimer.singleShot(2000, lambda: self._build_index_async(silent=True))
            return

        # Lazy init cache (avoid loading 6MB JSON at app startup)
        if self.cache is None:
            print("[FIND_CHART] Creating ChartIndexCache (lazy init)...")
            self.cache = ChartIndexCache()

        folder_paths = [e.text() for e in self.folder_entries if e.text()]

        if not folder_paths:
            self.index_status.setText("No folders configured")
            return

        # Filter out subfolders to avoid redundant indexing
        filtered_paths = self._filter_redundant_subfolders(folder_paths)

        self._rebuilding = True  # Lock out _refresh_results during rebuild
        self._silent_rebuild = silent
        self.index_status.setText("Building index...")

        if not silent and hasattr(self, 'gui') and hasattr(self.gui, 'loading_manager'):
            self.gui.loading_manager.start("Building chart index...")

        self._index_worker = IndexBuildWorker(self.cache, filtered_paths)
        self._index_worker.progress.connect(self._on_index_progress)
        self._index_worker.finished.connect(self._on_index_finished)
        self._index_worker.error.connect(self._on_index_error)
        self._index_worker.start()

    def _on_index_progress(self, current, total, filepath, is_cached, stats):
        """Update status label with indexing progress (main thread)."""
        cached = stats['cached_count']
        fresh = stats['calculated_count']
        status = "cached" if is_cached else "calculating"
        self.index_status.setText(f"[{current}/{total}] {status} ({cached} cached, {fresh} new)")
        if not getattr(self, '_silent_rebuild', False):
            if hasattr(self, 'gui') and hasattr(self.gui, 'loading_manager'):
                self.gui.loading_manager.set_progress(current, total)

    def _on_index_finished(self, count):
        """Handle index build completion (main thread)."""
        self._rebuilding = False
        self.index_status.setText(f"Indexed {count} charts")
        self._refresh_results()
        if not getattr(self, '_silent_rebuild', False):
            if hasattr(self, 'gui') and hasattr(self.gui, 'loading_manager'):
                self.gui.loading_manager.finish()
        self._silent_rebuild = False
        self._index_worker = None
        print(f"[FIND_CHART] Index build complete: {count} charts")

    def _on_index_error(self, error_msg):
        """Handle index build error (main thread)."""
        self._rebuilding = False
        self.index_status.setText("Index build failed")
        print(f"[FIND_CHART] Index build error: {error_msg}")
        if not getattr(self, '_silent_rebuild', False):
            if hasattr(self, 'gui') and hasattr(self.gui, 'loading_manager'):
                self.gui.loading_manager.force_finish()
        self._silent_rebuild = False
        self._index_worker = None

    def _rebuild_index(self, silent=False):
        """Refresh the index: keeps cached entries, recalculates new/changed files."""
        self._save_folder_paths()
        self._build_index_async(silent=silent)

    def _show_rebuild_context_menu(self, pos):
        """Right-click menu on REBUILD INDEX button."""
        menu = QMenu(self)
        refresh_action = menu.addAction("Refresh Index (keep cache)")
        clear_action = menu.addAction("Full Rebuild (clear cache)")
        action = menu.exec(self.rebuild_btn.mapToGlobal(pos))
        if action == refresh_action:
            self._rebuild_index()
        elif action == clear_action:
            self._full_rebuild_index()

    def _full_rebuild_index(self):
        """Nuke cache and rebuild from scratch (context menu only)."""
        if self.cache:
            self.cache.clear_cache()
        self._save_folder_paths()
        self._build_index_async(silent=False)

    def _load_folder_paths(self):
        """Load chart folder paths via SettingsManager (single source of truth)."""
        from utils.path_translator import translate_path
        from managers.settings_manager import get_settings

        s = get_settings()
        folders = s.get_chart_folders()
        paths = [translate_path(f) or '' if f else '' for f in folders]

        while len(self.folder_entries) < len(paths):
            self._add_folder_entry()

        for i, path in enumerate(paths):
            if i < len(self.folder_entries):
                self.folder_entries[i].setText(path)

    def _save_folder_paths(self):
        """Save chart folder paths via SettingsManager (single source of truth)."""
        from managers.settings_manager import get_settings

        paths = [e.text().strip() for e in self.folder_entries]
        while len(paths) < 3:
            paths.append("")
        paths = paths[:3]

        s = get_settings()
        s.set_chart_folders(paths)
        print(f"[FIND CHART] Saved {len([p for p in paths if p])} folder paths via SettingsManager")

    def closeEvent(self, event):
        """Stop all background workers on close to prevent crashes."""
        for worker in (self._web_worker, self._sort_worker, self._index_worker):
            if worker is not None and worker.isRunning():
                worker.quit()
                worker.wait(3000)
        super().closeEvent(event)

    def refresh_theme(self):
        """Update all colors when theme changes."""
        theme = get_theme_colors()

        # Main widget background
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
            }}
            QGroupBox {{
                background-color: {theme['secondary']};
                border: 1px solid {theme['secondary_light']};
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 10px;
                font-weight: bold;
                color: {theme['secondary_text']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }}
            QLineEdit {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_light']};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QLineEdit:focus {{
                border: 2px solid {theme['primary']};
            }}
            QComboBox {{
                background-color: {theme['secondary_dark']};
                color: {theme['secondary_text']};
                border: 1px solid {theme['secondary_light']};
                border-radius: 4px;
                padding: 2px 4px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox:hover {{
                border: 1px solid {theme['primary']};
            }}
            QTableWidget {{
                background-color: {theme['secondary_dark']};
                alternate-background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                gridline-color: {theme['secondary_light']};
                selection-background-color: {theme['primary']};
                selection-color: {theme['primary_text']};
                border: 1px solid {theme['secondary_light']};
            }}
            QHeaderView::section {{
                background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                padding: 4px;
                border: 1px solid {theme['secondary_light']};
                font-weight: bold;
            }}
            QHeaderView::section:hover {{
                background-color: {theme['secondary_light']};
            }}
            QLabel {{
                color: {theme['secondary_text']};
            }}
        """)

        # Update Add Folder button
        self.add_folder_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme['primary']};
                color: {theme['primary_text']};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {theme['primary_light']};
            }}
        """)

        # Update Browse buttons
        for i, entry in enumerate(self.folder_entries):
            # Find the browse button (it's the next sibling after the line edit)
            parent = entry.parent()
            if parent:
                layout = parent.layout()
                if layout:
                    # Browse button is at index 3 (checkbox, label, entry, browse)
                    for j in range(layout.count()):
                        widget = layout.itemAt(j).widget()
                        if isinstance(widget, QPushButton) and widget.text() == "Browse":
                            widget.setStyleSheet(f"""
                                QPushButton {{
                                    background-color: {theme['primary']};
                                    color: {theme['primary_text']};
                                    border: none;
                                    border-radius: 4px;
                                    padding: 4px 8px;
                                }}
                                QPushButton:hover {{
                                    background-color: {theme['primary_light']};
                                }}
                            """)

        # Update index status label
        self.index_status.setStyleSheet(f"color: {theme['secondary_text']};")

        # Update results label
        self.results_label.setStyleSheet(f"color: {theme['secondary_text']}; font-style: italic;")

        # Update collapsible section headers (Folder Paths, Filter by ...).
        # Built once at construction, so they need an explicit restyle here.
        header_style = self._collapsible_header_style(theme)
        for header_btn in getattr(self, "_collapsible_headers", []):
            header_btn.setStyleSheet(header_style)
