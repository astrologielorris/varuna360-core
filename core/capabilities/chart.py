# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``get_chart``: the chart itself (AIC plan 2 W7, wave 1 row 2).

The snapshot logic moved here from ``pro/remote_control.py`` (``read_chart``
and its helpers), unchanged, so the Pro live reader and the headless tool
produce one shape from one function (INV-1). ``read_chart`` now calls
``chart_snapshot`` with the live chart, varga, ascendant override and
outer-planet visibility; the tool calls it with the CalculationInput's.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

OUTER_PLANETS = frozenset({"Uranus", "Neptune", "Pluto"})


def in_sign_pair(p_or_cusp) -> Tuple[Optional[float], str]:
    """(degree_float, text) from libaditya ``in_sign_longitude()``; defensive
    against a float-like value or a DMS object."""
    try:
        isl = p_or_cusp.in_sign_longitude()
    except Exception:
        return None, ""
    text = str(isl)
    degree = None
    try:
        degree = float(isl)
    except (TypeError, ValueError):
        for attr in ("total_degrees", "decimal", "value", "deg", "degrees"):
            v = getattr(isl, attr, None)
            if isinstance(v, (int, float)):
                degree = float(v)
                break
    if degree is None:
        # libaditya 0.4 answers in_sign_longitude() as a "DD:MM:SS" string;
        # the degree is its amsha longitude within the sign.
        try:
            degree = float(p_or_cusp.amsha_raw_in_sign_longitude())
        except Exception:
            degree = None
    return degree, text


def build_sign_name_map(planets_dict, cusps) -> Dict[int, str]:
    """Live sign_index -> sign_name pairs from libaditya bodies."""
    m = {}
    for _name, p in planets_dict.items():
        try:
            m[p.sign() - 1] = p.sign_name()
        except Exception:
            continue
    try:
        for i in range(1, 13):
            c = cusps[i]
            try:
                m[c.sign() - 1] = c.sign_name()
            except Exception:
                continue
    except Exception:
        pass
    return m


def sign_name_for(sign_index: int, sign_names: Dict[int, str]) -> str:
    name = sign_names.get(int(sign_index) % 12)
    if name is not None:
        return name
    from core.varga_codes import ADITYA_SIGNS
    return ADITYA_SIGNS[(int(sign_index) % 12) + 1]


