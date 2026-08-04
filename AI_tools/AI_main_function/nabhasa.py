# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""
Nabhasa Yogas adapter (pure reshape of the libaditya detection engine).
=======================================================================
The *detection* engine already exists on ``libaditya.calc.rashi.Rashi``
(``nabhasa_yogas()``, ``ashraya_yogas()``, ``dala_yogas()``, ``sankhya_yogas()``,
``akriti_yogas()``, ``panchamahapurusha_yogas()``), each yoga carrying a
``to_move`` "how many of the 7 karakas must move to complete this yoga" score
(the classical "most nearly formed" metric, Jyotish Building Blocks manual
and personal notes extracted from the course, L957-977). This module is a
**pure, GUI-free reshape**: it consumes those
dataclasses and emits ONE stable dict the widget renders, grouped by the four
Nabhasa families (Asraya / Dala / Sankhya / Akriti) plus the five Pancha
Mahapurusha yogas.

Mirrors ``interchange.py`` (adapter layer): takes an ALREADY-FRAMED chart, reads
NO GUI state, imports NO ``pro/`` code (H11). Sidereal/other framing is the
caller's (controller's) responsibility.

TWO course-corrections live HERE, not in the shared engine (the engine has other
callers):

  * **Dala:** the engine's ``dala_yogas()`` scores "all benefics in
    kendras" as a distance. From course notes on Ernst Wilhelm's teaching, the
    reading is MAJORITY/proportional — count gentle vs cruel karakas AT the
    angles; the dominant class is the yoga and the ratio is the reading. We
    present that as the default and keep the engine's strict reading as an
    off-by-default alternate.
  * **Pancha Mahapurusha:** the engine treats moolatrikona ("MT")
    as forming and ignores cancellation. Per course notes, own/exaltation ONLY,
    read from the ascendant, with Sun/Moon-conjunction cancellation. We recompute
    ``formed`` as ``dig in ("OH","EX")`` and flag ``cancelled`` when the Sun or
    Moon shares the yoga-planet's sign.

