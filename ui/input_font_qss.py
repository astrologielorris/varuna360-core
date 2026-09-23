# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Global input-widget font scaling (td-q43fm / G9d).

qt-material's app-wide stylesheet freezes EVERY widget at ``* { font-size: 13px }``,
and setFont is inert under a QSS font rule, so comboboxes, spin boxes and text inputs
stay 13px while their scaled_area_* neighbours shrink/grow — at the HD preset the
13px combos dwarf their 8-9px labels (Lorris's readability gate).

Fix: one app-level QSS block whose TYPE selectors beat the universal ``*`` by CSS
specificity, so every page inherits a scaling font on these controls without any
per-widget setStyleSheet. Combos + spin boxes (and the popup QAbstractItemView) ride
the ``buttons`` area; free-text inputs ride ``info_text``; message boxes and input
dialogs follow the pop-up rule (text ``info_text``, buttons ``action_buttons``). Re-applied after qt-material
at boot and on every theme change (qt-material resets the app sheet), and on every
font-size change (the effective px changes).

Lives in its own module rather than ui/qt_theme.py because that module is at its
SI-architecture line ceiling (down-only ratchet — never grow a frozen module).
"""
from ui.qt_theme import scaled_area_px

_INPUT_FONT_QSS_BEGIN = "/* G9D_INPUT_FONT_BEGIN */"
_INPUT_FONT_QSS_END = "/* G9D_INPUT_FONT_END */"


def get_input_font_qss() -> str:
    """App-level QSS giving comboboxes / spin boxes (``buttons`` area) and free-text
    inputs (``info_text`` area) a SCALING font-size, overriding qt-material's frozen
    universal 13px by type-selector specificity. Wrapped in sentinel comments so
    apply_global_input_font_qss() can replace it idempotently."""
    buttons_px = scaled_area_px('buttons')
    text_px = scaled_area_px('info_text')
    return (
        f"{_INPUT_FONT_QSS_BEGIN}\n"
        f"QComboBox, QComboBox QAbstractItemView, QSpinBox, QDoubleSpinBox "
        f"{{ font-size: {buttons_px}px; }}\n"
        # QTextEdit[readOnly="false"] scales EDITABLE text areas but leaves
        # read-only QTextBrowser HTML info panels (readOnly=True by default) on
        # their own earlier-group sizes. Property selectors out-specify `*`.
        # Caveat: a field toggled readOnly at RUNTIME would need an unpolish/
        # repolish to re-evaluate this rule; none of the affected editable fields
        # toggle readOnly, so their construction-time state is stable.
        f"QLineEdit, QPlainTextEdit, QTextEdit[readOnly=\"false\"] "
        f"{{ font-size: {text_px}px; }}\n"
        # Standard pop-ups (SPEC-FONT-001 §3.2, td-168ze A1): every QMessageBox /
        # QInputDialog (117 call sites) follows the pop-up rule from here, not per
        # call: its text is prose (info_text), its buttons are the bottom row
        # (action_buttons). Descendant selectors out-specify `*` and plain QLabel.
        f"QMessageBox QLabel, QInputDialog QLabel {{ font-size: {text_px}px; }}\n"
        f"QMessageBox QPushButton, QInputDialog QPushButton "
        f"{{ font-size: {scaled_area_px('action_buttons')}px; }}\n"
        f"{_INPUT_FONT_QSS_END}"
    )


def apply_global_input_font_qss(app) -> None:
    """Append (or refresh) the global input-font QSS on the QApplication stylesheet.
    Idempotent: strips any prior sentinel-wrapped block first, so it is safe to call
    after every theme apply AND on every font-size change without accumulating."""
    if app is None:
        return
    current = app.styleSheet() or ""
    b = current.find(_INPUT_FONT_QSS_BEGIN)
    if b != -1:
        e = current.find(_INPUT_FONT_QSS_END)
        if e != -1:
            current = current[:b] + current[e + len(_INPUT_FONT_QSS_END):]
        else:
            current = current[:b]
    current = current.rstrip("\n")
    app.setStyleSheet(current + "\n" + get_input_font_qss())
