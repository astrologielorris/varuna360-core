# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Add Chart Dialog (Qt) - Birth Chart Creation from natural language input.
PySide6 dialog — uses offline regex parser (text_to_chtk) + geocoding.
"""

import html
import math
import re

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QFrame, QMessageBox, QCheckBox, QLineEdit
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QFont, QTextCursor, QKeySequence, QGuiApplication
from ui.image_paste import extract_image as _extract_clipboard_image

from ui.qt_theme import (
    SURFACE, BG, BORDER, TEXT_PRIMARY, TEXT_SECONDARY,
    STATUS, HOVER, get_theme_colors, scaled_area_font
)
# Issue 8b-R: Chart-Everywhere — uses core.chart_factory directly.


# ---------------------------------------------------------------------------
# Review mode (SPEC-TRN-005 D-6): AddChartDialog doubles as the review surface
# for LLM-extracted chart data. B5 (the future caller) hands us a structured
# extraction payload; the dialog pre-fills a canonical, re-parseable line and
# shows a read-only detected-fields summary + source snippet. The user may edit
# the text freely before Generate — the pipeline reparse is the truth, never
# the payload.
# ---------------------------------------------------------------------------

# Auto-confirm gate threshold (SPEC-TRN-005 §4 "Auto-confirm extension").
# When the dialog is opened in review mode AND the user has opted into
# auto-confirm AND the extraction's `confidence` is at least this value, the
# dialog fires Generate itself without waiting for a click. The B5 caller
# decides whether to even open the dialog; this constant is the dialog's OWN
# independent gate so a low-confidence payload can never auto-fire. Confidence
# is a 0.0–1.0 float in the extraction contract; 0.85 == "high confidence".
REVIEW_AUTO_CONFIRM_CONFIDENCE_THRESHOLD = 0.85

# Source snippet longer than this (characters) is elided in the read-only
# display (full text preserved in the widget tooltip).
SOURCE_SNIPPET_MAX_CHARS = 200

# Canonical field order for the re-parseable prefill line. Matches the
# "Name, Date, Time, Location" shape parse_birth_text accepts.
_REVIEW_LINE_FIELDS = ("name", "date", "time", "place")


# ---------------------------------------------------------------------------
# SHARED strict validators for LLM-extraction payload fields (td-c9u4.5 F4).
# ONE implementation used by BOTH pro.managers.reading_date_extraction
# (outcome normalization) and this dialog's _should_auto_confirm gate, so the
# two layers can never diverge on what counts as a trustworthy confidence /
# a non-ambiguous payload. They live HERE (core ui/, not pro/) because the
# Lite build ships this dialog without pro/ — the import direction must be
# pro -> ui, never ui -> pro.
# ---------------------------------------------------------------------------

def strict_confidence(value) -> float:
    """Fail-CLOSED confidence coercion.

    Accepts ONLY a real int/float instance (bool is rejected even though it
    subclasses int: JSON ``true`` must never become 1.0; numeric STRINGS like
    "0.99" are rejected — a model that cannot follow the number contract does
    not get to auto-confirm), finite, inside [0.0, 1.0]. Anything else maps
    to 0.0, which routes to review and can never auto-confirm."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    conf = float(value)
    if not math.isfinite(conf) or conf < 0.0 or conf > 1.0:
        return 0.0
    return conf


def strict_ambiguous(payload) -> bool:
    """Fail-CLOSED ambiguity read from a payload dict.

    Only a clean ABSENCE of the key or an explicit boolean ``False`` counts
    as not-ambiguous. Any other value ({}, [], "", "false", None, 0, true, …)
    means the model garbled the flag — treat as ambiguous so the extraction
    lands in review instead of auto-confirming."""
    if not isinstance(payload, dict) or "ambiguous" not in payload:
        return False
    return payload["ambiguous"] is not False


# A name may arrive carrying a date/time — an unnamed chart is often labelled
# "Transit 2017-08-20" by the extractor. Left alone that puts a SECOND date and
# extra commas into a positional "Name, Date, Time, Location" line, and the
# parser then swallows the real date into the CITY: geocoding fails, the chart
# silently falls back to (0,0)/UTC, and ok=True is still returned. A wrong chart
# that reports success is the worst outcome here, so the name is sanitized at
# the one place every caller goes through.
_NAME_DATE_RE = re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b")
_NAME_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")


def sanitize_line_name(name) -> str:
    """Strip dates, times and commas out of a chart NAME so it cannot corrupt
    the positional line. Returns "" when nothing usable is left."""
    text = str(name or "")
    text = _NAME_DATE_RE.sub(" ", text)
    text = _NAME_TIME_RE.sub(" ", text)
    text = text.replace(",", " ")
    return " ".join(text.split()).strip(" -–—:")


