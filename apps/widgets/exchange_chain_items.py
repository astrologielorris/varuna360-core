# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The exchange chain on the chart views (SPEC-EXCH-002 §3.4-3.8, td-m79zy).

One overlay pass per view, run on the finished scene after its planet pass
(the vector South Indian view and the wheel), and again by the THREAD key's
light redraw (``refresh_chains``). Per exchange two items: its chains (z under)
and its knot + pins (z over), so every knot sits over every chain. Each item
replays a QPicture recorded ONCE per (surface, geometry, style, exchanges) and
kept in a small LRU (INV-5): a redraw of the same chart records nothing, a paint
runs no Python per link. Items take no click (INV-4) and are owned by the scene
at once (Rule 18).
"""
from __future__ import annotations

import logging
from collections import OrderedDict

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QPicture
from PySide6.QtWidgets import QGraphicsItem

from core import exchange_chain as xc, exchange_knot as xk, exchange_knot_place as xkp
from core.exchange_chain_default import migrate_default
from apps.widgets import exchange_chain_paint as xp

_log = logging.getLogger(__name__)

TAG = Qt.ItemDataRole.UserRole + 41          # the pair of planets of the item's exchange
GLYPHS = {"Sun": "☉︎", "Moon": "☽︎", "Mars": "♂︎",
          "Mercury": "☿︎", "Jupiter": "♃︎", "Venus": "♀︎",
          "Saturn": "♄︎"}
SI_Z = (60.0, 62.0)                          # chains, knots: over the centre content, under the planets
WHEEL_Z = (7.5, 8.5)                         # over the hub numbers and sign names, under the planets
MOCK_HUB = 120.6                             # the mockup wheel's hub radius (px)

_FOCUS = [None]                              # the focused pair (managers.exchange_chain writes it)
_CACHE = OrderedDict()                       # key -> [(pair, chain picture, knot picture)]
_CACHE_SIZE = 32
STATS = {"recorded": 0, "hits": 0}           # pictures recorded / cache hits (tests, profile)


class ChainPictureItem(QGraphicsItem):
    """A recorded picture on the scene: no click, no hover, device cache."""

    def __init__(self, picture: QPicture, rect: QRectF):
        super().__init__()
        self._picture = picture
        self._rect = rect
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        self.setCacheMode(QGraphicsItem.CacheMode.DeviceCoordinateCache)

    def boundingRect(self):
        return self._rect

    def shape(self):
        return QPainterPath()                # INV-4: never takes a click

    def paint(self, painter, _option, _widget=None):
        painter.drawPicture(0, 0, self._picture)


def _record(draw):
    pic = QPicture()
    p = QPainter(pic)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    draw(p)
    p.end()
    STATS["recorded"] += 1
    rect = QRectF(pic.boundingRect()).adjusted(-4, -4, 4, 4)
    return pic, rect


def _cached(key, build):
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        STATS["hits"] += 1
        return hit
    value = build()
    _CACHE[key] = value
    while len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return value


def house_keyword(house):
    from core.i18n import t
    words = {1: t("panel.exchange.house.1", "self"), 2: t("panel.exchange.house.2", "resources"),
             3: t("panel.exchange.house.3", "courage"), 4: t("panel.exchange.house.4", "home"),
             5: t("panel.exchange.house.5", "creativity"),
             6: t("panel.exchange.house.6", "daily work"),
             7: t("panel.exchange.house.7", "partners"), 8: t("panel.exchange.house.8", "hidden"),
             9: t("panel.exchange.house.9", "fortune"), 10: t("panel.exchange.house.10", "career"),
             11: t("panel.exchange.house.11", "gains"), 12: t("panel.exchange.house.12", "retreat")}
    return words.get(int(house), "")


def _opts(link, k, style, seed, px, band=False, shadow=True, broken=None):
    marks = link.marks if broken is None else link.marks._replace(broken=broken)
    end8 = 0 if band or link.house_a == 8 else 1        # bands and rims: the mockup's 0
    end12 = 0 if band or link.house_a == 12 else 1
    return xc.ChainOpts(link.rank, k, marks, end8, end12, seed, band, shadow, style, px)


# ---------------------------------------------------------------- South Indian
def si_pictures(links, style, surface=None):
    """[(pair, chain picture, knot picture)] of a South Indian scene; ``surface``
    (name, cell, rect_of, centre box), the vector view's by default (3.4.2)."""
    from apps.widgets.exchange_chain_classic import vector_surface
    from core.i18n import current_process_language
    name, cell, rect_of, box = surface or vector_surface()
    small = xc.compact(len(links))
    key = ("si", name, cell, style, links, current_process_language())   # the pill's words

    def build():
        u = cell / 176.0
        out = []
        for j, knot in enumerate(xkp.si_layout(links, rect_of, box, u, small, style)):
            lk = knot.link
            k = (0.7 if small else 1.0) * u

            def chains(p, lk=lk, knot=knot, j=j, k=k):
                for sign, seed in ((lk.sign_a, j * 7 + 3), (lk.sign_b, j * 7 + 5)):
                    x, y, w, h = rect_of(sign)
                    rim = xc.Poly(xc.rim_points(x, y, w, h, 3 * u, 10 * u))
                    o = _opts(lk, .55 * u, style, seed, u, band=True, shadow=False, broken=False)
                    xp.paint_chain(p, rim, o._replace(marks=o.marks._replace(chaos=False)))
                path = xc.Poly(xc.bezier(knot.A, knot.C, knot.B, 160))
                xp.paint_chain(p, path, _opts(lk, k, style, (j + 1) * 101 + lk.rank, u))

            def knot_pic(p, lk=lk, knot=knot):
                m = xc.METAL[lk.rank]
                words = f"{house_keyword(lk.house_a)} · {house_keyword(lk.house_b)}"
                xp.pill(p, knot.K[0], knot.K[1] + knot.tier.dy * u, lk, knot.tier, u, words)
                pr = (16 if small else 19) * u
                xp.pin(p, knot.A[0], knot.A[1], GLYPHS.get(lk.planet_b, ""), m.li, pr)
                xp.pin(p, knot.B[0], knot.B[1], GLYPHS.get(lk.planet_a, ""), m.li, pr)
            out.append((lk.pair, _record(chains), _record(knot_pic)))
        return out
    return _cached(key, build)


