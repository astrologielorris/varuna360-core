# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Exchange (Parivartana) + Final-Dispositor panel widget.
=======================================================
A "Solar-Dawn" card stack (spec §4 / R1): a verdict HERO card for the chart's
dominant final-dispositor theme, a ranked "Final Dispositor Themes" section, and
the classic "Exchanges (Parivartana)" section, all inside one QScrollArea.

Clicking a card expands its full reading IN PLACE (an exclusive accordion, one
open at a time), so chart readings stay integrated in the page rather than in a
pop-up (matches the kuta-panel rule). The ONLY pop-up is a single "(i)" tutorial
that teaches what Parivartana / final dispositors ARE (doctrine, not this chart).

Presentation only: refresh() takes ALREADY-COMPUTED engine output (the controller
frames the chart and calls the engines, hardening H3), so this widget never reads
GUI state. Colours come from ui/qt_theme.py (pari_sem severity map); NO raw hex.
Imports NOTHING from pro/ so the public Core build stays isolated (H11): the
strength bar is duplicated here and the tutorial text lives inline.
"""

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QBrush
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QSizePolicy, QDialog,
)

from ui.themed_style import ThemedStyleMixin
from ui.qt_theme import (
    get_theme_colors,
    pari_sem,
    dim_text,
    scaled_px,
    elevation_surface_style,
)
from AI_tools.AI_main_function.constants import PARIVARTANA_YOGA_FULL
from AI_tools.AI_main_function.parivartana_descriptions import describe_exchange

# Vedic classification -> pari_sem key + human label (for the Exchanges section).
_CLASS_LABEL = {
    "MAHA": ("maha", "Maha Yoga"),
    "KHALA": ("khala", "Khala Yoga"),
    "DAINYA_6": ("dainya6", "Dainya Yoga (6th)"),
    "DAINYA_8": ("dainya8", "Dainya Yoga (8th)"),
    "DAINYA_12": ("dainya12", "Dainya Yoga (12th)"),
    "DAINYA_DOUBLE": ("dainya_double", "Dainya Yoga (double)"),
}
_CLASS_ORDER = ["MAHA", "KHALA", "DAINYA_6", "DAINYA_8", "DAINYA_12", "DAINYA_DOUBLE"]

# Inline tutorial text ((i) popup). Paraphrased in the app author's voice; the
# taxonomy is classical (cited). NO pro/ import (H11).
_DOC_TITLE = "Exchanges and Final Dispositors"
_DOC_SECTIONS = [
    ("WHAT AN EXCHANGE IS",
     "Two planets sit in each other's ruling signs, so each governs the other's "
     "affairs. This mutual exchange (Parivartana) fuses the two houses they occupy "
     "into one linked theme, for better (Maha) or worse (Dainya)."),
    ("WHAT A FINAL DISPOSITOR IS",
     "Follow any planet to the ruler of its sign, then that ruler to the ruler of "
     "ITS sign, and so on. Every chain eventually loops. The planets in that loop "
     "are the chart's final dispositors, and the houses they occupy are where the "
     "chart's energy finally funnels. An exchange is simply the tightest case, a "
     "two-planet loop."),
    ("READING THE STRENGTH",
     "The basin count is how many of the seven planets funnel into a theme. A "
     "larger basin means a more dominant life theme. The severity (Maha grace "
     "through Dainya affliction) comes from the houses the theme occupies."),
    ("CLASSICAL SOURCES",
     "The Maha, Khala and Dainya taxonomy of exchanges is given in Phaladeepika "
     "VI.32-34; the final-dispositor reading systematises classical dispositor "
     "doctrine."),
]

# House-type reference (PAC7). An exchange is graded by the two houses it links,
# so the tutorial explains what those house TYPES mean. Author's voice, classical
# taxonomy cited, no pro/ import (H11).
_HOUSE_TYPE_HEADING = "House types: the road of growth"
_HOUSE_TYPE_SECTIONS = [
    ("WHY HOUSE TYPE MATTERS HERE",
     "An exchange is graded by the two houses it links. Maha yogas join good "
     "houses, Dainya yogas touch the difficult 6th, 8th or 12th. A house TYPE "
     "sets the road a planet's growth travels: smooth or turbulent, fast or slow, "
     "seen or hidden. It does not add work, it changes the story around the work."),
    ("ANGLES AND TRINES (1, 4, 5, 7, 9, 10)",
     "The easiest road. Growth here is supported and low in intensity. House 1 is "
     "both an angle and a trine, and house 10 both manifests easily and grows over "
     "time, so those two are the strongest of all."),
    ("EFFORT HOUSES (2, 3, 11)",
     "Neither easy nor a bad place. Growth asks for extra will: house 2 through "
     "responsibility and burden, house 3 through short intense effort and "
     "competition, house 11 through long persistence. Houses 3 and 11 keep "
     "compounding over time."),
    ("DUSTHANAS (6, 8, 12)",
     "The hardest, most intense road. Full growth is still reachable, but the "
     "circumstances carry more stress, more fear and less support. House 6 improves "
     "over time with grit; houses 8 and 12 are the deeper difficulties, 8 hidden "
     "even from oneself and 12 the house of loss."),
    ("HIDDEN HOUSES (4, 8, 12)",
     "Real development that others do not see. A fine planet here can be missed, "
     "and a difficult one can hide behind a good first impression."),
    ("TIMING (ANGLE, SUCCEDENT, CADENT)",
     "Angles (1, 4, 7, 10) change fast but can reverse fast if effort stops. "
     "Succedent houses (2, 5, 8, 11) change slowly yet permanently. Cadent houses "
     "(3, 6, 9, 12) are where lessons land, and their gift is that the same mistake "
     "is not repeated."),
    ("SOURCES: CLASSICAL ROOTS",
     "The house-type categories are classical Parashari doctrine, not a modern "
     "invention. Mantreswara's Phaladeepika (chapter 1) states it plainly: 'The "
     "1st, the 10th, the 7th and the 4th houses are known by the term Kendra... "
     "The 9th and the 5th are known as Trikona and these are auspicious... The "
     "10th, the 3rd, the 6th and the 11th houses are called Upachaya.' The same "
     "house doctrine, with the Dusthanas (6, 8, 12), runs through the Brihat "
     "Parashara Hora Shastra and Kalyanavarma's Saravali. Houses are counted whole "
     "sign from the ascendant."),
    ("SOURCES: OLDER GREEK ROOTS",
     "The very words kendra, panaphara and apoklima are older still: they are the "
     "Greek kentron, epanaphora and apoklima (angular, succedent, cadent) carried "
     "into Sanskrit through the Yavanajataka. As the scholar David Pingree showed, "
     "these terms have plain meaning in Greek but survive in Sanskrit only as "
     "astrological technical words, which is why he read them as proof that the "
     "house doctrine reached India from Hellenistic Greece."),
    ("SOURCES: MODERN TEACHING",
     "The Parent, Adult and Child reading of these houses, and the avastha "
     "(planetary-state) layer behind it, follows the modern teaching of Ernst "
     "Wilhelm through his video astrology courses at astrology-videos.com (the "
     "evolved form of his earlier Vault of the Heavens work). His Parent, Adult "
     "and Child model draws on Thomas A. Harris's book 'I'm OK, You're OK', the "
     "classic popularisation of Eric Berne's Transactional Analysis. Test all of "
     "it against your own chart."),
]


# SPEC-THM-002 W4: was one of four byte-equivalent private copies of this
# helper. Now a thin re-export of the shared one, so a fix lands in one place.
# (cards_of_truth_view._rgba is NOT one of them — it returns a QColor, not a
# QSS string, and keeps its own implementation.)
from ui.qt_theme import _alpha as _rgba  # noqa: F401


class _StrengthBar(QWidget):
    """Slim basin-strength bar (rounded track + gradient fill). Duplicated here
    rather than imported from pro/ (apps must not depend on pro, H11). Reads the
    severity colour live in paintEvent so it restyles on a theme switch."""

    def __init__(self, frac, sem_key="neutral", parent=None):
        super().__init__(parent)
        self._frac = max(0.0, min(1.0, frac))
        self._sem_key = sem_key
        self.setFixedHeight(scaled_px(10))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        theme = get_theme_colors()
        sem = pari_sem(self._sem_key)
        h = self.height()
        p.setPen(Qt.NoPen)
        track = QColor(theme["secondary_light"])
        track.setAlpha(90)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 1, self.width(), h - 2), 4, 4)
        w = max(6.0, self.width() * self._frac)
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0, QColor(sem["lo"]))
        grad.setColorAt(1, QColor(sem["hi"]))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(QRectF(0, 1, w, h - 2), 4, 4)
        p.end()


class _ClickableLabel(QLabel):
    """A QLabel that emits clicked and shows a hand cursor."""
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setWordWrap(True)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ParivartanaWidget(ThemedStyleMixin, QWidget):
    """Exchange + final-dispositor card stack. Public API mirrors the other
    Solar-Dawn panels: refresh(themes, interchanges) / clear() / refresh_theme().

    ``wide=True`` (fullscreen pop-out) pre-expands every card and scales type up.
    """

    def __init__(self, wide=False, parent=None):
        super().__init__(parent)
        self._wide = wide
        self._themes = None            # last-rendered data (H13: re-render, not recompute)
        self._interchanges = None
        self._open_key = None          # exclusive-accordion open card id
        self._details = {}             # card id -> detail QWidget
        self._cards = {}               # card id -> card QFrame (for ensureWidgetVisible)
        self._doc_dialog = None        # retained so the non-modal (i) popup is not GC'd (H6)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(scaled_px(4))

        # Header row: title + a single (?) tutorial button (the ONLY popup).
        # Small right margin so the round button is not clipped by the panel edge.
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, scaled_px(4), 0)
        self._title = QLabel("Exchange & Dispositor Themes")
        self._register_themed(self._title, self._kicker_style)
        header.addWidget(self._title)
        header.addStretch(1)
        self._info_btn = QPushButton("?")
        self._info_btn.setFixedSize(scaled_px(22), scaled_px(22))
        self._info_btn.setCursor(Qt.PointingHandCursor)
        self._info_btn.setToolTip("Learn what exchanges and final dispositors are")
        self._register_themed(self._info_btn, self._info_btn_style)
        self._info_btn.clicked.connect(self._open_tutorial)
        header.addWidget(self._info_btn)
        root.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._register_themed(self._scroll, self._scroll_style)
        self._host = QWidget()
        self._cards_lay = QVBoxLayout(self._host)
        self._cards_lay.setContentsMargins(scaled_px(2), scaled_px(2), scaled_px(2), scaled_px(2))
        self._cards_lay.setSpacing(scaled_px(8))
        self._cards_lay.addStretch(1)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, 1)

        # Baseline: the PERSISTENT chrome registrations (title, info button,
        # scroll). Everything registered past this point is per-render (cards,
        # placeholder) and MUST be pruned from the themed registry when the cards
        # are torn down, or refresh_theme() will style deleted C++ widgets
        # (RuntimeError: object already deleted). See _reset_cards (H6).
        self._chrome_registry_len = len(self.__dict__.get("_themed_registry", []))

        self._show_placeholder("No chart loaded.")

    # ---- style callables (re-evaluated on every theme change) -------------
    def _kicker_style(self):
        t = get_theme_colors()
        return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.8)}; "
                f"font-weight: 700; font-size: {scaled_px(10)}px; letter-spacing: 1.2px; }}")

    def _info_btn_style(self):
        # Bright glyph + faint pill so the help button is clearly visible (the
        # earlier dimmed, transparent, borderless-radius version rendered an
        # almost invisible "?" clipped at the panel edge).
        t = get_theme_colors()
        return (f"QPushButton {{ color: {t['secondary_text']}; "
                f"border: 1px solid {_rgba(t['secondary_light'], 0.7)}; border-radius: {scaled_px(11)}px; "
                f"font-weight: 800; font-size: {scaled_px(13)}px; padding: 0px; "
                f"background: {_rgba(t['secondary_light'], 0.15)}; }}"
                f"QPushButton:hover {{ background: {_rgba(t['primary'], 0.30)}; }}")

    def _scroll_style(self):
        return "QScrollArea { background: transparent; border: none; }"

    def _card_style(self):
        # SPEC-THM-002 W4: a gentle lift off the page, now from the shared ramp
        # rather than a hand-tuned translucent overlay. Level 2 = "card". The
        # brief the old code recorded (soft, low contrast, not a hard dark box
        # with a bright border) is exactly what the ramp plus the E3 rim gives,
        # and it now tracks the theme instead of one alpha guess.
        return elevation_surface_style("QFrame#pcard", 2, scaled_px(10))

    def _placeholder_style(self):
        t = get_theme_colors()
        return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.7)}; "
                f"font-size: {scaled_px(12)}px; padding: {scaled_px(16)}px; }}")

    def viewport(self):
        """Expose the inner scroll viewport so _bind_panel_popup's double-click
        filter reaches the cards (hardening H7). _bind_panel_popup installs its
        filter on any widget that has a viewport()."""
        return self._scroll.viewport()

    # ---- public API -------------------------------------------------------
    def refresh(self, themes, interchanges):
        """Render already-computed engine output (H3/H13: no recompute here)."""
        self._themes = list(themes or [])
        self._interchanges = interchanges or {}
        self._rebuild()

    def clear(self):
        """No chart: a state visibly distinct from 'loaded but no exchange' (H14)."""
        self._themes = None
        self._interchanges = None
        self._reset_cards()
        self._show_placeholder("No chart loaded.")

    def refresh_theme(self):
        """Replay registered styles, then re-render cards from cached data (H13)."""
        self._replay_themed()
        if self._themes is None and self._interchanges is None:
            self._show_placeholder("No chart loaded.")
        else:
            self._rebuild()

    # ---- rendering --------------------------------------------------------
    def _reset_cards(self):
        """Tear down every card row (H6 Rule 18: deleteLater, never raw del).
        Also drops accordion state and closes the (i) popup before a rebuild."""
        if self._doc_dialog is not None:
            self._doc_dialog.close()
            self._doc_dialog = None
        self._open_key = None
        self._details = {}
        self._cards = {}
        # Prune per-render entries from the themed registry so refresh_theme()
        # never styles a deleted card widget (H6). Chrome entries are kept.
        reg = self.__dict__.get("_themed_registry")
        if reg is not None:
            del reg[getattr(self, "_chrome_registry_len", 0):]
        while self._cards_lay.count():
            item = self._cards_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _show_placeholder(self, text):
        self._reset_cards()
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignCenter)
        self._register_themed(lbl, self._placeholder_style)
        self._cards_lay.addWidget(lbl)
        self._cards_lay.addStretch(1)

    def _rebuild(self):
        self._reset_cards()
        themes = self._themes or []
        inter = self._interchanges or {}

        if not themes:
            # Loaded chart but no house frame (no ascendant): distinct from clear().
            self._show_placeholder("This chart has no house frame (no ascendant).")
            return

        # 1. Verdict hero = dominant theme.
        self._cards_lay.addWidget(self._theme_card(themes[0], rank=1, hero=True))

        # 2. Ranked remaining themes.
        if len(themes) > 1:
            self._cards_lay.addWidget(self._section_label("Final Dispositor Themes"))
            for i, th in enumerate(themes[1:], start=2):
                self._cards_lay.addWidget(self._theme_card(th, rank=i, hero=False))

        # 3. Classic exchanges section.
        self._cards_lay.addWidget(self._section_label("Exchanges (Parivartana)"))
        by_type = inter.get("by_type", {})
        any_exchange = any(by_type.get(k) for k in _CLASS_ORDER)
        if not any_exchange:
            note = QLabel("No mutual exchange in this chart.")
            self._register_themed(note, self._placeholder_style)
            self._cards_lay.addWidget(note)
        else:
            for cls in _CLASS_ORDER:
                for rec in by_type.get(cls, []):
                    self._cards_lay.addWidget(self._exchange_card(cls, rec))

        self._cards_lay.addStretch(1)

    def _section_label(self, text):
        lbl = QLabel(text)
        self._register_themed(lbl, self._kicker_style)
        return lbl

    def _sev_chip(self, sem_key, label):
        chip = QLabel(label)
        chip.setAlignment(Qt.AlignCenter)

        def _style(k=sem_key):
            s = pari_sem(k)
            return (f"QLabel {{ color: {s['text']}; background: {_rgba(s['hi'], 0.14)}; "
                    f"border: 1px solid {_rgba(s['hi'], 0.5)}; border-radius: {scaled_px(8)}px; "
                    f"padding: {scaled_px(1)}px {scaled_px(7)}px; font-weight: 700; "
                    f"font-size: {scaled_px(9)}px; }}")
        self._register_themed(chip, _style)
        return chip

    def _house_pills(self, houses):
        row = QHBoxLayout()
        row.setSpacing(scaled_px(4))
        for h in houses:
            pill = QLabel(f"H{h}")

            def _style():
                t = get_theme_colors()
                return (f"QLabel {{ color: {t['secondary_text']}; "
                        f"background: {_rgba(t['secondary_light'], 0.25)}; "
                        f"border-radius: {scaled_px(6)}px; padding: 0 {scaled_px(6)}px; "
                        f"font-size: {scaled_px(9)}px; }}")
            self._register_themed(pill, _style)
            row.addWidget(pill)
        row.addStretch(1)
        w = QWidget()
        w.setLayout(row)
        return w

    def _strength_row(self, basin, sem_key):
        """The strength bar WITH its 'N/7 planets' count inline (one element)."""
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(scaled_px(8))
        bar = _StrengthBar(basin / 7.0, sem_key)
        bar.setToolTip("How many of the 7 planets funnel into this theme (its strength)")
        row.addWidget(bar, 1)
        cap = QLabel(f"{basin}/7 planets")

        def _s():
            t = get_theme_colors()
            return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.75)}; "
                    f"font-size: {scaled_px(10)}px; font-weight: 600; }}")
        self._register_themed(cap, _s)
        row.addWidget(cap)
        return w

    def _houses_line(self, houses):
        """Occupied houses as a plain, quiet line (no pill boxes -> calmer card)."""
        txt = ("Houses " + ", ".join(str(h) for h in houses)) if houses else ""
        lbl = QLabel(txt)

        def _s():
            t = get_theme_colors()
            return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.7)}; "
                    f"font-size: {scaled_px(10)}px; }}")
        self._register_themed(lbl, _s)
        return lbl

    def _body_text(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)

        def _style():
            t = get_theme_colors()
            return (f"QLabel {{ color: {t['secondary_text']}; font-size: {scaled_px(11)}px; "
                    f"line-height: 140%; }}")
        self._register_themed(lbl, _style)
        return lbl

    def _theme_card(self, theme, rank, hero):
        key = f"theme-{rank}"
        card = QFrame()
        card.setObjectName("pcard")
        self._register_themed(card, self._card_style)
        v = QVBoxLayout(card)
        v.setContentsMargins(scaled_px(14), scaled_px(10), scaled_px(14), scaled_px(12))
        v.setSpacing(scaled_px(5))

        planets = theme["cycle_planets"]
        joiner = "  <->  " if theme["is_exchange"] else "  >  "
        title = joiner.join(planets)
        sem_key = theme["severity_key"]

        # Header row: (kicker for hero) + clickable title + severity chip.
        if hero:
            v.addWidget(self._mini_kicker("Dominant Theme"))
        head = QHBoxLayout()
        header = _ClickableLabel(title)
        big = scaled_px(16 if hero else 12) * (1.25 if self._wide else 1.0)

        def _title_style(sz=big, k=sem_key):
            s = pari_sem(k)
            return (f"QLabel {{ color: {s['text']}; font-weight: 800; font-size: {int(sz)}px; }}")
        self._register_themed(header, _title_style)
        header.clicked.connect(lambda k=key: self._toggle(k))
        head.addWidget(header, 1)
        _, cls = _sev_label_for(theme)
        head.addWidget(self._sev_chip(sem_key, _sev_chip_text(theme)))
        v.addLayout(head)

        # ONE integrated strength row: the bar carries its own "N/7 planets"
        # count inline, so strength is a single element (not a sentence strip +
        # a separate bar). Houses follow as a plain quiet line (no pill boxes),
        # so the whole card reads as one block, not five (user feedback).
        v.addWidget(self._strength_row(theme["basin"], sem_key))
        v.addWidget(self._houses_line(theme["occupied_houses"]))

        # Detail (accordion body), hidden unless wide.
        detail = self._theme_detail(theme)
        detail.setVisible(self._wide)
        v.addWidget(detail)
        self._details[key] = detail
        self._cards[key] = card
        if self._wide:
            self._open_key = key
        return card

    def _theme_detail(self, theme):
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, scaled_px(4), 0, 0)
        lay.setSpacing(scaled_px(4))
        rec = theme.get("exchange_record")
        if theme["is_exchange"] and rec is not None:
            pa, sa, ha, pb, sb, hb, cls = rec
            lay.addWidget(self._body_text(f"{pa} ({sa}, H{ha})  <->  {pb} ({sb}, H{hb})"))
            # SPECIFIC per-house-pair reading (not the old general per-type text).
            specific = describe_exchange(ha, hb)
            lay.addWidget(self._body_text(specific or PARIVARTANA_YOGA_FULL.get(cls, "")))
        else:
            # R3: multi-house / self-loop themes have no classical name -> houses + summary.
            hs = ", ".join(f"H{h}" for h in theme["occupied_houses"])
            summary = (f"A theme of {len(theme['cycle_planets'])} planets "
                       f"({', '.join(theme['cycle_planets'])}) funnelling into houses {hs}.")
            if theme["dusthana_houses"]:
                dh = ", ".join(f"H{h}" for h in theme["dusthana_houses"])
                summary += f" It touches the difficult houses {dh}."
            lay.addWidget(self._body_text(summary))
        return box

    def _exchange_card(self, cls, rec):
        key = f"exch-{cls}-{rec[0]}-{rec[3]}"
        sem_key, label = _CLASS_LABEL.get(cls, ("neutral", cls))
        card = QFrame()
        card.setObjectName("pcard")
        self._register_themed(card, self._card_style)
        v = QVBoxLayout(card)
        v.setContentsMargins(scaled_px(14), scaled_px(8), scaled_px(14), scaled_px(10))
        v.setSpacing(scaled_px(4))

        head = QHBoxLayout()
        header = _ClickableLabel(label)

        def _hs(k=sem_key):
            s = pari_sem(k)
            return f"QLabel {{ color: {s['text']}; font-weight: 700; font-size: {scaled_px(12)}px; }}"
        self._register_themed(header, _hs)
        header.clicked.connect(lambda k=key: self._toggle(k))
        head.addWidget(header, 1)
        head.addWidget(self._sev_chip(sem_key, label.split()[0].upper()))
        v.addLayout(head)

        pa, sa, ha, pb, sb, hb, _ = rec
        v.addWidget(self._body_text(f"{pa} ({sa}, H{ha})  <->  {pb} ({sb}, H{hb})"))

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, scaled_px(4), 0, 0)
        # SPECIFIC per-house-pair reading (rec houses at index 2 and 5).
        specific = describe_exchange(rec[2], rec[5])
        dl.addWidget(self._body_text(specific or PARIVARTANA_YOGA_FULL.get(cls, "")))
        detail.setVisible(self._wide)
        v.addWidget(detail)
        self._details[key] = detail
        self._cards[key] = card
        return card

    def _mini_kicker(self, text):
        lbl = QLabel(text)

        def _style():
            t = get_theme_colors()
            return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.7)}; font-weight: 700; "
                    f"font-size: {scaled_px(8)}px; letter-spacing: 1.5px; }}")
        self._register_themed(lbl, _style)
        return lbl

    # ---- accordion --------------------------------------------------------
    def _toggle(self, key):
        """Exclusive accordion: open `key`, collapse the previously open one."""
        if self._wide:
            return  # everything is pre-expanded in the pop-out
        detail = self._details.get(key)
        if detail is None:
            return
        if self._open_key == key:
            detail.setVisible(False)
            self._open_key = None
            return
        if self._open_key is not None:
            prev = self._details.get(self._open_key)
            if prev is not None:
                prev.setVisible(False)
        detail.setVisible(True)
        self._open_key = key
        card = self._cards.get(key)
        if card is not None:
            self._scroll.ensureWidgetVisible(card)

    # ---- (i) tutorial popup (the ONLY popup) ------------------------------
    def _open_tutorial(self):
        if self._doc_dialog is not None:
            self._doc_dialog.close()
            self._doc_dialog = None
        theme = get_theme_colors()
        dlg = QDialog(self)  # parented to the widget, never to a card (H6)
        dlg.setWindowTitle(_DOC_TITLE)
        dlg.setModal(False)
        dlg.setMinimumWidth(scaled_px(460))
        dlg.setStyleSheet(
            f"QDialog {{ background: {theme['secondary_dark']}; }}"
            f"QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(scaled_px(18), scaled_px(16), scaled_px(18), scaled_px(14))
        lay.setSpacing(scaled_px(6))
        title = QLabel(_DOC_TITLE)
        title.setStyleSheet(
            f"color: {pari_sem('maha')['hi']}; font-weight: 800; font-size: {scaled_px(17)}px;")
        title.setWordWrap(True)
        lay.addWidget(title)

        # Sections live in a bounded scroll area: exchange doc + house-type
        # reference together are taller than one dialog, so keep it on-screen.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(scaled_px(460))
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        content = QWidget()
        clay = QVBoxLayout(content)
        clay.setContentsMargins(0, 0, scaled_px(8), 0)
        clay.setSpacing(scaled_px(6))

        def _add_section(kicker, body):
            k = QLabel(kicker)
            k.setStyleSheet(
                f"color: {dim_text(theme['secondary_text'], 0.75)}; font-weight: 700; "
                f"font-size: {scaled_px(9)}px; letter-spacing: 1.5px; margin-top: {scaled_px(6)}px;")
            clay.addWidget(k)
            b = QLabel(body)
            b.setWordWrap(True)
            b.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_px(11)}px;")
            clay.addWidget(b)

        for kicker, body in _DOC_SECTIONS:
            _add_section(kicker, body)

        # Divider heading, then the PAC7 house-type reference.
        heading = QLabel(_HOUSE_TYPE_HEADING)
        heading.setWordWrap(True)
        heading.setStyleSheet(
            f"color: {pari_sem('maha')['hi']}; font-weight: 800; font-size: {scaled_px(13)}px; "
            f"margin-top: {scaled_px(12)}px; border-top: 1px solid {_rgba(theme['secondary_light'], 0.5)}; "
            f"padding-top: {scaled_px(10)}px;")
        clay.addWidget(heading)
        for kicker, body in _HOUSE_TYPE_SECTIONS:
            _add_section(kicker, body)

        clay.addStretch(1)
        scroll.setWidget(content)
        lay.addWidget(scroll)

        close = QPushButton("Close")
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{ color: {theme['secondary_text']}; "
            f"border: 1px solid {_rgba(theme['secondary_light'], 0.6)}; border-radius: {scaled_px(6)}px; "
            f"padding: {scaled_px(4)}px {scaled_px(14)}px; }}"
            f"QPushButton:hover {{ background: {_rgba(theme['primary'], 0.2)}; }}")
        close.clicked.connect(dlg.close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
        self._doc_dialog = dlg  # retain so it is not GC'd while shown (H6)
        dlg.show()


def _sev_label_for(theme):
    """(sem_key, classification) for a theme."""
    return theme["severity_key"], theme.get("classification")


def _sev_chip_text(theme):
    """Short uppercase chip text for a theme's severity."""
    cls = theme.get("classification")
    if cls and cls in _CLASS_LABEL:
        return _CLASS_LABEL[cls][1].split()[0].upper()
    if theme["cycle_size"] == 1:
        return "SELF"
    return "THEME"
