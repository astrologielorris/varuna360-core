# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""QPainter drawing of the exchange chain (SPEC-EXCH-002 §3.3-3.5, td-m79zy).

Ported from the round 4 winner's SVG code (``chain``, ``seal``, ``pin``, the
knot pill). Every function paints into any QPainter: the chart items record
them once into a QPicture (INV-5), the EXCH panel paints its swatches, tags and
seals with the same code. Colours are the rank metals of ``core.exchange_chain``
(a semantic palette, Rule 20 exception like ``ui/dignity_colors``).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPolygonF, QRadialGradient)

from core import exchange_chain as xc


def _c(hex_, alpha=1.0):
    col = QColor(hex_)
    col.setAlphaF(max(0.0, min(1.0, alpha)))
    return col


def _pen(col, width, cap=Qt.PenCapStyle.RoundCap):
    pen = QPen(col, max(0.01, width))
    pen.setCapStyle(cap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def vertical_metal(m: xc.Metal, top, bottom):
    """The wire gradient across a link (light, specular, body, shadow)."""
    g = QLinearGradient(0, top, 0, bottom)
    g.setColorAt(0.0, QColor(m.li))
    g.setColorAt(0.22, QColor(m.hi))
    g.setColorAt(0.5, QColor(m.ba))
    g.setColorAt(1.0, QColor(m.dk))
    return QBrush(g)


def horizontal_metal(m: xc.Metal, left, right):
    """The knot border / rank tag gradient (dark, body, light, spec, light, body, dark)."""
    g = QLinearGradient(left, 0, right, 0)
    for pos, col in ((0, m.dk), (0.2, m.ba), (0.42, m.li), (0.5, m.hi), (0.6, m.li),
                     (0.82, m.ba), (1.0, m.dk)):
        g.setColorAt(pos, QColor(col))
    return QBrush(g)


def symbol_font(px):
    f = QFont()
    f.setFamilies(["Segoe UI Symbol", "Noto Sans Symbols", "Noto Sans Symbols2", "DejaVu Sans"])
    f.setPixelSize(max(1, int(round(px))))
    return f


def text_font(px, weight=QFont.Weight.Bold):
    f = QFont()
    f.setFamilies(["Inter", "Segoe UI", "Roboto", "DejaVu Sans"])
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(weight)
    return f


def star(p: QPainter, s):
    """The 4 point star glint, centred on the origin."""
    pts = [(0, -s), (s * .2, -s * .2), (s, 0), (s * .2, s * .2), (0, s), (-s * .2, s * .2),
           (-s, 0), (-s * .2, -s * .2)]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFFEF2"))
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    p.setBrush(QColor("#FFFFFF"))
    p.drawEllipse(QPointF(0, 0), s * .28, s * .28)


# ---------------------------------------------------------------- one link
def _ring_path(pose: xc.LinkPose, rx, ry, o: xc.ChainOpts):
    path = QPainterPath()
    if pose.open:
        g = 0.0 if pose.open > 0 else math.pi
        a0, a1 = g + .75, g - .75 + 2 * math.pi
        # an ellipse arc from a0 to a1 (the long way round), as in the SVG arc
        steps = 24
        for j in range(steps + 1):
            a = a0 + (a1 - a0) * j / steps
            pt = QPointF(rx * math.cos(a), ry * math.sin(a))
            path.moveTo(pt) if j == 0 else path.lineTo(pt)
        return path
    if pose.crush:
        pts = []
        for j in range(7):
            a = j / 7 * math.pi * 2 + pose.r3
            k = .72 + .42 * xc.rnd(o.seed * 31 + pose.i * 13 + j)
            pts.append(QPointF(rx * k * math.cos(a), ry * k * math.sin(a)))
        path.addPolygon(QPolygonF(pts))
        path.closeSubpath()
        return path
    path.addEllipse(QPointF(0, 0), rx, ry)
    return path


def _spot(pose, o, g, rx, ry, a, salt, spread):
    """A point on the link's wire: on an edge-on cable bar along its length."""
    if pose.edge:
        return (xc.rnd(salt) - .5) * g.L * spread, 0.0
    return rx * math.cos(a), ry * math.sin(a)


def _rust(p, pose, o, g, rx, ry):
    """Rust flakes on the irons (ranks 2 and 1)."""
    w = g.w
    for j in range(3 if o.rank == 1 else 2):
        a = xc.rnd(o.seed * 7 + pose.i * 17 + j) * math.pi * 2
        px, py = _spot(pose, o, g, rx, ry, a, o.seed + pose.i * 5 + j, .8)
        p.save()
        p.translate(px, py)
        p.rotate(a * 57)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(xc.RUST[1], .75) if j % 2 else _c(xc.RUST[0], .55))
        p.drawEllipse(QPointF(0, 0), w * .62, w * .42)
        p.restore()