# ---------------------------------------------------------------- wheel
def wheel_pictures(links, style, g: xc.WheelGeom):
    n = len(links)
    small = xc.compact(n)
    key = ("wheel", tuple(round(v, 3) for v in g), style, links)

    def build():
        R = g.R
        px = R / MOCK_HUB
        rr = R * .17
        radii = tuple(R * f for f in ((.10, .08) if small else (.13, .10, .08)))
        k_hub = R / 95 * (.38 if small else .47)        # mockup: link scale .47 R / 95
        k_band = R / 95 * (.58 if small else .72)
        out, knots = [], []
        for i, lk in enumerate(links):
            A, B = xc.sign_angles(g, lk.sign_a), xc.sign_angles(g, lk.sign_b)
            nA, nB = xc.polar(g, g.Rn, A[2]), xc.polar(g, g.Rn, B[2])
            c = (g.cx, g.cy)

            def inward(pt):
                dx, dy = xc._norm(c[0] - pt[0], c[1] - pt[1])
                return (pt[0] + dx * rr, pt[1] + dy * rr)
            s0, s1 = inward(nA), inward(nB)
            _t, kpt = xc.wheel_knot_t(s0, c, s1, knots, radii[0] * 2.3)
            knots.append(kpt)
            sr = xk.wheel_seal_r(s0, c, s1, kpt, radii, lk.rank, style, k_hub, px, R * .03)

            def chains(p, lk=lk, i=i, A=A, B=B, nA=nA, nB=nB, s0=s0, s1=s1):
                for arc, seed in ((A, i * 17 + 1), (B, i * 17 + 2)):
                    pts = xc.arc_points(g, g.Ro - 10 * px, arc[0] + 1.2, arc[1] - 1.2)
                    xp.paint_chain(p, xc.Poly(pts),
                                   _opts(lk, k_band, style, seed, px, band=True, broken=False))
                hub = xc.Poly(xc.bezier(s0, c, s1, 120))
                xp.paint_chain(p, hub, _opts(lk, k_hub, style, (i + 1) * 53 + lk.rank, px))
                for pt in (nA, nB):
                    xp.number_ring(p, pt[0], pt[1], rr, R, lk.rank, lk.marks.see_through)

            def knot_pic(p, lk=lk, A=A, B=B, kpt=kpt, sr=sr):
                m = xc.METAL[lk.rank]
                xp.seal(p, lk.rank, kpt[0], kpt[1], sr)
                if lk.letter:
                    xp.letter_tab(p, kpt[0] + sr * .95, kpt[1] - sr * .95, R * .15, R * .15,
                                  lk.letter, lk.rank, R * .12, max(1.0, px))
                pa, pb = xc.polar(g, R * 1.2, A[2]), xc.polar(g, R * 1.2, B[2])
                xp.pin(p, pa[0], pa[1], GLYPHS.get(lk.planet_b, ""), m.li, R * .14)
                xp.pin(p, pb[0], pb[1], GLYPHS.get(lk.planet_a, ""), m.li, R * .14)
            out.append((lk.pair, _record(chains), _record(knot_pic)))
        return out
    return _cached(key, build)


# ---------------------------------------------------------------- the passes
def clear_chains(scene):
    """Take the chain items off ``scene``. Returns how many were removed. A scene
    that holds none (``xc_chains`` 0: THREAD off) is not scanned."""
    gone = [i for i in scene.items() if isinstance(i, ChainPictureItem)] if scene.property("xc_chains") else []
    for item in gone:
        scene.removeItem(item)
    scene.setProperty("xc_chains", 0)
    return len(gone)


