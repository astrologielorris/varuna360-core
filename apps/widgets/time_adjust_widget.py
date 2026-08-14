#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Time Adjust Widget
Time adjustment buttons for birth time or transit time navigation.

Displays two columns of buttons overlaid on the chart center:
- Left column: Time decrements (red buttons)
- Right column: Time increments (green buttons)

Time adjustments range from ±1 second to ±50 years.

NOTE: This widget is overlaid ON TOP of the chart view (not embedded in scene)
to avoid ownership conflicts when the chart is redrawn.
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QGridLayout, QFrame, QLabel
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from pathlib import Path
from datetime import datetime, timedelta

# Import centralized theme
from ui.qt_theme import (
    scaled_area_px, is_light_theme
)

# Per-theme popup palette (SPEC-THM-001; Opus 5 v2 dark + v3 light). The popup
# is a self-painting instrument panel: a DARK HUD on the dark app theme (Lorris
# approved) and a matching LIGHT panel on the light theme. Both dicts are fixed
# (NOT get_theme_colors) so a user's amber/pink light theme cannot collide with
# the semantic red/gold, following the _PARI_SEM/pari_sem precedent. Resolved
# live via is_light_theme() on every call, never cached. Every token clears
# WCAG AA on its surface; the red/green are Rule 20 semantic exceptions.
_TIME_ADJUST_SEM = {
    "dark": {
        "shell": "#1B1D21", "rim": "#8A8F96", "grip": "#AAAAAA",
        "handle_border": "#444444",
        "chip_bg": "#0C0D10", "chip_border": "#3A3F46",
        "ink": "#ECEDEF", "dim": "#98A0A8", "red": "#FF8A80", "green": "#7BD69B",
        "hairline": "#DAA520",
        "minus": {
            "r1": "#6B3535", "r2": "#4A2020", "text": "#E8C8C8",
            "border": "#7A4040", "bborder": "#351515",
            "h1": "#8B4545", "h2": "#5A3030", "htext": "#FFD0D0",
            "hborder": "#AA5555", "p1": "#351515", "p2": "#4A2020",
        },
        "plus": {
            "r1": "#354A6B", "r2": "#20354A", "text": "#C8D8E8",
            "border": "#40557A", "bborder": "#152035",
            "h1": "#456A8B", "h2": "#30455A", "htext": "#D0E0FF",
            "hborder": "#5575AA", "p1": "#152035", "p2": "#20354A",
        },
        "save": {"rest": "#2A6ACF", "hover": "#3A7ADF", "press": "#1A5ABF",
                 "text": "#FFFFFF"},
        "revert": {"text": "#E3C46A", "border": "#8A7B52", "hbg": "#33302A",
                   "htext": "#F2D89A", "hborder": "#DAA520",
                   "dtext": "#7A7F86", "dborder": "#3F444B"},
    },
    "light": {
        "shell": "#F7F8FA", "rim": "#838C99", "grip": "#7C8593",
        "handle_border": "#C6CCD6",
        "chip_bg": "#E8EBF0", "chip_border": "#7D8698",
        "ink": "#1A1D22", "dim": "#565E6B", "red": "#B3261E", "green": "#1B6B3A",
        "hairline": "#9A7B1E",
        "minus": {
            "r1": "#FBEAE7", "r2": "#F3D6D1", "text": "#7A1C16",
            "border": "#B15C4E", "bborder": "#8F3A2F",
            "h1": "#F7DDD8", "h2": "#EEC5BE", "htext": "#5E120D",
            "hborder": "#A24839", "p1": "#EEC5BE", "p2": "#F3D6D1",
        },
        "plus": {
            "r1": "#EFF4FB", "r2": "#DFEAF7", "text": "#14406F",
            "border": "#5183BA", "bborder": "#2F6096",
            "h1": "#E3EDF8", "h2": "#CFE0F2", "htext": "#0F3560",
            "hborder": "#4076B4", "p1": "#CFE0F2", "p2": "#DFEAF7",
        },
        "save": {"rest": "#1A5ABF", "hover": "#2A6ACF", "press": "#14448F",
                 "text": "#FFFFFF"},
        "revert": {"text": "#7A5B0F", "border": "#A9852B", "hbg": "#F6EDD6",
                   "htext": "#5E4409", "hborder": "#8A6C15",
                   "dtext": "#8A909B", "dborder": "#A6AEBB"},
    },
}