def _sick(p, pose, o, g, rx, ry):
    """The 6th: Rolo craters with a pale lip, Cable pits with a crust dot."""
    w = g.w
    for j in range(3 if o.style == xc.ROLO else 2):
        a = xc.rnd(o.seed * 11 + pose.i * 23 + j * 3) * math.pi * 2
        px, py = _spot(pose, o, g, rx, ry, a, o.seed * 3 + pose.i * 7 + j, .75)
        p.setPen(Qt.PenStyle.NoPen)
        if o.style == xc.CABLE:
            p.setBrush(_c("#1C120A", .85))
            p.drawEllipse(QPointF(px, py), w * .42, w * .42)
            p.setBrush(_c("#E2D7BE", .75))
            p.drawEllipse(QPointF(px + w * .45, py - w * .25), w * .28, w * .28)
            continue
        p.setBrush(_c("#160E07", .9))
        p.drawEllipse(QPointF(px, py), w * .45, w * .45)
        lip = QPainterPath(QPointF(px + w * .42, py - w * .1))
        lip.quadTo(QPointF(px + w * .35, py + w * .4), QPointF(px - w * .1, py + w * .44))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen(_c("#EADFC8", .8), w * .18))
        p.drawPath(lip)


def _crack(p, pose, o, g, rx, ry):
    """The 8th on a Cable face-on link: a black zigzag crack across the wire."""
    w = g.w
    a = pose.r2 * math.pi * 2
    px, py, nx, ny = rx * math.cos(a), ry * math.sin(a), math.cos(a), math.sin(a)
    crack = QPainterPath(QPointF(px - nx * w * .8, py - ny * w * .8))
    crack.lineTo(px + ny * w * .3, py - nx * w * .3)
    crack.lineTo(px + nx * w * .8, py + ny * w * .8)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(QColor("#0E0804"), max(.7 * o.px, w * .24)))
    p.drawPath(crack)


def _texture(p, pose, o, g, rx, ry):
    if o.rank <= 2:
        _rust(p, pose, o, g, rx, ry)
    if o.marks.sick:
        _sick(p, pose, o, g, rx, ry)
    if o.marks.chaos and o.style == xc.CABLE and not pose.edge and pose.i % 2 == 0:
        _crack(p, pose, o, g, rx, ry)


class _Kit:
    """What every link of one chain shares: sizes, gradients, cached ring paths."""

    def __init__(self, o, g):
        self.o, self.g = o, g
        self.m = xc.METAL[o.rank]
        self.hh = g.w * 1.35
        self.wire = vertical_metal(self.m, -g.ry - g.w / 2, g.ry + g.w / 2)
        self.bar = vertical_metal(self.m, -self.hh / 2, self.hh / 2)
        self._paths = {}

    def shape(self, pose):
        key = (pose.i if (pose.crush or pose.open) else -1, pose.open, pose.crush)
        if key not in self._paths:
            self._paths[key] = _ring_path(pose, self.g.rx, self.g.ry, self.o)
        return self._paths[key]

    def bar_rect(self):
        L, hh = self.g.L, self.hh
        return QRectF(-L / 2, -hh / 2, L, hh)


def _shadows(p, kit, poses):
    o, g = kit.o, kit.g
    dx, dy = 1.2 * o.px + .25 * g.w, 1.6 * o.px + .3 * g.w
    for pose in poses:
        p.save()
        p.translate(pose.x + dx, pose.y + dy)
        p.rotate(pose.ang)
        p.setOpacity(.3 * pose.op)
        if pose.edge:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#000000"))
            p.drawRoundedRect(kit.bar_rect(), kit.hh / 2, kit.hh / 2)
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(_pen(QColor("#000000"), g.w + o.px))
            p.drawPath(kit.shape(pose))
        p.restore()