def _add(scene, entries, z):
    added = 0
    for pair, (chain_pic, chain_rect), (knot_pic, knot_rect) in entries:
        for (pic, rect), zz in (((chain_pic, chain_rect), z[0]), ((knot_pic, knot_rect), z[1])):
            item = ChainPictureItem(pic, rect)
            item.setZValue(zz)
            item.setData(TAG, pair)
            scene.addItem(item)
            del item                         # Rule 18: the scene owns it
            added += 1
    scene.setProperty("xc_chains", added)
    apply_focus(scene)
    return added


def _eligible(view):
    from apps.widgets.dignity_view_pass import CENTRE_MINI
    if view.property(CENTRE_MINI) or getattr(view, "_chart", None) is None:
        return False
    return getattr(view, "_varga_code", None) in (None, 1)   # exchanges are D1 (rashi) only


_WATCH = {"installed": False, "pending": False}


def _watched(*_args):
    """Any writer of the two keys (THREAD, Settings Apply, a remote or AI write,
    a reset): one light redraw at the next event-loop turn, coalesced."""
    if _WATCH["pending"]:
        return
    _WATCH["pending"] = True
    QTimer.singleShot(0, lambda: refresh_now() if _WATCH["pending"] else None)


def refresh_now():
    _WATCH["pending"] = False
    return refresh_chains()


def ensure_watch(settings):
    """Subscribe once (process life) to the two keys."""
    if _WATCH["installed"]:
        return False
    migrate_default(settings)                # the changed factory default, once (4.5)
    for key in (xc.KEY_ON, xc.KEY_STYLE):
        settings.on_changed(key, _watched)
    _WATCH["installed"] = True
    return True


def _app_get():
    """The running settings' getter; makes sure any writer redraws the chains."""
    from managers.settings_manager import get_settings
    settings = get_settings()
    ensure_watch(settings)
    return settings.get


def si_pass(view, get=None, surface=None):
    """THE chain pass of a South Indian view (vector by default). Returns the items added."""
    scene = view.scene
    clear_chains(scene)
    try:
        get = get or _app_get()
        if not xc.chain_on(get) or not _eligible(view):
            return 0
        links = xc.chart_links(view._chart)
        if not links:
            return 0
        return _add(scene, si_pictures(links, xc.chain_style(get), surface), SI_Z)
    except Exception:
        _log.exception("exchange chain pass failed on %s", type(view).__name__)
        return 0


def wheel_geom(view):
    return xc.WheelGeom(float(view.cx), float(view.cy), float(view.r_center),
                        float(view.r_center) * 0.65, float(view.r_middle),
                        float(view.rotation_offset))


def wheel_pass(view, get=None):
    """THE chain pass of a wheel view. Returns the items added."""
    scene = view.scene
    clear_chains(scene)
    try:
        get = get or _app_get()
        if not xc.chain_on(get) or not _eligible(view):
            return 0
        links = xc.chart_links(view._chart)
        if not links:
            return 0
        return _add(scene, wheel_pictures(links, xc.chain_style(get), wheel_geom(view)), WHEEL_Z)
    except Exception:
        _log.exception("exchange chain pass failed on %s", type(view).__name__)
        return 0


# ---------------------------------------------------------------- focus
def set_focus(pair):
    _FOCUS[0] = tuple(pair) if pair else None


def focus():
    return _FOCUS[0]


def apply_focus(scene):
    """Dim the other exchanges to 18 % while one is focused; a scene whose
    chart does not hold the focused pair dims nothing."""
    items = [(i, tuple(i.data(TAG) or ())) for i in scene.items() if isinstance(i, ChainPictureItem)]
    pair = _FOCUS[0]          # the tag comes back from Qt as a list: compared as a tuple
    held = pair is not None and any(tag == pair for _i, tag in items)
    for item, tag in items:
        item.setOpacity(xc.FOCUS_DIM if held and tag != pair else 1.0)
    return len(items)


# ---------------------------------------------------------------- light redraw
_PASSES = []                                 # (view class, its chain pass)


def register_chain_pass(view_class, run):
    _PASSES.append((view_class, run))


def _views():
    from apps.widgets.planet_decoration_refresh import _graphics_views
    kinds = tuple(k for k, _r in _PASSES)
    return [v for v in _graphics_views() if kinds and isinstance(v, kinds)]


def _rerun(view):
    for cls, run in _PASSES:
        if isinstance(view, cls):
            run(view)
            return


def refresh_chains():
    """The THREAD key's light redraw: the chain pass again on every view that
    draws it, now on the views on screen, at show on the others."""
    import shiboken6
    from apps.widgets.planet_decoration_refresh import when_shown
    off, done = not xc.chain_on(_app_get()), 0
    for view in _views():
        if shiboken6.isValid(view) and getattr(view, "_chart", None) is not None:
            if off:                          # no chain left anywhere, hidden views too
                clear_chains(view.scene)
            done += when_shown(view, "exchange_chain", _rerun)
    return done


def refresh_focus():
    """A card click: only the item opacities change, on every view."""
    import shiboken6
    return sum(bool(apply_focus(view.scene)) for view in _views() if shiboken6.isValid(view))