def render_extraction_line(payload) -> str:
    """Render an extraction payload as a single canonical line that
    parse_birth_text accepts ("Name, Date, Time, Location").

    Missing/empty keys are tolerated and simply omitted. `tz_hint`, `notes`,
    `confidence`, and `source_snippet` are metadata only (not parseable text)
    and never appear in this line — they live in the summary.
    """
    payload = payload or {}
    parts = []
    for key in _REVIEW_LINE_FIELDS:
        val = payload.get(key)
        if val is None or not str(val).strip():
            continue
        text = sanitize_line_name(val) if key == "name" else str(val).strip()
        if text:
            parts.append(text)
    return ", ".join(parts)


def format_extraction_summary(payload) -> str:
    """Human-readable, read-only summary of what the extraction detected.

    Grouped under explicit headings so the two ROLES can never be confused:
    the birth data that becomes a new chart vs the reading date the transit
    is pointed at. Missing fields show as "(not detected)" so gaps are
    visible rather than silently absent.
    """
    payload = payload or {}
    field_labels = (
        ("name", "Name"),
        ("date", "Date"),
        ("time", "Time"),
        ("place", "Place"),
        ("tz_hint", "Timezone hint"),
    )
    lines = []
    for key, label in field_labels:
        val = payload.get(key)
        if val is not None and str(val).strip():
            lines.append(f"{label}: {str(val).strip()}")
        else:
            lines.append(f"{label}: (not detected)")
    # Joined on ONE wrapped line, not five stacked rows: the editable birth
    # line directly below carries the same values, so this is an at-a-glance
    # breakdown and should not dominate the dialog.
    return "  ·  ".join(lines)


def format_transit_summary(payload) -> str:
    """The OTHER role: the reading/transit date this paste carried. Always
    returns a line — an absent date reads as an explicit statement rather
    than an invisible omission the user has to infer."""
    payload = payload or {}
    transit = payload.get("transit_datetime")
    if transit is not None and str(transit).strip():
        return str(transit).strip()
    return "(none detected — the transit chart is left unchanged)"


def format_extraction_confidence_short(payload) -> str:
    """Just the confidence, e.g. "Confidence 99%" — for the one-line meta row
    (notes are rendered separately because they can be long)."""
    payload = payload or {}
    conf = payload.get("confidence")
    if conf is None:
        return ""
    try:
        return f"Confidence {float(conf) * 100:.0f}%"
    except (TypeError, ValueError):
        return f"Confidence {conf}"


def format_extraction_confidence(payload) -> str:
    """Confidence + notes line, or "" when the payload carries neither."""
    payload = payload or {}
    lines = []
    conf = payload.get("confidence")
    if conf is not None:
        try:
            lines.append(f"Confidence: {float(conf) * 100:.0f}%")
        except (TypeError, ValueError):
            lines.append(f"Confidence: {conf}")
    notes = payload.get("notes")
    if notes is not None and str(notes).strip():
        lines.append(f"Notes: {str(notes).strip()}")
    return "\n".join(lines)


def format_extraction_provenance(payload) -> str:
    """One short line naming WHICH AI read the paste, e.g.
    "Extracted by AI — GPT-5.6 (gpt-5.6-sol)". Empty string when the payload
    carries no provenance (offline/legacy callers), so the caller can hide
    the label entirely rather than render a bare prefix."""
    payload = payload or {}
    provider = str(payload.get("provider") or "").strip()
    model = str(payload.get("model") or "").strip()
    if not provider and not model:
        return ""
    if provider and model:
        return f"Extracted by AI — {provider} ({model})"
    return f"Extracted by AI — {provider or model}"


