#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Help Manual Dialog — Full documentation viewer with sidebar TOC.

Opens from Help > Manual (F1). Non-modal, singleton, resizable.
Uses QTextBrowser for HTML rendering with theme-injected CSS.
Pattern reused from planet_dialog.py (TOC + QTextBrowser splitter).
"""
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QListWidget, QListWidgetItem, QPushButton, QLineEdit, QLabel,
    QTextBrowser
)
from PySide6.QtCore import Qt

from ui.qt_theme import (
    get_theme_colors, scaled_area_px,
    scaled_area_factor,
)
from ui.popup_fonts import (tier_px, in_dialog_button_style, popup_group_px, live_refresh,
                             live_style, fit_text_width)

PROJECT_ROOT = Path(__file__).parent.parent.parent

_MANUAL_FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+)px")


def _scale_manual_font_sizes(html: str, scale: float) -> str:
    """Multiply every CSS px font-size in the manual by ``scale``, preserving the
    manual's internal ratios.

    The manual's typographic scale (h1 22 / h2 18 / h3 14 / table 12 /
    kbd-caption 11) is descriptive content inside a pop-up, so the caller passes
    the Info text factor (SPEC-FONT-001 §3.2, td-168ze): one knob for the whole
    document, ratios held, identical to the old Display-Scale result at the
    default Info text size.
    """
    def _repl(m):
        return f"font-size: {max(6, round(int(m.group(1)) * scale))}px"
    return _MANUAL_FONT_SIZE_RE.sub(_repl, html)

# Section definitions: (anchor_id, display_title)
MANUAL_SECTIONS = [
    ("welcome", "Welcome / Overview"),
    ("getting-started", "Getting Started"),
    ("chart-views", "Chart Views"),
    ("info-panels", "Info Panels (Right Side)"),
    ("dasha-system", "Dasha System (Left Side)"),
    ("chart-memory", "Chart Memory & Profiles"),
    ("edit-chart", "New & Edit"),
    ("human-design", "Human Design"),
    ("toolbar", "Toolbar (Left to Right)"),
    ("varga-charts", "Varga (Divisional) Charts"),
    ("planet-placements", "Planet Placements"),
    ("chart-search", "Chart Search"),
    ("settings", "Settings"),
    ("faq", "Common Questions"),
    ("troubleshooting", "When Something Goes Wrong"),
    ("reporting", "Reporting a Problem"),
    ("ask-an-ai", "Ask an AI About This Manual"),
    ("modify-yourself", "Modifying Varuna360 Yourself"),
    ("chtk-files", "Chart Files: CHTK and TOML"),
    ("keyboard-shortcuts", "Keyboard Shortcuts"),
    ("search-navigation", "Search & Navigation"),
    ("zodiac-modes", "Zodiac Modes"),
    ("ernst-wilhelm", "About Ernst Wilhelm's System"),
    ("glossary", "Glossary"),
    ("ai-instructions", "Notes for an AI Assistant"),
]


class HelpDialog(QDialog):
    """Full help manual viewer with sidebar table of contents."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme = get_theme_colors()
        self.setWindowTitle("Varuna360 — Help Manual")
        self.resize(950, 720)
        self.setMinimumSize(600, 400)
        self._setup_ui()
        self._load_manual()
        # The manual's own size tiers follow Info text, so an open Help window
        # re-renders on a Fonts Apply (SPEC-FONT-001 §3.2), keeping its place.
        live_refresh(self, self._reload_manual_keep_scroll)


    def _fit_toolbar(self):
        """Keep the toolbar whole at any Buttons size (td-168ze sweep: at 24
        Back / Forward / Home were cut to 'BAC' / 'RWARI' / 'HON'). The fixed
        widths stay floors, so defaults keep their look; the dialog widens only
        when the whole row needs more than its current width."""
        for btn, legacy in ((self.back_btn, 85), (self.forward_btn, 100),
                            (self.home_btn, 85)):
            btn.ensurePolished()
            btn.setFixedWidth(max(legacy, btn.sizeHint().width()))
        self.search_input.setFixedWidth(fit_text_width(
            self.search_input.placeholderText(), 200, button=False))
        self._toolbar.invalidate()
        m = self.layout().contentsMargins()
        need = self._toolbar.sizeHint().width() + m.left() + m.right()
        target = max(950, need)
        self.setMinimumWidth(target)
        self.resize(target, self.height())
    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # === TOOLBAR: Back, Forward, Home, Search ===
        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)

        self.back_btn = QPushButton("\u25C0 Back")
        self.back_btn.setFixedWidth(85)
        live_style(self, self.back_btn, lambda: in_dialog_button_style())
        self.back_btn.clicked.connect(self._on_back)
        toolbar.addWidget(self.back_btn)

        self.forward_btn = QPushButton("Forward \u25B6")
        self.forward_btn.setFixedWidth(100)
        live_style(self, self.forward_btn, lambda: in_dialog_button_style())
        self.forward_btn.clicked.connect(self._on_forward)
        toolbar.addWidget(self.forward_btn)

        self.home_btn = QPushButton("\u2302 Home")
        self.home_btn.setFixedWidth(85)
        live_style(self, self.home_btn, lambda: in_dialog_button_style())
        self.home_btn.clicked.connect(self._on_home)
        toolbar.addWidget(self.home_btn)

        toolbar.addSpacing(15)

        search_label = QLabel("Search:")
        # O-6: font-size in QSS, not setFont (qt-material overrides setFont).
        live_style(self, search_label, lambda: f"color: {self.theme['secondary_text']}; "
            f"font-size: {scaled_area_px('info_text')}px;")
        toolbar.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type to search...")
        self.search_input.setFixedWidth(200)
        live_style(self, self.search_input, lambda: f"""
            QLineEdit {{
                background-color: {self.theme['secondary']};
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: {tier_px('buttons', 11)}px;
            }}
        """)
        self.search_input.returnPressed.connect(self._on_search)
        toolbar.addWidget(self.search_input)

        toolbar.addStretch()

        # Export the manual as one .zip the reader can hand to an AI assistant.
        # Placed on the existing toolbar's spare width rather than in a row of
        # its own (standing layout rule: no new chrome rows).
        # Named for what the reader WANTS, not for what the code does. "Export
        # manual" describes the mechanism and answers a question nobody asked;
        # somebody stuck on a panel is looking for a way to ask a question.
        self.export_btn = QPushButton("\U0001F4E6 Answer my question with AI")
        live_style(self, self.export_btn, lambda: in_dialog_button_style())
        self.export_btn.setToolTip(
            "Stuck? Let an AI answer for you.\n"
            "\n"
            "This saves the whole manual, text and screenshots, as one .zip "
            "file.\n"
            "Drag that file into ChatGPT, Claude or another AI assistant and "
            "ask\n"
            "your question in plain language. No need to unzip it.\n"
            "\n"
            "The assistant answers from this manual instead of from whatever "
            "it\n"
            "happens to remember about astrology software, so it will not "
            "invent\n"
            "buttons that do not exist.")
        self.export_btn.clicked.connect(self._on_export_manual)
        toolbar.addWidget(self.export_btn)

        main_layout.addLayout(toolbar)
        self._toolbar = toolbar
        # Registered after the toolbar styles, so on a live Fonts Apply it runs
        # once they carry the new size.
        live_refresh(self, self._fit_toolbar, now=True)

        # === SPLITTER: TOC (left) + Content (right) ===
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # --- LEFT: Table of Contents ---
        toc_widget = QWidget()
        toc_layout = QVBoxLayout(toc_widget)
        toc_layout.setContentsMargins(0, 0, 5, 0)
        toc_layout.setSpacing(5)

        toc_header = QLabel("Contents")
        live_style(self, toc_header, lambda: f"color: {self.theme['primary']}; "
            f"font-size: {popup_group_px(14)}px; font-weight: bold;")
        toc_layout.addWidget(toc_header)

        self.toc_list = QListWidget()
        live_style(self, self.toc_list, lambda: f"""
            QListWidget {{
                background-color: {self.theme['secondary']};
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                border-radius: 6px;
                padding: 5px;
                font-size: {tier_px('sidebar', 11)}px;
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
        live_style(self, self.content_browser, lambda: f"""
            QTextBrowser {{
                background-color: {self.theme['secondary']};
                color: {self.theme['secondary_text']};
                border: 1px solid {self.theme['primary']};
                border-radius: 8px;
                padding: 15px;
                font-size: {scaled_area_px('info_text')}px;
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

        # Scale the manual's CSS px font-sizes by the Info text factor (which
        # already carries Display Scale). Ratios preserved.
        html = _scale_manual_font_sizes(html, scaled_area_factor('info_text'))

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

    def _reload_manual_keep_scroll(self):
        bar = self.content_browser.verticalScrollBar()
        ratio = bar.value() / bar.maximum() if bar.maximum() else 0.0
        self._load_manual()
        bar.setValue(round(ratio * bar.maximum()))

    def _on_toc_clicked(self, item):
        """Scroll content browser to the clicked TOC section.

        Reuses the pattern from planet_dialog.py _scroll_to_anchor (line 311-340):
        use QTextDocument.find() to locate the header text, then scroll viewport.
        """
        title = item.text().strip()

        doc = self.content_browser.document()
        # Find the HEADING, not merely the first place the words appear. A plain
        # doc.find() lands on prose: "Settings > Chart Display" occurs dozens of
        # times before the Settings heading, and a sentence pointing the reader
        # at the Glossary occurs before the Glossary itself. Both sent the
        # reader to a random paragraph. A heading is a block whose entire text
        # IS the title, so walk the matches until one satisfies that.
        cursor = doc.find(title)
        while not cursor.isNull() and cursor.block().text().strip() != title:
            cursor = doc.find(title, cursor)
        scrollbar = self.content_browser.verticalScrollBar()
        if cursor.isNull():
            # No heading carries this exact text, so there is nothing to scroll
            # to. That is the case for the first entry, whose section is titled
            # by the manual's <h1> rather than by its own heading. Go to the top
            # rather than doing nothing: a contents entry that visibly ignores
            # the click reads as a broken viewer.
            if scrollbar:
                scrollbar.setValue(0)
            return
        cursor.movePosition(cursor.MoveOperation.StartOfBlock)
        self.content_browser.setTextCursor(cursor)
        rect = self.content_browser.cursorRect(cursor)
        if scrollbar:
            scroll_pos = scrollbar.value() + rect.top() - 20
            scrollbar.setValue(max(0, scroll_pos))

    def _on_export_manual(self):
        """Save the manual as one .zip the reader can give to an AI assistant.

        Defaults to the Desktop when there is one, because the point of the
        file is to be dragged into a chat window, and a file the user cannot
        find is a file they will not use.
        """
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from core import manual_export

        if not manual_export.manual_available():
            QMessageBox.warning(
                self, "Manual not found",
                "The manual files could not be located, so there is nothing "
                "to export.")
            return

        desktop = Path.home() / "Desktop"
        start_dir = desktop if desktop.is_dir() else Path.home()
        suggested = str(start_dir / manual_export.default_filename())

        path, _ = QFileDialog.getSaveFileName(
            self, "Save the manual for an AI assistant", suggested,
            "Zip archive (*.zip)")
        if not path:
            return

        ok, message, _stats = manual_export.build_manual_zip(path)
        if not ok:
            QMessageBox.warning(self, "Export failed", message)
            return

        QMessageBox.information(
            self, "Manual saved",
            f"{message}\n\n"
            "Drag this file straight into ChatGPT, Claude or another AI "
            "assistant and ask your question in plain language. There is no "
            "need to unzip it first: the assistant opens the archive itself.\n\n"
            "It will answer from the manual rather than from what it happens "
            "to remember about astrology software.\n\n"
            "There is a suggested prompt inside the archive, in "
            "READ-ME-FIRST.txt.")

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