The benefic/malefic classification the Dala reading needs is taken from the
engine's own ``planet.nature()`` — verified to match Ernst for the
two edge cases that matter: Mercury is unconditionally Benefic (planets.py) and
the Moon is Benefic iff within 180 deg of the Sun (waxing), i.e. the same
gentle/cruel axis.
"""

from core.chart_helpers import get_planet_sign_index, has_planet

# The seven embodied planets (karakas). NEVER Rahu/Ketu/Ascendant — Nabhasa
# yogas are built from these seven only (Jyotish Building Blocks manual and
# personal notes extracted from the course, L957-977).
KARAKAS = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn"]

ANGLES = frozenset({1, 4, 7, 10})

# Pancha Mahapurusha dignity set AFTER the D9 course-correction (drop "MT").
PMP_FORMING_DIGNITIES = frozenset({"OH", "EX"})

# The 20 canonical Akriti names, in the classical teaching order. The engine
# emits 33 AkritiYoga objects because Hala (3 trines), Gada (4 angle-pairs), Vapi
# (2), and Ardha Chandra (8) are returned at the variant level; the widget shows
# 20 rows, so we collapse variants to these canonical names.
CANONICAL_AKRITIS = (
    "Sringataka", "Hala", "Gada", "Sakata", "Vihaga", "Kamala", "Vapi",
    "Vajra", "Yava", "Yupa", "Sara", "Shakti", "Danda", "Nauka", "Kuta",
    "Chatra", "Chapa", "Ardha Chandra", "Chakra", "Samudra",
)

# Prefixes that mark an engine name as a VARIANT of a canonical Akriti. Order
# matters only in that each engine name matches at most one prefix.
_VARIANT_PREFIXES = ("Hala", "Gada", "Vapi", "Ardha Chandra")

# NOTE: Vajra/Yava are read like every other Akriti (by nearest formation, the
# closer the shape the stronger the effect) — no special "never forms" handling.
# Whether the fixed benefic/malefic table should ever let them reach to_move==0 is
# a separate open question tracked in bead td-pbw1 (see yoga_research doc).

# Asraya (modality) sign-index sets (0=Aries .. 11=Pisces). The Asraya combination
# is a MODALITY, not a house shape, so its defining pattern is the four signs of
# that modality; the widget/diagram convert them to houses via the ascendant.
_MOVABLE_SIGNS = (0, 3, 6, 9)     # Aries, Cancer, Libra, Capricorn
_FIXED_SIGNS = (1, 4, 7, 10)      # Taurus, Leo, Scorpio, Aquarius
_DUAL_SIGNS = (2, 5, 8, 11)       # Gemini, Virgo, Sagittarius, Pisces
ASRAYA_SIGNS = {
    "Rajju": _MOVABLE_SIGNS,
    "Musala": _FIXED_SIGNS,
    "Nala": _DUAL_SIGNS,
}

# The four kendras (angles) — the Dala combination.
ANGLE_HOUSES = (1, 4, 7, 10)


def _strength_fraction(to_move):
    """(7 - to_move) / 7, clamped to [0, 1] — drives the strength bar."""
    frac = (7 - to_move) / 7.0
    return max(0.0, min(1.0, frac))


def _split_canonical(engine_name):
    """Map an engine Akriti name -> (canonical_name, variant_label_or_None).

    'Hala Moksha' -> ('Hala', 'Moksha'); 'Ardha Chandra Kama Apoklima' ->
    ('Ardha Chandra', 'Kama Apoklima'); 'Kamala' -> ('Kamala', None).
    """
    for prefix in _VARIANT_PREFIXES:
        if engine_name == prefix:
            return engine_name, None
        if engine_name.startswith(prefix + " "):
            return prefix, engine_name[len(prefix) + 1:]
    return engine_name, None


def _reshape_house_yoga(yoga, canonical=None, variant=None):
    """Common shape for a house-set yoga (Asraya, Sankhya, Akriti)."""
    name = canonical if canonical is not None else yoga.name
    return {
        "name": name,
        "translation": getattr(yoga, "translation", ""),
        "variant": variant,
        "to_move": yoga.to_move,
        "strength_fraction": _strength_fraction(yoga.to_move),
        "houses": tuple(getattr(yoga, "houses", ()) or ()),
        "formed": yoga.to_move == 0,
    }


def _collapse_akriti(akriti_list):
    """Collapse the engine's 33 variant AkritiYoga objects to 20 canonical rows.

    For each canonical name keep the BEST (lowest to_move) variant and record
    which variant won (for the reading label, e.g. "Hala · moksha trine").
    Returns a list ranked by to_move ascending.
    """
    best = {}
    for yoga in akriti_list:
        canonical, variant = _split_canonical(yoga.name)
        prev = best.get(canonical)
        if prev is None or yoga.to_move < prev._raw_to_move:
            row = _reshape_house_yoga(yoga, canonical=canonical, variant=variant)
            # stash the raw score on a lightweight holder for the comparison above
            holder = _AkritiRow(row, yoga.to_move)
            best[canonical] = holder
    rows = [h.row for h in best.values()]
    rows.sort(key=lambda r: r["to_move"])
    return rows


class _AkritiRow:
    """Tiny internal holder pairing a reshaped row with its raw to_move score."""
    __slots__ = ("row", "_raw_to_move")

    def __init__(self, row, raw_to_move):
        self.row = row
        self._raw_to_move = raw_to_move


def _build_house_map(chart):
    """sign_index -> whole-sign house number (1-12), from the Ascendant sign.

    Mirrors interchange._build_sign_house_map (occupied-house convention).
    Returns None if the ascendant is unresolved.
    """
    asc_idx = get_planet_sign_index(chart, "Ascendant", default=-1)
    if asc_idx < 0:
        return None
    return {(asc_idx + h - 1) % 12: h for h in range(1, 13)}


def _karaka_houses(chart, sign_to_house):
    """{planet: house} for each of the 7 karakas present in the chart."""
    houses = {}
    for planet in KARAKAS:
        if not has_planet(chart, planet):
            continue
        idx = get_planet_sign_index(chart, planet, default=-1)
        if idx < 0:
            continue
        house = sign_to_house.get(idx)
        if house is not None:
            houses[planet] = house
    return houses


def _reshape_asraya(yoga, sign_to_house):
    """Asraya reshape: attach the modality's four signs AND their houses.

    Musala (all in fixed signs) has no intrinsic house shape, so its combination
    diagram is the four signs of the modality; we also pre-compute the houses
    those signs fall in (via the ascendant) so the North grid can highlight them.
    """
    row = _reshape_house_yoga(yoga)
    signs = ASRAYA_SIGNS.get(yoga.name, ())
    row["signs"] = tuple(signs)
    row["houses"] = tuple(sorted(
        sign_to_house[s] for s in signs if s in sign_to_house))
    return row


def _occupied_houses(chart, sign_to_house):
    """The set of whole-sign houses that hold at least one of the 7 karakas —
    the Sankhya combination (Sankhya counts exactly these)."""
    return tuple(sorted(set(_karaka_houses(chart, sign_to_house).values())))


def _dala_majority(chart, rashi, sign_to_house):
    """The MAJORITY Dala reading per course notes on Ernst Wilhelm's teaching.

    Count gentle vs cruel karakas AT the angles {1,4,7,10}; the dominant class is
    the yoga (Mala = gentle-heavy, Sarpa = cruel-heavy), the ratio is the reading.
    Uses the engine's planet.nature() (verified: Mercury always Benefic; Moon
    Benefic iff waxing) so this stays consistent with the rest of the app.

    # NABHASA-REVIEW: R1 Dala uses the majority/proportional reading (gentle
    #   vs cruel AT the angles), not the engine's strict all-benefics distance.
    #   Benefic/malefic taken from engine planet.nature() (verified match).
    #   Strict engine reading retained as `strict` for an off-by-default toggle.
    """
    gentle = 0
    cruel = 0
    gentle_houses = set()
    cruel_houses = set()
    for planet, house in _karaka_houses(chart, sign_to_house).items():
        if house not in ANGLES:
            continue
        try:
            nature = rashi.planets()[planet].nature()
        except Exception:
            # A planet whose nature can't be resolved makes the reading a guess;
            # surface as pending rather than a confident wrong value.
            return {"dominant": "pending", "gentle_in_angles": 0,
                    "cruel_in_angles": 0, "total_in_angles": 0,
                    "ratio_text": "pending", "review": "R1",
                    "angle_houses": ANGLE_HOUSES,
                    "gentle_houses": (), "cruel_houses": ()}
        if nature == "Benefic":
            gentle += 1
            gentle_houses.add(house)
        else:
            cruel += 1
            cruel_houses.add(house)

    total = gentle + cruel
    if total == 0:
        dominant = "none"          # no karaka at the angles -> no Dala (50/50)
        ratio_text = "no planets in the angles"
    elif gentle > cruel:
        dominant = "Mala"          # garland — gentle-heavy angles
        ratio_text = f"{gentle} gentle / {cruel} cruel in the angles"
    elif cruel > gentle:
        dominant = "Sarpa"         # serpent — cruel-heavy angles
        ratio_text = f"{cruel} cruel / {gentle} gentle in the angles"
    else:
        dominant = "balanced"      # 2-2 etc -> 50/50 (balanced)
        ratio_text = f"{gentle} gentle / {cruel} cruel in the angles (balanced)"

    return {
        "dominant": dominant,
        "gentle_in_angles": gentle,
        "cruel_in_angles": cruel,
        "total_in_angles": total,
        "ratio_text": ratio_text,
        "review": "R1",
        # Combination diagram data: the four kendras, with the occupied ones
        # tinted gentle (benefic) / cruel (malefic).
        "angle_houses": ANGLE_HOUSES,
        "gentle_houses": tuple(sorted(gentle_houses)),
        "cruel_houses": tuple(sorted(cruel_houses)),
    }


def _dala_strict(dala_list):
    """The engine's strict 'all benefics/malefics in kendras' reading (toggle)."""
    return [
        {
            "name": y.name,
            "translation": y.translation,
            "to_move": y.to_move,
            "strength_fraction": _strength_fraction(y.to_move),
            "formed": y.to_move == 0,
            "condition": y.condition,
        }
        for y in dala_list
    ]