def popup_palette():
    """The active popup palette, resolved live per theme (never cached)."""
    return _TIME_ADJUST_SEM["light" if is_light_theme() else "dark"]


# Month abbreviations for the unambiguous "07 Apr 1776" date form (the slashed
# MM/DD/YYYY was ambiguous and noisy).
_MONTHS_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# Time increment definitions: (label, timedelta_kwargs)
TIME_INCREMENTS = [
    ("1s", {"seconds": 1}),
    ("10s", {"seconds": 10}),
    ("1m", {"minutes": 1}),
    ("10m", {"minutes": 10}),
    ("30m", {"minutes": 30}),
    ("1h", {"hours": 1}),
    ("1d", {"days": 1}),
    ("1w", {"weeks": 1}),
    ("1mo", {"days": 30}),  # Approximate month
    ("1y", {"days": 365}),  # Approximate year
    ("10y", {"days": 3650}),  # Approximate 10 years
    ("50y", {"days": 18250}),  # Approximate 50 years
]

def nudged_jd(base_jd: float, onesec_jd: float, delta_seconds: float) -> float:
    """The adjusted instant. Extracted so it can be tested without Qt.

    Inline in _adjust_time this arithmetic was unreachable headlessly, so the
    smoke gate could only grep the source for it — and a source grep cannot
    tell `base + delta * onesec` from `base`. A mutation that dropped the
    delta entirely (every time adjustment silently discarded, then written to
    disk by Save As) passed the whole suite. Scenario P asserts on this
    function against anchored values instead.
    """
    return base_jd + delta_seconds * onesec_jd


def display_components(comps):
    """Re-express a raw (year, month, day, hour, minute, second) tuple in the
    DISPLAY calendar convention (SPEC-CAL-001). Only the date is converted; the
    time-of-day components are calendar-independent. Returns None unchanged.

    The mask MUST be computed on these displayed values, not the raw ones: a
    one-day Julian nudge can cross a Gregorian month/year boundary while the
    raw Julian month stays fixed, which would otherwise leave a visibly-changed
    component un-highlighted for pre-1582 charts.
    """
    if comps is None:
        return None
    from core.time_utils import display_civil_date
    y, mo, d, h, mi, s = comps
    dy, dmo, dd = display_civil_date(y, mo, d)
    return (dy, dmo, dd, h, mi, s)


def component_mask(current_disp, baseline_disp):
    """Per-component changed flags (year, month, day, hour, minute, second).
    All-False when either side is missing. Inputs are DISPLAY-frame tuples."""
    if current_disp is None or baseline_disp is None:
        return (False,) * 6
    return tuple(a != b for a, b in zip(current_disp, baseline_disp))


def delta_caption(current_raw, baseline_raw):
    """Worded caption carrying magnitude AND direction, e.g. '1h 30m earlier'.
    'saved time' when identical, 'unsaved change' when uncomputable. Direction
    is a word ('earlier'/'later'), not a sign, so it never collides with the
    +/- button language. Color-blind-safe (survives grayscale)."""
    if current_raw is None or baseline_raw is None:
        return "saved time"
    if current_raw == baseline_raw:
        return "saved time"
    # Python's datetime is proleptic Gregorian; it misreports (or rejects, e.g.
    # 1500-02-29) genuine Julian-calendar dates. The red mask already shows
    # WHICH components changed, so for pre-Gregorian instants fall back to a
    # worded cue rather than a wrong signed delta.
    if current_raw[0] < 1583 or baseline_raw[0] < 1583:
        return "unsaved change"
    try:
        total = int((datetime(*current_raw) - datetime(*baseline_raw)).total_seconds())
    except (ValueError, TypeError):
        return "unsaved change"
    if total == 0:
        return "saved time"
    direction = "later" if total > 0 else "earlier"
    total = abs(total)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    if secs and not days:  # seconds only matter for small deltas
        parts.append(f"{secs}s")
    if not parts:
        parts.append("0s")
    return f"{' '.join(parts)} {direction}"


