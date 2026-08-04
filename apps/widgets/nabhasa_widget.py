# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Nabhasa Yogas panel widget (Option B: family sections + ranked cards).
======================================================================
A Parivartana-style card stack for the whole-chart Nabhasa yogas:

  * a HERO card for the prevalent Akriti ("the shape of your chart"),
  * a FOUNDATION section (prevalent Asraya modality, the comparative Dala reading,
    the exact Sankhya number),
  * a SHAPE section: the 20 canonical Akriti ranked by how nearly they form,
  * a PERSONAGE section: the 5 Pancha Mahapurusha yogas, formed or not.

Each Akriti card carries a [view combination] button that opens a small, movable,
non-modal popup drawing the yoga's defining house pattern in BOTH North and South
Indian styles (spec §5), so the user drags it beside their own chart to compare.
That affordance is disabled while the app shows the WHEEL chart (the comparison is
house-grid to house-grid).

Presentation only: refresh() takes ALREADY-COMPUTED adapter output (H3/H13, the
controller frames the chart and calls the adapter), so this widget never reads GUI
state. Colours come from ui/qt_theme.py; NO raw hex. Imports NOTHING from pro/
(H11): the strength bar is duplicated here and the doctrine text lives inline.
"""

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QPainter, QColor, QLinearGradient, QBrush
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea,
    QPushButton, QSizePolicy, QDialog,
)

from ui.themed_style import ThemedStyleMixin
from ui.qt_theme import (
    get_theme_colors, pari_sem, dim_text, scaled_px, elevation_surface_style,
)
from AI_tools.AI_main_function.nabhasa_descriptions import (
    describe_nabhasa_yoga, DOC_TITLE, DOC_SECTIONS, PMP_ESCALATION,
)
from apps.widgets.nabhasa_diagram import DualNabhasaDiagram, SEM_FOR_AUSPICIOUSNESS

# Fixed benefic/malefic house split for the two distribution Akriti (drawn apart
# in the diagram popup). Vajra: benefics 1/7, malefics 4/10. Yava: the reverse.
_SPLIT_HOUSES = {
    "Vajra": {"benefic": (1, 7), "malefic": (4, 10)},
    "Yava": {"benefic": (4, 10), "malefic": (1, 7)},
}


# SPEC-THM-002 W4: re-export of the shared helper (was a private duplicate).
from ui.qt_theme import _alpha as _rgba  # noqa: F401


def _sem_for(auspiciousness):
    return SEM_FOR_AUSPICIOUSNESS.get(auspiciousness, "neutral")


def _dala_sem(dominant):
    return {"Mala": "maha", "Sarpa": "dainya8",
            "balanced": "khala", "none": "neutral"}.get(dominant, "neutral")


class _StrengthBar(QWidget):
    """Slim strength bar (rounded track + gradient fill). Duplicated, not
    imported from pro/ (H11). Reads the severity colour live so it restyles on a
    theme switch."""

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
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setWordWrap(True)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class NabhasaWidget(ThemedStyleMixin, QWidget):
    """Nabhasa yogas card stack. Public API mirrors the sibling panels:
    refresh(result[, wheel_mode]) / clear() / refresh_theme(). ``wide=True``
    (fullscreen pop-out) pre-expands every card."""

    def __init__(self, wide=False, parent=None):
        super().__init__(parent)
        self._wide = wide
        self._result = None            # last-rendered adapter output (H13)
        self._asc_sign_index = None    # ascendant sign (0-11) for the South grid
        self._wheel_mode = False       # active chart display is the wheel?
        self._open_key = None          # exclusive-accordion open card id
        self._details = {}
        self._cards = {}
        self._combo_buttons = []       # [view combination] buttons (wheel gating)
        self._doc_dialog = None        # retained non-modal (i) popup (H6)
        self._combo_dialog = None      # retained non-modal diagram popup (H6)
        self._combo_diagram = None     # the DualNabhasaDiagram inside _combo_dialog
        self._combo_sig = None         # chart signature the open popup was built for

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(scaled_px(4))

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, scaled_px(4), 0)
        self._title = QLabel("Nabhasa Yogas")
        self._register_themed(self._title, self._kicker_style)
        header.addWidget(self._title)
        header.addStretch(1)
        self._info_btn = QPushButton("?")
        self._info_btn.setFixedSize(scaled_px(22), scaled_px(22))
        self._info_btn.setCursor(Qt.PointingHandCursor)
        self._info_btn.setToolTip("Learn what the Nabhasa yogas are")
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

        # Baseline for the H6 per-render prune (see _reset_cards).
        self._chrome_registry_len = len(self.__dict__.get("_themed_registry", []))
        self._show_placeholder("No chart loaded.")

    # ---- style callables --------------------------------------------------
    def _kicker_style(self):
        t = get_theme_colors()
        return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.8)}; "
                f"font-weight: 700; font-size: {scaled_px(10)}px; letter-spacing: 1.2px; }}")

    def _info_btn_style(self):
        t = get_theme_colors()
        return (f"QPushButton {{ color: {t['secondary_text']}; "
                f"border: 1px solid {_rgba(t['secondary_light'], 0.7)}; border-radius: {scaled_px(11)}px; "
                f"font-weight: 800; font-size: {scaled_px(13)}px; padding: 0px; "
                f"background: {_rgba(t['secondary_light'], 0.15)}; }}"
                f"QPushButton:hover {{ background: {_rgba(t['primary'], 0.30)}; }}")

    def _scroll_style(self):
        return "QScrollArea { background: transparent; border: none; }"

    def _card_style(self):
        # SPEC-THM-002 W4: shared elevation ramp, level 2 ("card").
        return elevation_surface_style("QFrame#ncard", 2, scaled_px(10))

    def _placeholder_style(self):
        t = get_theme_colors()
        return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.7)}; "
                f"font-size: {scaled_px(12)}px; padding: {scaled_px(16)}px; }}")

    def viewport(self):
        """Expose the scroll viewport so _bind_panel_popup's double-click filter
        reaches the cards (H7)."""
        return self._scroll.viewport()

    # ---- public API -------------------------------------------------------
    def refresh(self, result, wheel_mode=None):
        """Render already-computed adapter output (no recompute here, H3/H13)."""
        self._result = result
        asc = (result or {}).get("asc_sign_index")
        self._asc_sign_index = asc if isinstance(asc, int) and asc >= 0 else None
        if wheel_mode is not None:
            self._wheel_mode = bool(wheel_mode)
        self._rebuild()
        # The combination popup is ascendant-anchored (chart-dependent), so it must
        # not outlive a chart change: close it when the underlying chart differs.
        # A cosmetic re-render (same chart, font/theme) keeps the same signature,
        # so the popup survives and is only re-themed.
        if self._combo_dialog is not None and self._result_signature() != self._combo_sig:
            self._combo_dialog.close()
            self._combo_dialog = None
            self._combo_diagram = None
        else:
            self._retheme_combo_popup()

    def clear(self):
        self._result = None
        self._close_popups()
        self._reset_cards()
        self._show_placeholder("No chart loaded.")

    def refresh_theme(self):
        self._replay_themed()
        if self._result is None:
            self._show_placeholder("No chart loaded.")
        else:
            self._rebuild()
        # A theme/font refresh must NOT close an open popup (that defeats the
        # diagram's built-in live re-theming). Re-theme it in place instead.
        self._retheme_combo_popup()

    def _retheme_combo_popup(self):
        """Re-skin an open combination popup in place: the diagram content (live)
        AND the dialog background (frozen at build time otherwise)."""
        if self._combo_diagram is None:
            return
        try:
            self._combo_diagram.refresh_theme()
            if self._combo_dialog is not None:
                self._combo_dialog.setStyleSheet(
                    f"QDialog {{ background: {get_theme_colors()['secondary_dark']}; }}")
        except RuntimeError:
            # The C++ dialog was destroyed out from under us; drop the refs.
            self._combo_dialog = None
            self._combo_diagram = None

    def set_wheel_mode(self, on):
        """Called by the controller when the chart display mode changes. Greys
        out the [view combination] affordance in wheel mode (spec §5).
        # NABHASA-REVIEW: R6 the controller must call this from the chart-display
        #   mode signal so the button state tracks wheel/diamond live.
        """
        self._wheel_mode = bool(on)
        for btn in self._combo_buttons:
            self._apply_combo_enabled(btn)
        # The diagram compares house-grid to house-grid, so it is meaningless in
        # wheel mode: close it (but leave the tutorial popup alone).
        if self._wheel_mode and self._combo_dialog is not None:
            self._combo_dialog.close()
            self._combo_dialog = None
            self._combo_diagram = None

    def _close_popups(self):
        """Close and drop both retained popups. Called on clear() and on new
        chart data (which makes an open combination popup stale), NOT on a
        per-render theme/font refresh (that re-themes an open popup in place)."""
        for attr in ("_doc_dialog", "_combo_dialog"):
            dlg = getattr(self, attr, None)
            if dlg is not None:
                dlg.close()
                setattr(self, attr, None)
        self._combo_diagram = None

    # ---- teardown / placeholder ------------------------------------------
    def _reset_cards(self):
        """Tear down cards (H6 Rule 18: deleteLater). Drops accordion state and
        prunes per-render themed entries. Does NOT touch the retained popups:
        their lifecycle is data/clear-scoped, not per-render, so a theme or font
        refresh re-themes an open popup in place rather than closing it."""
        self._open_key = None
        self._details = {}
        self._cards = {}
        self._combo_buttons = []
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

    # ---- rendering --------------------------------------------------------
    def _rebuild(self):
        self._reset_cards()
        res = self._result or {}
        if not res.get("available"):
            self._show_placeholder("This chart has no house frame (no ascendant).")
            return

        # 1. Hero = prevalent Akriti ("the shape of your chart").
        hero = res.get("akriti", {}).get("prevalent")
        if hero:
            self._cards_lay.addWidget(self._akriti_card(hero, hero=True))

        # 2. Foundation section.
        self._cards_lay.addWidget(self._section_label("Foundation"))
        asr = res.get("asraya", {}).get("prevalent")
        if asr:
            self._cards_lay.addWidget(self._simple_yoga_card(
                asr, key="asraya", kicker="Asraya (modality)"))
        dala = res.get("dala", {}).get("majority")
        if dala:
            self._cards_lay.addWidget(self._dala_card(dala))
        sankhya = res.get("sankhya", {}).get("active")
        if sankhya:
            self._cards_lay.addWidget(self._simple_yoga_card(
                sankhya, key="sankhya", kicker="Sankhya (number)", badge="now"))

        # 3. Shape section (20 canonical Akriti, most-formed first).
        self._cards_lay.addWidget(self._section_label("Shape (Akriti)"))
        # Nearest-formation doctrine (applies to every Akriti): the closer the
        # chart comes to the complete shape, the stronger its effect.
        self._cards_lay.addWidget(self._quiet_line(
            "Read by nearest formation: the closer to the complete shape, the "
            "stronger the effect."))
        for i, ak in enumerate(res.get("akriti", {}).get("ranked", [])):
            self._cards_lay.addWidget(self._akriti_card(ak, hero=False, idx=i))

        # 4. Personage section (Pancha Mahapurusha).
        self._cards_lay.addWidget(self._section_label("Great personage (Pancha Mahapurusha)"))
        pmp = res.get("panchamahapurusha", [])
        formed_count = sum(1 for y in pmp if y.get("formed"))
        for y in pmp:
            self._cards_lay.addWidget(self._pmp_card(y))
        if formed_count > 1:
            self._cards_lay.addWidget(self._escalation_note(formed_count))

        self._cards_lay.addStretch(1)
        # Apply current wheel gating to freshly built buttons.
        for btn in self._combo_buttons:
            self._apply_combo_enabled(btn)

    # ---- shared card pieces ----------------------------------------------
    def _section_label(self, text):
        lbl = QLabel(text)
        self._register_themed(lbl, self._kicker_style)
        return lbl

    def _mini_kicker(self, text):
        lbl = QLabel(text)

        def _style():
            t = get_theme_colors()
            return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.7)}; font-weight: 700; "
                    f"font-size: {scaled_px(8)}px; letter-spacing: 1.5px; }}")
        self._register_themed(lbl, _style)
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

    def _strength_row(self, frac, sem_key, caption):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(scaled_px(8))
        bar = _StrengthBar(frac, sem_key)
        row.addWidget(bar, 1)
        cap = QLabel(caption)

        def _s():
            t = get_theme_colors()
            return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.75)}; "
                    f"font-size: {scaled_px(10)}px; font-weight: 600; }}")
        self._register_themed(cap, _s)
        row.addWidget(cap)
        return w

    def _body_text(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)

        def _style():
            t = get_theme_colors()
            return (f"QLabel {{ color: {t['secondary_text']}; font-size: {scaled_px(11)}px; }}")
        self._register_themed(lbl, _style)
        return lbl

    def _quiet_line(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)

        def _s():
            t = get_theme_colors()
            return (f"QLabel {{ color: {dim_text(t['secondary_text'], 0.7)}; "
                    f"font-size: {scaled_px(10)}px; }}")
        self._register_themed(lbl, _s)
        return lbl

    def _reading_detail(self, name):
        """Accordion body: the yoga's reading + classical citation."""
        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, scaled_px(4), 0, 0)
        lay.setSpacing(scaled_px(4))
        entry = describe_nabhasa_yoga(name)
        if entry:
            lay.addWidget(self._body_text(entry["reading"]))
            lay.addWidget(self._quiet_line("Source: " + entry["cite"]))
        else:
            lay.addWidget(self._quiet_line("pending"))
        return box

    def _new_card(self):
        card = QFrame()
        card.setObjectName("ncard")
        self._register_themed(card, self._card_style)
        return card

    def _attach_detail(self, card, v, key, detail):
        detail.setVisible(self._wide)
        v.addWidget(detail)
        self._details[key] = detail
        self._cards[key] = card
        if self._wide:
            self._open_key = key

    # ---- Akriti card (with the movable-diagram affordance) ----------------
    def _akriti_card(self, ak, hero, idx=0):
        name = ak["name"]
        variant = ak.get("variant")
        key = f"akriti-{'hero' if hero else idx}-{name}"
        sem_key = _sem_for(_auspiciousness_of(name))
        card = self._new_card()
        v = QVBoxLayout(card)
        v.setContentsMargins(scaled_px(14), scaled_px(10), scaled_px(14), scaled_px(12))
        v.setSpacing(scaled_px(5))

        if hero:
            v.addWidget(self._mini_kicker("The shape of your chart"))

        head = QHBoxLayout()
        label = name if not variant else f"{name} ({variant})"
        trans = ak.get("translation")
        if trans:
            label = f"{label}  ·  {trans}"
        header = _ClickableLabel(label)
        big = scaled_px(15 if hero else 12) * (1.25 if self._wide else 1.0)

        def _title_style(sz=big, k=sem_key):
            s = pari_sem(k)
            return f"QLabel {{ color: {s['text']}; font-weight: 800; font-size: {int(sz)}px; }}"
        self._register_themed(header, _title_style)
        header.clicked.connect(lambda k=key: self._toggle(k))
        head.addWidget(header, 1)
        head.addWidget(self._sev_chip(sem_key, "FORMED" if ak.get("formed") else _short_frac(ak)))
        v.addLayout(head)

        v.addWidget(self._strength_row(
            ak.get("strength_fraction", 0.0), sem_key, _short_frac(ak)))

        # R2 RESOLVED (Lorris 2026-07-14): every Akriti, Vajra/Yava included, is
        # read by NEAREST formation. No "never forms" wording; the strength bar
        # already shows how near, and the [view combination] popup shows the
        # complete (strongest) shape to compare against.
        houses = ak.get("houses", ())
        line = "Houses " + ", ".join(str(h) for h in houses) if houses else ""
        v.addWidget(self._quiet_line(line))

        # [view combination] opens the movable dual-diagram popup.
        self._add_combo(v, ak)

        self._attach_detail(card, v, key, self._reading_detail(name))
        return card

    def _add_combo(self, layout, item):
        """Attach a [view combination] button that opens the dual-diagram popup
        for any yoga that carries a house set (Akriti, Asraya, Dala, Sankhya)."""
        if not item.get("houses"):
            return
        combo = QPushButton("view combination")
        combo.setCursor(Qt.PointingHandCursor)
        self._register_themed(combo, self._combo_btn_style)
        combo.clicked.connect(lambda _=False, a=item: self._open_combination(a))
        self._combo_buttons.append(combo)
        crow = QHBoxLayout()
        crow.addWidget(combo)
        crow.addStretch(1)
        layout.addLayout(crow)

    def _combo_btn_style(self):
        t = get_theme_colors()
        return (f"QPushButton {{ color: {t['secondary_text']}; "
                f"border: 1px solid {_rgba(t['secondary_light'], 0.5)}; border-radius: {scaled_px(6)}px; "
                f"padding: {scaled_px(2)}px {scaled_px(10)}px; font-size: {scaled_px(10)}px; }}"
                f"QPushButton:hover {{ background: {_rgba(t['primary'], 0.20)}; }}"
                f"QPushButton:disabled {{ color: {dim_text(t['secondary_text'], 0.35)}; "
                f"border-color: {_rgba(t['secondary_light'], 0.2)}; }}")

    def _apply_combo_enabled(self, btn):
        btn.setEnabled(not self._wheel_mode)
        btn.setToolTip(
            "Switch to a diamond or square chart to compare"
            if self._wheel_mode else
            "Open the yoga's defining pattern in North + South Indian styles")

    # ---- Foundation cards -------------------------------------------------
    def _simple_yoga_card(self, yoga, key, kicker, badge=None):
        """A no-diagram card for Asraya / Sankhya (a modality or a number, not a
        house shape)."""
        name = yoga["name"]
        sem_key = _sem_for(_auspiciousness_of(name))
        card = self._new_card()
        v = QVBoxLayout(card)
        v.setContentsMargins(scaled_px(14), scaled_px(8), scaled_px(14), scaled_px(10))
        v.setSpacing(scaled_px(4))
        v.addWidget(self._mini_kicker(kicker))
        head = QHBoxLayout()
        label = name
        if yoga.get("translation"):
            label = f"{name}  ·  {yoga['translation']}"
        header = _ClickableLabel(label)

        def _hs(k=sem_key):
            s = pari_sem(k)
            return f"QLabel {{ color: {s['text']}; font-weight: 700; font-size: {scaled_px(12)}px; }}"
        self._register_themed(header, _hs)
        header.clicked.connect(lambda k=key: self._toggle(k))
        head.addWidget(header, 1)
        if badge:
            head.addWidget(self._sev_chip(sem_key, badge.upper()))
        v.addLayout(head)
        v.addWidget(self._strength_row(
            yoga.get("strength_fraction", 0.0), sem_key, _short_frac(yoga)))
        # Asraya (the four modality signs) and Sankhya (the occupied houses) now
        # carry a house set, so they get a combination diagram too.
        self._add_combo(v, yoga)
        self._attach_detail(card, v, key, self._reading_detail(name))
        return card

    def _dala_card(self, dala):
        dominant = dala.get("dominant", "none")
        sem_key = _dala_sem(dominant)
        # The named yoga for the reading (Mala/Sarpa); balanced/none has no name.
        read_name = {"Mala": "Mala", "Sarpa": "Sarpa"}.get(dominant)
        key = "dala"
        card = self._new_card()
        v = QVBoxLayout(card)
        v.setContentsMargins(scaled_px(14), scaled_px(8), scaled_px(14), scaled_px(10))
        v.setSpacing(scaled_px(4))
        v.addWidget(self._mini_kicker("Dala (angles)"))
        head = QHBoxLayout()
        label = {"Mala": "Mala  ·  garland", "Sarpa": "Sarpa  ·  serpent",
                 "balanced": "Balanced angles", "none": "No planets in the angles",
                 "pending": "pending"}.get(dominant, dominant)
        header = _ClickableLabel(label)

        def _hs(k=sem_key):
            s = pari_sem(k)
            return f"QLabel {{ color: {s['text']}; font-weight: 700; font-size: {scaled_px(12)}px; }}"
        self._register_themed(header, _hs)
        header.clicked.connect(lambda k=key: self._toggle(k))
        head.addWidget(header, 1)
        v.addLayout(head)
        v.addWidget(self._quiet_line(dala.get("ratio_text", "")))

        # Combination diagram: the four kendras, gentle ones tinted benefic and
        # cruel ones malefic. Skipped only when the reading is pending (a guess).
        if dominant != "pending":
            self._add_combo(v, {
                "name": read_name or "Dala (angles)",
                "houses": dala.get("angle_houses", (1, 4, 7, 10)),
                "benefic": dala.get("gentle_houses", ()),
                "malefic": dala.get("cruel_houses", ()),
                "subtitle": "the four angles (kendras)",
                "auspiciousness": _auspiciousness_of(read_name) if read_name else "mixed",
            })

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(0, scaled_px(4), 0, 0)
        if read_name:
            entry = describe_nabhasa_yoga(read_name)
            dl.addWidget(self._body_text(entry["reading"]))
            dl.addWidget(self._quiet_line("Source: " + entry["cite"]))
        elif dominant == "pending":
            # The engine could not resolve a planet's nature; never guess a
            # reading (a wrong-but-confident value is the forbidden outcome).
            dl.addWidget(self._body_text(
                "The gentle or cruel nature of a planet at the angles could not be "
                "resolved for this chart, so the Dala reading is left pending "
                "rather than guessed."))
        elif dominant == "none":
            dl.addWidget(self._body_text(
                "No planet occupies the four angles, so no Dala yoga forms here; "
                "the structure of the life is set by the other Nabhasa families."))
        else:  # balanced
            dl.addWidget(self._body_text(
                "The gentle and cruel planets are evenly matched at the angles, so "
                "the life reads as neither strongly supported nor strongly pressured "
                "by its structure (roughly fifty-fifty)."))
        self._attach_detail(card, v, key, detail)
        return card

    # ---- Personage cards --------------------------------------------------
    def _pmp_card(self, y):
        name = y["name"]
        planet = y.get("planet", "")
        formed = y.get("formed")
        cancelled = y.get("cancelled")
        key = f"pmp-{name}"
        sem_key = "maha" if formed else ("khala" if cancelled else "neutral")
        card = self._new_card()
        v = QVBoxLayout(card)
        v.setContentsMargins(scaled_px(14), scaled_px(8), scaled_px(14), scaled_px(10))
        v.setSpacing(scaled_px(4))
        head = QHBoxLayout()
        header = _ClickableLabel(f"{name}  ·  {planet}")

        def _hs(k=sem_key):
            s = pari_sem(k)
            weight = 800 if formed else 600
            return f"QLabel {{ color: {s['text']}; font-weight: {weight}; font-size: {scaled_px(12)}px; }}"
        self._register_themed(header, _hs)
        header.clicked.connect(lambda k=key: self._toggle(k))
        head.addWidget(header, 1)
        if formed:
            chip = "FORMED"
        elif cancelled:
            chip = "CANCELLED"
        else:
            chip = "not formed"
        head.addWidget(self._sev_chip(sem_key, chip))
        v.addLayout(head)

        # A quiet status line explaining WHY (house/dignity/cancellation).
        house = y.get("house")
        dig = y.get("dignity")
        if formed:
            status = f"{planet} in house {house}, {_dignity_word(dig)}."
        elif cancelled:
            status = (f"{planet} would form it (house {house}, {_dignity_word(dig)}) "
                      f"but {y.get('cancel_reason', 'the luminary conjunction')} "
                      f"cancels it.")
        elif y.get("mt_only"):
            # Angular + moolatrikona: forms under the wider classical rule, but
            # this app follows Ernst (own/exaltation only), so explain the miss.
            status = (f"{planet} is angular (house {house}) in its moolatrikona "
                      f"sign. The wider classical rule would form {name}, but this "
                      f"panel follows Ernst Wilhelm's rule (only own sign or "
                      f"exaltation counts), so it does not form here.")
        else:
            status = f"{planet} in house {house}, {_dignity_word(dig)}."
        v.addWidget(self._quiet_line(status))

        self._attach_detail(card, v, key, self._reading_detail(name))
        return card

    def _escalation_note(self, count):
        note = QLabel(f"{PMP_ESCALATION.get(count, '')}  (Source: {PMP_ESCALATION['cite']})")
        note.setWordWrap(True)
        self._register_themed(note, self._placeholder_style)
        return note

    # ---- accordion --------------------------------------------------------
    def _toggle(self, key):
        if self._wide:
            return
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

    # ---- movable dual-diagram popup ---------------------------------------
    def _result_signature(self):
        """A cheap per-chart signature: the ascendant plus the ranked Akriti
        identities. Equal across a cosmetic re-render of the same chart, different
        the moment a new chart is loaded — used to decide whether an open
        combination popup is still valid (it is ascendant-anchored)."""
        res = self._result or {}
        akriti = tuple((r.get("name"), r.get("to_move"))
                       for r in res.get("akriti", {}).get("ranked", []))
        return (res.get("asc_sign_index"), akriti)

    def _open_combination(self, ak):
        if self._wheel_mode:
            return
        if self._combo_dialog is not None:
            self._combo_dialog.close()
            self._combo_dialog = None
            self._combo_diagram = None
        theme = get_theme_colors()
        dlg = QDialog(self)          # parented to the widget, never a card (H6)
        dlg.setWindowTitle("Yoga combination")
        dlg.setModal(False)
        dlg.setStyleSheet(f"QDialog {{ background: {theme['secondary_dark']}; }}")
        lay = QVBoxLayout(dlg)
        m = scaled_px(8)
        lay.setContentsMargins(m, m, m, m)
        diagram = DualNabhasaDiagram(dlg)
        name = ak["name"]
        variant = ak.get("variant")
        title = name if not variant else f"{name} ({variant})"
        # Vajra/Yava carry a fixed benefic/malefic split; other families pass
        # their own split (Dala's gentle/cruel angles) or none.
        split = _SPLIT_HOUSES.get(name, {})
        benefic = ak.get("benefic") or split.get("benefic", ())
        malefic = ak.get("malefic") or split.get("malefic", ())
        houses = ak.get("houses", ())
        caption = ak.get("subtitle") or (
            ("Houses " + ", ".join(str(h) for h in houses)) if houses else "")
        diagram.set_yoga(
            title, houses, caption=caption,
            benefic=benefic, malefic=malefic,
            auspiciousness=ak.get("auspiciousness") or _auspiciousness_of(name),
            asc_sign_index=self._asc_sign_index)
        lay.addWidget(diagram)
        dlg.resize(scaled_px(380), scaled_px(240))
        self._combo_dialog = dlg     # retained so it is not GC'd (H6)
        self._combo_diagram = diagram  # kept so refresh_theme() can re-skin it live
        self._combo_sig = self._result_signature()  # close it if the chart changes
        dlg.show()

    # ---- (i) tutorial popup ----------------------------------------------
    def _open_tutorial(self):
        if self._doc_dialog is not None:
            self._doc_dialog.close()
            self._doc_dialog = None
        theme = get_theme_colors()
        dlg = QDialog(self)
        dlg.setWindowTitle(DOC_TITLE)
        dlg.setModal(False)
        dlg.setMinimumWidth(scaled_px(460))
        dlg.setStyleSheet(
            f"QDialog {{ background: {theme['secondary_dark']}; }}"
            f"QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(scaled_px(18), scaled_px(16), scaled_px(18), scaled_px(14))
        lay.setSpacing(scaled_px(6))
        title = QLabel(DOC_TITLE)
        title.setStyleSheet(
            f"color: {pari_sem('maha')['hi']}; font-weight: 800; font-size: {scaled_px(16)}px;")
        title.setWordWrap(True)
        lay.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMaximumHeight(scaled_px(460))
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        content = QWidget()
        clay = QVBoxLayout(content)
        clay.setContentsMargins(0, 0, scaled_px(8), 0)
        clay.setSpacing(scaled_px(6))
        for kicker, body in DOC_SECTIONS:
            k = QLabel(kicker)
            k.setStyleSheet(
                f"color: {dim_text(theme['secondary_text'], 0.75)}; font-weight: 700; "
                f"font-size: {scaled_px(9)}px; letter-spacing: 1.5px; margin-top: {scaled_px(6)}px;")
            clay.addWidget(k)
            b = QLabel(body)
            b.setWordWrap(True)
            b.setStyleSheet(f"color: {theme['secondary_text']}; font-size: {scaled_px(11)}px;")
            clay.addWidget(b)
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
        self._doc_dialog = dlg
        dlg.show()


# --- module helpers --------------------------------------------------------
def _auspiciousness_of(name):
    entry = describe_nabhasa_yoga(name)
    return entry["auspiciousness"] if entry else "mixed"


def _short_frac(yoga):
    """'N/7 planets' style caption from a yoga's to_move."""
    to_move = yoga.get("to_move")
    if to_move is None:
        return ""
    return f"{7 - to_move}/7 planets"


def _dignity_word(dig):
    return {"OH": "own sign", "EX": "exaltation", "MT": "moolatrikona",
            "E": "enemy sign", "GE": "great enemy sign", "F": "friend sign",
            "GF": "great friend sign", "N": "neutral sign",
            "DB": "debilitation"}.get(dig, dig or "unresolved")