def _panchamahapurusha(chart, rashi):
    """Reshape + course-correct the 5 Pancha Mahapurusha yogas.

    Engine: formed iff angular AND dig in ("OH","EX","MT"). Course correction:
      * drop moolatrikona -> dig in ("OH","EX") only;
      * cancel when the Sun or Moon shares the yoga-planet's sign (per course notes).
    Read from the ascendant (the engine's `house` already is; see rashi.py).

    # NABHASA-REVIEW: R3 PMP forming set course-corrected to ("OH","EX") only
    #   (moolatrikona dropped per course notes / Phaladeepika 6.1). Sun/Moon
    #   conjunction cancellation uses a WHOLE-SIGN (same-rasi) definition of
    #   "conjunct"; an orb-based definition is not implemented.
    """
    sun_idx = get_planet_sign_index(chart, "Sun", default=-1)
    moon_idx = get_planet_sign_index(chart, "Moon", default=-1)

    out = []
    for y in rashi.panchamahapurusha_yogas():
        in_angle = y.house in ANGLES
        dignified = y.dignity in PMP_FORMING_DIGNITIES
        formed = bool(in_angle and dignified)

        # Cancellation: Sun or Moon in the same sign as the yoga-planet.
        cancelled = False
        cancel_reason = None
        planet_idx = get_planet_sign_index(chart, y.planet, default=-1)
        if formed and planet_idx >= 0:
            if sun_idx >= 0 and planet_idx == sun_idx:
                cancelled, cancel_reason = True, "Sun conjunct"
            elif moon_idx >= 0 and planet_idx == moon_idx:
                cancelled, cancel_reason = True, "Moon conjunct"

        # Whether MT-only would have formed it (so the widget can explain why a
        # chart that "looks" like it has the yoga does not, post-correction).
        mt_only = bool(in_angle and y.dignity == "MT")

        out.append({
            "name": y.name,
            "translation": y.translation,
            "planet": y.planet,
            "house": y.house,
            "dignity": y.dignity,
            "in_angle": in_angle,
            "formed": formed and not cancelled,
            "formed_before_cancel": formed,
            "cancelled": cancelled,
            "cancel_reason": cancel_reason,
            "mt_only": mt_only,
            "review": "R3",
        })
    return out


