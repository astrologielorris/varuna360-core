# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under the GNU AGPL-3.0. See LICENSE at the repository root.
"""Content-rect fit helpers for QSS-styled (qt-material) widgets — td-2o8u.

WHY THIS EXISTS
    Under qt-material a widget's OUTER rect includes QSS padding + border, and
    combos/spinboxes carry edit sub-controls (a spinbox spends ~40px of its
    width on the up/down buttons). The text paints only in the CONTENT rect.
    Sizing or asserting geometry against the OUTER rect therefore hides real
    clipping: a button can be 38px tall yet give its glyph only a 26px content
    band, so at large Wave-7 fonts (fm.height ~50) the text clips while
    ``height()`` still reads a comfortable 38.

WHAT THESE DO
    ``content_height`` / ``content_width`` return the rectangle where the glyph
    actually paints (SE_PushButtonContents for buttons, the edit sub-control for
    combos/spinboxes, contents-margins for plain widgets). ``chrome_v`` /
    ``chrome_h`` return the FIXED padding+border+sub-control overhead, measured
    against a large probe rect so it is independent of the widget's current
    size. ``fit_height`` / ``fit_width`` compose them into the outer dimension
    that makes the CONTENT rect hold the widget's OWN fontMetrics — floored at a
    legacy value so default-area parity is preserved exactly.

    Geometry code sizes with fit_*; pins assert content_* >= own fm.
"""
from PySide6.QtCore import QRect
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QStyleOptionComboBox,
    QStyleOptionSpinBox,
)

# Large probe rect: chrome (padding/border/sub-controls) is a fixed inset, so
# subtracting the content rect from a big rect isolates it from the outer size.
_PROBE = QRect(0, 0, 4000, 400)


def _content_rect(w, rect):
    """The content sub-rectangle of ``w`` within ``rect`` (where text paints)."""
    st = w.style()
    if isinstance(w, QCheckBox):
        # A checkbox spends part of its width on the indicator box + the
        # indicator-to-text spacing; the label paints only in SE_CheckBoxContents.
        # Falling through to contents-margins would leave that ~20px band blind.
        opt = QStyleOptionButton()
        w.initStyleOption(opt)
        opt.rect = rect
        return st.subElementRect(QStyle.SubElement.SE_CheckBoxContents, opt, w)
    if isinstance(w, QPushButton):
        opt = QStyleOptionButton()
        w.initStyleOption(opt)
        opt.rect = rect
        return st.subElementRect(QStyle.SubElement.SE_PushButtonContents, opt, w)
    if isinstance(w, QComboBox):
        opt = QStyleOptionComboBox()
        w.initStyleOption(opt)
        opt.rect = rect
        return st.subControlRect(
            QStyle.ComplexControl.CC_ComboBox, opt,
            QStyle.SubControl.SC_ComboBoxEditField, w)
    if isinstance(w, QAbstractSpinBox):
        opt = QStyleOptionSpinBox()
        w.initStyleOption(opt)
        opt.rect = rect
        return st.subControlRect(
            QStyle.ComplexControl.CC_SpinBox, opt,
            QStyle.SubControl.SC_SpinBoxEditField, w)
    m = w.contentsMargins()
    return rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())


def content_height(w):
    """Vertical px the widget's text gets at its CURRENT size."""
    return _content_rect(w, w.rect()).height()


def content_width(w):
    """Horizontal px the widget's text gets at its CURRENT size."""
    return _content_rect(w, w.rect()).width()


def chrome_v(w):
    """Fixed vertical chrome (padding+border), independent of the widget size."""
    return _PROBE.height() - _content_rect(w, _PROBE).height()


def chrome_h(w):
    """Fixed horizontal chrome (padding+border+sub-controls e.g. spin buttons)."""
    return _PROBE.width() - _content_rect(w, _PROBE).width()


def fit_height(w, legacy=0, pad=0):
    """Outer height whose CONTENT rect holds ``w``'s own fm.height().

    Floored at ``legacy`` so default-area rendering is pixel-identical to the
    pristine fixed value; grows only when the live font needs more.
    """
    return max(legacy, w.fontMetrics().height() + chrome_v(w) + pad)


def fit_width(w, text, legacy=0, pad=0):
    """Outer width whose CONTENT rect holds ``text`` at ``w``'s own fm."""
    return max(legacy, w.fontMetrics().horizontalAdvance(text) + chrome_h(w) + pad)


def fits_v(w):
    """True iff the content rect currently holds the widget's own fm.height()."""
    return content_height(w) >= w.fontMetrics().height()


def fits_h(w, text):
    """True iff the content rect currently holds ``text`` at the widget's fm."""
    return content_width(w) >= w.fontMetrics().horizontalAdvance(text)
