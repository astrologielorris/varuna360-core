"""Qt-free South Indian projection.

Planets are placed in the sign frame: the planet's sign and in-sign degree,
varga-aware. An edition may set an alternate placement frame object
(``RenderProjection.frame``, passed through ``configure``). While one is set
it decides each planet's cell and degree, may put a short label above a
planet and may mark one cell, and the view leaves out the sign-frame layers
(house numbers, cusps, ascendant stripe). Core ships no such frame; with none
set the projection is the sign frame alone.

A placement frame provides:
    name                              str, reported as the retinue 'frame'
    guide_notice                      str, the reading guide's text while set
    invalidate()                      drop per-chart caches (new chart, clear)
    accepts(projection) -> bool       may it be switched on for this chart
    in_effect(projection) -> bool     does it place this chart (else sign fallback)
    notice(projection, varga_code)    str | None, a status text for the host
    placement(projection, planet)     (cell, deg) | None (None: sign fallback)
    planet_label(projection, planet)  (text, tooltip, emphasised) | None
    click_extras(projection, planet)  dict added to the click payload
    marked_cell(projection)           int | None
"""
from dataclasses import dataclass

from core.planet_label import CaptionSet, caption_set


@dataclass(frozen=True)
class PlanetRenderRecord:
    name: str
    cell: int
    degree: float
    payload: tuple
    label: tuple | None
    label_tip: str | None

@dataclass(frozen=True)
class RenderSnapshot:
    source_identity: int
    generation: int
    varga_code: int | None
    has_chart: bool
    ascendant_sign: int
    ascendant_degrees: tuple
    ascendant_override: int | None
    frame_active: bool
    marked_cell: int | None
    frame_guide_notice: str | None
    aditya_mode: str
    use_western_names: bool
    sign_language: str
    planets: tuple
    cusps: tuple
    captions: CaptionSet   # the text under each glyph (F11, core.planet_label)