def preview_html(current_disp, mask, caption, sizes, colors):
    """Build the RichText for the recessed readout chip: a dim date line, a big
    hero time line, and a caption line. Changed components get color + bold +
    underline (three redundant, color-blind-safe cues). `sizes` is a
    (date_px, time_px, caption_px) tuple; `colors` is a dict with ink/dim/red/
    green so the readout tracks the active theme. Pure values in, HTML out."""
    if current_disp is None:
        return ""
    dy, dmo, dd, h, mi, s = current_disp
    date_px, time_px, cap_px = sizes
    ink, dim, red, green = colors["ink"], colors["dim"], colors["red"], colors["green"]

    def span(txt, changed, base_color):
        if changed:
            return (f"<span style=\"color:{red};font-weight:700;"
                    f"text-decoration:underline\">{txt}</span>")
        return f"<span style=\"color:{base_color}\">{txt}</span>"

    sep = f"<span style=\"color:{dim}\">{{}}</span>"
    month = _MONTHS_ABBR[dmo] if 1 <= dmo <= 12 else f"{dmo:02d}"
    # Date line: dim, small, unambiguous "07 Apr 1776"
    date_line = (
        f"<span style=\"font-size:{date_px}px;letter-spacing:.4px\">"
        + span(f"{dd:02d}", mask[2], dim) + " "
        + span(month, mask[1], dim) + " "
        + span(str(dy), mask[0], dim) + "</span>")
    # Time line: the hero. Big, bright, changed digits red.
    time_line = (
        f"<span style=\"font-size:{time_px}px;font-weight:600\">"
        + span(f"{h:02d}", mask[3], ink) + sep.format(":")
        + span(f"{mi:02d}", mask[4], ink) + sep.format(":")
        + span(f"{s:02d}", mask[5], ink) + "</span>")
    # Caption: green "saved time" (with dot) when unchanged, else dim worded delta.
    if caption == "saved time":
        cap_html = (f"<span style=\"font-size:{cap_px}px;color:{green}\">"
                    f"&#9679; {caption}</span>")
    else:
        cap_html = (f"<span style=\"font-size:{cap_px}px;color:{dim}\">"
                    f"{caption}</span>")
    return (f"<div style=\"text-align:center;line-height:135%\">"
            f"{date_line}<br>{time_line}<br>{cap_html}</div>")


def _tint_pixmap(pix, color):
    """Return a copy of a (monochrome) pixmap recolored to `color`, preserving
    its alpha shape. Used to theme the grey drag-grip SVG per theme."""
    out = QPixmap(pix.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, pix)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return out