def _link(p, kit, pose):
    o, g, m = kit.o, kit.g, kit.m
    w = g.w
    if pose.edge:
        p.setBrush(kit.bar)
        p.setPen(_pen(_c(xc.CASE, .8), max(.8 * o.px, w * .22)))
        p.drawRoundedRect(kit.bar_rect(), kit.hh / 2, kit.hh / 2)
        p.setPen(_pen(_c(m.hi, m.hi_op), w * .3))
        p.drawLine(QPointF(-g.L / 2 + kit.hh * .6, -kit.hh * .18),
                   QPointF(g.L / 2 - kit.hh * .6, -kit.hh * .18))
        return
    path = kit.shape(pose)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(_c(xc.CASE, .82), w + 2.2 * o.px))
    p.drawPath(path)
    pen = QPen(kit.wire, w)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPath(path)
    if not pose.crush and not pose.open:
        p.setPen(_pen(_c(m.hi, m.hi_op), w * .34))
        p.drawArc(QRectF(-g.rx, -g.ry, 2 * g.rx, 2 * g.ry), 45 * 16, 90 * 16)


def _glints(p, kit, poses):
    m, g = kit.m, kit.g
    for pose in poses:
        if pose.op > .5 and not pose.edge and pose.i % m.glint == 0:
            s = g.w * m.glint_size * (.75 + .5 * pose.r3)
            p.save()
            p.translate(pose.x, pose.y)
            p.rotate(pose.ang)
            p.translate(-g.rx * .35, -g.ry - g.w * .05)
            p.rotate(-pose.ang + 15)
            star(p, s)
            p.restore()


def _break_flakes(p, P, o, g):
    (bx, by), d = xc.mark_point(P, o, .3)
    nx, ny = -d[1], d[0]
    p.setPen(Qt.PenStyle.NoPen)
    for j in range(4):
        f1 = (xc.rnd(o.seed + j) - .5) * g.pitch * .9
        f2 = (xc.rnd(o.seed + j + 9) - .2) * g.H * .9
        p.save()
        p.translate(bx + d[0] * f1 + nx * f2, by + d[1] * f1 + ny * f2)
        p.rotate(xc.rnd(o.seed + j + 3) * 90)
        p.setBrush(QColor(xc.RUST[1] if j % 2 else xc.RUST[0]))
        p.drawRect(QRectF(-g.w * .35, -g.w * .25, g.w * .7, g.w * .5))
        p.restore()


def paint_chain(p: QPainter, P: xc.Poly, o: xc.ChainOpts):
    """One chain along ``P``: shadows, then links, then glints, then the break
    flakes and the Rolo hazard sign (mockup ``chain()``). Returns the link count."""
    if P.T <= 0:
        return 0
    g, poses = xc.link_poses(P, o)
    kit = _Kit(o, g)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if o.shadow:
        _shadows(p, kit, poses)
    for pose in poses:
        p.save()
        p.translate(pose.x, pose.y)
        p.rotate(pose.ang)
        p.setOpacity(pose.op)
        _link(p, kit, pose)
        _texture(p, pose, o, g, g.rx, g.ry)
        p.restore()
    p.setOpacity(1.0)
    if kit.m.glint:
        _glints(p, kit, poses)
    if xc.break_at(o, P.T) >= 0:
        _break_flakes(p, P, o, g)
    if o.marks.chaos and o.style == xc.ROLO and not o.band:
        (hx, hy), _d = xc.mark_point(P, o, .14 if o.rank == 1 else .3)
        hazard(p, hx, hy, g.H * .95, o.px)
    p.restore()
    return len(poses)


