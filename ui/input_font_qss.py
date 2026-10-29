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
        f"{_stamp_rules()}"
        f"{_INPUT_FONT_QSS_END}"
    )


# ── td-8m3kd: a font change restyles the targeted widgets, not the app ─────
#
# Re-writing the app sheet above repolishes EVERY widget of the app (4894 in
# the full window, 7.5-11 s at load 8-13) to change the font of a few
# hundred. So the block also holds one CONSTANT rule per pixel size, keyed on
# a dynamic property of the targeted widget itself (no ancestor walk):
# ``QComboBox[v360fs="12"] { font-size: 12px; }``. A font change
# (``apply_input_font_sizes``) stamps each targeted widget on screen with its
# area's new px and repolishes it alone; a targeted widget not on screen is
# stamped just before it is next shown (a Show hook on the app's one Python
# event filter, ``managers.context_menu_manager.add_show_hook``). The rules
# out-specify the sentinel block's plain type rules (type + attribute), so
# a stamped widget shows its stamp and an unstamped one the block's sizes,
# which a full re-apply (boot, theme change) brings up to date, stamps
# included. Where the hook cannot run (the filter is held off for a web view,
# or there is no block yet) the font change falls back to the full re-apply.

STAMP = "v360fs"
_STAMP_MIN, _STAMP_MAX = 5, 80          # scaled_area_px: 5 .. 48 x 1.6
_STAMP_TYPES = ("QComboBox", "QAbstractItemView", "QSpinBox", "QDoubleSpinBox",
                "QLineEdit", "QPlainTextEdit", "QTextEdit", "QLabel", "QPushButton")
# The sizes the sentinel block was last written with ({area: px}).
_block_sizes = {}
_stamped_any = False


def _stamp_rules() -> str:
    lines = []
    for px in range(_STAMP_MIN, _STAMP_MAX + 1):
        sel = ", ".join(f'{t}[{STAMP}="{px}"]' for t in _STAMP_TYPES)
        lines.append(f"{sel} {{ font-size: {px}px; }}\n")
    return "".join(lines)


def _sizes() -> dict:
    return {a: scaled_area_px(a) for a in ("buttons", "info_text", "action_buttons")}


def _area_of(widget):
    """The font area the sentinel block gives ``widget``, or None when the
    block does not target it (the same choice as its type rules)."""
    from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDoubleSpinBox,
                                   QInputDialog, QLabel, QLineEdit, QMessageBox,
                                   QPlainTextEdit, QPushButton, QSpinBox, QTextEdit)
    if isinstance(widget, (QComboBox, QSpinBox, QDoubleSpinBox)):
        return "buttons"
    if isinstance(widget, (QLineEdit, QPlainTextEdit)):
        return "info_text"
    if isinstance(widget, QTextEdit):
        return None if widget.isReadOnly() else "info_text"
    if isinstance(widget, QAbstractItemView):
        parent = widget.parentWidget()
        while parent is not None and not isinstance(parent, QComboBox):
            parent = parent.parentWidget()      # the popup sits in a container
        return "buttons" if parent is not None else None
    if isinstance(widget, (QLabel, QPushButton)):
        box = widget.window()
        if isinstance(box, (QMessageBox, QInputDialog)) and box is not widget:
            return "info_text" if isinstance(widget, QLabel) else "action_buttons"
    return None


def _stamp(widget, px: int, repolish: bool) -> None:
    global _stamped_any
    widget.setProperty(STAMP, str(px))
    _stamped_any = True
    if repolish:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.updateGeometry()
        widget.update()


def _on_show(widget) -> None:
    """The Show hook: a targeted widget shows its area's current size."""
    if not _stamped_any:
        return                                  # no scoped change yet
    area = _area_of(widget)
    if area is None:
        return
    px = scaled_area_px(area)
    have = widget.property(STAMP)
    if have is None and _block_sizes.get(area) == px:
        return                                  # the block's size is current
    if have != str(px):
        _stamp(widget, px, repolish=True)


def stamp_for_draw(root) -> None:
    """``root`` is about to be drawn without being shown (an export, a
    capture): its targeted widgets drawn with it take their area's current
    size now, as their Show would (managers.font_refresh_deferral
    .run_pending_for)."""
    if not _stamped_any or root is None:
        return
    from PySide6.QtWidgets import QWidget
    _on_show(root)
    for w in root.findChildren(QWidget):
        if w.isVisibleTo(root):
            _on_show(w)


def _restamp_all(sizes) -> None:
    """Before a full re-apply: every stamped widget gets the new size, so a
    stamp never keeps an old size over the block (the app restyle that
    follows repolishes them)."""
    from PySide6.QtWidgets import QApplication
    for w in QApplication.allWidgets():
        if w.property(STAMP) is not None:
            area = _area_of(w)
            if area is not None:
                w.setProperty(STAMP, str(sizes[area]))


def apply_input_font_sizes(app) -> None:
    """A font size or the display scale changed: the targeted widgets take
    their area's new size. Scoped (only the targeted widgets on screen are
    repolished, the others when shown) when the sentinel block is in the app
    sheet and the Show hook can run; otherwise the full re-apply."""
    global _stamped_any
    if app is None:
        return
    from managers import context_menu_manager as cm
    if (_INPUT_FONT_QSS_BEGIN not in (app.styleSheet() or "")
            or not cm.is_search_context_menu_active()):
        apply_global_input_font_qss(app)
        return
    cm.add_show_hook(_on_show)
    from PySide6.QtWidgets import QApplication
    sizes = _sizes()
    if sizes == _block_sizes and not _stamped_any:
        return                                  # nothing to change
    _stamped_any = True                         # the hook now checks shows
    for w in QApplication.allWidgets():
        if not w.isVisible():
            continue
        area = _area_of(w)
        if area is None:
            continue
        want = str(sizes[area])
        have = w.property(STAMP)
        if have == want or (have is None and _block_sizes.get(area) == sizes[area]):
            continue
        _stamp(w, sizes[area], repolish=True)


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
    # SPEC-THM-001 §13: the accent-ink block rides the same single write.
    from ui.accent_ink_qss import accent_selection_qss, strip_accent_selection_qss
    current = strip_accent_selection_qss(current).rstrip("\n")
    global _block_sizes
    sizes = _sizes()
    if _stamped_any:
        _restamp_all(sizes)
    _block_sizes = sizes
    sheet = current + "\n" + accent_selection_qss() + "\n" + get_input_font_qss()
    if sheet == (app.styleSheet() or ""):
        # td-8m3kd: an unchanged sheet would still repolish every widget of
        # the app (seconds on the full window); most font areas (tabs, chart
        # names, sidebar...) never reach this block.
        return
    # The app-wide restyle sends an event to every widget: the Python
    # right-click filter stays off for it (it only wants ContextMenu).
    from managers.context_menu_manager import search_context_menu_paused
    with search_context_menu_paused():
        app.setStyleSheet(sheet)