class RenderProjection:
    def __init__(self):
        self.generation = 0
        self.frame = None
        self._chart = self._cusps = self._planets = None
        self._varga_code = None
        self._use_western_names = False
        self._aditya_mode = 'aditya'
        self.sign_language = 'en'
        self.ascendant_override = None

    def configure(self, chart, cusps, planets, varga, mode, western, language, ascendant, frame=None):
        self._chart, self._cusps, self._planets = chart, cusps, planets
        self._varga_code, self._aditya_mode = varga, mode
        self._use_western_names, self.sign_language = western, language
        self.ascendant_override, self.frame = ascendant, frame

    def snapshot(self, names, show_outer=True, planet_label="degrees"):
        self.generation += 1
        rows = []
        if self._planets:
            for name in names:
                if not show_outer and name in {'Uranus','Neptune','Pluto'}:
                    continue
                try:
                    obj = self._planets[name]
                    cell, degree = self._placement(obj)
                except Exception:
                    continue
                rows.append(PlanetRenderRecord(name, cell, degree,
                    tuple(self._planet_to_click_dict(name, obj).items()), *self._planet_label(obj)))
        return RenderSnapshot(id(self._chart), self.generation, self._varga_code, bool(self._chart), self._effective_ascendant_sign_index(),
            self.ascendant_degrees(), self.ascendant_override, *self._frame_fields(), self._aditya_mode,
            self._use_western_names, self.sign_language, tuple(rows), self.cusp_labels(),
            caption_set(planet_label, self.sign_language, rows, self._planets))

    def cusp_labels(self):
        result = {}
        if not self._cusps:
            return ()
        try:
            for i in range(1,13):
                cusp = self._cusps[i]
                sign = cusp.sign()-1
                degree = cusp.amsha_raw_in_sign_longitude() if self._varga_code else cusp.real_in_sign_longitude()
                result.setdefault(sign,[]).append(f'C{i} {int(degree)}°')
        except Exception:
            return ()
        return tuple((sign, tuple(labels)) for sign,labels in result.items())

    def ascendant_degrees(self):
        try:
            cusp = self._cusps[1]
            degree = cusp.amsha_raw_in_sign_longitude() if self._varga_code else cusp.real_in_sign_longitude()
            return int(degree), int((degree % 1)*60)
        except Exception:
            return (0,0)

    def _effective_ascendant_sign_index(self):
        """Effective Ascendant sign index: F4 override, else cusp 1
            (classic chart_view.py:2427-2433)."""
        if self.ascendant_override is not None:
            return self.ascendant_override % 12
        if not self._cusps:
            return 0
        return self._cusps[1].sign() - 1

    def _sky_deg_min(self, planet):
        """(degrees, minutes) within the SKY sign, varga-aware (classic
            :2790-2792). Renamed from _planet_deg_min (SPEC-SIC-004 INV-6): this is
            the sign frame, used ONLY by the click payload so nobody rewires it to
            a placement frame's degree by accident. The glyph label under a planet
            uses the placement degree instead."""
        risl = planet.amsha_raw_in_sign_longitude() if self._varga_code else planet.real_in_sign_longitude()
        return (int(risl), int(risl % 1 * 60))

    def chart_jd(self):
        """The chart's UT Julian Day, or None (no chart / no time)."""
        try:
            return self._chart.context.timeJD.jd
        except Exception:
            return None

    _chart_jd = chart_jd

    @property
    def chart(self):
        return self._chart

    @property
    def use_western_names(self):
        return self._use_western_names

    def active_frame_name(self):
        """The name of the placement frame placing this chart, or None (no
        frame set, or a frame that falls back to the sign frame here)."""
        frame = self.frame
        return frame.name if frame is not None and frame.in_effect(self) else None

    def reset_frame(self, varga_code):
        """Drop the placement frame's per-chart caches and return its notice
        for the current chart (None without a frame)."""
        if self.frame is None:
            return None
        self.frame.invalidate()
        return self.frame.notice(self, varga_code)

    def _frame_fields(self):
        """(frame_active, marked_cell, frame_guide_notice) for the snapshot."""
        frame = self.frame
        if frame is None:
            return (False, None, None)
        return (True, frame.marked_cell(self), frame.guide_notice)

    def _planet_label(self, planet):
        """((text, emphasised), tooltip) of the frame's label above a planet,
        or (None, None)."""
        label = self.frame.planet_label(self, planet) if self.frame is not None else None
        if label is None:
            return (None, None)
        return ((label[0], label[2]), label[1])

    def _placement(self, planet):
        """The SINGLE (cell, deg) read for a planet (INV-6): the cell it is
            grouped into, the sort key, the lone-planet zone and the degree label
            under the glyph all come from here. No placement frame (or one that
            returns None for this chart): the sign and in-sign degree,
            varga-aware. Otherwise the frame's own (cell, deg)."""
        if self.frame is not None:
            pos = self.frame.placement(self, planet)
            if pos is not None:
                return pos
        varga = self._varga_code
        risl = planet.amsha_raw_in_sign_longitude() if varga else planet.real_in_sign_longitude()
        return (planet.sign() - 1, risl)

    def _planet_to_click_dict(self, planet_name, planet):
        """Classic click payload shape (chart_view.py:2794-2805). Always the
            sign frame (sign + sign degree); a placement frame may ADD its own
            keys so the dialog can show both frames without mixing them."""
        deg, mins = self._sky_deg_min(planet)
        payload = {'sign': planet.sign_name(), 'aditya_zodiac': planet.sign_name(), 'sign_index': planet.sign() - 1, 'degrees': deg, 'minutes': mins, 'decimal_degrees': planet.ecliptic_longitude(), 'is_retrograde': planet.retrograde()}
        if self.frame is not None:
            payload.update(self.frame.click_extras(self, planet))
        return payload