def hazard(p: QPainter, x, y, z, px=1.0):
    """The 8th's hazard sign: a dark diamond with an ochre border and a bolt."""
    p.save()
    p.translate(x, y)
    dia = QPolygonF([QPointF(0, -z), QPointF(z, 0), QPointF(0, z), QPointF(-z, 0)])
    p.setBrush(QColor(xc.HAZARD[0]))
    p.setPen(_pen(QColor(xc.HAZARD[1]), max(px, z * .13)))
    p.drawPolygon(dia)
    bolt = [(.12, -.62), (-.26, .06), (.06, .06), (-.14, .62), (.3, -.12), (-.02, -.12)]
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(xc.HAZARD[1]))
    p.drawPolygon(QPolygonF([QPointF(z * a, z * b) for a, b in bolt]))
    p.restore()


# ---------------------------------------------------------------- seal, pin, tag
def seal(p: QPainter, rank, x, y, r):
    """The rank disc: radial metal, casing, inner ring, specular arc, the number."""
    m = xc.METAL[rank]
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(x, y)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c(xc.CASE, .9))
    p.drawEllipse(QPointF(0, 0), r + 1.8 * r / 18, r + 1.8 * r / 18)
    rg = QRadialGradient(QPointF(-.24 * r, -.36 * r), 1.56 * r)
    for pos, col in ((0, m.hi), (.3, m.li), (.68, m.ba), (1, m.dk)):
        rg.setColorAt(pos, QColor(col))
    p.setBrush(QBrush(rg))
    p.drawEllipse(QPointF(0, 0), r, r)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(_c(m.dk, .55), max(.7 * r / 18, r * .07)))
    p.drawEllipse(QPointF(0, 0), r * .78, r * .78)
    arc = QPainterPath(QPointF(-r * .62, -r * .5))
    arc.quadTo(QPointF(-r * .2, -r * .95), QPointF(r * .35, -r * .72))
    p.setPen(_pen(_c(m.hi, m.hi_op * .9), r * .1))
    p.drawPath(arc)
    if rank <= 2:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(xc.RUST[1], .8))
        p.drawEllipse(QPointF(r * .45, r * .4), r * .16, r * .16)
        p.setBrush(_c(xc.RUST[0], .6))
        p.drawEllipse(QPointF(-r * .5, r * .3), r * .12, r * .12)
    p.setFont(text_font(r * 1.12, QFont.Weight.ExtraBold))
    p.setPen(QColor(m.ink))
    p.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, str(rank))
    if rank == 1:
        crack = QPainterPath(QPointF(r * .15, -r))
        for a, b in ((-.08, -.35), (.2, -.05), (-.05, .35)):
            crack.lineTo(r * a, r * b)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_pen(QColor("#0E0804"), max(.8 * r / 18, r * .09)))
        p.drawPath(crack)
    if rank == 6:
        p.translate(r * .62, -r * .62)
        star(p, r * .42)
    p.restore()


