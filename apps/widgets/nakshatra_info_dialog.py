"""
Nakshatra Information Dialog (Core and Lite)
Modal popup showing rich nakshatra detail when a sector is clicked: on the
Core F2 nakshatra wheel, on the Pro Nakshatra tab and on the Pro Antikythera
property ring.

Layout: QSplitter with TOC sidebar (left) + QTextBrowser (right), and a
visible credit line under them.
Data source: core/data/nakshatra_data.json (27 entries), the descriptions by
Ernst Wilhelm and Michael Reed, used with permission.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QTextBrowser, QWidget, QListWidget, QListWidgetItem, QSplitter,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from ui.qt_theme import (
    FONT_PRIMARY, get_theme_colors, dim_text, scaled_area_px,
    scaled_tier_size,
)
from ui.popup_fonts import tier_px, popup_group_px

# Pop-up rule (td-168ze): every descriptive size in the reading is a tier of the
# Info text area, so the whole reading follows Settings > Fonts > Info text.
_PROSE = "info_text"

# Compatibility import for existing callers; both views share one cached source.
from core.nakshatra_properties import (
    load_nakshatra_data as _load_nakshatra_data,
    credit_line,
    detail_index,
)


# ── Badge color palettes ─────────────────────────────────────────

DOSHA_COLORS = {
    "Vata":  ("#7EB8D8", "#1A1A2E"),
    "Pitta": ("#E8915A", "#1A1A2E"),
    "Kapha": ("#5B9E8F", "#1A1A2E"),
}

KINGDOM_COLORS = {
    "Dhatu": ("#6B7B8D", "#E0E8F0"),
    "Mula":  ("#4A7A4A", "#D8F0D8"),
    "Jiva":  ("#B8962E", "#FFF8E0"),
}

GANA_COLORS = {
    "Deva":     ("#C4A132", "#FFF8E0"),
    "Manusha":  ("#7A7A6A", "#E8E8E0"),
    "Rakshasa": ("#A03030", "#FFD8D8"),
}


def _badge_html(text, bg, fg):
    """Return HTML for an inline colored pill badge."""
    return (
        f'<span style="background-color:{bg}; color:{fg}; '
        f'padding:2px 8px; border-radius:8px; font-size:{scaled_tier_size(11, _PROSE)}px; '
        f'font-weight:bold; white-space:nowrap;">{text}</span>'
    )


def _neutral_badge(text):
    """td-wtqd: a THEME-AWARE neutral pill for utility chips with no semantic
    identity colour (nature, ruler, unknown category). The identity-hued badges
    (dosha/kingdom/gana) keep their self-contained bg+fg colours — they read on
    any theme; only these grey utility pills were hardcoded dark
    (#444455/#555555) and stuck on the light theme."""
    theme = get_theme_colors()
    return _badge_html(
        text,
        theme.get("secondary_dark", "#e6e6e6"),
        theme.get("secondary_text", "#555555"),
    )


def _dosha_badge(dosha):
    pal = DOSHA_COLORS.get(dosha)
    return _badge_html(dosha, *pal) if pal else _neutral_badge(dosha)


def _kingdom_badge(raw_kingdom):
    """Normalize kingdom string (may contain 'Dhatu (Mineral)' etc.) and badge it."""
    for key in KINGDOM_COLORS:
        if raw_kingdom.startswith(key):
            bg, fg = KINGDOM_COLORS[key]
            return _badge_html(raw_kingdom, bg, fg)
    return _neutral_badge(raw_kingdom)


def _gana_badge(gana):
    # Every known gana keeps its identity hue (Deva gold / Manusha earthy grey /
    # Rakshasa red) — each is a self-contained bg+fg pill that reads on any theme,
    # same pattern as dosha/kingdom. Only an unknown gana falls to the neutral pill.
    pal = GANA_COLORS.get(gana)
    return _badge_html(gana, *pal) if pal else _neutral_badge(gana)


def _kingdom_bg_color(raw_kingdom):
    """Return a muted tint for the header banner's left band based on kingdom.
    Known kingdoms carry their own identity tint; an unknown one falls to a
    theme-aware neutral (td-wtqd) so it never leaves a dark stripe on light."""
    for key, (bg, _) in KINGDOM_COLORS.items():
        if raw_kingdom.startswith(key):
            return bg
    return get_theme_colors().get("secondary_dark", "#e6e6e6")


# ── Section Titles (for TOC) ─────────────────────────────────────

SECTIONS = [
    ("header",        "Overview"),
    ("verse",         "Taittiriya Verse"),
    ("summary",       "Summary"),
    ("classification","Classification"),
    ("esoteric",      "Esoteric Properties"),
    ("yoni",          "Yoni"),
    ("ketu_rahu",     "Ketu & Rahu"),
    ("professions",   "Professions"),
]


# ══════════════════════════════════════════════════════════════════
# Dialog
# ══════════════════════════════════════════════════════════════════

class NakshatraInfoDialog(QDialog):
    """Modal dialog showing full nakshatra detail with TOC sidebar."""

    def __init__(self, nak_index, parent=None):
        super().__init__(parent)
        self.nak_index = nak_index

        data_list = _load_nakshatra_data()
        if 0 <= nak_index < len(data_list):
            self.nak = data_list[nak_index]
        else:
            self.nak = {}

        self._setup_ui()

    # ── UI Setup ──────────────────────────────────────────────────

    def _setup_ui(self):
        theme = get_theme_colors()
        name = self.nak.get("name", f"Nakshatra #{self.nak_index + 1}")

        self.setWindowTitle(f"{name}: Nakshatra Details")
        self.setMinimumWidth(850)
        self.setMinimumHeight(700)
        self.resize(950, 800)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {theme['secondary_dark']};
            }}
            QSplitter::handle {{
                background-color: {theme['secondary']};
                width: 3px;
            }}
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # ── Splitter: TOC + Content ──────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(4)

        # LEFT — TOC sidebar
        toc_widget = QWidget()
        toc_layout = QVBoxLayout(toc_widget)
        toc_layout.setContentsMargins(0, 0, 5, 0)
        toc_layout.setSpacing(5)

        toc_header = QLabel("Contents")
        # WIDGET CHROME: setFont is O-6-WIPED under qt-material (rendered flat at
        # ~13px); the size/weight live in the stylesheet. A group header inside
        # a pop-up -> info_text x 1.25 (SPEC-FONT-001 §3.2).
        toc_header.setStyleSheet(
            f"color: {theme.get('primary', '#1565C0')}; "
            f"font-size: {popup_group_px(12)}px; font-weight: bold;")
        toc_layout.addWidget(toc_header)

        self.toc_list = QListWidget()
        # WIDGET CHROME: setFont O-6-WIPED under qt-material -> font-size in the
        # QListWidget QSS, sidebar area (this navigation list's intended 10px).
        self.toc_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                border: 1px solid {theme.get('primary', '#1565C0')};
                border-radius: 6px;
                padding: 5px;
                font-size: {scaled_area_px('sidebar')}px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            QListWidget::item:hover {{
                background-color: {theme.get('secondary_light', '#2A2A2E')};
            }}
            QListWidget::item:selected {{
                background-color: {theme.get('primary', '#1565C0')};
                color: {theme.get('primary_text', '#FFFFFF')};
            }}
        """)
        self.toc_list.itemClicked.connect(self._scroll_to_section)
        toc_layout.addWidget(self.toc_list, 1)

        # Populate TOC
        for key, title in SECTIONS:
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, title)
            self.toc_list.addItem(item)

        splitter.addWidget(toc_widget)

        # RIGHT — Content browser
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 0, 0, 0)
        content_layout.setSpacing(0)

        self.content_browser = QTextBrowser()
        self.content_browser.setOpenExternalLinks(False)
        # CONTENT surface: descriptive prose follows the Info text area (pop-up
        # rule, td-168ze). The narrative HTML keeps its size tiers as multiples
        # of info_text (scaled_tier_size); the document base is info_text itself
        # (setFont is O-6-WIPED, so the base goes in the QSS).
        self.content_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {theme['secondary']};
                color: {theme['secondary_text']};
                border: 1px solid {theme.get('primary', '#1565C0')};
                border-radius: 8px;
                padding: 15px;
                selection-background-color: {theme.get('primary', '#1565C0')};
                font-size: {scaled_area_px('info_text')}px;
            }}
        """)

        # Build and set HTML
        html = self._build_html()
        self.content_browser.setHtml(html)

        # Shadow for depth (Rule #18: release Python ref after Qt ownership)
        shadow_effect = QGraphicsDropShadowEffect()
        shadow_effect.setBlurRadius(20)
        shadow_effect.setOffset(0, 5)
        shadow_effect.setColor(QColor(0, 0, 0, 100))
        self.content_browser.setGraphicsEffect(shadow_effect)
        del shadow_effect

        content_layout.addWidget(self.content_browser)
        splitter.addWidget(content_widget)

        # Proportions: TOC 22%, Content 78%
        splitter.setSizes([200, 700])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        main_layout.addWidget(splitter, 1)

        # ── Credit line + Close button ───────────────────────────
        btn_layout = QHBoxLayout()
        # The descriptions are used with permission of both authors; the
        # credit stays visible whatever section is scrolled into view.
        self.credit_label = QLabel(credit_line())
        self.credit_label.setObjectName("nakshatraCreditLabel")
        self.credit_label.setWordWrap(True)
        self.credit_label.setStyleSheet(
            f"color: {dim_text(theme['secondary_text'])}; "
            f"font-size: {scaled_tier_size(11, _PROSE)}px; font-style: italic;")
        btn_layout.addWidget(self.credit_label, 1)
        close_btn = QPushButton("Close")
        # WIDGET CHROME: setFont O-6-WIPED under qt-material -> size/weight in QSS.
        # The dialog's bottom row -> action_buttons (pop-up rule, td-168ze).
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {theme.get('primary', '#1565C0')};
                color: {theme.get('primary_text', '#FFFFFF')};
                border: none;
                padding: 10px 28px;
                border-radius: 8px;
                font-size: {tier_px('action_buttons', 10)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: {theme.get('primary_light', '#1E88E5')};
            }}
        """)
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

    # ── TOC Navigation ────────────────────────────────────────────

    def _scroll_to_section(self, item):
        """Scroll content browser to the clicked section heading."""
        title = item.data(Qt.ItemDataRole.UserRole)
        if not title:
            return
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

    # ── HTML Builder ──────────────────────────────────────────────

    def _colors(self):
        """td-wtqd: theme-derived colours for the HTML content, so the cards,
        banners, muted text and neutral chips follow the LIVE theme instead of
        the hardcoded dark palette they were baked with. Cards ride a 3-level
        raised hierarchy that reads on both themes: dialog=secondary_dark <
        body=secondary < card=secondary_light. Muted text is theme-relative via
        dim_text(). Colours only — geometry is untouched."""
        theme = get_theme_colors()
        text = theme.get("secondary_text", "#555555")
        return {
            "text": text,
            "card": theme.get("secondary_light", "#ffffff"),
            "badge": theme.get("secondary_dark", "#e6e6e6"),
            "dim": dim_text(text),          # muted hierarchy (rgba, theme-relative)
            "faint": dim_text(text, 0.25),  # hairline borders / table rules
            "primary": theme.get("primary", "#2979ff"),
        }

    def _build_html(self):
        """Build full HTML document from nakshatra JSON entry."""
        nak = self.nak
        if not nak:
            return "<h2>No data available</h2>"

        c = self._colors()

        summary = nak.get("summary", {})
        detail = nak.get("detail", {})
        esoteric = nak.get("esoteric", {})
        ketu_rahu = nak.get("ketu_rahu", {})
        classification = detail.get("classification", {})

        name = nak.get("name", "Unknown")
        astro_idx = nak.get("astronomical_index", "?")
        deity = summary.get("deity", "")
        deity_desc = summary.get("deity_description", "")
        emissary = summary.get("emissary", "")
        constellation = summary.get("constellation_shape", "")
        kingdom_raw = esoteric.get("kingdom", classification.get("category", ""))
        kingdom_bg = _kingdom_bg_color(kingdom_raw)

        parts = []
        parts.append(self._css())

        # ── A. Header Banner ──────────────────────────────────────
        parts.append(f"""
        <div class="header-banner" style="border-left: 5px solid {kingdom_bg};">
            <h1 style="margin:0; font-size:{scaled_tier_size(24, _PROSE)}px; color:{c['text']};">
                {name}
                <span class="index-badge">#{astro_idx}</span>
            </h1>
            <p style="margin:4px 0 0 0; color:{c['dim']}; font-size:{scaled_tier_size(13, _PROSE)}px;">
                <b>Deity:</b> {deity}
                {f'<br><i>{deity_desc}</i>' if deity_desc else ''}
            </p>
            <p style="margin:2px 0 0 0; color:{c['dim']}; font-size:{scaled_tier_size(12, _PROSE)}px;">
                <b>Emissary:</b> {emissary}
                {f'&nbsp;&nbsp;|&nbsp;&nbsp;<b>Constellation:</b> {constellation}' if constellation else ''}
            </p>
        </div>
        """)

        # ── B. Taittiriya Verse ───────────────────────────────────
        verse = summary.get("taittiriya_verse", "")
        if verse:
            parts.append(f"""
            <h2>Taittiriya Verse</h2>
            <div class="verse-block">
                <i>{verse}</i>
            </div>
            """)

        # ── C. Summary Table ──────────────────────────────────────
        parts.append("<h2>Summary</h2>")
        table_rows = []

        for label, key in [
            ("Deity", "deity"),
            ("Description", "deity_description"),
            ("Emissary", "emissary"),
            ("Body Part", "body_part"),
        ]:
            val = summary.get(key, "")
            if val:
                table_rows.append(f"<tr><td class='tkey'>{label}</td><td>{val}</td></tr>")

        # Yoni (list)
        yoni_list = summary.get("yoni", [])
        if yoni_list:
            table_rows.append(f"<tr><td class='tkey'>Yoni</td><td>{', '.join(yoni_list)}</td></tr>")

        # Symbol (list)
        symbol_list = summary.get("symbol", [])
        if symbol_list:
            table_rows.append(f"<tr><td class='tkey'>Symbol</td><td>{', '.join(symbol_list)}</td></tr>")

        for label, key in [
            ("Place", "place"),
            ("Stars", "number_of_stars"),
        ]:
            val = summary.get(key, esoteric.get(key, ""))
            if val:
                table_rows.append(f"<tr><td class='tkey'>{label}</td><td>{val}</td></tr>")

        if table_rows:
            parts.append(f"<table class='info-table'>{''.join(table_rows)}</table>")

        # Brihat Samhita paragraph
        brihat = summary.get("brihat_samhita", "")
        if brihat:
            parts.append(f"""
            <p class="brihat"><b>Brihat Samhita:</b> {brihat}</p>
            """)

        # ── D. Classification & Meaning ───────────────────────────
        meaning_title = detail.get("meaning_title", "")
        parts.append("<h2>Classification</h2>")

        if meaning_title:
            parts.append(f"<h3>{meaning_title}</h3>")

        # Badge row
        nature = classification.get("nature", esoteric.get("nature", ""))
        category = classification.get("category", "")
        ruler = classification.get("ruler", "")
        badge_parts = []
        if nature:
            badge_parts.append(_neutral_badge(nature))
        if category:
            badge_parts.append(_kingdom_badge(category))
        if ruler:
            badge_parts.append(_neutral_badge(f"Ruler: {ruler}"))
        if badge_parts:
            parts.append(f"<p>{'&nbsp; '.join(badge_parts)}</p>")

        # Translation
        translation = detail.get("english_translation", "")
        if translation:
            parts.append(f"<p><b>Translation:</b> {translation}</p>")

        # Word breakdown
        breakdown = detail.get("word_breakdown", "")
        if breakdown:
            parts.append(f"<p class='breakdown'><b>Word Breakdown:</b> {breakdown}</p>")

        # ── E. Esoteric Properties ────────────────────────────────
        parts.append("<h2>Esoteric Properties</h2>")

        eso_rows = []

        # Rows with colored badges
        dosha = esoteric.get("dosha", "")
        if dosha:
            eso_rows.append(f"<tr><td class='tkey'>Dosha</td><td>{_dosha_badge(dosha)}</td></tr>")

        kingdom_eso = esoteric.get("kingdom", "")
        if kingdom_eso:
            eso_rows.append(f"<tr><td class='tkey'>Kingdom</td><td>{_kingdom_badge(kingdom_eso)}</td></tr>")

        gana = esoteric.get("gana", "")
        if gana:
            eso_rows.append(f"<tr><td class='tkey'>Gana</td><td>{_gana_badge(gana)}</td></tr>")

        # Regular text rows
        for label, key in [
            ("Nature", "nature"),
            ("Gender", "gender"),
            ("Activity", "activity"),
            ("Caste", "caste"),
            ("Facing", "facing"),
            ("Gunas", "gunas"),
            ("KBN", "kbn"),
            ("Trimurthi", "trimurthi"),
            ("Motivation", "primary_motivation"),
        ]:
            val = esoteric.get(key, "")
            if val:
                eso_rows.append(f"<tr><td class='tkey'>{label}</td><td>{val}</td></tr>")

        if eso_rows:
            parts.append(f"<table class='info-table'>{''.join(eso_rows)}</table>")

        # Shakti (highlighted full-width)
        shakti = esoteric.get("shakti", "")
        if shakti:
            parts.append(f"""
            <div class="shakti-block">
                <b>Shakti:</b> {shakti}
            </div>
            """)

        # ── F. Yoni Description ───────────────────────────────────
        yoni_raw = esoteric.get("yoni_description", {})
        # Normalise: single dict → list for uniform handling (Uttara Ashadha has two yonis)
        yoni_list = yoni_raw if isinstance(yoni_raw, list) else [yoni_raw] if yoni_raw else []
        if yoni_list:
            parts.append("<h2>Yoni</h2>")
            for yoni_desc in yoni_list:
                animal = yoni_desc.get("animal", "")
                short = yoni_desc.get("short", "")
                hora = yoni_desc.get("hora_ratnam", "")

                if animal:
                    parts.append(f"<p><b>{animal}</b>"
                                 f"{f': {short}' if short else ''}</p>")
                if hora:
                    parts.append(f"""
                    <div class="verse-block" style="border-left-color:#B8962E;">
                        <i>Hora Ratnam: {hora}</i>
                    </div>
                    """)

        # ── G. Ketu / Rahu Traits ─────────────────────────────────
        ketu_traits = ketu_rahu.get("ketu_traits", [])
        rahu_traits = ketu_rahu.get("rahu_traits", [])
        if ketu_traits or rahu_traits:
            parts.append("<h2>Ketu &amp; Rahu</h2>")

            ketu_bullets = "".join(f"<li>{t}</li>" for t in ketu_traits)
            rahu_bullets = "".join(f"<li>{t}</li>" for t in rahu_traits)

            parts.append(f"""
            <table class="kr-table">
                <tr>
                    <td class="kr-col kr-ketu">
                        <h3 style="margin:0 0 6px 0; color:{c['dim']};">Ketu</h3>
                        <ul>{ketu_bullets}</ul>
                    </td>
                    <td class="kr-col kr-rahu">
                        <h3 style="margin:0 0 6px 0; color:{c['primary']};">Rahu</h3>
                        <ul>{rahu_bullets}</ul>
                    </td>
                </tr>
            </table>
            """)

        # ── H. Professions & Activities ───────────────────────────
        professions = esoteric.get("people_professions_activities", "")
        articles = esoteric.get("articles_people_brihat_samhita", "")
        if professions or articles:
            parts.append("<h2>Professions</h2>")
            if professions:
                parts.append(f"<p>{professions}</p>")
            if articles:
                parts.append(f"""
                <div class="brihat-card">
                    <b>Brihat Samhita:</b> {articles}
                </div>
                """)

        return "".join(parts)

    # ── CSS Stylesheet ────────────────────────────────────────────

    def _css(self):
        """Return HTML <style> block for the content browser.

        td-wtqd: card backgrounds, muted text and hairline borders are now
        theme-derived (via _colors()) instead of the hardcoded dark palette that
        stayed dark on the light theme. Geometry (padding/radius/margins) is
        unchanged; only colours moved. Semantic accents (h2/verse primary, the
        Rahu-blue and gold verse borders) and the identity-hued badges are kept.
        """
        c = self._colors()
        return f"""
        <style>
            body {{
                font-family: {FONT_PRIMARY}, sans-serif;
                color: {c['text']};
                background: transparent;
                margin: 0;
                padding: 0;
            }}
            h1 {{ font-size: {scaled_tier_size(22, _PROSE)}px; margin: 8px 0; }}
            h2 {{
                font-size: {scaled_tier_size(16, _PROSE)}px;
                color: {c['primary']};
                border-bottom: 1px solid {c['faint']};
                padding-bottom: 4px;
                margin: 20px 0 8px 0;
            }}
            h3 {{
                font-size: {scaled_tier_size(14, _PROSE)}px;
                color: {c['dim']};
                margin: 10px 0 4px 0;
            }}
            p {{ margin: 6px 0; line-height: 1.5; }}
            ul {{
                margin: 4px 0;
                padding-left: 18px;
            }}
            li {{
                margin: 3px 0;
                line-height: 1.4;
            }}

            .header-banner {{
                background: {c['card']};
                padding: 14px 16px;
                border-radius: 8px;
                margin-bottom: 6px;
            }}
            .index-badge {{
                background: {c['badge']};
                color: {c['text']};
                padding: 2px 8px;
                border-radius: 10px;
                font-size: {scaled_tier_size(13, _PROSE)}px;
                font-weight: bold;
                margin-left: 8px;
            }}

            .verse-block {{
                background: {c['card']};
                border-left: 4px solid {c['primary']};
                padding: 10px 14px;
                margin: 8px 0;
                border-radius: 0 6px 6px 0;
                color: {c['dim']};
                font-size: {scaled_tier_size(13, _PROSE)}px;
                line-height: 1.6;
            }}

            .info-table {{
                width: 100%;
                border-collapse: collapse;
                margin: 6px 0;
            }}
            .info-table td {{
                padding: 5px 8px;
                border-bottom: 1px solid {c['faint']};
                vertical-align: top;
                font-size: {scaled_tier_size(12, _PROSE)}px;
            }}
            .tkey {{
                color: {c['dim']};
                font-weight: bold;
                width: 120px;
                white-space: nowrap;
            }}

            .brihat {{
                color: {c['dim']};
                font-size: {scaled_tier_size(12, _PROSE)}px;
                font-style: italic;
                margin: 8px 0;
            }}

            .breakdown {{
                color: {c['dim']};
                font-size: {scaled_tier_size(12, _PROSE)}px;
            }}

            .shakti-block {{
                background: {c['card']};
                border: 1px solid {c['faint']};
                padding: 10px 14px;
                border-radius: 6px;
                margin: 8px 0;
                color: {c['text']};
                font-size: {scaled_tier_size(12, _PROSE)}px;
            }}

            .kr-table {{
                width: 100%;
                border-collapse: collapse;
            }}
            .kr-col {{
                width: 50%;
                vertical-align: top;
                padding: 8px 10px;
            }}
            .kr-ketu {{
                border-left: 3px solid #888888;
                background: {c['card']};
                border-radius: 4px 0 0 4px;
            }}
            .kr-rahu {{
                border-left: 3px solid #446688;
                background: {c['card']};
                border-radius: 0 4px 4px 0;
            }}
            .kr-col ul {{
                padding-left: 16px;
                margin: 4px 0;
            }}
            .kr-col li {{
                font-size: {scaled_tier_size(12, _PROSE)}px;
                line-height: 1.4;
                margin: 2px 0;
            }}

            .brihat-card {{
                background: {c['card']};
                border: 1px solid {c['faint']};
                padding: 10px 14px;
                border-radius: 6px;
                margin: 8px 0;
                color: {c['dim']};
                font-size: {scaled_tier_size(12, _PROSE)}px;
                font-style: italic;
            }}
        </style>
        """

    # ── Cleanup (Rule #18) ────────────────────────────────────────

    def closeEvent(self, event):
        """Clear graphics effects before close to prevent double-deletion."""
        if hasattr(self, 'content_browser'):
            self.content_browser.setGraphicsEffect(None)
        super().closeEvent(event)


def open_nakshatra_info_dialog(nak_index, parent=None):
    """Open the info dialog for wheel sector ``nak_index`` (0 = Ashvini).

    The single entry point the Core wheel, the Pro Nakshatra tab and the Pro
    Antikythera ring share: the sector index is the astronomical order of
    ``libaditya`` names, resolved to the data row by identity (never by the
    file's display order). Returns the dialog after it closes, or None for an
    out-of-range index."""
    from libaditya.constants import names
    identities = names['eng']['nakshatras']
    if not 0 <= nak_index < len(identities):
        return None
    source_index = detail_index(identities[nak_index])
    dialog = NakshatraInfoDialog(
        source_index if source_index is not None else -1, parent=parent)
    dialog.exec()
    dialog.deleteLater()
    return dialog
