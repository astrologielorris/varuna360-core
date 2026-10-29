# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Painted fields and painters of the dasha presentations (SPEC-LAYOUT-001 A.1/A.2/D7a).

The right dasha panel keeps ONE QListWidget and ONE DashaHighlightDelegate in
every presentation. This module turns an item (its display text plus the
renderer's UserRole entry) into the fields a presentation paints (glyph, lord,
span, dates, time left, flags) and paints them as a two-line row (side Full), a
rail tile (side Rail, 64 px) or a card (bottom shelf). ``fields`` is also what the
AI capture reports for Rail/Shelf (D7a), so painting and observation never drift.

Every mode renders its own text format; parsing is defensive and falls back to
the raw text, so an unknown format still paints (one line, no glyph).
"""
from __future__ import annotations

import re
import time

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPen

_LEAD = re.compile(r"^[^\w(-]+")          # markers before the name (▶, ZR peak/LB marks)
_DATE = re.compile(r"\d{1,4}[/.-]\d{1,2}[/.-]-?\d{1,4}")
_YEAR = re.compile(r"-?\d{3,4}$")

# Identifier tables (lowercase lord names from the renderers' entries -> glyph).
_PLANETS = {
    "sun": "☉", "moon": "☽", "mars": "♂", "mercury": "☿", "jupiter": "♃",
    "venus": "♀", "saturn": "♄", "rahu": "☊", "ketu": "☋",
}
_ABBR = {"su": "sun", "mo": "moon", "ma": "mars", "me": "mercury", "ju": "jupiter",
         "ve": "venus", "sa": "saturn", "ra": "rahu", "ke": "ketu"}
_SIGNS = ("♈", "♉", "♊", "♋", "♌", "♍", "♎", "♏", "♐", "♑", "♒", "♓")
_SIGN_NAMES = (            # (western, aditya) per sign, Aries = Dhata = #1
    ("aries", "dhata"), ("taurus", "aryama"), ("gemini", "mitra"), ("cancer", "varuna"),
    ("leo", "indra"), ("virgo", "vivasvan"), ("libra", "tvasta"), ("scorpio", "vishnu"),
    ("sagittarius", "amzu"), ("capricorn", "bhaga"), ("aquarius", "pusha"),
    ("pisces", "parjanya"))
GLYPHS = dict(_PLANETS)
GLYPHS.update({a: _PLANETS[n] for a, n in _ABBR.items()})
for _i, _names in enumerate(_SIGN_NAMES):
    for _n in _names:
        GLYPHS[_n] = _SIGNS[_i]
        GLYPHS[_n[:3]] = _SIGNS[_i]


def glyph_for(lord: str) -> str:
    return GLYPHS.get(lord.lower(), "")


def _entry(index):
    e = index.data(Qt.ItemDataRole.UserRole)
    return e if isinstance(e, dict) else {}


def _pieces(rest: str):
    """Split the text after the lord on runs of 2+ spaces; a bracketed group
    stays one piece."""
    return [p.strip() for p in re.split(r"\s{2,}", rest.strip()) if p.strip()]


def _date_part(piece: str) -> str:
    """The date text of a piece: bracketed group inner, or from the first date on
    (ZR puts the ruler abbreviation before its date)."""
    if piece.startswith("(") and piece.endswith(")"):
        return piece[1:-1].strip()
    m = _DATE.search(piece)
    return piece[m.start():].strip() if m else piece


def fields(index, now_jd=None) -> dict:
    """Painted fields of one list item, from the renderer's structured entry
    where it has one: the period identity is ``sign_label`` (ZR sign periods: their
    ``lord`` is the sign's ruler) else ``lord`` (Vimshottari path "Ju/Sa",
    Nisarga planet); dates and span come from the display text."""
    text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
    e = _entry(index)
    marked = text[:1] in "▶►"
    body = _LEAD.sub("", text)
    separator = bool(e.get("is_separator")) or body.startswith("--") or not e
    out = {"text": text, "separator": separator, "current": bool(e.get("is_current")) or marked,
           "maturation": bool(e.get("is_maturation")), "lord": "", "glyph": "",
           "span": "", "dates": "", "left": "", "left_short": "", "section": ""}
    if separator:
        out["section"] = body.strip("- ").strip()
        return out
    name = str(e.get("sign_label") or e.get("lord") or (body.split() or [""])[0])
    rest = body[body.find(name) + len(name):] if name and name in body else body
    spans, dates = [], []
    for p in _pieces(rest):
        (dates if (p.startswith("(") or _DATE.search(p)) else spans).append(
            _date_part(p) if (p.startswith("(") or _DATE.search(p)) else p)
    out.update(lord=name, glyph=glyph_for(name.split("/")[-1]),
               span=" ".join(spans), dates=" ".join(dates))
    if out["current"]:
        out["left"], out["left_short"] = _time_left(e, out["span"], now_jd)
    return out


def _now_jd():
    return time.time() / 86400.0 + 2440587.5


_SPAN_YEARS = re.compile(r"^(\d+)-(\d+)y")


def _end_jd(entry, span):
    """The period's end: the entry's ``end_jd`` (Vimshottari, ZR), else
    start ``jd`` + the 'a-by' age span (Nisarga periods and maturation years)."""
    end = entry.get("end_jd")
    if isinstance(end, (int, float)):
        return end
    m = _SPAN_YEARS.match(span or "")
    start = entry.get("jd")
    if m and isinstance(start, (int, float)):
        return start + (int(m.group(2)) - int(m.group(1))) * 365.2425
    return None


def _time_left(entry, span, now_jd):
    """('7y 3m left', '7y 3m'); ('', '') when the end is unknown or past."""
    end = _end_jd(entry, span)
    if end is None:
        return "", ""
    days = end - (now_jd if now_jd is not None else _now_jd())
    if days <= 0:
        return "", ""
    from core.i18n import t
    y, m = divmod(int(days / 30.4375), 12)
    if y:
        return (t("dasha.rail.time_left_ym", "{years}y {months}m left", years=y, months=m),
                t("dasha.rail.time_ym", "{years}y {months}m", years=y, months=m))
    return (t("dasha.rail.time_left_m", "{months}m left", months=m),
            t("dasha.rail.time_m", "{months}m", months=m))


def years(dates: str):
    """('2008', '2028') from a date range text, else ('', '')."""
    found = _DATE.findall(dates)
    ys = [_YEAR.search(d).group(0) if _YEAR.search(d) else "" for d in found]
    return (ys[0] if ys else "", ys[1] if len(ys) > 1 else "")


def observed_cell(f: dict) -> str:
    """One-line text of what a Rail/Shelf item paints (capture, D7a)."""
    if f["separator"]:
        return f["section"]
    parts = [f["glyph"], f["lord"], f["span"], f["dates"], f["left"]]
    flags = [n for n in ("current", "maturation") if f[n]]
    return " · ".join(p for p in parts if p) + (f" [{', '.join(flags)}]" if flags else "")


# --------------------------------------------------------------- geometry ---
def _font(base: QFont, scale: float, bold=False) -> QFont:
    f = QFont(base)
    px = base.pixelSize() if base.pixelSize() > 0 else round(base.pointSizeF() * 4 / 3)
    f.setPixelSize(max(7, round(px * scale)))
    f.setBold(bold)
    return f


# Two-line row rhythm from the winning mockup (Astra): about 10 px above and
# below, a few px between the name line and the dates line.
ROW_PAD, ROW_GAP = 9, 4


def two_line_size(option) -> QSize:
    fm = QFontMetrics(option.font)
    # Width 1, not the one-line text's hint: a list lays every row out at its
    # widest hint, and with a large font that hint is wider than the column,
    # which pushed the right-aligned span (0-1y) off-screen (Lorris 2026-10-15).
    # The two-line layout elides the name, so the viewport width is always enough.
    return QSize(1, fm.height() * 2 + ROW_PAD * 2 + ROW_GAP)


def rail_size(option, f: dict) -> QSize:
    fm = QFontMetrics(option.font)
    if f["separator"]:
        return QSize(0, fm.height() + 8)
    if f["current"]:
        return QSize(0, fm.height() * 6 + 22)
    return QSize(0, fm.height() * 2 + 14)


def card_size(height: int, f: dict, unit: int) -> QSize:
    return QSize(unit // 6 if f["separator"] else unit, height)


# ---------------------------------------------------------------- painting --
def paint_two_line(painter, option, f, bg, fg, muted):
    r = option.rect
    painter.save()
    painter.fillRect(r, bg)
    painter.setPen(QPen(muted, 1))
    painter.drawLine(r.bottomLeft(), r.bottomRight())
    fm = QFontMetrics(option.font)
    pad = 8
    top = QRect(r.left() + pad, r.top() + ROW_PAD, r.width() - 2 * pad, fm.height())
    bot = QRect(top.left() + fm.height() + 6, top.bottom() + 1 + ROW_GAP,
                top.width() - fm.height() - 6, fm.height())
    painter.setPen(fg)
    painter.setFont(option.font)
    painter.drawText(top, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     ("▶" if f["current"] else f["glyph"]) or " ")
    name_rect = top.adjusted(fm.height() + 6, 0, 0, 0)
    painter.drawText(name_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                     f["span"])
    span_w = fm.horizontalAdvance(f["span"]) + 8
    name_font = QFont(option.font)
    name_font.setWeight(QFont.Weight.Medium)
    painter.setFont(name_font)
    painter.drawText(name_rect.adjusted(0, 0, -span_w, 0),
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     fm.elidedText(f["lord"], Qt.TextElideMode.ElideRight,
                                   max(0, name_rect.width() - span_w)))
    painter.setFont(_font(option.font, 0.88))
    painter.setPen(fg if f["current"] else muted)
    painter.drawText(bot, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     f["dates"].replace(" - ", " → "))
    painter.restore()


def _centered(painter, rect, text, font, color):
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, text)


def paint_rail(painter, option, f, bg, fg, muted, border):
    r = option.rect.adjusted(4, 2, -4, -2)
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    fm = QFontMetrics(option.font)
    if f["separator"]:
        word = (f["section"].split() or [""])[0][:6].upper()
        _centered(painter, r, word, _font(option.font, 0.72), muted)
        painter.restore()
        return
    painter.setPen(QPen(border, 1))
    painter.setBrush(bg)
    painter.drawRoundedRect(r, 5, 5)
    h = fm.height()
    y = r.top() + 5
    big = _font(option.font, 1.5 if f["current"] else 1.25)
    gh = QFontMetrics(big).height()
    _centered(painter, QRect(r.left(), y, r.width(), gh), f["glyph"] or f["lord"][:2], big, fg)
    y += gh
    small = _font(option.font, 0.78)
    lines = []
    if f["current"]:
        lines.append((f["lord"][:7], _font(option.font, 0.8, bold=True)))
    lines.append((f["span"].split()[0] if f["span"] else "", small))
    if f["current"]:
        a, b = years(f["dates"])
        lines += [(a, small), (b, small), (f["left_short"], small)]
    for text, font in lines:
        if text:
            _centered(painter, QRect(r.left(), y, r.width(), h), text, font, fg)
            y += h - 2
    painter.restore()


def paint_card(painter, option, f, bg, fg, muted, border):
    r = option.rect.adjusted(3, 4, -3, -4)
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing, True)
    if f["separator"]:
        painter.setPen(QPen(border, 1))
        x = r.center().x()
        painter.drawLine(x, r.top() + 8, x, r.bottom() - 8)
        painter.restore()
        return
    painter.setPen(QPen(border, 1))
    painter.setBrush(bg)
    painter.drawRoundedRect(r, 5, 5)
    fm = QFontMetrics(option.font)
    h = fm.height()
    inner = r.adjusted(10, 8, -8, -8)
    y = inner.top()
    big = _font(option.font, 1.45)
    gh = QFontMetrics(big).height()
    painter.setFont(big)
    painter.setPen(fg)
    painter.drawText(QRect(inner.left(), y, inner.width(), gh), Qt.AlignmentFlag.AlignLeft,
                     f["glyph"] or "")
    y += gh + 4
    rows = [(("▶ " if f["current"] else "") + f["lord"], option.font, fg),
            (f["span"], _font(option.font, 0.9), fg)]
    for d in (f["dates"].split(" - ") if " - " in f["dates"] else [f["dates"]]):
        rows.append((d, _font(option.font, 0.8), fg if f["current"] else muted))
    if f["left"]:
        rows.append((f["left"], _font(option.font, 0.8), fg))
    for text, font, color in rows:
        if text and y + h <= inner.bottom() - h:
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(QRect(inner.left(), y, inner.width(), h),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight,
                                                           inner.width()))
            y += h
    if f["section"]:
        painter.setFont(_font(option.font, 0.7))
        painter.setPen(muted)
        painter.drawText(QRect(inner.left(), inner.bottom() - h, inner.width(), h),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         f["section"].upper())
    painter.restore()


def muted(color: QColor) -> QColor:
    c = QColor(color)
    c.setAlpha(170)
    return c
