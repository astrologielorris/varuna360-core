# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""The keycap and its lamp (SPEC-RST-001 D-20; the Strength and the Tajika matrix keys,
SPEC-TJK-003 §4.4). Colours: the caller's ``key_palette()``; measures: ``key_geometry()``."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFontMetricsF, QLinearGradient, QPainter,
                           QPainterPath, QPen, QRadialGradient)

from core.strength_stone import BLACK, INK_DARK, WHITE, mix
from ui.accent_ink import ACCENT_INK_MIN_CONTRAST, contrast_ratio


def paint_lamp(p: QPainter, centre: QPointF, d: float, lit: bool, hover: bool, pal: dict):
    """The small sun lamp before the label (Lamp Row): an empty ring when off; lit =
    radial gradient white centre, soft accent, accent, with a faint accent ring."""
    r = d / 2.0
    accent = QColor(pal["accent"])
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if not lit:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(pal["accent"] if hover else pal["muted"]), 1.5))
        p.drawEllipse(centre, r - 0.75, r - 0.75)
        p.restore()
        return
    ring = QColor(accent)
    ring.setAlphaF(0.30)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(ring, 1.5))
    p.drawEllipse(centre, r + 1.75, r + 1.75)
    focal = QPointF(centre.x() - 0.24 * d, centre.y() - 0.30 * d)
    g = QRadialGradient(centre, r * 1.15, focal)
    g.setColorAt(0.00, QColor(WHITE))
    g.setColorAt(0.20, QColor(WHITE))
    g.setColorAt(0.42, QColor(mix(pal["accent"], WHITE, 0.40)))
    g.setColorAt(0.78, accent)
    g.setColorAt(1.00, QColor(mix(pal["accent"], BLACK, 0.15)))
    p.setPen(QPen(QColor(mix(pal["accent"], BLACK, 0.10)), 0.8))
    p.setBrush(QBrush(g))
    p.drawEllipse(centre, r, r)
    p.restore()


def paint_keycap(p: QPainter, cell: QRectF, label: str, *, lit, pressing, hover, geo, font,
                 pal, radius_cap, disc=None):
    """One keycap in ``cell``: rounded face, lip, 1 px edge, lamp before the bold label.
    ``disc`` (a colour) is painted behind the label while lit."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # the key fills the section inside the key_geometry margins; its lip grows
    # with the label size; sunk = lip gone, face down (td-esl0r: every measure
    # follows the Table Headers px, so the key is never smaller than its label)
    body = cell.adjusted(geo["ml"], geo["top"], -geo["mr"], -geo["bottom"])
    radius = min(radius_cap, body.height() * 0.26)
    face = _paint_face(p, body, geo["lip"], radius, lit or pressing, lit or hover, pal)
    _paint_label(p, face, label, lit, hover, geo, font, pal, disc)


def _paint_face(p, body, lip, radius, sunk, accent, pal):
    """Lip, face gradient and edge; pushed in (sunk): down by the lip with 1 px of
    lip left and an inset shade along the top. Returns the face rect."""
    top = body.top() + (lip - 1.0 if sunk else 0.0)
    face = QRectF(body.left(), top, body.width(), body.height() - lip)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(pal["lip"]))
    p.drawRoundedRect(body, radius, radius)
    g = QLinearGradient(face.topLeft(), face.bottomLeft())
    g.setColorAt(0.0, QColor(pal["sunk_top" if sunk else "face_top"]))
    g.setColorAt(1.0, QColor(pal["sunk_bot" if sunk else "face_bot"]))
    p.setBrush(QBrush(g))
    p.setPen(QPen(QColor(pal["accent"] if accent else pal["edge"]), 1.0))
    p.drawRoundedRect(face.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    if sunk:
        clip = QPainterPath()
        clip.addRoundedRect(face.adjusted(1, 1, -1, -1), radius - 1, radius - 1)
        p.save()
        p.setClipPath(clip)
        sh = QLinearGradient(face.topLeft(), QPointF(face.left(), face.top() + face.height() * 0.45))
        c0, c1 = QColor(pal["shade"]), QColor(pal["shade"])
        c0.setAlphaF(0.30)
        c1.setAlphaF(0.0)
        sh.setColorAt(0.0, c0)
        sh.setColorAt(1.0, c1)
        p.fillRect(face, QBrush(sh))
        p.restore()
    return face


def _paint_label(p, face, label, lit, hover, geo, font, pal, disc):
    """Lamp + label centred together at the label's own size (never shrunk; elided only when the
    table is forced narrower than its key width); a lit ``disc``: a pill, white label if 3:1."""
    d, gap, pad = geo["d"], geo["gap"], geo["hpad"]
    avail = face.width() - 2 * pad - d - gap
    fm = QFontMetricsF(font)
    if fm.horizontalAdvance(label) > avail + 0.5:
        label = fm.elidedText(label, Qt.TextElideMode.ElideRight, max(0.0, avail))
    tw = fm.horizontalAdvance(label)
    x0 = face.center().x() - (d + gap + tw) / 2
    cy = face.center().y()
    if d > 0:
        paint_lamp(p, QPointF(x0 + d / 2, cy), d, lit, hover, pal)
    ink = QColor(pal["text"])
    if disc is not None and lit:
        ry = min(face.height() * 0.5 - 1.0, fm.height() * 0.56)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(disc))
        p.drawRoundedRect(QRectF(x0 + d + gap - 3, cy - ry, tw + 6, 2 * ry), ry, ry)
        ink = QColor(WHITE if contrast_ratio(WHITE, disc) >= ACCENT_INK_MIN_CONTRAST else INK_DARK)
    p.setFont(font)
    p.setPen(ink)
    p.drawText(QRectF(x0 + d + gap, face.top(), tw + 2, face.height()),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