def _nudge_button_style(spec, font_px):
    """Stylesheet for a minus/plus nudge button from a palette sub-dict."""
    return f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {spec['r1']}, stop:1 {spec['r2']});
            color: {spec['text']};
            font-weight: bold;
            font-size: {font_px}px;
            border: 1px solid {spec['border']};
            border-bottom: 2px solid {spec['bborder']};
            border-radius: 4px;
            padding: 4px 8px;
            min-width: 55px;
            min-height: 22px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {spec['h1']}, stop:1 {spec['h2']});
            border-color: {spec['hborder']};
            color: {spec['htext']};
        }}
        QPushButton:pressed {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {spec['p1']}, stop:1 {spec['p2']});
            border-bottom: 1px solid {spec['bborder']};
            padding-top: 5px;
        }}
    """


def _save_button_style(pal, font_px):
    s = pal["save"]
    return f"""
        QPushButton {{
            background-color: {s['rest']};
            color: {s['text']};
            font-weight: bold;
            font-size: {font_px}px;
            border: none;
            border-radius: 4px;
            padding: 6px 8px;
        }}
        QPushButton:hover {{ background-color: {s['hover']}; }}
        QPushButton:pressed {{ background-color: {s['press']}; }}
    """


def _revert_button_style(pal, font_px):
    r = pal["revert"]
    return f"""
        QPushButton {{
            background-color: transparent;
            color: {r['text']};
            font-weight: bold;
            font-size: {font_px}px;
            border: 1px solid {r['border']};
            border-radius: 4px;
            padding: 6px 8px;
        }}
        QPushButton:hover {{
            background-color: {r['hbg']};
            color: {r['htext']};
            border: 1px solid {r['hborder']};
        }}
        QPushButton:disabled {{
            color: {r['dtext']};
            border: 1px solid {r['dborder']};
        }}
    """


class TimeAdjustWidget(QWidget):
    """
    Widget containing time adjustment buttons for birth time or transit navigation.

    This widget is designed to be overlaid ON TOP of the chart view (not embedded
    in the QGraphicsScene) to avoid destruction when the chart is redrawn.
    """

    # Signal emitted when time is adjusted (optional - for external listeners)
    time_adjusted = Signal(int)  # delta_seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.gui = None  # Will be set by caller
        self._drag_active = False
        self._drag_offset = QPoint()
        # A bare QWidget subclass does NOT paint a stylesheet background unless
        # WA_StyledBackground is set. Without it, qt-material's blanket
        # `QWidget { background-color: secondaryDarkColor }` paints instead
        # (light grey on the light theme), which is why the readout was
        # invisible on white. Setting this makes the shell own its dark surface.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Live-preview baseline: the last-SAVED birth time as a raw civil tuple
        # (year, month, day, hour, minute, second), plus the memory-entry id it
        # belongs to so a chart switch under the open popup recaptures it.
        self._baseline = None
        self._baseline_entry_id = None
        self._setup_ui()

    def set_gui(self, gui):
        """Set reference to main GUI for accessing planets_data and recalculation."""
        self.gui = gui

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle_rect = self._drag_handle.geometry()
            if handle_rect.contains(event.position().toPoint()):
                self._drag_active = True
                self._drag_offset = event.position().toPoint()
                self._drag_handle.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active:
            new_pos = self.mapToParent(event.position().toPoint()) - self._drag_offset
            parent = self.parentWidget()
            if parent:
                pr = parent.rect()
                x = max(0, min(new_pos.x(), pr.width() - self.width()))
                y = max(0, min(new_pos.y(), pr.height() - self.height()))
                self.move(x, y)
            else:
                self.move(new_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_active:
            self._drag_active = False
            self._drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _setup_ui(self):
        """Build the widget tree; per-theme colors are applied in
        _apply_theme_styles so the popup can be re-skinned dark<->light."""
        # Main layout directly on self - compact margins
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(2)

        # Drag handle (3 horizontal bars). Border/grip color set per theme.
        self._drag_handle = QFrame()
        self._drag_handle.setFixedHeight(22)
        self._drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self._grip_label = QLabel(self._drag_handle)
        self._grip_uses_text = False
        self._grip_pix = None
        svg_path = Path(__file__).resolve().parents[2] / "img" / "icons" / "drag_grip.svg"
        icon = QIcon(str(svg_path))
        pix = icon.pixmap(100, 16)
        if not pix.isNull():
            self._grip_pix = pix  # keep the source shape; tinted per theme
            self._grip_label.setPixmap(pix)
        else:
            self._grip_label.setText("━ ━ ━")
            self._grip_uses_text = True
        self._grip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grip_layout = QHBoxLayout(self._drag_handle)
        grip_layout.setContentsMargins(0, 2, 0, 2)
        grip_layout.addWidget(self._grip_label, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._drag_handle)

        # Recessed readout chip (objectName selector beats qt-material's blanket
        # QFrame rule so it keeps its own surface on the light theme). Colors set
        # per theme in _apply_theme_styles.
        self._readout_chip = QFrame()
        self._readout_chip.setObjectName("TimeAdjustReadout")
        chip_layout = QVBoxLayout(self._readout_chip)
        chip_layout.setContentsMargins(12, 10, 12, 10)
        chip_layout.setSpacing(0)
        self.preview_label = QLabel("")
        self.preview_label.setTextFormat(Qt.TextFormat.RichText)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet(
            "font-family: 'Inter','Segoe UI','Arial',sans-serif;"
            "background: transparent; border: none;"
        )
        # Monospaced-ish digits so the time line does not reflow on each click.
        _pf = self.preview_label.font()
        _pf.setStyleHint(QFont.StyleHint.Monospace)
        _pf.setFixedPitch(True)
        self.preview_label.setFont(_pf)
        chip_layout.addWidget(self.preview_label)
        layout.addWidget(self._readout_chip)

        layout.addSpacing(8)

        # Gold hairline separating the readout (a display) from the grid (a
        # control), inset from the sides. Color set per theme.
        hairline_row = QHBoxLayout()
        hairline_row.setContentsMargins(10, 0, 10, 0)
        self._hairline = QFrame()
        self._hairline.setFixedHeight(1)
        hairline_row.addWidget(self._hairline)
        layout.addLayout(hairline_row)

        layout.addSpacing(8)

        # Button grid. Keep refs to both columns so _apply_theme_styles can
        # re-skin them on a live theme switch (else dark buttons strand on a
        # white shell).
        grid = QGridLayout()
        grid.setSpacing(4)
        self._minus_btns = []
        self._plus_btns = []
        for row, (label, delta_kwargs) in enumerate(TIME_INCREMENTS):
            td = timedelta(**delta_kwargs)
            delta_seconds = int(td.total_seconds())

            minus_btn = QPushButton(f"-{label}")
            minus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            minus_btn.setProperty("delta_seconds", -delta_seconds)
            minus_btn.clicked.connect(self._on_button_clicked)
            grid.addWidget(minus_btn, row, 0)
            self._minus_btns.append(minus_btn)

            plus_btn = QPushButton(f"+{label}")
            plus_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            plus_btn.setProperty("delta_seconds", delta_seconds)
            plus_btn.clicked.connect(self._on_button_clicked)
            grid.addWidget(plus_btn, row, 1)
            self._plus_btns.append(plus_btn)

        layout.addLayout(grid)

        # Save (primary) + Revert (gold-ghost, restores last-saved instant in one
        # jump). Styles set per theme.
        self.save_btn = QPushButton("Save")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setToolTip("Save adjusted time as the chart's birth time")
        self.save_btn.clicked.connect(self._save_adjusted_time)

        self.revert_btn = QPushButton("Revert to saved")
        self.revert_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.revert_btn.setToolTip("Restore the birth time you last saved")
        self.revert_btn.clicked.connect(self._revert_to_saved)

        # Footer: Revert (left, secondary) + Save (right, primary weight).
        footer = QHBoxLayout()
        footer.setSpacing(6)
        footer.addWidget(self.revert_btn, 40)
        footer.addWidget(self.save_btn, 60)
        layout.addLayout(footer)

        # Apply the active palette (shell, chip, hairline, buttons, save,
        # revert, readout) then size to the populated content.
        self._apply_theme_styles()
        self.adjustSize()

    def _apply_theme_styles(self):
        """Skin every surface from the active per-theme palette (dark HUD /
        light panel). Called at build, on each open, and on live theme change so
        a Dark<->Light switch re-skins instead of stranding one theme's colors.
        SPEC-THM-001 Rule 9/10: re-generate from the palette, never cache strings."""
        pal = popup_palette()
        font_px = scaled_area_px('buttons')
        # Shell + rim
        self.setStyleSheet(
            f"TimeAdjustWidget {{ background-color: {pal['shell']};"
            f" border-radius: 12px; border: 1px solid {pal['rim']}; }}"
        )
        # Drag handle divider + text-fallback grip
        if getattr(self, '_drag_handle', None) is not None:
            self._drag_handle.setStyleSheet(
                "QFrame { background: transparent; border: none;"
                f" border-bottom: 1px solid {pal['handle_border']}; }}"
            )
        if getattr(self, '_grip_label', None) is not None:
            if self._grip_uses_text:
                self._grip_label.setStyleSheet(
                    f"color: {pal['grip']}; font-size: {font_px}px;")
            elif getattr(self, '_grip_pix', None) is not None:
                # The grip SVG ships with a fixed grey stroke; tint its shape to
                # the palette grip color so it adapts to the theme.
                self._grip_label.setPixmap(_tint_pixmap(self._grip_pix, pal['grip']))
        # Readout chip
        if getattr(self, '_readout_chip', None) is not None:
            self._readout_chip.setStyleSheet(
                f"#TimeAdjustReadout {{ background: {pal['chip_bg']};"
                f" border: 1px solid {pal['chip_border']}; border-radius: 8px; }}"
            )
        # Gold hairline
        if getattr(self, '_hairline', None) is not None:
            self._hairline.setStyleSheet(
                f"background: {pal['hairline']}; border: none;")
        # Nudge buttons
        minus_style = _nudge_button_style(pal['minus'], font_px)
        plus_style = _nudge_button_style(pal['plus'], font_px)
        for b in getattr(self, '_minus_btns', []):
            b.setStyleSheet(minus_style)
        for b in getattr(self, '_plus_btns', []):
            b.setStyleSheet(plus_style)
        # Save + Revert
        if getattr(self, 'save_btn', None) is not None:
            self.save_btn.setStyleSheet(_save_button_style(pal, font_px))
        if getattr(self, 'revert_btn', None) is not None:
            self.revert_btn.setStyleSheet(_revert_button_style(pal, font_px))
        # Readout text (colors changed with the theme)
        self.refresh_preview()

    def refresh_theme(self):
        """SPEC-THM-001 Rule 7: re-skin on a live theme change. Wired into
        _on_theme_changed via a hasattr guard."""
        self._apply_theme_styles()

    def _apply_shell_style(self):
        """Back-compat shim: full re-skin (the shell is one of the surfaces)."""
        self._apply_theme_styles()

    def _transit_active(self):
        """True when the +/- buttons are driving the ephemeral transit time."""
        mgr = getattr(self.gui, 'transit_overlay_manager', None)
        return bool(mgr and getattr(mgr, 'transit_enabled', False)
                    and self._active_view_has_overlay())

    def _readout_suppressed(self):
        """The readout is a NATAL birth-time preview; suppress it whenever the
        displayed instant is not the birth time: the transit overlay (ephemeral)
        or Human Design (the -88 Sun shift moves the displayed time, so it would
        read as permanently 'changed' against the natal baseline)."""
        return self._transit_active() or bool(
            getattr(self.gui, 'is_human_design', False))

    def update_save_button_state(self):
        """Disable Save when the transit overlay is active (transit time is
        ephemeral). Revert state is owned by _update_action_enabled, called here
        so this method is self-consistent even if invoked without a repaint."""
        if self._transit_active():
            self.save_btn.setEnabled(False)
            self.save_btn.setToolTip(
                "Cannot save transit time (toggle transit OFF to adjust birth time)"
            )
        else:
            self.save_btn.setEnabled(True)
            self.save_btn.setToolTip("Save adjusted time as the chart's birth time")
        self._update_action_enabled(self._current_components())

    def _memory_panel(self):
        """The chart memory panel (both attribute names alias one instance)."""
        return (getattr(self.gui, 'chart_memory_panel', None)
                or getattr(self.gui, 'memory_panel', None))

    def _current_entry(self):
        """The active memory entry, or None."""
        panel = self._memory_panel()
        if panel and 0 <= panel.current_index < len(panel.charts):
            return panel.charts[panel.current_index]
        return None

    def _current_components(self):
        """Raw (year, month, day, hour, minute, second) of the active chart's
        instant, in the local/display frame the title also uses."""
        active = self.gui.state.active_chart if self.gui else None
        if not active:
            return None
        from core.chart_factory import timedec_to_hms
        njd = active.context.timeJD
        h, m, s = timedec_to_hms(njd.usrhour())
        return (njd.usryear(), njd.usrmonth(), njd.usrday(), h, m, s)

    def capture_baseline(self):
        """Set the baseline to the last-SAVED birth time, sourced from the
        memory entry recipe (so an unsaved close still shows red on reopen).
        Falls back to the active chart for charts not in the memory panel."""
        entry = self._current_entry()
        if entry and entry.get('recipe'):
            from core.chart_factory import timedec_to_hms
            r = entry['recipe']
            try:
                h, m, s = timedec_to_hms(r['timedec'])
                self._baseline = (r['year'], r['month'], r['day'], h, m, s)
                self._baseline_entry_id = entry.get('id')
                return
            except (KeyError, TypeError):
                pass
        self._baseline = self._current_components()
        self._baseline_entry_id = entry.get('id') if entry else None

    def _readout_sizes(self):
        """(date_px, time_px, caption_px), scaled with the app font size so the
        hero time leads, the date is context, the caption is small."""
        base = scaled_area_px('panel_titles')
        return (max(9, base - 2), round(base * 1.5), max(9, base - 3))

    def refresh_preview(self):
        """Recompute and repaint the readout. Recaptures the baseline when the
        active memory entry changed under the open popup (chart switch)."""
        if getattr(self, 'preview_label', None) is None:
            return
        cur_raw = self._current_components()
        if cur_raw is None:
            self.preview_label.setText("")
            self._update_action_enabled(None)
            return
        # Transit overlay or Human Design: the displayed instant is not the
        # birth time, so hide the readout rather than show a misleading always-
        # changed value, and disable Save/Revert.
        if self._readout_suppressed():
            self.preview_label.setText("")
            self._update_action_enabled(None)
            return

        cur_disp = display_components(cur_raw)
        entry = self._current_entry()
        cur_id = entry.get('id') if entry else None
        if self._baseline is None or cur_id != self._baseline_entry_id:
            self.capture_baseline()
        base_disp = display_components(self._baseline)
        mask = component_mask(cur_disp, base_disp)
        caption = delta_caption(cur_raw, self._baseline)
        html = preview_html(cur_disp, mask, caption, self._readout_sizes(),
                            popup_palette())
        self.preview_label.setText(html)
        self._update_action_enabled(cur_raw)

    def _update_action_enabled(self, cur_raw):
        """Revert is live only when there is an unsaved change AND a memory entry
        to revert to; a live Revert doubles as an 'unsaved changes' indicator.
        cur_raw None => nothing to revert."""
        if getattr(self, 'revert_btn', None) is None:
            return
        # No referent to revert to (transit/HD, or a chart not in the memory
        # panel where select_chart would be a no-op): keep Revert disabled so the
        # enabled-state and the action never disagree.
        if self._readout_suppressed() or self._current_entry() is None:
            self.revert_btn.setEnabled(False)
            return
        changed = (cur_raw is not None and self._baseline is not None
                   and cur_raw != self._baseline)
        self.revert_btn.setEnabled(changed)

    def _revert_to_saved(self):
        """Restore the last-saved birth time in one jump (the approximate
        1mo=30d / 1y=365d increments do not round-trip by hand). Rebuilds via
        the canonical memory-load path, which serves the cached SAVED chart
        (an unsaved adjustment never rewrites the memory entry)."""
        if not self.gui or self._transit_active():
            return
        panel = self._memory_panel()
        if not panel or not (0 <= panel.current_index < len(panel.charts)):
            return
        panel.select_chart(panel.current_index)
        self.capture_baseline()
        self.refresh_preview()  # also refreshed via _finalize hook; harmless
        if hasattr(self.gui, 'statusBar'):
            self.gui.statusBar().showMessage("Birth time reverted", 3000)

    def _on_button_clicked(self):
        """Handle time adjustment button click."""
        sender = self.sender()
        if sender:
            delta_seconds = sender.property("delta_seconds")
            if delta_seconds is not None:
                # Use QTimer to defer the adjustment slightly
                # This prevents issues with signal handling during scene updates
                QTimer.singleShot(10, lambda ds=delta_seconds: self._adjust_time(ds))

    def _active_view_has_overlay(self):
        """True when the active chart view renders a transit overlay."""
        return self.gui.state.chart_view_style in ("wheel", "south_indian", "north_indian")

    def _adjust_time(self, delta_seconds):
        """Adjust birth time (or transit time if overlay active) by delta_seconds."""
        if not self.gui:
            return
        mgr = getattr(self.gui, 'transit_overlay_manager', None)
        if mgr and mgr.transit_enabled and self._active_view_has_overlay():
            # SPEC-TRN-006 D-5: an overlay chart is a frozen moment; time-adjust
            # does not apply. Say so rather than appearing to do nothing.
            if getattr(mgr, 'transit_mode', '') == "overlay_chart":
                try:
                    self.gui.statusBar().showMessage(
                        "Time adjust does not apply to an overlay chart.", 4000)
                except Exception:
                    pass
                return
            mgr.adjust_time(delta_seconds)
            return

        old_chart = self.gui.state.active_chart
        if not old_chart:
            return

        from dataclasses import replace as dc_replace
        from core.chart_factory import make_source_params, timedec_to_hms
        from libaditya.objects.julian_day import JulianDay
        from libaditya.charts.chart import Chart
        from state.events import SetActiveChart

        try:
            ctx = old_chart.context
            old_jd = ctx.timeJD

            # Nudge JD (EphContext is frozen → replace)
            new_jd_float = nudged_jd(old_jd.jd, old_jd.onesecjd, delta_seconds)
            new_timeJD = JulianDay(new_jd_float, utcoffset=old_jd.utcoffset)
            _chart = Chart(dc_replace(ctx, timeJD=new_timeJD))

            # Update source_params for mode-switch rebuild / session restore
            sp = self.gui.state.source_params or {}
            old_bd = sp.get("birth_data", {})
            njd = _chart.context.timeJD
            hour_float = njd.usrhour()
            h, m, s = timedec_to_hms(hour_float)

            new_bd = dict(old_bd)
            new_bd.update({
                'year': njd.usryear(), 'month': njd.usrmonth(),
                'day': njd.usrday(), 'hour': h, 'minute': m,
                'second': s, 'timedec': hour_float,
                'latitude': ctx.location.lat,
                'longitude': ctx.location.long,
                # td-nbl8, second channel: without this the STALE julian_day
                # from old_bd rides along in source_params, and a later
                # Save As writes a .toml whose [civil] block holds the
                # adjusted time while [moment].jd holds the original — the
                # revert made permanent on disk, reachable without ever
                # touching the memory panel. new_jd_float IS the adjusted
                # instant, so carry it rather than clearing it.
                'julian_day': new_jd_float,
            })

            # Live-title fix: a CHTK-direct load carries local_* keys in
            # source_params birth_data, and _format_chart_title PREFERS them
            # over the plain keys. Updating only the plain keys above left the
            # stale local_* riding along, freezing the window title at the
            # pre-adjustment time on every click. usr*() is already the
            # local/display frame (the JD carries the chart's offset), so these
            # equal the plain values just written.
            new_bd.update({
                'local_year': njd.usryear(), 'local_month': njd.usrmonth(),
                'local_day': njd.usrday(), 'local_hour': h,
                'local_minute': m, 'local_second': s,
            })
            self.gui.state.dispatch(SetActiveChart(chart=_chart, source_params=make_source_params(
                chtk_path=sp.get("chtk_path"),
                birth_data=new_bd,
                mode=sp.get("mode", self.gui.state.aditya_mode),
                ayanamsa=sp.get("ayanamsa",
                                getattr(self.gui, 'chart_sidereal_ayanamsa_id', 100)),
                house_system=sp.get("house_system", "campanus"),
                is_human_design=sp.get("is_human_design", False),
            )))

            self.gui.birth_jd = new_jd_float

            new_meta = dict(new_bd)
            new_meta.setdefault('timezone', 'UTC')
            for key in ['name', 'city', 'country', 'gender',
                        'timezone', 'iana_timezone']:
                if key in old_bd:
                    new_meta.setdefault(key, old_bd[key])
            self.gui._current_chart_data = None
            self.gui.current_birth_data = new_meta

            if hasattr(self.gui, '_finalize_chart_load'):
                self.gui._finalize_chart_load(
                    skip_varga_reset=True, skip_loading=True)

        except Exception as e:
            print(f"[TIME_ADJUST] Error adjusting time: {e}")
            import traceback
            traceback.print_exc()

    def _save_adjusted_time(self):
        """Save the current adjusted time as the chart's definitive birth time."""
        if not self.gui:
            return
        active = self.gui.state.active_chart
        if not active:
            return

        njd = active.context.timeJD
        year = njd.usryear()
        month = njd.usrmonth()
        day = njd.usrday()
        timedec = njd.usrhour()

        saved = False
        if hasattr(self.gui, 'chart_memory_panel') and self.gui.chart_memory_panel:
            panel = self.gui.chart_memory_panel
            if 0 <= panel.current_index < len(panel.charts):
                panel.update_current_chart({
                    'year': year,
                    'month': month,
                    'day': day,
                    'timedec': timedec,
                })
                entry = panel.charts[panel.current_index]
                entry['_chart'] = active
                entry['_built_mode'] = self.gui.state.aditya_mode
                entry['_built_ayanamsa'] = getattr(
                    self.gui, 'chart_sidereal_ayanamsa_id', 100
                )
                # Store the house system too, or get_or_build_chart serves this
                # freshly-built chart under a stale _built_hsys to Transit/Solar
                # Return (td-5lr1). Same source the consumers read as current_hsys.
                entry['_built_hsys'] = getattr(self.gui.state, 'house_system', 'campanus')
                saved = True

                if hasattr(self.gui, 'edit_chart_panel') and self.gui.edit_chart_panel:
                    self.gui.edit_chart_panel.load_chart_from_memory(entry)

        if hasattr(self.gui, '_update_title'):
            self.gui._update_title()

        if hasattr(self.gui, '_toggle_time_adjust'):
            self.gui._toggle_time_adjust()

        if saved:
            self.gui.statusBar().showMessage("Birth time saved", 3000)
        else:
            self.gui.statusBar().showMessage("No chart selected to save", 3000)

def create_time_adjust_overlay(gui):
    """
    Create and return a TimeAdjustWidget configured for the given GUI.

    Args:
        gui: The main ChartGUI instance

    Returns:
        TimeAdjustWidget instance (as child of chart_view for proper positioning)
    """
    # Create widget as child of chart_stack so it overlays on any chart view
    if hasattr(gui, 'chart_stack') and gui.chart_stack:
        widget = TimeAdjustWidget(gui.chart_stack)
    elif hasattr(gui, 'chart_view') and gui.chart_view:
        widget = TimeAdjustWidget(gui.chart_view)
    else:
        widget = TimeAdjustWidget()

    widget.set_gui(gui)
    widget.hide()  # Start hidden
    return widget