def pin(p: QPainter, x, y, glyph, col, r):
    """A phantom pin: the partner planet at home in the sign it rules."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_c("#000000", .28))
    p.drawEllipse(QPointF(x, y), r * (1 + 2 / 19), r * (1 + 2 / 19))
    p.setBrush(QColor("#17130E"))
    p.drawEllipse(QPointF(x, y), r, r)
    pen = _pen(QColor(col), r * .13, Qt.PenCapStyle.FlatCap)
    pen.setDashPattern([.22 / .13, .16 / .13])
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    rr = r * (1 - 1.6 / 19)
    p.drawEllipse(QPointF(x, y), rr, rr)
    p.setFont(symbol_font(r * 1.15))
    p.setPen(QColor("#FFFFFF"))
    p.drawText(QRectF(x - r, y - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, glyph)
    p.restore()


def letter_tab(p: QPainter, x, y, w, h, letter, rank, font_px, border):
    """The dark letter tab (A, B, C) with a rim in the rank metal."""
    m = xc.METAL[rank]
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(x - w / 2, y - h / 2, w, h)
    p.setBrush(QColor("#2E251B"))
    p.setPen(QPen(horizontal_metal(m, rect.left(), rect.right()), border))
    p.drawRoundedRect(rect, h * .27, h * .27)
    p.setFont(text_font(font_px, QFont.Weight.ExtraBold))
    p.setPen(QColor("#F3E9D6"))
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter)
    p.restore()


def rank_tag(p: QPainter, rect: QRectF, rank, rank_text):
    """The bookmark RANK tag of an exchange card: notched, horizontal metal,
    the number and the word in the metal ink, rust spots on ranks 2 and 1."""
    m = xc.METAL[rank]
    w, h = rect.width(), rect.height()
    poly = QPolygonF([rect.topLeft(), rect.topRight(), rect.bottomRight(),
                      QPointF(rect.left() + w / 2, rect.top() + h * .8), rect.bottomLeft()])
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(horizontal_metal(m, rect.left(), rect.right()))
    p.drawPolygon(poly)
    if rank <= 2:
        for fx, fy, rr, col, a in ((.3, .7, 3.5, xc.RUST[1], .85), (.72, .3, 3.0, xc.RUST[0], .6),
                                  (.6, .82, 2.5, xc.RUST[0], .55)):
            p.setBrush(_c(col, a))
            p.drawEllipse(QPointF(rect.left() + fx * w, rect.top() + fy * h), rr * w / 36, rr * w / 36)
    p.setPen(QColor(m.ink))
    p.setFont(text_font(h * .375, QFont.Weight.ExtraBold))
    p.drawText(QRectF(rect.left(), rect.top() + h * .1, w, h * .4),
               Qt.AlignmentFlag.AlignCenter, str(rank))
    f = text_font(max(6.0, h * .16), QFont.Weight.Bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
    p.setFont(f)
    p.drawText(QRectF(rect.left(), rect.top() + h * .48, w, h * .2),
               Qt.AlignmentFlag.AlignCenter, rank_text)
    p.restore()


def number_ring(p: QPainter, x, y, r, R, rank, see_through):
    m = xc.METAL[rank]
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(_pen(_c(xc.CASE, .85), R * .06))
    p.drawEllipse(QPointF(x, y), r, r)
    if see_through:
        p.setOpacity(.45)
    p.setPen(QPen(vertical_metal(m, y - r, y + r), R * .03))
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


_PILL = {  # tier -> numbers px, numbers x, numbers baseline, seal r, seal y, casing, border, tab
    "full": (30, 52, 6, 18, -5, 7, 3.6, (28, 22, 15, 2)),
    "compact": (23, 36, 8, 14, 0, 6, 3, (22, 18, 12.5, 1.6)),
    "mini": (17, 28, 6, 11, 0, 5, 2.4, (18, 15, 10.5, 1.3)),
    "seal": (0, 0, 0, 15, 0, 0, 0, (18, 15, 10.5, 1.3)),
}


def pill(p: QPainter, x, y, link, tier, u, keywords):
    """The SI knot of a size tier (3.4.1): pill, numbers, seal, keywords (full), letter tab."""
    (num_px, nx, base, seal_r, seal_y, casing, border, tab), w, h = _PILL[tier.name], tier.pw, tier.ph
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(x, y)
    p.scale(u, u)
    rect = QRectF(-w / 2, -h / 2, w, h)
    if num_px:                                   # the SEAL tier is the seal alone
        p.setBrush(_c("#14100B", .94))
        p.setPen(_pen(QColor(xc.CASE), casing))
        p.drawRoundedRect(rect, h / 2, h / 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(horizontal_metal(xc.METAL[link.rank], rect.left(), rect.right()), border))
        p.drawRoundedRect(rect, h / 2, h / 2)
        p.setFont(text_font(num_px))
        p.setPen(QColor("#F3EAD8"))
        for sx, txt in ((-nx, link.house_a), (nx, link.house_b)):
            p.drawText(QRectF(sx - 30, base - num_px, 60, num_px * 1.2),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, str(txt))
    seal(p, link.rank, 0, seal_y, seal_r)
    if tier.name == "full" and keywords:
        p.setFont(text_font(13, QFont.Weight.Normal))
        p.setPen(QColor("#D6CCBA"))
        p.drawText(QRectF(-w / 2, 13, w, 16), Qt.AlignmentFlag.AlignCenter, keywords)
    if link.letter:
        tw, th, tpx, tpen = tab
        letter_tab(p, 0, -h / 2 - th / 2 + 1, tw, th, link.letter, link.rank, tpx, tpen)
    p.restore()
