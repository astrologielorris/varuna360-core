#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Chart Info Dialog

Background worker (ChartInfoWorker) and dialog (ChartInfoDialog) for fetching
and displaying a complete Wikipedia biography with images for the current chart
person. Extracted verbatim from chart_title_widget.py (SPEC-IMPORT-001 §7.2,
bead td-clt6.12) to keep chart_title_widget.py focused.

Dependency direction is one-way: chart_title_widget imports from this module.
This module must NOT import chart_title_widget (would create a cycle).
"""
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QDialog, QTextEdit, QApplication, QScrollArea, QFrame,
    QComboBox, QLineEdit, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap

# Import centralized theme
from ui.qt_theme import (
    TEXT_PRIMARY, TEXT_SECONDARY, SURFACE, BG, BORDER, HOVER,
    get_theme_accent, scaled_area_px, scaled_area_font, desat_hex
)


# =============================================================================
# Rodden Rating color coding (SPEC-IMPORT-001 §7.3)
# =============================================================================
# These are SEMANTIC colors (reliability of the birth time), not theme accents,
# so hardcoded hex is intentional and allowed by the project theme rules.
RODDEN_GREEN = "#4CAF50"   # reliable    (AA / A)
RODDEN_AMBER = "#FF9500"   # uncertain   (B / C)
RODDEN_RED = "#FF3B30"     # unreliable  (DD / X / XX)
RODDEN_GREY = "#9E9E9E"    # not rated   (None / absent / unknown code)


def rodden_color(rodden) -> str:
    """Return the semantic color (hex) for a Rodden rating string.

    Pure function (no Qt dependency) so it is unit-testable in isolation.
    SPEC-IMPORT-001 §7.3 color coding:
      - AA / A      -> green  (reliable)
      - B / C       -> amber  (uncertain)
      - DD / X / XX  -> red    (unreliable)
      - None / absent / unknown code -> grey ("Not rated")

    The comparison is case-insensitive and whitespace-tolerant. Any code that
    is not a recognised Rodden rating falls back to grey.
    """
    if rodden is None:
        return RODDEN_GREY
    code = str(rodden).strip().upper()
    if not code:
        return RODDEN_GREY
    if code in ("AA", "A"):
        return RODDEN_GREEN
    if code in ("B", "C"):
        return RODDEN_AMBER
    if code in ("DD", "X", "XX"):
        return RODDEN_RED
    return RODDEN_GREY


def _source_format_label(chart_path) -> str:
    """Human-readable source format derived from a file path's extension.

    SPEC-IMPORT-001 §7.3: source_format is NOT stored in the recipe; it is
    derived from the extension of current_chart_path. Pure / Qt-free.
    """
    if not chart_path:
        return "Unknown"
    import os
    ext = os.path.splitext(str(chart_path))[1].lower()
    if ext == ".toml":
        return "Open Astrology Chart (.toml)"
    if ext == ".chtk":
        return "CHTK (.chtk)"
    if ext:
        return ext
    return "Unknown"


def _debug_log(msg):
    """Write debug message to both console and log file."""
    print(msg)
    try:
        import os
        log_path = os.path.expanduser("~/chart_info_debug.log")
        with open(log_path, "a") as f:
            import datetime
            f.write(f"[{datetime.datetime.now().isoformat()}] {msg}\n")
    except:
        pass

class ChartInfoWorker(QThread):
    """
    Background worker thread for fetching complete Wikipedia biography with images.

    Uses Wikipedia API to get full article content and Wikimedia Commons for images.
    """
    finished = Signal(str, str, list)  # Emits (title, content, images) on success
    error = Signal(str)                # Emits error message on failure
    progress = Signal(str)             # Emits progress messages

    # Image filename patterns to SKIP (not photos of people)
    SKIP_PATTERNS = [
        'flag', 'logo', 'icon', 'map', 'coat_of_arms', 'seal', 'emblem',
        'signature', 'autograph', 'chart', 'graph', 'diagram', 'symbol',
        'commons-logo', 'wiki', 'edit-clear', 'question_mark', 'stub',
        'ambox', 'crystal', 'folder', 'gnome', 'nuvola', 'p_', 'pictogram',
        'red_pencil', 'speaker', 'wiktionary', 'wikibooks', 'wikiquote',
        'wikisource', 'location', 'locator', 'position', '.svg'
    ]

    def __init__(self, name: str):
        super().__init__()
        self.name = name

    def run(self):
        """Execute the Wikipedia API call in background thread."""
        import requests
        import re

        try:
            self.progress.emit(f"Searching Wikipedia for '{self.name}'...")

            headers = {"User-Agent": "Varuna360/1.0 (Vedic Astrology App)"}

            # Step 1: Search for the page
            search_url = "https://en.wikipedia.org/w/api.php"
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": self.name,
                "srlimit": 5,
                "format": "json"
            }

            response = requests.get(search_url, params=search_params, headers=headers, timeout=15)
            response.raise_for_status()
            search_data = response.json()

            search_results = search_data.get("query", {}).get("search", [])
            if not search_results:
                self.error.emit(f"No Wikipedia article found for '{self.name}'")
                return

            # Use the first result
            page_title = search_results[0]["title"]
            self.progress.emit(f"Found: {page_title}")

            # Step 2: Get article content AND image list
            self.progress.emit(f"Fetching complete article...")

            content_params = {
                "action": "parse",
                "page": page_title,
                "prop": "text|images",  # Added images
                "format": "json",
                "disabletoc": "true"
            }

            content_response = requests.get(search_url, params=content_params, headers=headers, timeout=30)
            content_response.raise_for_status()
            content_data = content_response.json()

            if "error" in content_data:
                self.error.emit(f"Error fetching article: {content_data['error'].get('info', 'Unknown error')}")
                return

            parse_data = content_data.get("parse", {})
            html_content = parse_data.get("text", {}).get("*", "")
            image_list = parse_data.get("images", [])

            if not html_content:
                self.error.emit(f"No content found for '{page_title}'")
                return

            # Convert HTML to clean text
            clean_text = self._html_to_text(html_content)

            if not clean_text.strip():
                self.error.emit(f"Could not extract text from '{page_title}'")
                return

            # Step 3: Fetch images from Wikimedia Commons
            self.progress.emit("Fetching images...")
            images_data = self._fetch_images(image_list, headers)

            _debug_log(f"[ChartInfo DEBUG] Final images count: {len(images_data)}")
            self.progress.emit("Biography loaded successfully!")
            self.finished.emit(page_title, clean_text, images_data)

        except requests.exceptions.Timeout:
            self.error.emit("Request timed out - Wikipedia may be slow")
        except requests.exceptions.RequestException as e:
            self.error.emit(f"Network error: {str(e)}")
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")

    def _fetch_images(self, image_list: list, headers: dict) -> list:
        """
        Fetch actual image URLs and data from Wikimedia Commons.

        Args:
            image_list: List of image filenames from Wikipedia article
            headers: HTTP headers for requests

        Returns:
            List of dicts with 'url' and 'bytes' keys (up to 5 images)
        """
        import requests

        # Filter out non-photo images
        photo_candidates = []
        _debug_log(f"[ChartInfo DEBUG] Total images from article: {len(image_list)}")
        for img_name in image_list:
            img_lower = img_name.lower()
            # Skip if matches any skip pattern
            if any(skip in img_lower for skip in self.SKIP_PATTERNS):
                continue
            # Only keep common image formats (not SVG which are usually icons)
            if img_lower.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                photo_candidates.append(img_name)

        _debug_log(f"[ChartInfo DEBUG] Photo candidates after filtering: {len(photo_candidates)}")
        if photo_candidates:
            _debug_log(f"[ChartInfo DEBUG] First 3 candidates: {photo_candidates[:3]}")

        if not photo_candidates:
            return []

        # Limit to first 8 candidates to check
        photo_candidates = photo_candidates[:8]

        self.progress.emit(f"Found {len(photo_candidates)} potential photos...")

        # Query Wikimedia Commons for image URLs
        commons_url = "https://en.wikipedia.org/w/api.php"
        images_data = []

        for img_name in photo_candidates:
            if len(images_data) >= 5:  # Max 5 images
                break

            try:
                self.progress.emit(f"Loading image {len(images_data) + 1}...")

                # Get image info (URL)
                info_params = {
                    "action": "query",
                    "titles": f"File:{img_name}",
                    "prop": "imageinfo",
                    "iiprop": "url|size",
                    "iiurlwidth": 400,  # Request thumbnail at 400px width
                    "format": "json"
                }

                info_response = requests.get(commons_url, params=info_params, headers=headers, timeout=10)
                info_response.raise_for_status()
                info_data = info_response.json()

                pages = info_data.get("query", {}).get("pages", {})
                for page_id, page_data in pages.items():
                    if page_id == "-1":
                        continue  # Image not found

                    imageinfo = page_data.get("imageinfo", [])
                    if imageinfo:
                        img_info = imageinfo[0]
                        # Prefer thumbnail URL if available, else full URL
                        img_url = img_info.get("thumburl") or img_info.get("url")

                        if img_url:
                            _debug_log(f"[ChartInfo DEBUG] Downloading: {img_url[:80]}...")
                            # Download the image
                            img_response = requests.get(img_url, headers=headers, timeout=15)
                            img_response.raise_for_status()

                            # Check if it's actually an image (not HTML error page)
                            content_type = img_response.headers.get('content-type', '')
                            _debug_log(f"[ChartInfo DEBUG] Content-Type: {content_type}, Size: {len(img_response.content)} bytes")
                            if 'image' in content_type:
                                images_data.append({
                                    'url': img_url,
                                    'bytes': img_response.content,
                                    'name': img_name
                                })
                                _debug_log(f"[ChartInfo DEBUG] Image added! Total: {len(images_data)}")

            except Exception as e:
                # Skip failed images, continue with others
                _debug_log(f"[ChartInfo] Failed to fetch image {img_name}: {e}")
                continue

        return images_data

    def _html_to_text(self, html: str) -> str:
        """Convert Wikipedia HTML to clean readable text."""
        import re

        text = html

        # Remove script and style tags
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Remove reference tags [1], [2], etc.
        text = re.sub(r'\[(?:edit|citation needed|\d+)\]', '', text)

        # Remove infobox, navbox, sidebar tables (they clutter the text)
        text = re.sub(r'<table[^>]*class="[^"]*(?:infobox|navbox|sidebar|vertical-navbox|wikitable)[^"]*"[^>]*>.*?</table>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Remove div elements with certain classes (navigation, etc.)
        text = re.sub(r'<div[^>]*class="[^"]*(?:navbox|catlinks|reflist|references|mw-references|toc|thumb|gallery)[^"]*"[^>]*>.*?</div>', '', text, flags=re.DOTALL | re.IGNORECASE)

        # Convert headers to readable format
        text = re.sub(r'<h2[^>]*><span[^>]*>([^<]*)</span>.*?</h2>', r'\n\n═══ \1 ═══\n\n', text, flags=re.DOTALL)
        text = re.sub(r'<h3[^>]*><span[^>]*>([^<]*)</span>.*?</h3>', r'\n\n─── \1 ───\n\n', text, flags=re.DOTALL)
        text = re.sub(r'<h4[^>]*><span[^>]*>([^<]*)</span>.*?</h4>', r'\n\n── \1 ──\n\n', text, flags=re.DOTALL)
        text = re.sub(r'<h[1-6][^>]*>([^<]*)</h[1-6]>', r'\n\n═══ \1 ═══\n\n', text)

        # Convert paragraph breaks
        text = re.sub(r'</p>\s*<p[^>]*>', '\n\n', text)
        text = re.sub(r'<p[^>]*>', '\n', text)
        text = re.sub(r'</p>', '\n', text)

        # Convert list items
        text = re.sub(r'<li[^>]*>', '\n  • ', text)
        text = re.sub(r'</li>', '', text)

        # Convert line breaks
        text = re.sub(r'<br\s*/?>', '\n', text)

        # Remove all remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)

        # Decode HTML entities
        import html
        text = html.unescape(text)

        # Clean up whitespace
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)  # Multiple blank lines to double
        text = re.sub(r'[ \t]+', ' ', text)  # Multiple spaces to single
        text = re.sub(r' +\n', '\n', text)  # Trailing spaces
        text = re.sub(r'\n +', '\n', text)  # Leading spaces on lines

        # Remove "See also", "References", "External links" sections and everything after
        for section in ['See also', 'References', 'External links', 'Further reading', 'Notes']:
            pattern = rf'\n═══ {section} ═══.*'
            text = re.sub(pattern, '', text, flags=re.DOTALL | re.IGNORECASE)

        return text.strip()


class ChartInfoDialog(QDialog):
    """
    Chart Info dialog (SPEC-IMPORT-001 §7.3).

    Two stacked sections:
      - Section A (always visible): chart metadata — Rodden rating (color
        coded), tags, source format (from file extension), notes (read-only).
      - Section B (on demand): the Wikipedia biography with images, fetched
        when the user clicks "Search Wikipedia".

    Construction:
      ChartInfoDialog(parent, chart_data=..., chart_path=...)
        Opens immediately showing Section A; Section B is empty until the
        user requests it.

    Backward-compatible legacy construction (pre-fetched bio):
      ChartInfoDialog(parent, chart_data=..., chart_path=...,
                      title=..., content=..., images=...)
        Pre-populates Section B with an already-fetched biography.
    """

    # Rodden dropdown options (SPEC-IMPORT-002 Phase 2). Index 0 is the
    # "no rating" sentinel; it maps to rodden=None on save.
    RODDEN_OPTIONS = ["Not rated", "AA", "A", "B", "C", "DD", "X", "XX"]
    _NOT_RATED = "Not rated"

    def __init__(self, parent, chart_data: dict = None, chart_path: str = None,
                 title: str = None, content: str = None, images: list = None):
        super().__init__(parent)

        self._chart_data = chart_data or {}
        self._chart_path = chart_path
        self._wiki_worker = None  # holds the running ChartInfoWorker (if any)

        person_name = self._chart_data.get('name') or ''
        win_title = f"Chart Info: {person_name}" if person_name else "Chart Info"
        self.setWindowTitle(win_title)
        self.setMinimumSize(900, 700)
        self.resize(1000, 800)

        # Dark theme styling
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {BG};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ---- Section A: Chart Metadata (always visible) ----
        self._build_metadata_section(layout)

        # ---- Section B: Wikipedia biography (on demand) ----
        self._build_wikipedia_section(layout)

        # ---- Bottom buttons ----
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        # Image count info (updated when a bio loads)
        self.img_info_label = QLabel("")
        self.img_info_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('info_text')}px;")
        self.img_info_label.setVisible(False)
        button_layout.addWidget(self.img_info_label)
        button_layout.addSpacing(20)

        # Copy button (copies whatever bio text is currently shown)
        self.copy_btn = QPushButton("📋 Copy to Clipboard")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.setStyleSheet(self._accent_button_style())
        self.copy_btn.clicked.connect(
            lambda: self._copy_to_clipboard(self.text_edit.toPlainText()))
        button_layout.addWidget(self.copy_btn)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #555;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: {scaled_area_px('buttons')}px;
            }}
            QPushButton:hover {{
                background-color: #666;
            }}
        """)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        # Legacy path: a biography was pre-fetched and passed in.
        if content is not None or images:
            self._populate_biography(title or person_name, content or "", images)

    # -------------------------------------------------------------------------
    # Section A — Chart Metadata
    # -------------------------------------------------------------------------
    def _build_metadata_section(self, parent_layout):
        """Build the always-visible chart metadata section (SPEC-IMPORT-001 §7.3)."""
        cd = self._chart_data

        frame = QFrame()
        frame.setObjectName("metadataFrame")
        frame.setStyleSheet(f"""
            QFrame#metadataFrame {{
                background-color: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
        """)
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(16, 14, 16, 14)
        frame_layout.setSpacing(8)

        # Section title
        section_title = QLabel("CHART INFO")
        section_title.setStyleSheet(f"""
            QLabel {{
                color: {TEXT_PRIMARY};
                font-size: {scaled_area_px('panel_titles')}px;
                font-weight: bold;
            }}
        """)
        frame_layout.addWidget(section_title)

        # --- Rodden Rating (editable dropdown, color coded) ---
        rodden = cd.get('rodden')
        rodden_row = QHBoxLayout()
        rodden_row.setSpacing(8)
        rodden_key = QLabel("Rodden Rating:")
        rodden_key.setStyleSheet(self._key_style())
        rodden_key.setFixedWidth(self._key_width())
        rodden_row.addWidget(rodden_key)

        self.rodden_combo = QComboBox()
        self.rodden_combo.addItems(self.RODDEN_OPTIONS)
        self._set_rodden_combo_value(rodden)
        # Re-tint on selection so the dropdown text keeps the semantic color.
        self.rodden_combo.currentTextChanged.connect(
            lambda _t: self._restyle_rodden_combo())
        self._restyle_rodden_combo()
        rodden_row.addWidget(self.rodden_combo)
        rodden_row.addStretch()
        frame_layout.addLayout(rodden_row)

        # --- Tags (editable chips) ---
        # `tags or []` guards both None (CHTK charts) and explicit empty list.
        tags = cd.get('tags')
        self._tag_values = ([str(t) for t in tags]
                            if isinstance(tags, (list, tuple))
                            else ([str(tags)] if tags else []))
        tags_key = QLabel("Tags:")
        tags_key.setStyleSheet(self._key_style())
        frame_layout.addWidget(tags_key)

        # Removable pills, rebuilt from self._tag_values on every change.
        self._tags_pills_host = QWidget()
        self._tags_pills_layout = QHBoxLayout(self._tags_pills_host)
        self._tags_pills_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_pills_layout.setSpacing(6)
        frame_layout.addWidget(self._tags_pills_host)
        self._rebuild_tag_pills()

        # Input row: free text + Add button (dedup, first-occurrence order).
        tags_input_row = QHBoxLayout()
        tags_input_row.setSpacing(6)
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("Add a tag, then press Enter")
        self._tag_input.setStyleSheet(self._input_style())
        self._tag_input.returnPressed.connect(self._on_add_tag)
        tags_input_row.addWidget(self._tag_input, stretch=1)
        add_tag_btn = QPushButton("Add")
        add_tag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_tag_btn.setStyleSheet(self._accent_button_style("6px 14px"))
        add_tag_btn.clicked.connect(self._on_add_tag)
        tags_input_row.addWidget(add_tag_btn)
        frame_layout.addLayout(tags_input_row)

        # --- Source Format (from extension of current_chart_path) ---
        src_row = QHBoxLayout()
        src_row.setSpacing(8)
        src_key = QLabel("Source Format:")
        src_key.setStyleSheet(self._key_style())
        src_key.setFixedWidth(self._key_width())
        src_row.addWidget(src_key)
        self.source_value_label = QLabel(_source_format_label(self._chart_path))
        self.source_value_label.setStyleSheet(self._value_style())
        src_row.addWidget(self.source_value_label)
        src_row.addStretch()
        frame_layout.addLayout(src_row)

        # --- Notes (editable text area) ---
        notes = cd.get('notes')
        notes_label = QLabel("Notes:")
        notes_label.setStyleSheet(self._key_style())
        frame_layout.addWidget(notes_label)

        self.notes_edit = QTextEdit()
        self.notes_edit.setObjectName("notesEdit")
        self.notes_edit.setReadOnly(False)
        self.notes_edit.setFixedHeight(90)
        self.notes_edit.setFont(scaled_area_font('info_text', family="Segoe UI"))
        # Placeholder (not real text) so an empty notes field is NOT saved as the
        # literal string "No notes".
        self.notes_edit.setPlaceholderText("No notes")
        if notes:
            self.notes_edit.setPlainText(str(notes))
        self.notes_edit.setStyleSheet(f"""
            QTextEdit#notesEdit {{
                background-color: {BG};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 8px;
            }}
        """)
        frame_layout.addWidget(self.notes_edit)

        # --- Save button (persists rodden / tags / notes) ---
        save_row = QHBoxLayout()
        self._save_status = QLabel("")
        self._save_status.setWordWrap(True)
        self._save_status.setStyleSheet(self._value_style())
        save_row.addWidget(self._save_status, stretch=1)
        self.save_meta_btn = QPushButton("Save Metadata")
        self.save_meta_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_meta_btn.setStyleSheet(self._accent_button_style())
        self.save_meta_btn.clicked.connect(self._on_save_metadata)
        save_row.addWidget(self.save_meta_btn)
        frame_layout.addLayout(save_row)

        parent_layout.addWidget(frame)

    # ====================================================================== #
    # Section A — editable metadata: widget helpers (SPEC-IMPORT-002 Phase 2)
    # ====================================================================== #
    def _set_rodden_combo_value(self, rodden):
        """Select the combo entry matching `rodden` (None/blank/unknown -> Not rated)."""
        code = str(rodden).strip().upper() if rodden else ""
        idx = self.rodden_combo.findText(code) if code else -1
        self.rodden_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _restyle_rodden_combo(self):
        """Tint the combo with the semantic rodden color of the current selection."""
        sel = self.rodden_combo.currentText()
        rodden = None if sel == self._NOT_RATED else sel
        self.rodden_combo.setStyleSheet(f"""
            QComboBox {{
                color: {desat_hex(rodden_color(rodden))};
                background-color: {BG};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: {scaled_area_px('info_text')}px;
                font-weight: bold;
            }}
            QComboBox QAbstractItemView {{
                background-color: {SURFACE};
                color: {TEXT_PRIMARY};
                selection-background-color: {HOVER};
            }}
        """)

    @staticmethod
    def _input_style():
        return f"""
            QLineEdit {{
                background-color: {BG};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 6px 8px;
                font-size: {scaled_area_px('info_text')}px;
            }}
        """

    def _rebuild_tag_pills(self):
        """Rebuild the pill row from self._tag_values (Qt-ownership safe, RULE 18)."""
        while self._tags_pills_layout.count():
            item = self._tags_pills_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not self._tag_values:
            empty = QLabel("No tags")
            empty.setStyleSheet(f"color: {TEXT_SECONDARY}; "
                                f"font-size: {scaled_area_px('info_text')}px;")
            self._tags_pills_layout.addWidget(empty)
        else:
            for tag in self._tag_values:
                self._tags_pills_layout.addWidget(self._make_pill(tag))
        self._tags_pills_layout.addStretch()

    def _make_pill(self, tag):
        """A removable tag chip rendered as '<tag>  x'."""
        pill = QFrame()
        pill.setStyleSheet(f"QFrame {{ background-color: {HOVER}; "
                           f"border: 1px solid {BORDER}; border-radius: 10px; }}")
        row = QHBoxLayout(pill)
        row.setContentsMargins(8, 2, 4, 2)
        row.setSpacing(4)
        lbl = QLabel(tag)
        lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; border: none; "
                          f"font-size: {scaled_area_px('info_text')}px;")
        row.addWidget(lbl)
        x = QPushButton("×")  # multiplication sign as a clean close glyph
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setFixedSize(18, 18)
        x.setStyleSheet(f"""
            QPushButton {{ color: {TEXT_SECONDARY}; background: transparent;
                           border: none; font-weight: bold;
                           font-size: {scaled_area_px('info_text')}px; }}
            QPushButton:hover {{ color: {desat_hex(RODDEN_RED)}; }}
        """)
        x.clicked.connect(lambda _checked=False, t=tag: self._remove_tag(t))
        row.addWidget(x)
        return pill

    def _on_add_tag(self):
        """Append input text as a tag (case-insensitive dedup, keep first order)."""
        text = self._tag_input.text().strip()
        self._tag_input.clear()
        if not text:
            return
        if any(t.lower() == text.lower() for t in self._tag_values):
            return
        self._tag_values.append(text)
        self._rebuild_tag_pills()

    def _remove_tag(self, tag):
        self._tag_values = [t for t in self._tag_values if t != tag]
        self._rebuild_tag_pills()

    # ====================================================================== #
    # Section A — editable metadata: save flow (SPEC-IMPORT-002 Phase 2.3)
    # ====================================================================== #
    def _collect_metadata(self):
        """Read edited widgets into (rodden, tags, notes); blank -> None."""
        sel = self.rodden_combo.currentText()
        new_rodden = None if sel == self._NOT_RATED else sel
        new_tags = list(self._tag_values) if self._tag_values else None
        notes_text = self.notes_edit.toPlainText().strip()
        new_notes = notes_text if notes_text else None
        return new_rodden, new_tags, new_notes

    @staticmethod
    def _apply_to_recipe(recipe, key, value):
        """Insert/update `key` in the recipe, or delete it when value is None.

        update_current_chart() silently no-ops for keys not already in the recipe
        (its `if mapped in recipe` guard), so for CHTK charts (rodden/tags/notes
        absent from the recipe) we mutate the recipe dict directly here (plan 2.3).
        """
        if value is None:
            recipe.pop(key, None)
        else:
            recipe[key] = value

    def _set_save_status(self, msg, ok=True):
        color = "#4CAF50" if ok else RODDEN_RED
        self._save_status.setStyleSheet(
            f"color: {desat_hex(color)}; font-size: {scaled_area_px('info_text')}px;")
        self._save_status.setText(msg)

    def _on_save_metadata(self):
        """Persist rodden/tags/notes to the recipe AND the source file (plan 2.3)."""
        gui = self.parent()
        mp = ((getattr(gui, 'chart_memory_panel', None)
               or getattr(gui, 'memory_panel', None)) if gui else None)
        if not mp or not (0 <= getattr(mp, 'current_index', -1)
                          < len(getattr(mp, 'charts', []))):
            self._set_save_status("No active chart to save to.", ok=False)
            return

        new_rodden, new_tags, new_notes = self._collect_metadata()

        entry = mp.charts[mp.current_index]
        recipe = entry.get('recipe')
        if recipe is None:
            self._set_save_status("Active chart has no recipe; cannot save.", ok=False)
            return

        # 1) Recipe is the serialization spine: update it so the edit survives a
        #    session restart even when there is no source file.
        self._apply_to_recipe(recipe, 'rodden', new_rodden)
        self._apply_to_recipe(recipe, 'tags', new_tags)
        self._apply_to_recipe(recipe, 'notes', new_notes)

        # 2) Invalidate the cached Chart so it rebuilds with the new metadata, and
        #    keep the dialog's own snapshot in sync for re-reads.
        entry['_chart'] = None
        self._chart_data['rodden'] = new_rodden
        self._chart_data['tags'] = new_tags
        self._chart_data['notes'] = new_notes

        # 3) Write through to the source file when there is one.
        chart_path = self._chart_path or getattr(gui, 'current_chart_path', None)
        suffix = str(chart_path).lower() if chart_path else ""
        status, ok = "Saved to session.", True
        try:
            if suffix.endswith('.toml'):
                ok = self._write_toml_metadata(gui, str(chart_path), recipe,
                                               new_rodden, new_tags, new_notes)
                status = ("Saved to .toml." if ok
                          else "Saved to session; .toml write failed.")
            elif suffix.endswith('.chtk'):
                ok = self._write_chtk_metadata(gui, str(chart_path), recipe,
                                               new_rodden, new_tags, new_notes)
                status = ("Saved (.chtk notes updated)." if ok
                          else "Saved to session (CHTK file notes update pending).")
            elif chart_path:
                status = "Saved to session (unrecognized file type)."
            # else: no file -> recipe-only persistence is the whole story.
        except Exception as exc:  # noqa: BLE001 - never lose the recipe save
            status, ok = f"Saved to session; file write failed: {exc}", False

        # 4) Refresh the dialog display + the title-bar Rodden badge.
        self._refresh_after_save(gui)
        self._set_save_status(status, ok=ok)

    def _build_canonical_for_write(self, gui, chart_path,
                                   new_rodden, new_tags, new_notes):
        """Full CANONICAL birth_data for the writer, with metadata merged in.

        The writers (update_toml_birth_data / update_chtk_birth_data) read CANONICAL
        keys (local_year..local_second, latitude, longitude, utc_offset_hours TOTAL,
        time_change_flag). Codex B1: neither gui.current_birth_data (which, after a
        select_chart cache invalidation, is the recipe-shaped birth_data_from_recipe
        reconstruction: year/lat/lon/utcoffset) NOR birth_data_from_recipe itself
        reliably carries those keys. A recipe-shaped dict makes the writer fall back
        to its 1970-01-01 / lat 0 / lon 0 / UTC defaults and SILENTLY CORRUPT the
        source file.

        This is a METADATA-ONLY edit, so the file already holds the correct birth
        data. Use gui.current_birth_data only when it is genuinely canonical (has
        local_year); otherwise re-read canonical birth_data from the source file via
        the same BirthDataManager dispatch the loader/indexer use (canonicalize=
        False so the user's file is never mutated). Returns None when no safe
        canonical source exists, so the caller blocks the file write instead of
        corrupting it (the metadata still persisted to the recipe/session).
        """
        def _is_canonical(d):
            return isinstance(d, dict) and d.get('local_year') is not None

        base = getattr(gui, 'current_birth_data', None) if gui else None
        if not _is_canonical(base):
            base = None
        if base is None and chart_path:
            try:
                from managers.birth_data_manager import BirthDataManager
                base = BirthDataManager.create_birth_data_from_file(
                    str(chart_path), canonicalize=False)
            except Exception as exc:  # noqa: BLE001 - never corrupt on a bad read
                _debug_log(f"[ChartInfo] canonical re-read failed for "
                           f"{chart_path}: {exc}")
                base = None
        if not _is_canonical(base):
            return None  # no safe canonical source -> caller must NOT write
        bd = dict(base)
        bd['rodden'] = new_rodden
        bd['tags'] = new_tags
        bd['notes'] = new_notes
        return bd

    def _write_toml_metadata(self, gui, chart_path, recipe,
                             new_rodden, new_tags, new_notes):
        bd = self._build_canonical_for_write(gui, chart_path,
                                             new_rodden, new_tags, new_notes)
        if bd is None:
            return False  # no safe canonical source; metadata kept in recipe/session
        from core.toml_chart import TOMLChartWriter
        return bool(TOMLChartWriter().update_toml_birth_data(chart_path, bd))

    def _write_chtk_metadata(self, gui, chart_path, recipe,
                             new_rodden, new_tags, new_notes):
        """Write rodden/tags/notes into the .chtk notes section (Phase 3).

        Builds the full canonical birth_data (so lines 1-14 stay correct) and sets
        the _chtk_write_metadata opt-in flag so update_chtk_birth_data rewrites ONLY
        the notes sub-block (muhurtas/residence preserved verbatim). Returns True on
        a successful file write.
        """
        bd = self._build_canonical_for_write(gui, chart_path,
                                             new_rodden, new_tags, new_notes)
        if bd is None:
            return False  # no safe canonical source; metadata kept in recipe/session
        bd['_chtk_write_metadata'] = True
        from core.chtk_reader import CHTKWriter
        return bool(CHTKWriter().update_chtk_birth_data(chart_path, bd))

    def _refresh_after_save(self, gui):
        """Re-tint the dialog widgets and refresh the title-bar Rodden badge."""
        self._restyle_rodden_combo()
        for attr in ('chart_title_widget', 'title_widget', 'chart_title'):
            tw = getattr(gui, attr, None) if gui else None
            if tw is None:
                continue
            for meth in ('refresh_metadata', 'refresh', 'update_metadata'):
                fn = getattr(tw, meth, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:  # noqa: BLE001 - badge refresh is best-effort
                        pass
                    return

    @staticmethod
    def _key_style():
        return f"color: {TEXT_SECONDARY}; font-size: {scaled_area_px('info_text')}px; font-weight: bold;"

    @staticmethod
    def _value_style():
        return f"color: {TEXT_PRIMARY}; font-size: {scaled_area_px('info_text')}px;"

    @staticmethod
    def _key_width():
        # Roughly aligns the value column; scales with font.
        return max(110, scaled_area_px('info_text') * 9)

    @staticmethod
    def _accent_button_style(padding: str = "10px 20px") -> str:
        """Shared stylesheet for the dialog's accent (blue) action buttons.

        Theme-driven (project theme rules): colors follow the selected theme
        accent via get_theme_accent() instead of hardcoded hex. The disabled
        state uses the theme HOVER/secondary tones. `padding` lets the two
        call sites (Copy: 10px 20px, Search: 8px 16px) share one definition.
        """
        accent = get_theme_accent()
        return f"""
            QPushButton {{
                background-color: {accent["base"]};
                color: {TEXT_PRIMARY};
                border: none;
                border-radius: 6px;
                padding: {padding};
                font-size: {scaled_area_px('buttons')}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {accent["hover"]};
            }}
            QPushButton:disabled {{
                background-color: {HOVER};
                color: {TEXT_SECONDARY};
            }}
        """

    # -------------------------------------------------------------------------
    # Section B — Wikipedia biography (on demand)
    # -------------------------------------------------------------------------
    def _build_wikipedia_section(self, parent_layout):
        """Build the on-demand Wikipedia biography section (SPEC-IMPORT-001 §7.3)."""
        # Header row: title + "Search Wikipedia" button
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self.bio_title_label = QLabel("📖 Wikipedia Biography")
        self.bio_title_label.setStyleSheet(f"""
            QLabel {{
                color: {TEXT_PRIMARY};
                font-size: {scaled_area_px('panel_titles')}px;
                font-weight: bold;
            }}
        """)
        header_row.addWidget(self.bio_title_label)
        header_row.addStretch()

        self.search_wiki_btn = QPushButton("🔍 Search Wikipedia")
        self.search_wiki_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_wiki_btn.setStyleSheet(self._accent_button_style(padding="8px 16px"))
        self.search_wiki_btn.clicked.connect(self._on_search_wikipedia)
        header_row.addWidget(self.search_wiki_btn)
        parent_layout.addLayout(header_row)

        # Container that will hold an image gallery once a bio loads.
        self._images_holder = QVBoxLayout()
        self._images_holder.setContentsMargins(0, 0, 0, 0)
        parent_layout.addLayout(self._images_holder)

        # Biography text area (empty until a search is run)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        person_name = self._chart_data.get('name') or ''
        hint = (f'Click "Search Wikipedia" to load a biography'
                + (f' for {person_name}.' if person_name else '.'))
        self.text_edit.setPlainText(hint)
        self.text_edit.setFont(scaled_area_font('info_text', family="Segoe UI"))
        accent = get_theme_accent()
        self.text_edit.setStyleSheet(f"""
            QTextEdit {{
                background-color: {SURFACE};
                color: {TEXT_PRIMARY};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 12px;
                selection-background-color: {accent["base"]};
            }}
            QScrollBar:vertical {{
                background-color: {SURFACE};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: #555;
                border-radius: 6px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #666;
            }}
        """)
        parent_layout.addWidget(self.text_edit, stretch=1)

    def _on_search_wikipedia(self):
        """Start the background Wikipedia fetch for the current chart person."""
        name = (self._chart_data.get('name') or '').strip()
        if not name or name in ("Unknown", "No Chart Loaded"):
            self.text_edit.setPlainText("This chart has no name to search Wikipedia for.")
            return

        self.search_wiki_btn.setEnabled(False)
        self.search_wiki_btn.setText("Searching…")
        self.text_edit.setPlainText(f"🔍 Searching Wikipedia for '{name}'...")

        worker = ChartInfoWorker(name)
        worker.progress.connect(self._on_wiki_progress)
        worker.finished.connect(self._on_wiki_finished)
        worker.error.connect(self._on_wiki_error)
        worker.finished.connect(self._cleanup_wiki_worker)
        worker.error.connect(self._cleanup_wiki_worker)
        self._wiki_worker = worker
        worker.start()

    def _on_wiki_progress(self, msg):
        self.text_edit.setPlainText(f"🔍 {msg}")

    def _on_wiki_finished(self, title, content, images):
        self.search_wiki_btn.setEnabled(True)
        self.search_wiki_btn.setText("🔄 Refresh Wikipedia")
        self._populate_biography(title, content, images)

    def _on_wiki_error(self, error_msg):
        self.search_wiki_btn.setEnabled(True)
        self.search_wiki_btn.setText("🔍 Search Wikipedia")
        self.text_edit.setPlainText(f"⚠ {error_msg}")

    def _cleanup_wiki_worker(self, *args):
        """Schedule the finished worker for deletion and drop our reference."""
        worker = self._wiki_worker
        if worker is not None:
            worker.deleteLater()
            self._wiki_worker = None

    def done(self, result):
        """Ensure a still-running Wikipedia worker is stopped before closing.

        A QThread must not be destroyed while running, so if the user closes
        the dialog mid-fetch we wait for the worker to finish before letting
        the dialog (and thus the worker's parent) tear down.

        ChartInfoWorker.run() is a blocking requests.get with no event loop,
        so quit() cannot interrupt it. If wait() TIMES OUT the thread is still
        running; calling deleteLater() on a live QThread aborts the process
        ("QThread: Destroyed while thread is still running"). In that case we
        drop our reference and LEAK the worker rather than crash — a leaked
        thread that finishes on its own is far cheaper than a hard abort.
        """
        worker = self._wiki_worker
        if worker is not None and worker.isRunning():
            if not worker.wait(5000):
                # Blocking HTTP can't be interrupted; leak the worker rather
                # than deleteLater() a live QThread (which aborts the process).
                self._wiki_worker = None
                return super().done(result)
        self._cleanup_wiki_worker()
        return super().done(result)

    def _populate_biography(self, title, content, images):
        """Fill Section B with a fetched biography (text + image gallery)."""
        _debug_log(f"[ChartInfo DEBUG] Populating bio '{title}' with "
                   f"{len(images) if images else 0} images")
        if title:
            self.bio_title_label.setText(f"📖 {title}")
        self.text_edit.setPlainText(content or "")

        # Clear any previous gallery, then add the new one.
        self._clear_images_holder()
        if images:
            self._add_images_section(self._images_holder, images)
            self.img_info_label.setText(
                f"📷 {len(images)} images from Wikimedia Commons")
            self.img_info_label.setVisible(True)
        else:
            self.img_info_label.setVisible(False)

    def _clear_images_holder(self):
        """Remove and delete any widgets currently in the image gallery slot."""
        while self._images_holder.count():
            item = self._images_holder.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _add_images_section(self, parent_layout, images: list):
        """
        Add a horizontal scrollable image gallery at the top.

        Args:
            parent_layout: The parent QVBoxLayout
            images: List of dicts with 'bytes' key containing image data
        """
        # Container frame for images
        images_frame = QFrame()
        images_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 8px;
            }}
        """)
        images_frame.setFixedHeight(220)

        # Scroll area for horizontal scrolling
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:horizontal {{
                background-color: {SURFACE};
                height: 10px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: #555;
                border-radius: 5px;
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: #666;
            }}
        """)

        # Container widget for images
        images_container = QWidget()
        images_layout = QHBoxLayout(images_container)
        images_layout.setContentsMargins(10, 10, 10, 10)
        images_layout.setSpacing(15)

        # Add each image
        _debug_log(f"[ChartInfo DEBUG] _add_images_section: Processing {len(images)} images")
        for idx, img_data in enumerate(images):
            try:
                img_bytes = img_data.get('bytes')
                if not img_bytes:
                    _debug_log(f"[ChartInfo DEBUG] Image {idx}: No bytes!")
                    continue

                _debug_log(f"[ChartInfo DEBUG] Image {idx}: {len(img_bytes)} bytes")

                # Create QPixmap from bytes
                pixmap = QPixmap()
                loaded = pixmap.loadFromData(img_bytes)
                _debug_log(f"[ChartInfo DEBUG] Image {idx}: loadFromData returned {loaded}")

                if pixmap.isNull():
                    _debug_log(f"[ChartInfo DEBUG] Image {idx}: Pixmap is NULL!")
                    continue

                _debug_log(f"[ChartInfo DEBUG] Image {idx}: Pixmap size {pixmap.width()}x{pixmap.height()}")

                # Scale to fit height while maintaining aspect ratio
                scaled_pixmap = pixmap.scaledToHeight(
                    180,
                    Qt.TransformationMode.SmoothTransformation
                )

                # Create label with rounded corners effect
                img_label = QLabel()
                img_label.setPixmap(scaled_pixmap)
                img_label.setStyleSheet(f"""
                    QLabel {{
                        background-color: {BG};
                        border: 2px solid {BORDER};
                        border-radius: 8px;
                        padding: 4px;
                    }}
                """)
                img_label.setToolTip(img_data.get('name', 'Wikipedia image'))

                images_layout.addWidget(img_label)
                _debug_log(f"[ChartInfo DEBUG] Image {idx}: Widget added to layout!")

            except Exception as e:
                _debug_log(f"[ChartInfo] Error displaying image: {e}")
                import traceback
                _debug_log(f"[ChartInfo] Traceback: {traceback.format_exc()}")
                continue

        _debug_log(f"[ChartInfo DEBUG] _add_images_section: Loop complete, adding stretch")
        images_layout.addStretch()  # Push images to the left

        scroll_area.setWidget(images_container)
        _debug_log(f"[ChartInfo DEBUG] _add_images_section: scroll_area widget set")

        # Layout for the frame
        frame_layout = QVBoxLayout(images_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.addWidget(scroll_area)

        parent_layout.addWidget(images_frame)
        _debug_log(f"[ChartInfo DEBUG] _add_images_section: COMPLETE - images_frame added to parent")

    def _copy_to_clipboard(self, content: str):
        """Copy biography content to clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(content)
        # Brief visual feedback would be nice but keeping it simple
