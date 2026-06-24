#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
# Commercial exception: see NOTICE file.
"""
Help Manual Dialog — Full documentation viewer with sidebar TOC.

Opens from Help > Manual (F1). Non-modal, singleton, resizable.
Uses QTextBrowser for HTML rendering with theme-injected CSS.
Pattern reused from planet_dialog.py (TOC + QTextBrowser splitter).
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QListWidget, QListWidgetItem, QPushButton, QLineEdit, QLabel,
    QTextBrowser
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.qt_theme import (
    get_theme_colors, get_secondary_button_style, FONT_PRIMARY,
    scaled_area_font, scaled_area_size,
)

PROJECT_ROOT = Path(__file__).parent.parent.parent

# Section definitions: (anchor_id, display_title)
MANUAL_SECTIONS = [
    ("welcome", "Welcome / Overview"),
    ("getting-started", "Getting Started"),
    ("chart-views", "Chart Views"),
    ("info-panels", "Info Panels (Right Side)"),
    ("dasha-system", "Dasha System (Left Side)"),
    ("chart-memory", "Chart Memory & Profiles"),
    ("edit-chart", "Edit Chart"),
    ("human-design", "Human Design"),
    ("toolbar", "Toolbar (Left to Right)"),
    ("varga-charts", "Varga (Divisional) Charts"),
    ("planet-placements", "Planet Placements"),
    ("chart-search", "Chart Search"),
    ("settings", "Settings"),
    ("chtk-files", "CHTK File Import/Export"),
    ("keyboard-shortcuts", "Keyboard Shortcuts"),
    ("search-navigation", "Search & Navigation"),
    ("zodiac-modes", "Zodiac Modes"),
    ("ernst-wilhelm", "About Ernst Wilhelm's System"),
]


class HelpDialog(QDialog):
    """Full help manual viewer with sidebar table of contents."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = get_theme_colors()
        self.setWindowTitle("Varuna 360 — Help Manual")
        self.resize(950, 720)
        self.setMinimumSize(600, 400)
        self._setup_ui()
        self._load_manual()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # === TOOLBAR: Back, Forward, Home, Search ===
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        self.back_btn = QPushButton("\u25C0 Back")
        self.back_btn.setFixedWidth(85)
        self.back_btn.setStyleSheet(get_secondary_button_style())
        self.back_btn.clicked.connect(self._on_back)
        toolbar.addWidget(self.back_btn)

        self.forward_btn = QPushButton("Forward \u25B6")
        self.forward_btn.setFixedWidth(100)
        self.forward_btn.setStyleSheet(get_secondary_button_style())
        self.forward_btn.clicked.connect(self._on_forward)
        toolbar.addWidget(self.forward_btn)

        self.home_btn = QPushButton("\u2302 Home")
        self.home_btn.setFixedWidth(85)
        self.home_btn.setStyleSheet(get_secondary_button_style())
        self.home_btn.clicked.connect(self._on_home)
        toolbar.addWidget(self.home_btn)

        toolbar.addSpacing(15)

        search_label = QLabel("Search:")
        search_label.setFont(scaled_area_font('info_text'))
        search_label.setStyleSheet(f"color: {self.theme['secondary_text']};")
        toolbar.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type to search...")
        self.search_input.setFixedWidth(200)
        self.search_input.setFont(scaled_area_font('info_text'))
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {self.theme['secondary']};
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)
        self.search_input.returnPressed.connect(self._on_search)
        toolbar.addWidget(self.search_input)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)

        # === SPLITTER: TOC (left) + Content (right) ===
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # --- LEFT: Table of Contents ---
        toc_widget = QWidget()
        toc_layout = QVBoxLayout(toc_widget)
        toc_layout.setContentsMargins(0, 0, 5, 0)
        toc_layout.setSpacing(5)

        toc_header = QLabel("Contents")
        toc_header.setFont(scaled_area_font('panel_titles', bold=True))
        toc_header.setStyleSheet(f"color: {self.theme['primary']};")
        toc_layout.addWidget(toc_header)

        self.toc_list = QListWidget()
        self.toc_list.setFont(scaled_area_font('info_text'))
        self.toc_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {self.theme['secondary']};
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                border-radius: 6px;
                padding: 5px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                background-color: {self.theme['secondary_light']};
            }}
            QListWidget::item:selected {{
                background-color: {self.theme['primary']};
                color: {self.theme['primary_text']};
            }}
        """)
        self.toc_list.itemClicked.connect(self._on_toc_clicked)

        for anchor, title in MANUAL_SECTIONS:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, anchor)
            self.toc_list.addItem(item)

        toc_layout.addWidget(self.toc_list, 1)
        splitter.addWidget(toc_widget)

        # --- RIGHT: Content Browser ---
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 0, 0, 0)
        content_layout.setSpacing(0)

        self.content_browser = QTextBrowser()
        self.content_browser.setOpenExternalLinks(False)
        self.content_browser.anchorClicked.connect(self._on_link_clicked)
        self.content_browser.setFont(scaled_area_font('info_text'))
        self.content_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {self.theme['secondary']};
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                border-radius: 8px;
                padding: 15px;
                selection-background-color: {self.theme['primary']};
            }}
        """)

        content_layout.addWidget(self.content_browser)
        splitter.addWidget(content_widget)

        # Proportions: TOC 22%, Content 78%
        splitter.setSizes([210, 740])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, 1)

    def _load_manual(self):
        """Read HTML manual and inject theme colors."""
        html_path = PROJECT_ROOT / "docs" / "help" / "manual.html"
        if not html_path.exists():
            self.content_browser.setHtml(
                "<h2>Manual not found</h2>"
                f"<p>Expected at: {html_path}</p>"
            )
            return

        html = html_path.read_text(encoding="utf-8")

        # Inject theme colors into CSS placeholders
        html = html.replace("{{text}}", self.theme["secondary_text"])
        html = html.replace("{{bg}}", self.theme["secondary"])
        html = html.replace("{{primary}}", self.theme["primary"])
        html = html.replace("{{heading}}", self.theme["primary_light"])
        html = html.replace("{{border}}", self.theme["secondary_light"])
        html = html.replace("{{surface}}", self.theme["secondary_dark"])
        html = html.replace("{{accent}}", self.theme.get("accent", self.theme["primary"]))

        # Set search paths so <img src="images/..."> resolves correctly
        self.content_browser.setSearchPaths([str(html_path.parent)])
        self.content_browser.setHtml(html)

    def _on_toc_clicked(self, item):
        """Scroll content browser to the clicked TOC section.

        Reuses the pattern from planet_dialog.py _scroll_to_anchor (line 311-340):
        use QTextDocument.find() to locate the header text, then scroll viewport.
        """
        title = item.text().strip()

        doc = self.content_browser.document()
        cursor = doc.find(title)
        if not cursor.isNull():
            cursor.movePosition(cursor.MoveOperation.StartOfBlock)
            self.content_browser.setTextCursor(cursor)
            rect = self.content_browser.cursorRect(cursor)
            scrollbar = self.content_browser.verticalScrollBar()
            if scrollbar:
                scroll_pos = scrollbar.value() + rect.top() - 20
                scrollbar.setValue(max(0, scroll_pos))

    def _on_link_clicked(self, url):
        """Open external links in the system's default browser."""
        url_str = url.toString()
        if url_str.startswith("http://") or url_str.startswith("https://"):
            import webbrowser
            webbrowser.open(url_str)

    def _on_back(self):
        self.content_browser.backward()

    def _on_forward(self):
        self.content_browser.forward()

    def _on_home(self):
        scrollbar = self.content_browser.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(0)

    def _on_search(self):
        text = self.search_input.text().strip()
        if text:
            self.content_browser.find(text)
