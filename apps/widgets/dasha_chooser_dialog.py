# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The dasha chooser: one dialog for a dasha panel's title choices (td-fj70t.11.5).

Design "Ledger" (mockup competition 2026-10-05, Lorris's pick): a searchable list
grouped by category on the left, the chosen entry's details on the right (its
description, an optional settings block, what the choice changes), and a footer
with the keys, the panel title the choice gives, Cancel and Apply.

Its user fills it with its own entries: the Vimshottari ayanamsa of a side
(`choose_dasha_ayanamsa`, below).

Colours come from get_theme_colors() (Rule 20; the beta tag uses the semantic
warning colour) and every text size is a QSS font-size from the pop-up tiers.
"""

from typing import Callable, NamedTuple, Optional, Sequence

from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from ui.qt_theme import (
    STATUS, get_primary_button_style, get_scroll_style, get_secondary_button_style,
    get_theme_colors, hex_to_rgb_str, is_light_theme, scaled_px,
)
from ui.popup_fonts import fit_fixed_button, popup_group_px, popup_title_px, tier_px

_ENTRY = Qt.ItemDataRole.UserRole
_HEADER = Qt.ItemDataRole.UserRole + 1


class ChooserEntry(NamedTuple):
    key: object              # what the dialog returns (ayanamsa id, dasa id)
    name: str
    group: str               # list category (header)
    description: str = ""
    badge: str = ""          # e.g. "Beta": a warning tag after the name


def palette():
    """The dialog's colours from the theme (light and dark differ in which
    secondary shade is the list, the panes and the bars)."""
    t = get_theme_colors()
    light = is_light_theme()
    text = t["primary_text"]
    return {
        "accent": t["primary"],
        "accent_text": t["primary_text"],
        "text": text,
        "muted": f"rgba({hex_to_rgb_str(text)}, 0.68)",
        "rule": f"rgba({hex_to_rgb_str(text)}, 0.14)",
        "list_bg": t["secondary_light"] if light else t["secondary_dark"],
        "pane_bg": t["secondary"],
        "bar_bg": t["secondary_dark"] if light else t["secondary"],
        "card_bg": t["secondary_light"] if light else t["secondary_dark"],
        "warning": STATUS["warning"],
    }


def beta_tag(text="Beta"):
    """The small warning tag shown next to a beta choice."""
    lab = QLabel(text)
    lab.setObjectName("chooserBeta")
    lab.setStyleSheet(
        f"QLabel#chooserBeta {{ background: {STATUS['warning']}; color: #000000;"
        f" border-radius: 3px; padding: 0px 5px; font-weight: 700;"
        f" font-size: {tier_px('info_text', 10)}px; min-height: 0px; }}")
    from PySide6.QtWidgets import QSizePolicy
    lab.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    lab.ensurePolished()
    lab.setFixedHeight(lab.fontMetrics().height() + 4)
    return lab


class _RowDelegate(QStyledItemDelegate):
    """Paints a category header (accent caps + count + rule) or an entry row
    (radio, name, tags) in the theme colours."""

    def __init__(self, dialog):
        super().__init__(dialog)
        self._dialog = dialog

    def _font(self, px, bold=False):
        f = QFont(self._dialog.font())
        f.setPixelSize(px)
        f.setBold(bold)
        return f

    def sizeHint(self, option, index):
        if index.data(_HEADER):
            return QSize(10, tier_px("info_text", 12) + scaled_px(18))
        return QSize(10, tier_px("buttons", 13) + scaled_px(20))

    def paint(self, painter, option, index):
        pal = self._dialog.pal
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        header = index.data(_HEADER)
        if header:
            name, count = header
            painter.setFont(self._font(tier_px("info_text", 11), True))
            painter.setPen(QColor(pal["accent"]))
            box = r.adjusted(scaled_px(10), 0, -scaled_px(10), -scaled_px(2))
            painter.drawText(box, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                             name.upper())
            painter.drawText(box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                             str(count))
            painter.setPen(QPen(QColor(pal["accent"]), 1))
            painter.drawLine(box.left(), r.bottom(), box.right(), r.bottom())
            painter.restore()
            return
        entry = self._dialog.entry_at(index.data(_ENTRY))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        body = r.adjusted(scaled_px(4), scaled_px(2), -scaled_px(4), -scaled_px(2))
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(pal["accent"]))
            painter.drawRoundedRect(QRectF(body), 4, 4)
        elif option.state & QStyle.StateFlag.State_MouseOver:
            hover = QColor(pal["text"])      # QColor cannot parse a QSS rgba() string
            hover.setAlphaF(0.14)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(hover)
            painter.drawRoundedRect(QRectF(body), 4, 4)
        text_col = QColor(pal["accent_text"] if selected else pal["text"])
        # radio
        d = scaled_px(12)
        cx = body.left() + scaled_px(10)
        cy = body.center().y() - d // 2
        ring = QColor(pal["accent_text"] if selected else pal["accent"])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(ring, 2))
        painter.drawEllipse(QRectF(cx, cy, d, d))
        if entry.key == self._dialog.picked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ring)
            painter.drawEllipse(QRectF(cx + d * 0.27, cy + d * 0.27, d * 0.46, d * 0.46))
        # tags, right to left
        x_right = body.right() - scaled_px(8)
        tags = []
        if entry.key == self._dialog.current:
            tags.append(("current", None))
        if entry.badge:
            tags.append((entry.badge, pal["warning"]))
        tag_font = self._font(tier_px("info_text", 10), True)
        painter.setFont(tag_font)
        fm = painter.fontMetrics()
        for label, fill in tags:
            w = fm.horizontalAdvance(label) + scaled_px(12)
            h = fm.height() + scaled_px(2)
            box = QRectF(x_right - w, body.center().y() - h / 2, w, h)
            if fill:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(fill))
                painter.drawRoundedRect(box, 3, 3)
                painter.setPen(QColor("#000000"))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(text_col, 1))
                painter.drawRoundedRect(box, h / 2, h / 2)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
            x_right = box.left() - scaled_px(6)
        painter.setFont(self._font(tier_px("buttons", 13)))
        painter.setPen(text_col)
        name_box = body.adjusted(cx - body.left() + d + scaled_px(10), 0, 0, 0)
        name_box.setRight(int(x_right))
        painter.drawText(name_box, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         painter.fontMetrics().elidedText(
                             entry.name, Qt.TextElideMode.ElideRight, name_box.width()))
        painter.restore()


class DashaChooserDialog(QDialog):
    """List + detail chooser. `title_preview(key)` gives the panel title the
    choice makes; `change_note(key)` what it changes; `detail_widget(key, dialog)`
    an optional settings block under the description (rebuilt on each pick; it
    calls `dialog.refresh_preview()` when its values change)."""

    def __init__(self, parent=None, *, title: str, subtitle: str,
                 entries: Sequence[ChooserEntry], current, search_placeholder: str,
                 title_preview: Callable[[object], str],
                 change_note: Callable[[object], str],
                 detail_widget: Optional[Callable[[object, "DashaChooserDialog"],
                                                  Optional[QWidget]]] = None):
        super().__init__(parent)
        self.setObjectName("dashaChooser")
        self.setWindowTitle(title)
        self.setModal(True)
        self.entries = list(entries)
        self.current = current
        self.picked = current
        self._title_preview = title_preview
        self._change_note = change_note
        self._detail_widget = detail_widget
        self._extra = None
        self.pal = palette()
        self.resize(scaled_px(860), scaled_px(600))
        self.setMinimumSize(scaled_px(640), scaled_px(440))
        self.setStyleSheet(self._qss())

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # header
        head = QFrame(objectName="chooserBar")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(scaled_px(16), scaled_px(10), scaled_px(16), scaled_px(10))
        t = QLabel(title, objectName="chooserTitle")
        s = QLabel(subtitle, objectName="chooserSub")
        s.setWordWrap(True)
        hl.addWidget(t)
        hl.addSpacing(scaled_px(10))
        hl.addWidget(s, 1)
        outer.addWidget(head)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # left: search + list
        left = QFrame(objectName="chooserLeft")
        left.setFixedWidth(scaled_px(320))
        ll = QVBoxLayout(left)
        ll.setContentsMargins(scaled_px(10), scaled_px(10), scaled_px(6), scaled_px(6))
        ll.setSpacing(scaled_px(8))
        self.search = QLineEdit(objectName="chooserSearch")
        self.search.setPlaceholderText(search_placeholder)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        ll.addWidget(self.search)
        self.list = QListWidget(objectName="chooserList")
        self.list.setItemDelegate(_RowDelegate(self))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self._on_current)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        self.list.installEventFilter(self)
        ll.addWidget(self.list, 1)
        body.addWidget(left)

        # right: details
        scroll = QScrollArea(objectName="chooserRightScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(get_scroll_style())
        right = QWidget(objectName="chooserRight")
        self._rl = QVBoxLayout(right)
        self._rl.setContentsMargins(scaled_px(22), scaled_px(18), scaled_px(22), scaled_px(18))
        self._rl.setSpacing(scaled_px(6))
        self.d_group = QLabel(objectName="chooserGroup")
        self.d_name = QLabel(objectName="chooserName")
        self.d_desc = QLabel(objectName="chooserDesc")
        self.d_desc.setWordWrap(True)
        self._extra_slot = QVBoxLayout()
        self._extra_slot.setContentsMargins(0, scaled_px(6), 0, 0)
        card = QFrame(objectName="chooserCard")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(scaled_px(14), scaled_px(10), scaled_px(14), scaled_px(12))
        cl.setSpacing(scaled_px(4))
        cl.addWidget(QLabel("WHAT THIS CHANGES", objectName="chooserCardTitle"))
        self.d_note = QLabel(objectName="chooserDesc")
        self.d_note.setWordWrap(True)
        cl.addWidget(self.d_note)
        for w in (self.d_group, self.d_name, self.d_desc):
            self._rl.addWidget(w)
        self._rl.addLayout(self._extra_slot)
        self._rl.addSpacing(scaled_px(8))
        self._rl.addWidget(card)
        self._rl.addStretch(1)
        scroll.setWidget(right)
        body.addWidget(scroll, 1)

        # footer
        foot = QFrame(objectName="chooserBar")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(scaled_px(16), scaled_px(10), scaled_px(16), scaled_px(10))
        fl.addWidget(QLabel("↑ ↓ move    Enter apply    Esc cancel", objectName="chooserHint"))
        fl.addStretch(1)
        fl.addWidget(QLabel("Panel title:", objectName="chooserHint"))
        self.preview = QLabel(objectName="chooserPreview")
        fl.addWidget(self.preview)
        fl.addSpacing(scaled_px(12))
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(get_secondary_button_style())
        cancel.clicked.connect(self.reject)
        apply_btn = QPushButton("Apply")
        apply_btn.setStyleSheet(get_primary_button_style())
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self.accept)
        for b in (cancel, apply_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            fit_fixed_button(b, scaled_px(88), scaled_px(34))
            fl.addWidget(b)
        self.apply_btn = apply_btn
        outer.addWidget(foot)
        # Enter applies (review round 1): the default button is only honoured once
        # the buttons live in the dialog, and Cancel must never auto-default.
        cancel.setAutoDefault(False)
        apply_btn.setAutoDefault(True)
        apply_btn.setDefault(True)

        self._fill()
        self._select(current)
        self.list.setFocus()

    # -- style ---------------------------------------------------------------- #

    def _qss(self):
        p = self.pal
        return f"""
            QDialog#dashaChooser {{ background: {p['pane_bg']}; }}
            QFrame#chooserBar {{ background: {p['bar_bg']}; border: none; }}
            QFrame#chooserLeft {{ background: {p['list_bg']};
                                 border-right: 1px solid {p['rule']}; }}
            QWidget#chooserRight {{ background: {p['pane_bg']}; }}
            QWidget#chooserExtra {{ background: transparent; }}
            QLabel#chooserTitle {{ color: {p['text']}; font-weight: 700;
                                  font-size: {popup_title_px(15)}px; }}
            QLabel#chooserSub, QLabel#chooserHint {{ color: {p['muted']};
                                  font-size: {tier_px('info_text', 11)}px; }}
            QLineEdit#chooserSearch {{ color: {p['text']}; background: {p['pane_bg']};
                                  border: 1px solid {p['rule']}; border-radius: 6px;
                                  padding: 6px 8px; font-size: {tier_px('buttons', 13)}px; }}
            QLineEdit#chooserSearch:focus {{ border: 1px solid {p['accent']}; }}
            QListWidget#chooserList {{ background: transparent; border: none;
                                  outline: none; }}
            QListWidget#chooserList::item {{ background: transparent; border: none; }}
            QLabel#chooserGroup {{ color: {p['accent']}; font-weight: 700;
                                  font-size: {popup_group_px(11)}px; }}
            QLabel#chooserName {{ color: {p['text']}; font-weight: 700;
                                  font-size: {popup_title_px(17)}px; }}
            QLabel#chooserDesc {{ color: {p['text']}; font-size: {tier_px('info_text', 13)}px; }}
            QLabel#chooserFieldLabel {{ color: {p['text']}; font-weight: 700;
                                  font-size: {tier_px('info_text', 12)}px; }}
            QLabel#chooserNoteSmall {{ color: {p['muted']};
                                  font-size: {tier_px('info_text', 11)}px; }}
            QFrame#chooserCard {{ background: {p['card_bg']}; border: 1px solid {p['rule']};
                                 border-radius: 6px; }}
            QLabel#chooserCardTitle {{ color: {p['muted']}; font-weight: 700;
                                  font-size: {tier_px('info_text', 10)}px; }}
            QLabel#chooserPreview {{ background: {p['accent']}; color: {p['accent_text']};
                                  border-radius: 4px; padding: 3px 8px; font-weight: 700;
                                  font-size: {tier_px('info_text', 12)}px; }}
            QFrame#chooserWarn {{ background: rgba({hex_to_rgb_str(p['warning'])}, 0.16);
                                 border: none; border-left: 4px solid {p['warning']};
                                 border-radius: 4px; }}
            QLabel#chooserWarnTitle {{ color: {p['text']}; font-weight: 700;
                                  font-size: {tier_px('info_text', 12)}px; }}
            QLabel#chooserWarnText {{ color: {p['text']}; font-size: {tier_px('info_text', 12)}px; }}
        """

    # -- list ----------------------------------------------------------------- #

    def _fill(self):
        self.list.clear()
        counts = {}
        for e in self.entries:
            counts[e.group] = counts.get(e.group, 0) + 1
        group = None
        for idx, e in enumerate(self.entries):
            if e.group != group:
                group = e.group
                h = QListWidgetItem()
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                h.setData(_HEADER, (group, counts[group]))
                self.list.addItem(h)
            it = QListWidgetItem(e.name)
            it.setData(_ENTRY, idx)
            it.setToolTip(e.description)
            self.list.addItem(it)

    def _filter(self, text):
        q = text.strip().lower()
        visible_groups = set()
        for i in range(self.list.count()):
            it = self.list.item(i)
            e = self.entry_at(it.data(_ENTRY))
            if e is not None:
                show = not q or q in e.name.lower() or q in e.group.lower()
                it.setHidden(not show)
                if show:
                    visible_groups.add(e.group)
        for i in range(self.list.count()):
            it = self.list.item(i)
            h = it.data(_HEADER)
            if h is not None:
                it.setHidden(h[0] not in visible_groups)
        cur = self.list.currentItem()
        if cur is None or cur.isHidden():
            first = self._first_visible()
            if first is not None:
                self.list.setCurrentItem(first)

    def _first_visible(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if not it.isHidden() and self.entry_at(it.data(_ENTRY)) is not None:
                return it
        return None

    def _select(self, key):
        for i in range(self.list.count()):
            it = self.list.item(i)
            e = self.entry_at(it.data(_ENTRY))
            if e is not None and e.key == key:
                self.list.setCurrentItem(it)
                self.list.scrollToItem(it, QListWidget.ScrollHint.PositionAtCenter)
                return
        first = self._first_visible()
        if first is not None:
            self.list.setCurrentItem(first)

    def _on_current(self, item, _prev=None):
        e = self.entry_at(item.data(_ENTRY)) if item is not None else None
        if e is None:
            return
        self.picked = e.key
        self.list.viewport().update()
        self.d_group.setText(e.group.upper())
        self.d_name.setText(e.name)
        self.d_desc.setText(e.description)
        self.d_desc.setVisible(bool(e.description))
        if self._extra is not None:
            self._extra_slot.removeWidget(self._extra)
            self._extra.hide()
            self._extra.setParent(None)      # gone now, not at the next event loop
            self._extra.deleteLater()
            self._extra = None
        if self._detail_widget is not None:
            w = self._detail_widget(e.key, self)
            if w is not None:
                self._extra_slot.addWidget(w)
                self._extra = w
        self.refresh_preview()

    def refresh_preview(self):
        """Re-read the panel title and the change note (a settings block calls
        this when one of its values changes)."""
        self.preview.setText(self._title_preview(self.picked))
        self.d_note.setText(self._change_note(self.picked))

    # -- keys ----------------------------------------------------------------- #

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        lst = getattr(self, "list", None)       # the search field exists first
        if lst is None:
            return super().eventFilter(obj, event)
        if obj is lst and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.accept()
                return True
            # typing in the list goes to the search field (QListWidget would
            # otherwise eat the letters for its own keyboard search)
            text = event.text()
            if (text and text.isprintable()
                    and not event.modifiers() & ~Qt.KeyboardModifier.ShiftModifier):
                self.search.setFocus()
                self.search.insert(text)
                return True
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.accept()
                return True
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self.list.setFocus()
                self.list.keyPressEvent(event)
                return True
            if event.key() == Qt.Key.Key_Escape and self.search.text():
                self.search.clear()
                return True
        return super().eventFilter(obj, event)

    def entry_at(self, idx):
        """The entry an item holds (items store the index: Qt turns a tuple into
        a list), or None for a header."""
        return self.entries[idx] if isinstance(idx, int) else None

    def selected_key(self):
        return self.picked


# --------------------------------------------------------------------------- #
# Vimshottari ayanamsa of a dasha side
# --------------------------------------------------------------------------- #

def ayanamsa_entries(jd=None):
    """Every ayanamsa, its name followed by the exact degrees it subtracts at ``jd``
    (default today)."""
    from core.ayanamsa_data import (AYANAMSA_OPTIONS, CATEGORY_ORDER, get_ayanamsa_tooltip,
                                    name_with_offset, today_jd)
    jd = today_jd() if jd is None else jd
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    opts = sorted(enumerate(AYANAMSA_OPTIONS),
                  key=lambda p: (order.get(p[1][2], len(order)), p[0]))
    return [ChooserEntry(aid, name_with_offset(aid, jd), cat, get_ayanamsa_tooltip(aid))
            for _i, (aid, _name, cat, _tip) in opts]


def ayanamsa_change_note(side):
    other = "left" if side == "right" else "right"
    # The edition names its pages that follow the left ayanamsa (td-txv5v).
    from ui.edition_panels import left_ayanamsa_note
    also = left_ayanamsa_note() if side == "left" else ""
    return ("The Moon's nakshatra is measured with this ayanamsa, so every Vimshottari "
            f"date in the {side} panel moves with it. The chart itself and the {other} "
            f"panel stay as they are.{also}")


def choose_dasha_ayanamsa(parent, side, current):
    """The dasha ayanamsa chooser of `side`: the picked id, or None (Cancel)."""
    from core.ayanamsa_data import get_ayanamsa_name
    other = "left" if side == "right" else "right"
    entries = ayanamsa_entries()
    dlg = DashaChooserDialog(
        parent, title="Dasha ayanamsa",
        subtitle=(f"Vimshottari, {side} panel. The {other} panel keeps its own ayanamsa. "
                  "The degrees are the sign offset each one subtracts today; Dhruva "
                  "and Vedanga nakshatras are equatorial, not a single shift."),
        entries=entries, current=current,
        search_placeholder=f"Search {len(entries)} ayanamsas",
        title_preview=lambda k: f"{get_ayanamsa_name(k)}  ▾",
        change_note=lambda _k: ayanamsa_change_note(side))
    try:
        return dlg.selected_key() if dlg.exec() else None
    finally:
        dlg.deleteLater()           # parented to the window: free it now it is closed
