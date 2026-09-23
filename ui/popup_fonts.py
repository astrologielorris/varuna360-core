"""Pop-up text sizes (SPEC-FONT-001 §3.2, td-168ze).

Everything descriptive in a pop-up window follows the Info text area, titles
included. panel_titles is capped low in the presets (SPEC-FONT-002 §3.1) and
would sit under the body text, so pop-up headings are fixed multiples of
info_text instead. Kept out of ui/qt_theme.py, which the SI architecture
ratchet does not let grow.
"""
import logging

from ui.qt_theme import AREA_DEFAULTS, scaled_area_px, scaled_tier_size

_LOG = logging.getLogger(__name__)

# Default parity (a2 review of td-168ze): the rule decides WHICH area a pop-up
# text follows; its size at default settings stays the size it had before the
# rule (base 41ef133d). Every site passes its own base px and gets
# scaled_tier_size(base_px, area): exactly base_px at defaults, scaled by the
# area's factor (setting x display scale) otherwise.


def tier_px(area: str, base_px: float) -> int:
    """QSS px for a pop-up text that follows `area` and was `base_px` at
    default settings."""
    return max(5, scaled_tier_size(base_px, area))


def tier_point_px(area: str, base_pt: float, family: str = "") -> int:
    """Route a historical point-size site through an area while preserving
    its effective default pixels at the current DPI."""
    from PySide6.QtGui import QFont, QFontInfo
    font = QFont(family) if family else QFont()
    font.setPointSizeF(base_pt)
    return tier_px(area, QFontInfo(font).pixelSize())


def popup_title_px(base_px: float = 14) -> int:
    """A pop-up's own title: follows Info text, keeps its base size (most
    titles were panel_titles 14 before the rule; pass the site's own)."""
    return tier_px("info_text", base_px)


def popup_group_px(base_px: float) -> int:
    """A group / section header inside a pop-up: follows Info text, keeps the
    site's base size."""
    return tier_px("info_text", base_px)


def in_dialog_button_style(primary: bool = False) -> str:
    """The shared primary / secondary button look, following ``buttons``, for a
    control INSIDE a pop-up (navigation, list actions). The shared helpers
    stay ``action_buttons`` for the dialog's bottom row (SPEC-FONT-001 §3.2,
    A14); the size at defaults is unchanged (the helpers' action_buttons px)."""
    from ui.qt_theme import get_primary_button_style, get_secondary_button_style
    qss = get_primary_button_style() if primary else get_secondary_button_style()
    return qss.replace(f"font-size: {scaled_area_px('action_buttons')}px",
                       f"font-size: {tier_px('buttons', AREA_DEFAULTS['action_buttons'])}px")


def fit_text_width(text: str, legacy: int, area: str = "buttons",
                   pad: int = 28, button: bool = True) -> int:
    """Width that shows `text` whole at the area's CURRENT size, never below the
    legacy fixed width (so defaults keep their look). qt-material draws push
    buttons bold and upper-case, so a button is measured that way."""
    from PySide6.QtGui import QFont, QFontMetrics
    f = QFont()
    f.setPixelSize(scaled_area_px(area))
    if button:
        f.setBold(True)
        text = text.upper()
    return max(legacy, QFontMetrics(f).horizontalAdvance(text) + pad)


def fit_fixed_button(btn, legacy_w: int, legacy_h: int) -> None:
    """Give a fixed-size button a size that is a FLOOR, not a cap: never
    narrower or shorter than the styled button needs for its current text and
    font, never smaller than the legacy size (so defaults keep their look).
    Call after the button's stylesheet is set, and again after setText."""
    btn.ensurePolished()
    btn.setFixedSize(max(legacy_w, btn.sizeHint().width()),
                     max(legacy_h, btn.fontMetrics().height() + 14))


# ── Live refresh for non-modal pop-ups ────────────────────────────────────────
# A non-modal pop-up can stay open while Settings > Fonts is applied, and Lorris
# tests it that way. Instead of a ChartGUI attribute per dialog (Rule 4b), a
# pop-up registers each font-bearing stylesheet ONCE, as a function that rebuilds
# it; ChartGUI._refresh_scaled_surfaces calls refresh_live_popups() on every font
# change and the visible ones re-apply. Entries leave the registry when Qt
# destroys the dialog. The strong reference keeps the Python wrapper (and its
# closures) alive exactly as long as the C++ dialog.
_LIVE = {}


def live_refresh(dialog, fn, *, now: bool = False) -> None:
    """Call ``fn()`` on every font change while ``dialog`` is visible (and once
    now when ``now``). For work beyond a stylesheet, e.g. re-rendering HTML."""
    key = id(dialog)
    entry = _LIVE.get(key)
    if entry is None:
        entry = (dialog, [])
        _LIVE[key] = entry
        dialog.destroyed.connect(lambda *_a, _k=key: _LIVE.pop(_k, None))
    entry[1].append(fn)
    if now:
        fn()


def live_style(dialog, widget, qss_fn) -> None:
    """Apply ``qss_fn()`` to ``widget`` now and again on every font change while
    ``dialog`` is visible (SPEC-FONT-001 §3.2 live refresh)."""
    live_refresh(dialog, lambda: widget.setStyleSheet(qss_fn()), now=True)


def refresh_live_popups() -> int:
    """Re-apply every registered style of every VISIBLE registered pop-up.
    Returns how many pop-ups were refreshed (for tests)."""
    done = 0
    for key, (dialog, pairs) in list(_LIVE.items()):
        try:
            if not dialog.isVisible():
                continue
        except RuntimeError:          # C++ side already gone
            _LIVE.pop(key, None)
            continue
        refreshed = False
        for fn in list(pairs):
            try:
                fn()
                refreshed = True
            except Exception:
                # A faulty callback must not prevent healthy open pop-ups from
                # following the same Fonts Apply fan-out.
                _LOG.exception("Pop-up font refresh callback failed")
                continue
        if refreshed:
            done += 1
    return done


def live_rebuild(dialog, rebuild) -> None:
    """For a pop-up built inline in one function: on a font change, while it is
    visible, ``rebuild()`` builds and shows a fresh one (and returns it); the
    fresh one takes the old one's place and size, the old one is disposed."""
    def _redo():
        geo = dialog.geometry()
        fresh = rebuild()
        if fresh is not None and fresh is not dialog:
            fresh.setGeometry(geo)
            dialog.hide()
            dialog.deleteLater()
    live_refresh(dialog, _redo)
