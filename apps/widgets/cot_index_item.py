# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
The in-chart Cards of Truth index — SPEC-COT-001 §4.10, one implementation.

Three chart views draw the same thing: for each sign, the card belonging to
that sign's LORD, as a small rank + suit plaque. They differ only in WHERE the
plaque goes, which is a property of each chart's geometry and belongs in each
view. Everything else — reading the setting, subscribing to changes without
pinning the widget, memoising the spread, and drawing the plaque itself — is
identical, and lives here.

Why one module rather than three copies
---------------------------------------
``SettingsManager.on_changed`` stores its callbacks strongly for the life of
the process and offers no unsubscribe. A callback closing over ``self`` pins
the view, and through it the whole widget tree; the host builds one view per
chart widget, with the dual-chart and comparison panels building more. That
trap was already sprung once and caught in review. Written by hand a second and
third time it would be sprung again, silently, in whichever copy got written in
a hurry. ``CotIndexMixin`` is the one place it is written.

The plaque art follows for the same reason ``card_suit_art`` exists: three
places computing a rank width and a pip offset is three places for them to
drift into three different-looking cards.
"""

import weakref

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF,
    QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsSimpleTextItem,
)

from apps.widgets.card_suit_art import suit_ink, suit_pixmap
from core.cards_of_truth_data import (
    CardsOfTruthUnavailable,
    DEFAULT_ORDER as COT_DEFAULT_ORDER,
    # Re-exported: the Qt-free CLI needs the same label table, so it lives in
    # the pure module and every surface imports it from wherever is handy.
    ORDER_LABELS,
    assemble_spread,
    sign_card_faces,
)

#: The two settings that change what this draws. Both are watched: the ORDER
#: changes which card a position holds, so a spread cached across an order
#: change is stale even though the chart did not move.
COT_SETTING_KEY = "cot.show_in_chart"
COT_ORDER_KEY = "cot.planet_order"


def read_persisted_order():
    """The stored position order, falling back to the Kala-verified default.

    The fallback is ``solar_system`` (SPEC-COT-001 D-5), NOT the library's
    ``vedic``: a missing setting must not silently mislabel three of the seven
    main cards. Never raises — a settings failure degrades to the default.
    """
    try:
        from managers.settings_manager import get_settings
        value = get_settings().get(COT_ORDER_KEY, COT_DEFAULT_ORDER)
    except Exception:                                # noqa: BLE001
        return COT_DEFAULT_ORDER
    return value if value in ORDER_LABELS else COT_DEFAULT_ORDER


#: Plaque metrics at ``scale=1.0``, in scene units. These are the values
#: SPEC-COT-001 §4.10 arrived at for the South Indian grid, where the sign name
#: renders at 24pt in a 2048-unit scene. Every other view scales them against
#: its own sign-name size rather than inventing its own numbers, so the card
#: keeps the same optical weight relative to the name it sits beside.
COT_RANK_PT = 26        # Inter points, one step above the sign name (24)
COT_PIP_PX = 30         # suit pip side, optically matched to the rank
COT_PAD_X = 13
COT_PAD_Y = 7
COT_SPACING = 5         # rank-to-pip gap

#: The sign-name size the metrics above were tuned against. A view whose names
#: render at some other size passes ``scale_for_name(its_size)`` so the card
#: keeps the same relation to the name — a rank one step larger — rather than
#: an absolute size that would read as huge in one chart and tiny in another.
COT_REFERENCE_NAME_PT = 24


def scale_for_name(name_pt):
    """Plaque scale that keeps the card in proportion to a sign name."""
    if not name_pt or name_pt <= 0:
        return 1.0
    return float(name_pt) / COT_REFERENCE_NAME_PT


#: Plaque z-values. Above the sign badge (4.5) so a plaque that lands on an
#: icon is readable, below the planets (6) so it never hides a body.
COT_Z_PLAQUE = 4.55
COT_Z_INK = 4.6


class CotPlaque:
    """A measured rank+suit plaque, ready to place.

    Measuring and placing are separate steps because every caller has to lay
    the plaque out against something else — a leftover band, a sector arc, a
    triangle tip — and needs the size before it can decide where the centre
    goes, or whether there is room at all.

    The plaque exists rather than bare ink because the sign cells are strongly
    coloured in both themes: a red pip on the red Dhata cell would vanish. It
    borrows the sign-name pill's recipe (theme secondary fill, gold hairline)
    so it reads as a peer of the name, and the suit ink is then contrasted
    against the pill rather than against whichever element the sign happens to
    be.
    """

    def __init__(self, card, scale=1.0, dpr=1.0, light=None):
        """
        Args:
            card: one row of an ``assemble_spread`` result.
            scale: multiplies every metric. Use ``sign_name_pt / 26`` so the
                card tracks the label it sits beside.
            dpr: device pixel ratio, forwarded to the pip raster cache.
            light: theme override; resolved live when omitted.
        """
        self.card = card
        self.scale = scale
        self.ink = QColor(suit_ink(card["is_red"], light))
        self.rank = card["rank_display"]

        # Same font pipeline as the sign names, so the plaque sits inside the
        # chart's typography rather than beside it.
        self.font = QFont("Inter")
        self.font.setPointSizeF(COT_RANK_PT * scale)
        self.font.setWeight(QFont.Weight.Bold)
        metrics = QFontMetricsF(self.font)
        self._rank_w = metrics.horizontalAdvance(self.rank)
        rank_h = metrics.height()

        self.pip = suit_pixmap(card["suit_name"], COT_PIP_PX * scale,
                               self.ink, dpr)
        self._pip_w = self.pip.width() / self.pip.devicePixelRatio() if self.pip else 0.0
        self._pip_h = self.pip.height() / self.pip.devicePixelRatio() if self.pip else 0.0

        self._pad_x = COT_PAD_X * scale
        self._pad_y = COT_PAD_Y * scale
        spacing = COT_SPACING * scale

        content_w = self._rank_w + (spacing + self._pip_w if self.pip else 0.0)
        content_h = max(rank_h, self._pip_h)
        self._spacing = spacing
        self.width = content_w + 2 * self._pad_x
        self.height = content_h + 2 * self._pad_y

    def add_to(self, scene, center_x, center_y, tag=None, z=COT_Z_PLAQUE):
        """Add the plaque centred on ``(center_x, center_y)``.

        Returns the list of items added, so a caller that keeps its own
        registry does not have to re-find them in the scene.
        """
        from ui.qt_theme import GOLD, get_theme_colors

        colors = get_theme_colors()
        fill = QColor(colors["secondary"])
        fill.setAlphaF(0.88)
        border = QColor(GOLD)
        border.setAlphaF(0.55)

        left = center_x - self.width / 2.0
        top = center_y - self.height / 2.0
        rect = QRectF(left, top, self.width, self.height)

        items = []

        path = QPainterPath()
        path.addRoundedRect(rect, self.height / 2, self.height / 2)
        plaque = QGraphicsPathItem(path)
        plaque.setBrush(QBrush(fill))
        plaque.setPen(QPen(border, 1.5 * self.scale))
        plaque.setZValue(z)
        if tag:
            plaque.setData(Qt.ItemDataRole.UserRole, tag)
        scene.addItem(plaque)
        items.append(plaque)

        ink_z = z + (COT_Z_INK - COT_Z_PLAQUE)

        text = QGraphicsSimpleTextItem(self.rank)
        text.setFont(self.font)
        text.setBrush(QBrush(self.ink))
        text.setPen(QPen(Qt.PenStyle.NoPen))
        tb = text.boundingRect()
        text.setPos(left + self._pad_x, center_y - tb.height() / 2.0)
        text.setZValue(ink_z)
        if tag:
            text.setData(Qt.ItemDataRole.UserRole, tag)
        scene.addItem(text)
        items.append(text)

        if self.pip:
            pip_item = QGraphicsPixmapItem(self.pip)
            pip_item.setTransformationMode(
                Qt.TransformationMode.SmoothTransformation)
            pip_item.setPos(left + self._pad_x + self._rank_w + self._spacing,
                            center_y - self._pip_h / 2.0)
            pip_item.setZValue(ink_z)
            if tag:
                pip_item.setData(Qt.ItemDataRole.UserRole, tag)
            scene.addItem(pip_item)
            items.append(pip_item)

        return items



class CotIndexMixin:
    """Setting, subscription and memoised faces for an in-chart card index.

    A view mixes this in, calls ``_cot_init()`` from ``__init__`` after its
    scene exists, and implements ``_cot_repaint()``. Placement stays with the
    view; nothing here knows what a sector or a house cell is.
    """

    #: Prefixes the warnings, so a message in the log names the view it came
    #: from rather than this module, which every view shares.
    _cot_log_prefix = "[COT]"

    def _cot_init(self):
        """Wire the caches and the live-update subscription.

        Subscribing matters: without it the checkbox appears to do nothing
        until the next chart load, because nothing else redraws. That was the
        original D-7 bug.
        """
        self._cot_cache_chart = None
        self._cot_cache_order = None
        self._cot_faces_cache = {}

        # WEAK reference, not ``self``. See the module docstring: ``on_changed``
        # never lets go, so what leaks now is one small closure per view rather
        # than the widget tree behind it.
        _ref = weakref.ref(self)

        def _cot_hook(_key, _value, _ref=_ref):
            view = _ref()
            if view is not None:
                view._on_cot_setting()

        self._cot_settings_hook = _cot_hook
        try:
            from managers.settings_manager import get_settings
            _settings = get_settings()
            _settings.on_changed(COT_SETTING_KEY, _cot_hook)
            _settings.on_changed(COT_ORDER_KEY, _cot_hook)
        except Exception:                            # noqa: BLE001
            # A view that cannot subscribe still draws; it just will not
            # live-update. Never take the chart tab down for a subscription.
            pass

    def _cot_supported(self):
        """Whether this view can show the index AT ALL, setting aside.

        Overridden by views with an inert or miniature rendering mode where the
        plaque would be present in the scene but unreadable on screen.
        """
        return True

    def _cot_enabled(self):
        """Whether to draw the index right now."""
        if not self._cot_supported():
            return False
        try:
            from managers.settings_manager import get_settings
            return bool(get_settings().get(COT_SETTING_KEY, False))
        except Exception as e:                       # noqa: BLE001
            print(f"{self._cot_log_prefix} Warning: could not read "
                  f"{COT_SETTING_KEY}: {e}")
            return False

    def _on_cot_setting(self):
        """A ``cot.*`` key changed: drop the memoised faces and redraw.

        No chart, no repaint. Views draw a REDUCED empty state when their
        chart is cleared — the North Indian one is cells and diagonals with no
        sign badges at all — and ``_cot_repaint`` is the full chart draw, not
        that one. Repainting a chartless view would therefore quietly replace
        its empty state with a fuller one that a later toggle would not undo.
        Nothing is lost by skipping: with no chart there are no faces, so there
        is nothing on screen for this setting to add or remove.
        """
        self._cot_forget_faces()
        if self._cot_chart() is None:
            return
        try:
            self._cot_repaint()
        except RuntimeError:
            # The C++ widget is gone while the Python wrapper lingers — normal
            # for a view whose host closed between the write and the callback.
            # Not a warning: there is nothing for anyone to do about it.
            pass
        except Exception as e:                       # noqa: BLE001
            print(f"{self._cot_log_prefix} Warning: redraw after a cot setting "
                  f"failed: {e}")

    def _cot_repaint(self):
        """Redraw the whole view. Implemented by the mixing class."""
        raise NotImplementedError

    def _cot_chart(self):
        """The Chart to spread. Views that store it elsewhere override this."""
        return getattr(self, "_chart", None)

    def _cot_faces(self):
        """``{sign_index: card}`` for the current chart, or ``{}``.

        Deliberately built from the NATAL rashi with no varga code. The fourteen
        card faces do not move with a division (SPEC-COT-001 INV-15 v2) and this
        index shows a face, never an occupant — so a D-9 chart must show the
        same cards as D-1. Feeding the varga through here would be work that
        changes nothing, and a reader who noticed it would reasonably conclude
        the opposite.

        Cached on (chart identity, order): the redraw runs on every hover-free
        repaint — ascendant override, theme switch, varga switch — and the
        spread costs ~0.3 ms each time.
        """
        chart = self._cot_chart()
        if chart is None:
            return {}
        try:
            from managers.settings_manager import get_settings
            order = get_settings().get(COT_ORDER_KEY, COT_DEFAULT_ORDER)
        except Exception:                            # noqa: BLE001
            order = COT_DEFAULT_ORDER

        # Identity, not equality: comparing Chart objects with == would call an
        # engine __eq__ this module knows nothing about, and `is` is what the
        # cache actually means — "the same chart object we already spread".
        if self._cot_cache_chart is chart and self._cot_cache_order == order:
            return self._cot_faces_cache
        try:
            data = assemble_spread(chart, order)
            faces = sign_card_faces(data)
        except CardsOfTruthUnavailable as e:
            # INV-12: a chart the engine cannot spread must cost the user the
            # card index, not the chart. Stay quiet on the chart itself.
            print(f"{self._cot_log_prefix} Cards of Truth unavailable for this "
                  f"chart: {e}")
            faces = {}
        except Exception as e:                       # noqa: BLE001
            print(f"{self._cot_log_prefix} Warning: could not assemble the "
                  f"spread: {e}")
            faces = {}
        self._cot_cache_chart = chart
        self._cot_cache_order = order
        self._cot_faces_cache = faces
        return faces

    def _cot_forget_faces(self):
        """Drop the memoised spread — call when the chart object is replaced.

        Identity caching makes this belt-and-braces for a genuinely new Chart,
        but a view that MUTATES its chart in place would otherwise keep the old
        faces forever.
        """
        self._cot_cache_chart = None
        self._cot_cache_order = None
        self._cot_faces_cache = {}