def elide_text(text, max_chars: int = SOURCE_SNIPPET_MAX_CHARS) -> str:
    """Collapse whitespace-trim and elide `text` to `max_chars` with a
    trailing ellipsis when it overruns."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 1)].rstrip() + "…"


class _ImagePasteTextEdit(QPlainTextEdit):
    """Birth-line input that diverts a pasted/dropped IMAGE to a signal.

    Text paste, typing and text-drop behave exactly as before; only image
    payloads are intercepted (and insert NO text, even when the clipboard
    carries a text fallback alongside the image).

    Unlike QLineEdit, QPlainTextEdit DOES expose ``insertFromMimeData`` to
    Python, but the keyPressEvent seam is used here as well so the paste chord
    is caught on every platform the same way the Pro reading-date field does it.
    """

    image_pasted = Signal(bytes, str)     # (image_bytes, media_type)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def _divert_image(self, mime) -> bool:
        found = _extract_clipboard_image(mime)
        if found is None:
            return False
        data, media_type = found
        self.image_pasted.emit(data, media_type)
        return True

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            clipboard = QGuiApplication.clipboard()
            mime = clipboard.mimeData() if clipboard is not None else None
            if self._divert_image(mime):
                event.accept()
                return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source):
        if self._divert_image(source):
            return
        super().insertFromMimeData(source)

    def dropEvent(self, event):
        if self._divert_image(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class _ImageExtractionWorker(QThread):
    """Run the injected extractor OFF the GUI thread.

    The extractor performs a network call that can take seconds; running it
    inline would freeze the dialog. Emits a plain dict (see
    ``pro.managers.chart_image_extraction``) — never a Pro type, so this Core
    widget stays edition-agnostic.
    """

    finished_with = Signal(dict)

    def __init__(self, extractor, data: bytes, media_type: str, parent=None):
        super().__init__(parent)
        self._extractor = extractor
        self._data = data
        self._media_type = media_type

    def run(self):
        try:
            result = self._extractor(self._data, self._media_type)
            if not isinstance(result, dict):
                result = {"ok": False,
                          "error": "extractor returned an unexpected result"}
        except Exception as exc:  # noqa: BLE001 — must reach the UI legibly
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self.finished_with.emit(result)


class AddChartDialog(QDialog):
    """Dialog for creating charts from natural language input (offline regex parser)."""

    # Class-level memory: persists between dialog opens within same app session
    _last_input_text = ""

    def __init__(self, parent=None, on_chart_loaded_callback=None,
                 review_payload=None, image_extractor=None):
        """Args:
            parent: parent QWidget.
            on_chart_loaded_callback: callback(chart, name, location, planets_data=...).
            image_extractor: PRO-ONLY capability — callable(bytes, media_type)
                returning a birth-data dict. When None (Core/Lite, and the
                default) the dialog shows no paste-a-screenshot affordance and
                an image paste is ignored exactly as before. Supplied by
                ChartGUI.ai_image_extractor(), which returns None outside Pro,
                so this Core file never imports pro.
            review_payload: optional structured extraction dict enabling REVIEW
                MODE (SPEC-TRN-005 D-6). Keys (all optional):
                {name, date, time, place, tz_hint, source_snippet, confidence,
                notes}. When None (the default), the dialog is in normal blank
                mode — byte-for-byte unchanged from before this feature.

        There is no persist_chart flag any more. Every generated chart is
        written to a file by the shared pipeline (SPEC-PERSIST-001 INV-1);
        the flag existed only because Add Chart historically wrote nothing,
        which is how a chart was lost on 2026-07-28.
        """
        super().__init__(parent)
        self.on_chart_loaded_callback = on_chart_loaded_callback
        # Review-mode state (additive; None payload == normal blank mode).
        self.review_payload = dict(review_payload) if review_payload else {}
        self._review_mode = review_payload is not None
        self._auto_confirm_fired = False
        self.review_summary_label = None
        self.review_snippet_label = None
        # Pro image-paste capability (None in Core/Lite). Review mode already
        # HAS its extraction, so the affordance only applies to blank mode.
        self._image_extractor = image_extractor if not self._review_mode else None
        self._image_worker = None
        self._image_closed = False
        # Set only when an extraction returned MORE than one chart. Until then
        # the input is treated as a single entry exactly as it always was — a
        # hand-typed paste may legitimately span several lines, so line
        # splitting must never be applied speculatively.
        self._multi_chart_mode = False
        self._setup_ui()

    @classmethod
    def for_review(cls, parent, extraction, on_chart_loaded_callback=None,
                   auto_confirm=False):
        """Construct the dialog in review mode for the B5 caller.

        Args:
            parent: parent QWidget.
            extraction: structured extraction payload (see __init__ keys).
            on_chart_loaded_callback: same callback as normal mode.
            auto_confirm: pre-check the auto-confirm box. Combined with a
                payload confidence >= REVIEW_AUTO_CONFIRM_CONFIDENCE_THRESHOLD
                this makes the dialog fire Generate itself on show (the
                dialog's own gate — see _should_auto_confirm).
        Returns the dialog; the caller shows/exec()s it.
        """
        dialog = cls(parent, on_chart_loaded_callback,
                     review_payload=dict(extraction or {}))
        dialog.auto_confirm_checkbox.setChecked(bool(auto_confirm))
        return dialog

    def _setup_ui(self):
        """Build the dialog UI."""
        self.setWindowTitle(
            "Review what the AI read — birth chart + transit date"
            if self._review_mode else "Add New Chart")
        # Review mode carries two titled role boxes + confidence + snippet +
        # provenance, and their height depends on the EXTRACTED CONTENT (notes
        # and snippets vary per paste). A fixed height is what clipped the
        # reading date, confidence and notes out of sight (live-test report),
        # so review mode pins only the WIDTH and lets the height follow the
        # layout — adjustSize() at the end of the build. Any fixed number
        # would just be a taller version of the same bug.
        if self._review_mode:
            self.setFixedWidth(750)
        else:
            self.setFixedSize(750, 400)
        self.setModal(True)

        # Dialog background
        self.setStyleSheet(f"QDialog {{ background-color: {SURFACE}; }}")

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 20, 25, 20)
        layout.setSpacing(12)

        # Review mode (SPEC-TRN-005 D-6): detected-fields summary + source
        # snippet, shown ABOVE the (pre-filled) editable text. Additive —
        # normal blank mode skips this entirely.
        if self._review_mode:
            self._build_review_section(layout)

        # Text input (plain text only — strips formatting on paste). In review
        # mode it holds ONE prefilled birth line, so it does not need the tall
        # free-typing box (which is what crowded the review content out).
        # Pro builds get the image-aware subclass so a pasted screenshot is
        # diverted to the AI; Core/Lite keep the plain editor (no capability,
        # no interception, unchanged behaviour).
        if self._image_extractor is not None:
            self.text_input = _ImagePasteTextEdit()
            self.text_input.image_pasted.connect(self._on_image_pasted)
        else:
            self.text_input = QPlainTextEdit()
        self.text_input.setMinimumHeight(56 if self._review_mode else 220)
        if self._review_mode:
            # One prefilled line — a tall free-typing box is what crowded the
            # review content out and left acres of dead space.
            self.text_input.setMaximumHeight(64)
        self.text_input.setFont(scaled_area_font('tables'))
        self.text_input.setPlaceholderText(
            "Name, Date, Time, Location\n"
            "(e.g. John Doe, January 15 1990, 10:30am, New York)"
            + ("\n\nor paste a chart screenshot (Ctrl+V) and the AI will read it"
               if self._image_extractor is not None else "")
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

        # Prefill: review mode uses the canonical re-parseable rendering of the
        # extraction (Generate then flows through the pipeline exactly like a
        # typed line); normal mode restores the previous session's input.
        if self._review_mode:
            self.text_input.setPlainText(
                render_extraction_line(self.review_payload))
            self.text_input.moveCursor(QTextCursor.End)
            # Role 2 (the editable reading date) + the meta/notes rows go
            # directly BELOW the birth line, keeping each heading adjacent to
            # the field it describes.
            self._build_transit_field(layout)
        elif AddChartDialog._last_input_text:
            self.text_input.setPlainText(AddChartDialog._last_input_text)
            self.text_input.selectAll()

        # Compact examples hint \u2014 Add-Chart boilerplate written for someone
        # TYPING a birth line from scratch. It has no notion of a transit and
        # only adds noise when the AI has already filled the line in, so review
        # mode omits it entirely (live-test report).
        if not self._review_mode:
            hint_label = QLabel(
                "Examples: John Doe, January 15 1990, 10:30am, New York  \u2014  "
                "Pierre Martin, 25/12/1975 23h15, Toulouse"
            )
            hint_label.setFont(scaled_area_font('buttons'))
            hint_label.setWordWrap(True)
            hint_label.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent;")
            layout.addWidget(hint_label)

        # Status label
        self.status_label = QLabel(
            "Generate creates the birth chart above and points the transit at "
            "the reading date."
            if self._review_mode
            else "Enter birth information and click 'Generate Chart'")
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

        # Stretch to push buttons to bottom. Review mode sizes to its content,
        # so a stretch there just opens a band of dead space above the buttons.
        if not self._review_mode:
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

        # Review mode sizes to its content (see the setFixedWidth comment).
        # adjustSize() alone is NOT enough — Qt caps it relative to the screen,
        # which silently reintroduces the clipping. Drive the height from the
        # layout's own requirement so every extracted field is reachable.
        if self._review_mode:
            needed = layout.sizeHint().height()
            self.setMinimumHeight(needed)
            self.resize(750, needed)

        # Focus on text input
        self.text_input.setFocus()

    def _section_heading(self, layout, text, *, accent=False):
        """A plain bold heading above a field.

        Deliberately NOT a QGroupBox: a group box draws its border THROUGH the
        title text (it renders struck-through / unreadable against this theme),
        and it added a frame-in-frame look for what is really just a labelled
        field. A bold label is legible and costs no vertical space."""
        theme = get_theme_colors()
        lbl = QLabel(text)
        lbl.setTextFormat(Qt.TextFormat.PlainText)
        lbl.setFont(scaled_area_font('buttons', bold=True))
        lbl.setStyleSheet(
            f"color: {theme['primary'] if accent else TEXT_SECONDARY}; "
            "background: transparent;")
        layout.addWidget(lbl)
        return lbl

    def _build_review_section(self, layout):
        """Read-only extraction review widgets (SPEC-TRN-005 D-6). Uses the
        theme constants like the rest of the dialog (Rule 20 — no raw hex)."""
        theme = get_theme_colors()

        header = QLabel(
            "The AI read two things from your paste. Both are editable — "
            "correct anything it got wrong, then Generate.")
        header.setFont(scaled_area_font('buttons'))
        header.setWordWrap(True)
        header.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(header)

        # --- role 1: the birth chart (its editable field is text_input, built
        # right after this section so the heading sits directly above it) -----
        self._section_heading(
            layout, "BIRTH CHART  —  a new natal chart is created from this")

        # Detected natal fields, on ONE compact line. The editable birth line
        # below carries the same values; this is the at-a-glance breakdown, so
        # it must not cost five stacked rows.
        self.review_summary_label = QLabel(
            format_extraction_summary(self.review_payload))
        # Finding 7: LLM-extracted text — PlainText, never interpreted HTML.
        self.review_summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.review_summary_label.setFont(scaled_area_font('buttons'))
        self.review_summary_label.setWordWrap(True)
        self.review_summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.review_summary_label.setStyleSheet(
            f"color: {TEXT_SECONDARY}; background: transparent;")
        layout.addWidget(self.review_summary_label)

    def _build_transit_field(self, layout):
        """Role 2: the reading date — an EDITABLE field.

        It was read-only, which left no way to correct a wrong reading date
        short of cancelling and re-pasting (live-test report: "we only have one
        editing field now"). Both roles the AI extracts are now correctable in
        place, and the panel commits THIS value, not the raw model output.
        """
        theme = get_theme_colors()
        self._section_heading(
            layout, "TRANSIT / READING DATE  —  the sky the reading is cast for",
            accent=True)

        self.transit_input = QLineEdit()
        self.transit_input.setFont(scaled_area_font('tables'))
        self.transit_input.setPlaceholderText(
            "YYYY-MM-DD HH:MM   (leave empty to keep the current transit)")
        self.transit_input.setMinimumHeight(34)
        self.transit_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {BG};
                color: {TEXT_PRIMARY};
                border: 2px solid {theme["primary"]};
                border-radius: 5px;
                padding: 4px 8px;
                font-weight: bold;
            }}
            QLineEdit:focus {{ border-color: {STATUS["success"]}; }}
        """)
        detected = str(self.review_payload.get("transit_datetime") or "").strip()
        self.transit_input.setText(detected)
        layout.addWidget(self.transit_input)

        if not detected:
            hint = QLabel("No reading date detected — the transit chart stays "
                          "as it is unless you type one.")
            hint.setFont(scaled_area_font('buttons'))
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent;")
            layout.addWidget(hint)

        # --- meta: confidence + which AI, on one line ------------------------
        meta_bits = [b for b in (
            format_extraction_confidence_short(self.review_payload),
            format_extraction_provenance(self.review_payload)) if b]
        if meta_bits:
            self.review_provenance_label = QLabel("  ·  ".join(meta_bits))
            self.review_provenance_label.setTextFormat(Qt.TextFormat.PlainText)
            self.review_provenance_label.setFont(scaled_area_font('buttons'))
            self.review_provenance_label.setWordWrap(True)
            self.review_provenance_label.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent; "
                "font-style: italic;")
            layout.addWidget(self.review_provenance_label)

        # Source snippet — kept as its OWN label rather than folded into the
        # meta line: it is PASTE-DERIVED content, so it needs the PlainText
        # guarantee and the elide+tooltip treatment (finding 7) on a widget
        # that can be asserted about directly.
        snippet_full = str(
            self.review_payload.get("source_snippet") or "").strip()
        if snippet_full:
            # The elision budget covers the WHOLE label, prefix included —
            # otherwise the caption silently pushes it over the cap.
            _prefix = "Source: "
            self.review_snippet_label = QLabel(
                _prefix + elide_text(
                    snippet_full, SOURCE_SNIPPET_MAX_CHARS - len(_prefix)))
            self.review_snippet_label.setTextFormat(Qt.TextFormat.PlainText)
            self.review_snippet_label.setFont(scaled_area_font('buttons'))
            self.review_snippet_label.setWordWrap(True)
            # Tooltips are always rich text in Qt; escape so the full snippet
            # displays literally (finding 7).
            self.review_snippet_label.setToolTip(html.escape(snippet_full))
            self.review_snippet_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            self.review_snippet_label.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent; "
                "font-style: italic;")
            layout.addWidget(self.review_snippet_label)

        notes = str(self.review_payload.get("notes") or "").strip()
        if notes:
            self.review_notes_label = QLabel(f"Notes: {notes}")
            self.review_notes_label.setTextFormat(Qt.TextFormat.PlainText)
            self.review_notes_label.setFont(scaled_area_font('buttons'))
            self.review_notes_label.setWordWrap(True)
            self.review_notes_label.setStyleSheet(
                f"color: {TEXT_SECONDARY}; background: transparent;")
            layout.addWidget(self.review_notes_label)

    def _generate_multiple(self):
        """Create one chart per non-empty line, then report what happened.

        Deliberately best-effort per line: with ten charts on screen, one
        unparseable row must not throw away the nine that worked. Failures are
        collected and reported by line number so the user can fix just those.
        """
        from PySide6.QtWidgets import QApplication
        from managers.chart_creation_pipeline import create_chart_from_text

        lines = [ln.strip() for ln in self.text_input.toPlainText().splitlines()]
        lines = [ln for ln in lines if ln]
        if not lines:
            QMessageBox.warning(self, "Empty Input",
                                "There are no chart lines to create.")
            return

        mode, ayanamsa_id = 'aditya', 1
        parent_gui = self.parent()
        if parent_gui is not None:
            mode = getattr(getattr(parent_gui, 'state', None),
                           'aditya_mode', mode)
            ayanamsa_id = getattr(parent_gui, 'chart_sidereal_ayanamsa_id',
                                  ayanamsa_id)

        self.generate_btn.setEnabled(False)
        created, failed = [], []
        for index, line in enumerate(lines, start=1):
            self._set_status(
                f"Creating chart {index} of {len(lines)}…", "info")
            QApplication.processEvents()
            try:
                # Warnings are SUPPRESSED per line here: a modal per chart
                # across ten charts is unusable. Anything that actually fails
                # is reported once, together, at the end.
                result = create_chart_from_text(
                    line, mode=mode, ayanamsa=ayanamsa_id,
                    on_warning=lambda kind, message: None,
                )
            except Exception as exc:  # noqa: BLE001 — one bad row of many
                failed.append((index, line, f"{type(exc).__name__}: {exc}"))
                continue
            if not result.ok:
                failed.append((index, line, result.error or "unknown error"))
                continue
            if getattr(result, "persist_error", None):
                # Not a failure — the chart was created — but the row must say
                # its file is missing (td-u84e).
                failed.append((index, line,
                               f"created WITHOUT a file: {result.persist_error}"))
            created.append(result)
            if self.on_chart_loaded_callback:
                try:
                    self.on_chart_loaded_callback(
                        result.chart, result.name, result.location_label,
                        planets_data=result.planets_data,
                        file_path=result.file_path)
                except Exception as exc:  # noqa: BLE001
                    failed.append((index, line, f"load failed: {exc}"))

        self.generate_btn.setEnabled(True)
        if not created:
            self._set_status("No charts could be created.", "error")
            QMessageBox.critical(
                self, "No Charts Created",
                "None of the lines could be turned into a chart:\n\n"
                + "\n".join(f"line {i}: {err}" for i, _l, err in failed[:10]))
            return

        self.accept()
        summary = (f"Created {len(created)} chart"
                   f"{'s' if len(created) != 1 else ''}:\n"
                   + "\n".join(f"  • {r.name} — {r.location_label}"
                               for r in created))
        if failed:
            summary += (f"\n\n{len(failed)} line"
                        f"{'s' if len(failed) != 1 else ''} could not be read:\n"
                        + "\n".join(f"  • line {i}: {err}"
                                    for i, _l, err in failed[:10]))
        QMessageBox.information(self.parent(), "Charts Created", summary)

    # ---- Pro image paste (capability-gated; inert in Core/Lite) -------------

    def _on_image_pasted(self, data: bytes, media_type: str):
        """A screenshot landed in the birth-line box: hand it to the AI.

        Runs on a worker thread — the extractor makes a network call. Only one
        extraction at a time: a second paste while one is in flight is ignored
        rather than racing two results into the same field.
        """
        if self._image_extractor is None or self._image_worker is not None:
            return
        self.status_label.setText(
            f"Reading the image with AI… ({len(data) // 1024} KB)")
        self.generate_btn.setEnabled(False)
        # Unparented worker + explicit teardown: a QThread owned by a dialog
        # that closes mid-run is the "QThread: Destroyed while still running"
        # crash this codebase has hit before.
        worker = _ImageExtractionWorker(self._image_extractor, data, media_type)
        self._image_worker = worker
        worker.finished_with.connect(self._on_image_extracted)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_image_extracted(self, result: dict):
        """Render the extraction: fill the birth line, or say what went wrong."""
        self._image_worker = None
        if self._image_closed:
            return                      # dialog went away mid-extraction
        self.generate_btn.setEnabled(True)

        if not result.get("ok"):
            detail = str(result.get("error") or "unknown error")
            if result.get("provider_unavailable"):
                detail += "  (Settings > AI Providers)"
            self.status_label.setText(f"Could not read that image: {detail}")
            return

        # One line per chart. A source can hold a couple's two charts, a dual
        # wheel (birth + transit), or a printed list of ten — each is a chart
        # in its own right, so each gets its own editable line and its own
        # entry in chart memory. A transit date is NOT special-cased away.
        charts = result.get("charts") or []
        if not charts:
            self.status_label.setText(
                "The AI read that image but found no chart data in it.")
            return

        lines = [render_extraction_line(c) for c in charts]
        lines = [ln for ln in lines if ln.strip()]
        self._multi_chart_mode = len(lines) > 1
        self.text_input.setPlainText("\n".join(lines))
        self.text_input.moveCursor(QTextCursor.End)

        bits = []
        conf = format_extraction_confidence_short(result)
        if conf:
            bits.append(conf)
        provenance = format_extraction_provenance(result)
        if provenance:
            bits.append(provenance)
        summary = "  ·  ".join(bits)
        if self._multi_chart_mode:
            self.generate_btn.setText(f"Create {len(lines)} Charts")
            lead = (f"Found {len(lines)} charts — one per line. Edit any of "
                    "them, then create.")
        else:
            self.generate_btn.setText("Generate Chart")
            lead = "Read from the image — check the line above, then Generate."
        self.status_label.setText(lead + (f"   {summary}" if summary else ""))

    def closeEvent(self, event):
        """Tear the extraction worker down deterministically.

        ``_image_closed`` also stops a late result from touching widgets that
        Qt has already deleted."""
        self._image_closed = True
        worker = self._image_worker
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.wait(3000)
            except RuntimeError:
                pass                    # already reaped by Qt
            self._image_worker = None
        super().closeEvent(event)

    def transit_datetime_text(self) -> str:
        """The reading date as the USER left it (edits included), or "" in
        non-review mode. The panel commits this, never the raw model value."""
        widget = getattr(self, "transit_input", None)
        return widget.text().strip() if widget is not None else ""

    def _should_auto_confirm(self) -> bool:
        """The dialog's OWN auto-confirm gate (SPEC-TRN-005 §4). True only when
        in review mode AND the user opted into auto-confirm AND the payload is
        NOT ambiguous AND it carries a well-formed confidence >=
        REVIEW_AUTO_CONFIRM_CONFIDENCE_THRESHOLD. Everything else fails
        closed: the review dialog stays up."""
        if not self._review_mode:
            return False
        if not self.auto_confirm_checkbox.isChecked():
            return False
        # An AMBIGUOUS extraction must NEVER skip review, regardless of
        # confidence (SPEC-TRN-005 B5 review finding 5): the flag means the
        # model itself could not settle which date plays which role. The
        # SHARED strict validators (F4) fail closed on garbled values ({} /
        # [] / strings / bool-as-number / NaN / out-of-range), and are the
        # SAME functions the extraction normalizer uses — no divergence.
        if strict_ambiguous(self.review_payload):
            return False
        conf_val = strict_confidence(self.review_payload.get("confidence"))
        return conf_val >= REVIEW_AUTO_CONFIRM_CONFIDENCE_THRESHOLD

    def showEvent(self, event):
        """On first show in review mode, fire Generate automatically when the
        auto-confirm gate passes (same code path as a manual click). Deferred
        via a 0ms timer so the dialog is fully painted first."""
        super().showEvent(event)
        if (self._review_mode and not self._auto_confirm_fired
                and self._should_auto_confirm()):
            self._auto_confirm_fired = True
            QTimer.singleShot(0, self._on_generate)

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
        """Handle Generate Chart button click — offline regex parser + geocoding.

        In MULTI-CHART mode (an AI extraction returned more than one chart) the
        input is one chart per line: each line runs through the very same
        pipeline, and each becomes its own entry in chart memory. The
        single-chart path below is untouched — line splitting is never applied
        speculatively, because a hand-typed entry may span several lines.
        """
        if self._multi_chart_mode:
            self._generate_multiple()
            return
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
            # Shared pipeline (SPEC-TRN-005 D-7): parse -> geocode ->
            # UTC via BirthDataManager.create_from_form_data (the one UTC
            # road, SPEC-UTC-001) -> JD -> build_chart_from_params.
            # No inline timezone/UTC arithmetic in this dialog.
            from managers.chart_creation_pipeline import (
                create_chart_from_text,
                WARN_DATE_AMBIGUITY, WARN_NO_TIME, WARN_GEOCODE_FAILED,
                STAGE_PARSE, STAGE_OFFSET,
            )

            # Mode comes from the parent GUI's current state; canonical fallback
            # 'aditya' (the legacy 'zodiac' literal is not a valid mode).
            mode = 'aditya'
            parent_gui = self.parent()
            if parent_gui is not None and hasattr(parent_gui, 'state'):
                mode = parent_gui.state.aditya_mode

            ayanamsa_id = 1
            if parent_gui is not None and hasattr(parent_gui, 'chart_sidereal_ayanamsa_id'):
                ayanamsa_id = parent_gui.chart_sidereal_ayanamsa_id

            _warn_titles = {
                WARN_DATE_AMBIGUITY: "Date Ambiguity",
                WARN_NO_TIME: "No Time Found",
                WARN_GEOCODE_FAILED: "Geocoding Failed",
            }

            def _on_warning(kind, message):
                if self.auto_confirm_checkbox.isChecked():
                    self._set_status(
                        f"Warning: {message.splitlines()[0]}", "warning")
                else:
                    QMessageBox.warning(
                        self, _warn_titles.get(kind, "Warning"), message)

            _progress_status = {
                'parsing': "Parsing birth data...",
                'geocoding': "Looking up location...",
                'calculating': "Calculating planetary positions...",
            }

            def _on_progress(stage):
                label = _progress_status.get(stage)
                if label:
                    self._set_status(label, "info")
                    QApplication.processEvents()

            result = create_chart_from_text(
                user_input, mode=mode, ayanamsa=ayanamsa_id,
                on_warning=_on_warning, on_progress=_on_progress,
            )

            if not result.ok:
                if result.error_stage == STAGE_PARSE:
                    # Same surface as the historical ValueError branch.
                    raise ValueError(result.error)
                if result.error_stage == STAGE_OFFSET:
                    # Explicit UTC-resolution failure (SPEC-UTC-001): the old
                    # silent local-as-UTC fallback is forbidden.
                    self._set_status(f"Timezone error: {result.error}", "error")
                    self.generate_btn.setEnabled(True)
                    QMessageBox.critical(
                        self, "Timezone Resolution Error",
                        "Could not resolve the UTC offset for this chart:\n\n"
                        f"{result.error}\n\n"
                        "The chart was NOT generated (a silent local-as-UTC "
                        "fallback would produce a wrong chart)."
                    )
                    return
                raise RuntimeError(result.error)

            chart = result.chart
            name = result.name
            location = result.location_label
            planets_data = result.planets_data

            # Step 4: Call the callback to load chart into GUI
            self._set_status("Loading chart...", "info")
            QApplication.processEvents()

            if self.on_chart_loaded_callback:
                try:
                    self.on_chart_loaded_callback(
                        chart, name, location, planets_data=planets_data,
                        file_path=result.file_path)
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
            if getattr(result, "persist_error", None):
                # td-u84e: the chart is fine, the FILE is not. INV-6 (td-rx09):
                # red, bottom left, held 30 s — NOT a modal dialog, which would
                # make a disk problem interrupt the work it did not stop. The
                # standing condition is recorded in Settings by the pipeline
                # and survives a restart; this is only about this chart.
                from ui.sticky_status import report_write_failure
                report_write_failure(self, result.persist_error, name)
            else:
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

    The AI screenshot-paste affordance is asked for, not assumed: ``parent`` is
    the main window, and only the Pro GUI answers ``ai_image_extractor()`` with
    a callable. Core/Lite return None (or lack the method entirely on an older
    parent), so the dialog is built exactly as it always was.
    """
    extractor = None
    probe = getattr(parent, "ai_image_extractor", None)
    if callable(probe):
        try:
            extractor = probe()
        except Exception:
            extractor = None
    dialog = AddChartDialog(parent, on_chart_loaded_callback,
                            image_extractor=extractor)
    dialog.exec()
