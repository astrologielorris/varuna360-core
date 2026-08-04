#!/usr/bin/env python3
# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The ONE center-mini renderer (SPEC-VGC-001 INV-1).

A South Indian chart has a 2x2 center box, and three different things are
drawn into it: the transit overlay, the mini North Indian chart, and — from
SPEC-VGC-001 — a divisional chart. Before this module each had its own
inline renderer, and two of the three baked a fixed-resolution pixmap into a
view that zooms to 3.0x, so they blurred exactly where the user zooms in.

This module owns the part they share: recording a prepared off-screen mini
view as PAINT COMMANDS and replaying them at whatever resolution the view is
currently at. What it deliberately does NOT own:

  * constructing the mini      — the class differs per theme and per chart
                                 type (SPEC-VGC-001 INV-7)
  * preparing the mini         — the classic caller flips a stone background
                                 and text colours, the vector caller copies
                                 display flags; there is no common shape
  * geometry and tagging       — the classic places at cell_size, the vector
                                 inside a medallion inset

so it imports neither view and keeps the existing one-way import arrow
(south_indian_vector_view -> chart_view) intact.

Why commands and not pixels (SPEC-SIC-003 INV-9, measured in its §2.8): a
952px cache is upscaled ~3x at max zoom while the outer cards stay sharp,
and sizing the cache for max zoom instead costs 31 MiB per host across nine
host instances. Commands replay through the view transform, so the inner
chart is drawn at exactly the fidelity of the outer one, for ~0.3 MB.
"""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPicture, QPixmap, QPixmapCache,
)
from PySide6.QtWidgets import QGraphicsItem

# Qt's app-wide pixmap cache ceiling defaults to 10 MiB, which predates
# large displays: one 1800px-square viewport of ARGB pixels is 12.9 MiB, so
# a zoomed-in item's device cache is evicted as fast as it is written. This
# is the ceiling we raise it to — enough for a maximised chart view on a 4K
# screen plus the dual-comparison pair, and an LRU ceiling rather than an
# allocation, so nothing is spent until something caches.
PIXMAP_CACHE_FLOOR_KB = 64 * 1024

# Used only when a caller supplies no label colour. The real gold comes from
# the theme (ui.qt_theme.GOLD); importing it here would drag the theme module
# into what is otherwise a pure-Qt helper.
GOLD_FALLBACK = "#D4AF37"


def _ensure_pixmap_cache_headroom():
    """Raise the QPixmapCache ceiling to PIXMAP_CACHE_FLOOR_KB, once, and
    only upward — another module may have asked for more, and stealing its
    headroom would trade one component's stutter for another's."""
    try:
        if QPixmapCache.cacheLimit() < PIXMAP_CACHE_FLOOR_KB:
            QPixmapCache.setCacheLimit(PIXMAP_CACHE_FLOOR_KB)
    except Exception as e:      # never let a cache hint break drawing
        print(f"[CENTER MINI] Warning: could not raise pixmap cache: {e}")


class CenterMiniItem(QGraphicsItem):
    """A chart drawn in the center box, as a RESOLUTION-INDEPENDENT item.

    Holds a ``QPicture`` — the mini scene's PAINT COMMANDS, not its pixels —
    and replays them through the current painter transform, so the inner
    chart is drawn at the same fidelity as the outer one at every zoom. It
    is also ~11x lighter than the bitmap it replaces (about 300 KB of
    commands vs 3.5 MB of ARGB pixels).

    ``DeviceCoordinateCache`` is what keeps that affordable: Qt caches the
    rendered result at the CURRENT device resolution, so panning and
    ordinary repaints are a blit and the commands are replayed only when the
    zoom changes. Two guards make that cache actually hold (SPEC-SIC-003
    §2.8): the pixmap-cache headroom above, and clipping to
    ``option.exposedRect`` so a partial exposure never replays into pixels
    nobody can see. Without them, at a 1800px viewport and 3.0x zoom the
    mini went from +0.3 ms to +22 ms per repaint against a 4 ms scene.

    IMPORTANT: the picture is recorded AT THE TARGET SIZE and this item is
    placed with ``setPos`` only. Do NOT call ``setScale`` on it — the two
    classic renderers this replaces scaled a pixmap that had been rendered
    at the mini's own ``chart_size``, and keeping that scale on top of a
    correctly-sized recording is a silent 2x geometry bug.
    """

    def __init__(self, picture, size, veil=False, label=None,
                 label_color=None):
        super().__init__()
        self._picture = picture
        self._rect = QRectF(0, 0, size, size)
        self._veil = veil
        self._label = label
        self._label_color = label_color
        _ensure_pixmap_cache_headroom()
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        exposed = getattr(option, "exposedRect", None)
        if (exposed is not None and exposed.isValid()
                and not exposed.contains(self._rect)):
            painter.setClipRect(exposed)
        if isinstance(self._picture, QPixmap):
            painter.drawPixmap(self._rect, self._picture,
                               QRectF(self._picture.rect()))
        else:
            self._picture.play(painter)
        if self._veil:
            painter.fillRect(self._rect, QColor(0, 0, 0, 96))
        if self._label:
            self._paint_label(painter)

    def _paint_label(self, painter):
        """Name the chart in the mini's hollow middle.

        A South Indian chart has no cards in the centre, so the label costs
        nothing and answers the question the feature creates: with the main
        chart on D-1 and a second chart inside it, WHICH divisional chart is
        that? Drawn at paint time rather than recorded, so changing it never
        costs a re-record — and it is painter text, so it stays sharp at any
        zoom like everything else here.
        """
        side = self._rect.width()
        font = QFont("Inter", max(8, int(side * 0.11)), QFont.Weight.Bold)
        painter.setFont(font)
        painter.setPen(self._label_color or QColor(GOLD_FALLBACK))
        painter.drawText(self._rect, Qt.AlignmentFlag.AlignCenter, self._label)


def record_center_picture(mini_view, size):
    """Record a PREPARED mini view's scene as paint commands at ``size``.

    The caller has already fed the mini its chart, varga code and display
    settings — preparation cannot be generalised across a South Indian and a
    North Indian mini, so this function does exactly one thing.

    Returns None when the mini has nothing usable to draw. That guard is
    here rather than at the call sites because it is the same for all of
    them and because it protects against a specific, silent failure:
    ``update_from_chart`` swallows exceptions reading rashi/cusps/planets, so
    a half-built chart leaves the mini as an EMPTY GRID, and an empty grid in
    the center box reads as "these are the positions" — worse than drawing
    nothing at all.
    """
    if mini_view is None:
        return None
    if getattr(mini_view, "_planets", None) is None \
            or getattr(mini_view, "_cusps", None) is None:
        print("[CENTER MINI] Mini has no planets/cusps; drawing nothing "
              "rather than an empty grid")
        return None

    picture = QPicture()
    painter = QPainter(picture)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    mini_view.scene.render(painter, QRectF(0, 0, size, size),
                           mini_view.scene.sceneRect())
    painter.end()
    return picture


# How much larger than the on-screen box the raster path renders. The view
# zooms to 3.0x; 2x oversample costs ~4x the pixels of a 1x bake and still
# lands far under the command-list record cost, so it is the practical
# middle of that trade.
RASTER_OVERSAMPLE = 2


def record_center_pixmap(mini_view, size, oversample=RASTER_OVERSAMPLE):
    """Render a PREPARED mini to an oversampled pixmap instead of commands.

    For a mini whose scene already embeds a large BITMAP — the classic South
    Indian theme draws a stone texture — recording paint commands is a bad
    trade. QPicture serialises that texture into the command stream, and
    measurement is brutal: ~508 ms per varga change through the command
    path against ~5 ms through a pixmap, because `QGraphicsScene.render()`
    into a QPicture is ~92% of a cold classic redraw.

    Sharpness was the point of the command path, but it was never fully
    achievable here: the background is a raster by design, so the classic
    mini can never be resolution-independent. Oversampling recovers most of
    the visible benefit — the text and geometry are baked at 2x the box —
    for a hundredth of the cost.

    The vector theme keeps `record_center_picture`: its scene is genuinely
    vector, so commands are both cheap to record and perfectly sharp.
    """
    if mini_view is None:
        return None
    if getattr(mini_view, "_planets", None) is None \
            or getattr(mini_view, "_cusps", None) is None:
        print("[CENTER MINI] Mini has no planets/cusps; drawing nothing "
              "rather than an empty grid")
        return None

    side = max(1, int(size * oversample))
    pixmap = QPixmap(side, side)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    mini_view.scene.render(painter, QRectF(0, 0, side, side),
                           mini_view.scene.sceneRect())
    painter.end()
    return pixmap


class CenterMiniCache:
    """Recording cost per redraw, avoided.

    Both themes re-emit their center content on every ``draw_full_chart()``
    (the classic gate at the tail of its rebuild, the vector one inside
    ``_draw_medallion``), and a redraw fires on every varga click, theme
    refresh, ascendant override and variation change. Uncached, each of
    those costs a full mini ``draw_full_chart()`` plus a fresh recording, in
    both South Indian children.

    Invalidation is EVENT-BASED, not a value key: the chart behind the mini
    can change without jd, mode or labels changing — a dasha-locked chart
    switch recalculates at the same jd with a different ayanamsa. A value key
    would serve the previous chart's picture. What has no event to hook (the
    display flags, the theme's background choice) is compared through
    ``signature``, which the caller supplies.
    """

    def __init__(self):
        self.picture = None
        self.signature = None

    def get(self, signature):
        """Return the cached picture if ``signature`` still matches."""
        if self.picture is not None and self.signature == signature:
            return self.picture
        return None

    def put(self, picture, signature):
        self.picture = picture
        self.signature = signature
        return picture

    def invalidate(self):
        self.picture = None
        self.signature = None