def get_nabhasa_yogas(chart):
    """Detect + reshape all Nabhasa (32) + Pancha Mahapurusha (5) yogas.

    PURE: takes an ALREADY-FRAMED chart, reads no GUI state, imports no pro/ code.
    Returns a stable dict the widget consumes; see module docstring for the two
    course-corrections applied here (Dala majority, PMP drop-MT + cancellation).
    """
    empty = {
        "available": False,
        "asc_sign_index": -1,
        "asraya": {"prevalent": None, "all": []},
        "dala": {"majority": None, "strict": [], "review": "R1"},
        "sankhya": {"active": None, "all": []},
        "akriti": {"prevalent": None, "ranked": []},
        "panchamahapurusha": [],
    }

    if chart is None:
        return empty

    try:
        rashi = chart.rashi()
    except Exception:
        return empty

    sign_to_house = _build_house_map(chart)
    if sign_to_house is None:
        return empty
    asc_idx = get_planet_sign_index(chart, "Ascendant", default=-1)
    occupied_houses = _occupied_houses(chart, sign_to_house)

    # --- Asraya (modality) ---
    asraya_all = [_reshape_asraya(y, sign_to_house) for y in rashi.ashraya_yogas()]
    asraya_all.sort(key=lambda r: r["to_move"])
    asraya_prevalent = asraya_all[0] if asraya_all else None

    # --- Dala (benefic/malefic weight in angles) ---
    dala = {
        "majority": _dala_majority(chart, rashi, sign_to_house),
        "strict": _dala_strict(rashi.dala_yogas()),
        "review": "R1",
    }

    # --- Sankhya (number of occupied houses) — exactly one is always to_move 0 ---
    sankhya_all = [_reshape_house_yoga(y) for y in rashi.sankhya_yogas()]
    for r in sankhya_all:
        # The Sankhya combination is which houses are actually occupied.
        r["houses"] = occupied_houses
    sankhya_all.sort(key=lambda r: r["to_move"])
    sankhya_active = next((r for r in sankhya_all if r["to_move"] == 0), None)

    # --- Akriti (shape) — 33 variants collapsed to 20 canonical, ranked ---
    akriti_ranked = _collapse_akriti(rashi.akriti_yogas())
    akriti_prevalent = akriti_ranked[0] if akriti_ranked else None

    # --- Pancha Mahapurusha (5) ---
    pmp = _panchamahapurusha(chart, rashi)

    return {
        "available": True,
        "asc_sign_index": asc_idx,
        "asraya": {"prevalent": asraya_prevalent, "all": asraya_all},
        "dala": dala,
        "sankhya": {"active": sankhya_active, "all": sankhya_all},
        "akriti": {"prevalent": akriti_prevalent, "ranked": akriti_ranked},
        "panchamahapurusha": pmp,
    }