def _pada(p) -> Optional[int]:
    """The nakshatra quarter (1-4) from the planet's own nakshatra object."""
    try:
        nak = p.nakshatra()
        quarter = float(nak.naksize()) / 4
        return min(4, int(float(nak.degrees_elapsed()) // quarter) + 1)
    except Exception:
        return None


def planet_snapshot(name: str, p, outer_names=OUTER_PLANETS,
                    outer_visible: bool = True) -> Dict[str, Any]:
    sign_num = p.sign()
    try:
        lon = float(p.ecliptic_longitude())
    except Exception:
        lon = None
    try:
        speed = float(p.longitude_speed())
    except Exception:
        speed = None
    deg, text = in_sign_pair(p)
    pada = None
    if hasattr(p, "nakshatra_pada"):
        try:
            pada = p.nakshatra_pada()
        except Exception:
            pada = None
    if pada is None:
        pada = _pada(p)
    return {
        "sign_number": int(sign_num),
        "sign_index": int(sign_num) - 1,
        "sign_name": p.sign_name(),
        "longitude": lon,
        "in_sign_degree": deg,
        "in_sign_text": text,
        "nakshatra": p.nakshatra_name(),
        "nakshatra_pada": pada,
        "retrograde": (speed is not None and speed < 0),
        "speed": speed,
        "visible": not (name in outer_names and not outer_visible),
    }


def ascendant_snapshot(cusps, override: Optional[int] = None) -> Dict[str, Any]:
    asc = cusps[1]
    sign_num = asc.sign()
    deg, text = in_sign_pair(asc)
    try:
        lon = float(asc.ecliptic_longitude())
    except Exception:
        lon = None
    computed = {
        "sign_number": int(sign_num),
        "sign_index": int(sign_num) - 1,
        "sign_name": asc.sign_name(),
        "longitude": lon,
        "in_sign_degree": deg,
        "in_sign_text": text,
    }
    if override is None:
        effective_idx = computed["sign_index"]
        effective_name = computed["sign_name"]
    else:
        effective_idx = int(override)
        effective_name = None  # filled in by the caller via the sign-name map
    return {
        "computed": computed,
        "effective": {
            "sign_number": (effective_idx % 12) + 1,
            "sign_index": effective_idx % 12,
            "sign_name": effective_name,
        },
        "override": int(override) if override is not None else None,
    }


def whole_sign_houses(eff_asc_idx: int, sign_names: Dict[int, str],
                      planets_dict) -> Dict[int, Dict[str, Any]]:
    """House 1 = effective ascendant sign; planets grouped by (sign - asc)."""
    eff = int(eff_asc_idx) % 12
    out = {}
    for h in range(1, 13):
        sign_idx = (eff + (h - 1)) % 12
        out[h] = {"sign_number": sign_idx + 1,
                  "sign_name": sign_name_for(sign_idx, sign_names),
                  "planets": []}
    for name, p in planets_dict.items():
        try:
            p_sign_idx = p.sign() - 1
        except Exception:
            continue
        out[((p_sign_idx - eff) % 12) + 1]["planets"].append(name)
    return out


def cusp_houses(cusps) -> Dict[int, Dict[str, Any]]:
    out = {}
    for i in range(1, 13):
        c = cusps[i]
        try:
            lon = float(c.ecliptic_longitude())
        except Exception:
            lon = None
        try:
            sign_num = int(c.sign())
            sign_name = c.sign_name()
        except Exception:
            sign_num = None
            sign_name = None
        out[i] = {"cusp_longitude": lon, "sign_number": sign_num,
                  "sign_name": sign_name}
    return out


def planet_cusp_house(planet_lon: float, cusps) -> int:
    """House i spans [cusps[i], cusps[i+1]) on the ecliptic, with wrap-around."""
    try:
        cusp_lons = [float(cusps[i].ecliptic_longitude()) for i in range(1, 13)]
    except Exception:
        return 1
    for house in range(1, 13):
        start = cusp_lons[house - 1]
        end = cusp_lons[house % 12]
        if end <= start:
            end += 360.0
        lon = planet_lon
        if lon < start:
            lon += 360.0
        if start <= lon < end:
            return house
    return 1


def planet_to_houses(planets_dict, cusps, eff_asc_idx: int) -> Dict[str, Dict]:
    out = {}
    eff = int(eff_asc_idx) % 12
    for name, p in planets_dict.items():
        try:
            whole = ((p.sign() - 1 - eff) % 12) + 1
        except Exception:
            whole = None
        try:
            cusp_h = planet_cusp_house(float(p.ecliptic_longitude()), cusps)
        except Exception:
            cusp_h = None
        out[name] = {"whole_sign": whole, "cusp": cusp_h}
    return out


def varga_surfaces(varga, varga_in_center, display_offset):
    """Which varga each chart surface draws, and its display offset
    (SPEC-VGC-001, SPEC-VGO-001). The one rule: ChartGUI._apply_current_varga
    paints the chart views with it, render_chart draws with it.

    ``varga`` is the GUI varga number (1 = rashi), translated with
    core.varga_codes.to_libaditya_varga_code. With ``varga_in_center`` and a
    varga, the MAIN chart stays D-1 and the varga goes to the second surface
    (the South Indian center box, the wheel and North Indian outer ring).
    ``display_offset`` is the D-1 sidereal offset (``_disp_ayan``); a surface
    drawing a varga full-size gets ``_disp_render_off`` (0 off D-1)."""
    from core.varga_codes import to_libaditya_varga_code
    rcode = None if varga == 1 else to_libaditya_varga_code(varga)
    in_second = bool(varga_in_center) and rcode is not None
    main = None if in_second else rcode
    render_off = 0.0 if varga != 1 else display_offset
    return {
        "main": main, "ring": rcode if in_second else None,
        "grid": main, "center": rcode if in_second else None,
        "main_offset": display_offset if main is None else render_off,
        "grid_offset": display_offset if main is None else render_off,
    }


def main_surface_varga(varga: int, varga_in_center: bool) -> int:
    """The GUI varga number the MAIN chart surface draws (and the retinue
    rings drawn on it): 1 when ``display.varga_in_center`` moves the varga to
    the second surface, else ``varga`` (``varga_surfaces``'s "main")."""
    varga = varga or 1
    return 1 if varga_surfaces(varga, varga_in_center, 0.0)["main"] is None else varga


def varga_source(chart, varga: int):
    """The chart body the panels read for ``varga`` (1 = rashi)."""
    varga = varga or 1
    if varga != 1:
        try:
            from core.varga_codes import to_libaditya_varga_code
            libcode = to_libaditya_varga_code(varga)
        except Exception:
            libcode = varga
        return chart.varga(libcode)
    return chart.rashi()


def _relabel_snapshot(snap: Dict[str, Any], use_western_names: bool,
                      sign_language: str = "en") -> None:
    """Every ``sign_name`` in ``snap`` -> the label the app shows for its sign
    under the chosen label set and sign language
    (``core.aditya_mode.displayed_sign_name``, the chart wheel's rule: the
    language only changes the Western set). The ordinal is kept (Dhata =
    Aries = 1); only the label changes. In place."""
    from core.aditya_mode import displayed_sign_name

    def fix(entry, index):
        if isinstance(entry, dict) and entry.get("sign_name") is not None \
                and isinstance(index, int):
            entry["sign_name"] = displayed_sign_name(index % 12, None,
                                                     use_western_names,
                                                     sign_language or "en")

    for p in snap["planets"].values():
        fix(p, p.get("sign_index"))
    for part in ("computed", "effective"):
        fix(snap["ascendant"][part], snap["ascendant"][part].get("sign_index"))
    for houses in (snap["houses_whole_sign"], snap["houses_cusp"]):
        for h in houses.values():
            num = h.get("sign_number")
            fix(h, num - 1 if isinstance(num, int) else None)


def chart_snapshot(source, ascendant_override: Optional[int] = None,
                   outer_visible: bool = True,
                   use_western_names: Optional[bool] = None,
                   sign_language: str = "en") -> Dict[str, Any]:
    """Planets, ascendant (computed and effective), whole-sign and cusp houses
    of one chart body (rashi or a varga).

    ``use_western_names``: the label set on screen. Given, every ``sign_name``
    is the label the app displays (an Advanced user's Western names on the
    Aditya Circle, or Aditya names on the sidereal circle); None keeps the
    engine's names (the mode's own set, which is also what Beginner shows).
    ``sign_language`` (``zodiac.sign_language``): the language of the Western
    labels, as the chart drawings show them; used with ``use_western_names``."""
    planets_data = source.planets()
    planets = {name: planet_snapshot(name, p, OUTER_PLANETS, outer_visible)
               for name, p in planets_data.items()}
    cusps = source.cusps()
    ascendant = ascendant_snapshot(cusps, ascendant_override)
    sign_names = build_sign_name_map(planets_data, cusps)
    if ascendant["effective"]["sign_name"] is None:
        ascendant["effective"]["sign_name"] = sign_name_for(
            ascendant["effective"]["sign_index"], sign_names)
    effective_idx = ascendant["effective"]["sign_index"]
    snap = {
        "planets": planets,
        "ascendant": ascendant,
        "houses_whole_sign": whole_sign_houses(effective_idx, sign_names, planets_data),
        "houses_cusp": cusp_houses(cusps),
        "planet_houses": planet_to_houses(planets_data, cusps, effective_idx),
    }
    if use_western_names is not None:
        _relabel_snapshot(snap, bool(use_western_names), sign_language)
    return snap


# ------------------------------------------------------------- capability

def _run_get_chart(inp, options):
    chart = inp.build_chart()
    # Human Design: the Design chart, labelled as the app draws it
    mode, use_western = inp.chart_display()
    snap = chart_snapshot(varga_source(chart, inp.view.varga),
                          inp.view.ascendant_override,
                          inp.frame.show_outer_planets,
                          use_western_names=use_western,
                          sign_language=options["sign_language"])
    snap["varga"] = inp.view.varga
    snap["zodiac"] = {"mode": mode, "ayanamsa_id": inp.frame.ayanamsa_id,
                      "house_system": inp.frame.house_system}
    if options.get("compact"):
        # SPEC-COACH-001 §4.4: planets, ascendant and each planet's houses only
        for key in COMPACT_DROPS:
            snap.pop(key, None)
    return snap


# The house tables a compact reply leaves out (planet_houses stays).
COMPACT_DROPS = ("houses_whole_sign", "houses_cusp")


def _register():
    from core.capabilities.catalog import Capability, register
    from core.capabilities.setting_args import INPUT, setting
    from core.settings_registry import option_schema
    register(Capability(
        id="get_chart",
        title="Chart",
        description=("Planet positions (longitude, sign, nakshatra, pada, "
                     "retrograde), ascendant (computed and effective after an "
                     "override), whole-sign and cusp houses, for the chart's "
                     "zodiac system and the selected varga."),
        run=_run_get_chart,
        # The chart drawings localize the Western sign names (Settings tab
        # language); the labels here are the ones the chart shows.
        options_schema={"type": "object", "additionalProperties": False,
                        "properties": {"sign_language": option_schema(
                            "zodiac.sign_language", "sign_language",
                            description=("Language of the Western sign "
                                         "names (the chart's labels).")),
                            "compact": {"type": "boolean", "default": False,
                                        "description": ("Leave out the house tables "
                                                        "(each planet's houses stay) "
                                                        "and the settings echo: a "
                                                        "short reply.")}}},
        setting_args={"sign_language": setting("zodiac.sign_language"),
                      "compact": INPUT},
        output_schema={"type": "object",
                       "required": ["planets", "ascendant", "planet_houses", "varga",
                                    "zodiac"]},
        sources=(("core/capabilities/chart.py", "chart_snapshot"),
                 ("core/chart_factory.py", "build_chart_from_params")),
    ))


_register()
