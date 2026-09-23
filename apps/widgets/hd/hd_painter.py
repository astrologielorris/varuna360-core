"""Painting the BodyGraph: pure QPainter drawing, no widgets and no scene.

Split out from the view so the whole graph can be rendered to an image in a test without
a window, and so the layer items stay thin. Everything here takes an :class:`HDGraphState`
and paints one slice of the picture in canvas coordinates; the caller sets up the
transform.

Layer order, bottom to top, is the mockup's own and is not arbitrary:

    aura        soft halo per centre, breathing
    glow        wide translucent twins of the lit traces -- UNDER the dead layer, so a
                lit channel blooms beneath its neighbours instead of over them
    dead        every unactivated trace, thin copper, in ONE layer so no dim trace can
                cut across a lit core where two channels cross or meet at a junction
    lit         the defined halves and braid tracks
    centres     the nine shapes, opaque: channels run behind them
    terminals   ringed pads on the 64 gate seats, vias at the 30 ordinary midpoints,
                and the braid's two junctions (the braid channels get no via -- their
                midpoints ARE the junctions)
    gates       the numerals, on a disc when activated
    pulse       the travelling dash, drawn last so it reads over everything it rides

Rule 20: no colour here is a literal. The nine centre fills and the two activation
colours come from ``hd_palette()``, the one approved semantic-palette exception; board,
chrome and text come from the theme like everywhere else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QRadialGradient,
)

from . import hd_geometry as G

#: The mockup's own viewBox: the canvas cropped to what the graph occupies.
VIEWBOX = QRectF(20.0, 10.0, 520.0, 900.0)

#: Terminal radii, from mockup 27.
PAD_RADIUS = 2.7
VIA_RADIUS = 3.1
JUNCTION_RADIUS = 3.1

#: Gate numeral furniture.
DISC_RADIUS = 6.0
DISC_GLOW_RADIUS = 10.5
PLAIN_HALO_RADIUS = 7.6

#: How far the dead network is knocked back before anything is focused. The mockup runs
#: its whole copper layer at .70 so a lit core reads as lit rather than merely coloured.
DEAD_OPACITY = 0.70

#: Focus dimming, from the plan's interaction table. A hovered element keeps full
#: strength; everything unrelated drops to these.
DIM = {
    "dead": 0.09,
    "trace": 0.12,
    "junction": 0.16,
    "terminal": 0.16,
    "gate": 0.20,
    "centre": 0.34,
    "aura": 0.05,
}
#: On a light ground an opacity drop washes toward white rather than toward black, so the
#: same ratio loses the shape sooner. Light dims less.
DIM_LIGHT = {**DIM, "centre": 0.44, "gate": 0.30}

#: Striping. A gate activated in BOTH sets shows the Design colour with the Personality
#: colour dashed over it.
STRIPE_DASH = (5.5, 5.5)
#: The travelling pulse: a short bright dash with a long gap, riding the lit traces.
PULSE_DASH = (5.0, 62.0)
PULSE_PERIOD_MS = 5200


def _centroid(centre: str) -> tuple[float, float]:
    points = G.centre_polygon(centre)
    return (sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points))


def _aura_radius(centre: str) -> float:
    """The mockup's own: furthest vertex from the centroid, times 1.05, times 1.3."""
    cx, cy = _centroid(centre)
    reach = max(math.hypot(p[0] - cx, p[1] - cy) for p in G.centre_polygon(centre))
    return reach * 1.05 * 1.3


#: The only gate states the painter knows how to draw. Anything else is unactivated.
_GATE_STATES = frozenset({"none", "personality", "design", "both"})

#: Model fields the page reads as a mapping. A list or a None here is what actually
#: reaches us from a half-written engine or a contract that moved, and every reader
#: downstream calls ``.get`` on them.
_DICT_FIELDS = ("gates", "channels", "centers", "incarnation_cross")
#: Fields read as text. A caller that forgets to serialise a datetime sends a number or
#: a datetime object, and the reading card calls ``.replace`` on it.
_TEXT_FIELDS = ("type", "strategy", "authority", "profile", "profile_name", "definition",
                "frame", "schema_version", "design_datetime", "personality_datetime")
_SIDES = ("design", "personality")


def normalise_model(model) -> dict:
    """Coerce whatever arrives into the shape this page can draw.

    The model crosses a module boundary and a contract that has already moved twice, so
    the interesting inputs are not "a missing key" -- those were always handled -- but
    the WRONG TYPE in a present key: ``gates`` as a list, ``centers`` as None, a root
    that is not a dict at all, a timestamp that is still an int. Each of those used to
    raise AttributeError from inside a paint or a label refresh, which takes the whole
    tab down on the user's own chart.

    Defending at each read site was the alternative and it is the worse one: there are
    thirty-odd of them, a new one arrives with every field, and the one that gets
    forgotten is found by a user rather than by us. So the shape is guaranteed ONCE,
    here, at the door.

    Unrecognised keys are passed through untouched. A later contract may add fields this
    page does not read yet, and dropping them would make this function a silent filter
    on somebody else's data.
    """
    if not isinstance(model, dict):
        # a list, a string, None: nothing to read, but the page must still draw empty
        return {}
    clean = dict(model)
    for field_name in _DICT_FIELDS:
        if field_name in clean and not isinstance(clean[field_name], dict):
            clean[field_name] = {}
    for field_name in _TEXT_FIELDS:
        value = clean.get(field_name)
        if value is not None and not isinstance(value, str):
            clean[field_name] = str(value)
    activations = clean.get("activations")
    if activations is not None:
        if not isinstance(activations, dict):
            activations = {}
        clean["activations"] = {
            side: [row for row in (activations.get(side) or []) if isinstance(row, dict)]
            for side in _SIDES}
    if "errors" in clean and not isinstance(clean["errors"], (list, tuple)):
        clean["errors"] = []
    return clean


@dataclass
class HDGraphState:
    """Everything the painter needs: the chart, and what the user is doing to it.

    ``model`` is an HDModel dict (contract v1.0). The painter reads it defensively --
    a missing gate or channel renders as unactivated rather than raising, because a
    half-built model must never take the view down mid-paint.
    """

    model: dict
    palette: dict
    label_mode: str = "numbers"          # numbers | hexagrams
    activation_filter: str = "both"      # both | personality | design
    pulse: bool = True
    phase: float = 0.0                   # 0..1, the shared animation clock
    #: What the pointer is on, or what is pinned. None means nothing is focused and
    #: everything paints at full strength.
    focus_centres: frozenset = field(default_factory=frozenset)
    focus_gates: frozenset = field(default_factory=frozenset)
    focus_channels: frozenset = field(default_factory=frozenset)
    focus_tracks: frozenset = field(default_factory=frozenset)

    @property
    def focusing(self) -> bool:
        return bool(self.focus_centres or self.focus_gates
                    or self.focus_channels or self.focus_tracks)

    @property
    def dim(self) -> dict:
        return DIM_LIGHT if self.palette.get("is_light") else DIM

    # -- reading the model, defensively ------------------------------------------------

    def gate_state(self, gate: int) -> str:
        """``none`` | ``personality`` | ``design`` | ``both``, after the P/D/Both filter.

        The filter hides one side rather than recomputing the chart: a channel whose
        other half is filtered out still shows the half that survives, which is what
        makes the filter useful for reading a chart rather than a different chart.
        """
        raw = (self.model.get("gates") or {}).get(str(gate), "none")
        # The model comes from another module. Anything this painter does not recognise
        # is treated as unactivated rather than carried forward: a None or a typo would
        # otherwise pass channel_defined() and then index a three-key palette map, and
        # the view would die mid-paint on a chart it could have drawn as unactivated.
        if raw not in _GATE_STATES:
            raw = "none"
        if self.activation_filter == "personality":
            return "personality" if raw in ("personality", "both") else "none"
        if self.activation_filter == "design":
            return "design" if raw in ("design", "both") else "none"
        return raw

    def centre_defined(self, centre: str) -> bool:
        if self.activation_filter != "both":
            # with one side hidden, a centre is only as defined as its visible channels
            return any(self.channel_defined(k)
                       for k in G.CHANNEL_KEYS
                       if centre in {G.centre_of_gate(g) for g in G.gates_of_channel(k)})
        return bool((self.model.get("centers") or {}).get(centre, False))

    def channel_state(self, key: str) -> dict:
        """One channel's row, or an empty one. The model may still be half built."""
        row = (self.model.get("channels") or {}).get(key)
        return row if isinstance(row, dict) else {}

    def channel_defined(self, key: str) -> bool:
        """A channel is defined when BOTH its gates are activated in the visible sets."""
        a, b = G.gates_of_channel(key)
        return self.gate_state(a) != "none" and self.gate_state(b) != "none"


def _colour(state: str, palette: dict) -> QColor:
    if state == "personality":
        return QColor(palette["personality"])
    if state == "design":
        return QColor(palette["design"])
    return QColor(palette["dead_trace"])


def _alpha(colour: QColor, factor: float) -> QColor:
    out = QColor(colour)
    out.setAlphaF(max(0.0, min(1.0, colour.alphaF() * factor)))
    return out


def path_of(kind: str, data: Sequence) -> QPainterPath:
    """Build a QPainterPath from the geometry module's two path shapes.

    A braid path is drawn straight, never splined: its polyline IS the finished curve,
    and re-smoothing reintroduces the overshoot its geometric construction removes.
    """
    path = QPainterPath()
    if not len(data):
        return path
    if kind == G.KIND_POLY:
        path.moveTo(*data[0])
        for point in data[1:]:
            path.lineTo(*point)
        return path
    path.moveTo(*data[0][0])
    for p0, p1, p2, p3 in data:
        path.cubicTo(QPointF(*p1), QPointF(*p2), QPointF(*p3))
    return path


def centre_path(centre: str) -> QPainterPath:
    """A centre's outline. The three squares get the mockup's 9px corner radius."""
    path = QPainterPath()
    shape = G.CENTER_SHAPE[centre]
    if shape["shape"] == "rect":
        path.addRoundedRect(QRectF(shape["x"], shape["y"], shape["w"], shape["h"]), 9, 9)
    else:
        points = shape["pts"]
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        path.closeSubpath()
    return path


# ---------------------------------------------------------------------------
# the layers
# ---------------------------------------------------------------------------

#: Built once, on first use. The 65 trace paths are pure geometry -- they do not depend
#: on the chart, the theme, the filter or the phase -- so rebuilding them per frame cost
#: about 1,560 QPainterPath constructions a second at 24 fps for no gain. QPainterPath is
#: not mutated by drawPath, so one instance is safely shared by every pass and painter.
_TRACES: tuple | None = None


def _trace_segments(state: HDGraphState):
    """``(path, gate, key, is_track)`` for every drawable trace.

    The braid is yielded as its five TRACKS, each coloured by its own gate -- never as
    its six channels. Drawing the channels instead paints the shared track up to six
    times, and a Personality-20 that should stop at the junction runs the whole rail.

    ``state`` is unused: the shapes are fixed. It stays in the signature because every
    caller has one, and because a future frame-dependent path would need it.
    """
    global _TRACES
    if _TRACES is None:
        built = []
        for key in G.CHANNEL_KEYS:
            if G.is_braid(key):
                continue
            kind, first, second = G.channel_halves(key)
            start_gate, end_gate = G.CHANNEL_ENDS[key]
            built.append((path_of(kind, first), start_gate, key, False))
            built.append((path_of(kind, second), end_gate, key, False))
        for track in G.TRACK_NAMES:
            built.append((path_of(G.KIND_POLY, G.track_polyline(track)),
                          _TRACK_GATE.get(track), track, True))
        _TRACES = tuple(built)
    return _TRACES


#: Which gate owns each braid track. The trunk has no owner: it belongs to whichever
#: defined channels route through it, and takes the union of their states.
_TRACK_GATE = {"stem20": 20, "stem10": 10, "stem57": 57, "stem34": 34}


def _trunk_state(state: HDGraphState) -> str:
    """The trunk's colour: the union of the gate states of the channels crossing it.

    On the standard sample all four integration gates are activated in both sets, so the
    trunk stripes under any interpretation; the rule matters on other charts.
    """
    seen = set()
    for key in G.channels_on_track("trunk"):
        if not state.channel_defined(key):
            continue
        for gate in G.gates_of_channel(key):
            seen.add(state.gate_state(gate))
    seen.discard("none")
    if not seen:
        return "none"
    return "both" if len(seen) > 1 or "both" in seen else seen.pop()


def _track_state(state: HDGraphState, track: str) -> str:
    """The colour a braid track paints in.

    A STEM is one gate's own approach to the junction, so it lights on that gate alone --
    the same rule as a half channel, and for the same reason: a hanging integration gate
    is a real thing in a reading. Requiring a defined channel here hid gate 20's stem on
    a chart where 20 is activated and nothing completes it, and hid a cross-side
    integration channel entirely under a one-side filter.

    The TRUNK is different: it is shared, so it has no gate of its own and takes the
    union of the states of the defined channels that actually travel it.

    Whether a track carries the PULSE is again a separate question -- see _is_live.
    """
    if track == "trunk":
        return _trunk_state(state)
    return state.gate_state(_TRACK_GATE[track])


def _is_lit(state: HDGraphState, key: str, gate, is_track: bool) -> str:
    """The state a trace should paint in, or ``none`` if it stays dead copper.

    A HALF lights on its OWN gate alone. A single activated gate is a real thing in a
    reading -- it is what a partner or a transit completes -- so a half channel with one
    end lit and one end dead is the picture the chart is actually making. Requiring the
    whole channel here would hide every hanging gate on the graph.

    Whether the channel is DEFINED is a separate question, and it governs only the pulse:
    light travels a completed circuit, not a stub.
    """
    if is_track:
        return _track_state(state, key)
    return state.gate_state(gate)


def _is_live(state: HDGraphState, key: str, is_track: bool) -> bool:
    """Whether a lit trace also carries the travelling pulse: the circuit is closed."""
    if is_track:
        return any(state.channel_defined(k) for k in G.channels_on_track(key))
    return state.channel_defined(key)


def _focused(state: HDGraphState, key: str, is_track: bool) -> bool:
    if not state.focusing:
        return True
    if is_track:
        return key in state.focus_tracks
    return key in state.focus_channels


#: The mockup's four drifting blobs, as (diameter, centre-x, centre-y, rgba) in
#: fractions of the graph box. They are ambient, not data: warm light so the dark ground
#: is a room rather than a void. Kept to the mockup's own numbers.
_AURORA = (
    (0.48, 0.30, 0.26, (251, 247, 173, 0.42)),
    (0.54, 0.73, 0.53, (208, 74, 74, 0.44)),
    (0.46, 0.43, 0.77, (180, 138, 120, 0.40)),
    (0.38, 0.49, 0.35, (102, 154, 141, 0.38)),
)


#: Blob radius as a fraction of the graph box. The mockup states a DIAMETER as a
#: percentage of its stage and then blurs it by 78 px, which spreads the light roughly
#: half again; 0.72 (rather than a plain 0.5) is that spread expressed as radius.
_AURORA_SPREAD = 0.72


def paint_ground(painter: QPainter, state: HDGraphState) -> None:
    """The ambient behind everything: four soft blobs, then a veil over the body.

    Drawn in Screen so the blobs add light instead of muddying each other, exactly as
    the mockup's ``mix-blend-mode: screen``. In a light theme they darken instead, which
    is what the mockup switches to Multiply for.
    """
    box = VIEWBOX
    light = bool(state.palette.get("is_light"))
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply if light
                               else QPainter.CompositionMode.CompositionMode_Screen)
    strength = 0.26 if light else 0.5
    for diameter, fx, fy, (r, g, b, alpha) in _AURORA:
        # The mockup's blobs are a 78 px Gaussian blur over a circle, so their light
        # reaches well past the circle's own edge. A gradient that hits zero at the
        # mockup's 68% stop is the un-blurred version of the same shape and reads as a
        # patch; the falloff is carried out to the full radius instead, and the blobs are
        # widened to cover the graph the way the blurred originals do.
        radius = diameter * box.width() * _AURORA_SPREAD
        cx = box.left() + fx * box.width()
        cy = box.top() + fy * box.height()
        gradient = QRadialGradient(cx, cy, radius)
        gradient.setColorAt(0.0, QColor(r, g, b, round(255 * alpha * strength)))
        gradient.setColorAt(0.45, QColor(r, g, b, round(255 * alpha * strength * 0.55)))
        gradient.setColorAt(0.78, QColor(r, g, b, round(255 * alpha * strength * 0.16)))
        gradient.setColorAt(1.0, QColor(r, g, b, 0))
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
    painter.restore()

    # The body veil: one wide gradient centred on the graph, so the figure sits in a
    # pool of light rather than being evenly lit corner to corner.
    #
    # Drawn as an ELLIPSE, not a rect. As a rect its corners carried the gradient right
    # up to the viewbox edge and stopped dead there, which is what made the whole graph
    # read as a lit rectangle pasted onto the page -- "a kid drawing in the middle".
    # A radial gradient inside an ellipse of the same radius reaches zero alpha before
    # its own edge, so there is no boundary to see.
    radius = box.width() * 0.78
    veil = QRadialGradient(box.center(), radius)
    veil.setColorAt(0.0, QColor(251, 247, 173, round(255 * 0.10)))
    veil.setColorAt(0.55, QColor(180, 138, 120, round(255 * 0.05)))
    veil.setColorAt(1.0, QColor(102, 154, 141, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(veil))
    painter.drawEllipse(box.center(), radius, radius)


def paint_auras(painter: QPainter, state: HDGraphState) -> None:
    """A soft halo behind each centre, brighter where the centre is defined.

    The halo is drawn in the centre's LIFTED twin, not its base hue, so a brown Throat
    still glows against a dark ground instead of turning into a smudge.
    """
    palette = state.palette
    breath = 0.965 + 0.07 * (0.5 - 0.5 * math.cos(2 * math.pi * state.phase))
    for centre in G.CENTERS:
        defined = state.centre_defined(centre)
        highlighted = centre in state.focus_centres
        if not defined and not highlighted:
            opacity = 0.07                       # a ghost, so an open centre still sits in space
        else:
            opacity = 0.9
        if state.focusing and not highlighted:
            opacity = state.dim["aura"]
        if opacity <= 0:
            continue

        scale = breath
        if highlighted:
            # hovered: the halo lifts and swells rather than merely brightening
            scale = 1.14 + 0.16 * (0.5 - 0.5 * math.cos(2 * math.pi * state.phase))
            opacity = 1.0

        cx, cy = _centroid(centre)
        radius = _aura_radius(centre) * scale
        edge = QColor(palette[f"edge_{centre}"])
        gradient = QRadialGradient(cx, cy, radius)
        for stop, alpha in ((0.0, 0.55), (0.40, 0.22), (0.72, 0.07), (1.0, 0.0)):
            gradient.setColorAt(stop, _alpha(edge, alpha * opacity))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QPointF(cx, cy), radius, radius)


def paint_network(painter: QPainter, state: HDGraphState) -> None:
    """Glow, dead copper and lit cores -- in that order, each as ONE global layer.

    Layering globally rather than per channel is what removes the need for a junction
    ribbon: there is no per-channel casing to union, so two lit stems meeting at a
    junction are simply the same bright colour, and no channel's dim copper can cut
    across another's lit core where they cross.
    """
    palette = state.palette
    traces = _trace_segments(state)
    glow_alpha = palette["glow_alpha"]

    # QPainter.drawPath FILLS with whatever brush is current, and an open channel path
    # encloses a large lens-shaped area. Leaving a brush set from an earlier layer
    # floods the graph with it -- which is exactly what happened once the gate numerals
    # started leaving their ink brush behind. Stroke-only layers say so explicitly.
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # 1. glow, beneath everything: two wide translucent passes rather than a blur
    #    effect, which would cost a full-scene render per trace.
    for path, gate, key, is_track in traces:
        lit = _is_lit(state, key, gate, is_track)
        if lit == "none":
            continue
        factor = 1.0 if _focused(state, key, is_track) else state.dim["trace"]
        base = _colour("design" if lit == "both" else lit, palette)
        for width, alpha in ((8.0, 0.30), (5.2, 0.34)):
            pen = QPen(_alpha(base, alpha * glow_alpha * factor), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)

    # 2. the dead layer: every trace, always drawn, thin copper
    copper = QColor(palette["dead_trace"])
    for path, gate, key, is_track in traces:
        factor = DEAD_OPACITY
        if state.focusing:
            factor = 1.0 if _focused(state, key, is_track) else state.dim["dead"]
        pen = QPen(_alpha(copper, factor), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

    # 3. the lit cores, and the Personality stripe over a "both" trace
    for path, gate, key, is_track in traces:
        lit = _is_lit(state, key, gate, is_track)
        if lit == "none":
            continue
        factor = 1.0 if _focused(state, key, is_track) else state.dim["trace"]
        core = _colour("design" if lit == "both" else lit, palette)
        pen = QPen(_alpha(core, factor), 3.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)

        if lit == "both":
            stripe = QPen(_alpha(QColor(palette["personality"]), factor), 3.2)
            stripe.setCapStyle(Qt.PenCapStyle.FlatCap)
            stripe.setDashPattern([STRIPE_DASH[0] / 3.2, STRIPE_DASH[1] / 3.2])
            painter.setPen(stripe)
            painter.drawPath(path)


def paint_pulse(painter: QPainter, state: HDGraphState) -> None:
    """A short bright dash travelling along every lit trace.

    One shared phase drives all of them, so the whole graph pulses together and the view
    needs a single timer rather than one per channel. Skipped entirely under Calm or
    reduced motion -- the caller simply does not call this.
    """
    palette = state.palette
    painter.setBrush(Qt.BrushStyle.NoBrush)          # stroke only; see paint_network
    for path, gate, key, is_track in _trace_segments(state):
        lit = _is_lit(state, key, gate, is_track)
        if lit == "none" or not _is_live(state, key, is_track):
            continue
        factor = 1.0 if _focused(state, key, is_track) else state.dim["trace"]
        colour = QColor(palette[{"personality": "pulse_personality",
                                 "design": "pulse_design",
                                 "both": "pulse_both"}[lit]])
        pen = QPen(_alpha(colour, (0.85 if lit == "both" else 0.92) * factor), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setDashPattern([PULSE_DASH[0] / 1.6, PULSE_DASH[1] / 1.6])
        # dashOffset is in pen widths; one full period walks the whole dash cycle
        pen.setDashOffset(-state.phase * (PULSE_DASH[0] + PULSE_DASH[1]) / 1.6)
        painter.setPen(pen)
        painter.drawPath(path)


def paint_centres(painter: QPainter, state: HDGraphState) -> None:
    """The nine centres. A defined one wears its Human Design hue; an open one is near
    white with a clear outline.

    The fill is a gentle radial lift toward the centre rather than a flat colour, so the
    shape reads as lit from inside without turning into a spotlight. The identity is
    always the base hue: only the middle lifts.
    """
    palette = state.palette
    for centre in G.CENTERS:
        defined = state.centre_defined(centre)
        highlighted = centre in state.focus_centres
        opacity = 1.0
        if state.focusing and not highlighted:
            opacity = state.dim["centre"]

        path = centre_path(centre)
        cx, cy = _centroid(centre)
        rect = path.boundingRect()
        edge = QColor(palette[f"edge_{centre}"])

        if defined:
            hue = QColor(palette[f"fill_{centre}"])
            lift = QColor(palette[f"hover_{centre}"])
            gradient = QRadialGradient(cx, rect.top() + rect.height() * 0.44,
                                       max(rect.width(), rect.height()) * 0.70)
            gradient.setColorAt(0.0, _alpha(lift, opacity))
            gradient.setColorAt(0.38, _alpha(hue, opacity))
            gradient.setColorAt(1.0, _alpha(hue, opacity))
            painter.setBrush(QBrush(gradient))
        else:
            fill = _open_fill(palette, highlighted)
            painter.setBrush(QBrush(_alpha(fill, opacity)))
            edge = QColor(palette["open_edge"])

        pen = QPen(_alpha(edge, opacity), 3.4 if highlighted else 1.7)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)


def qcolor(raw: str) -> QColor:
    """A palette token as a QColor. Two of them are stated as ``rgba(r,g,b,a)``.

    QColor parses ``#RRGGBB`` but not CSS ``rgba()`` with a fractional alpha, and silently
    yields an INVALID (black, opaque) colour rather than raising -- which would paint a
    translucent open centre as a solid black one.
    """
    if raw.startswith("rgba"):
        parts = raw[raw.index("(") + 1:raw.index(")")].split(",")
        colour = QColor(int(parts[0]), int(parts[1]), int(parts[2]))
        colour.setAlphaF(float(parts[3]))
        return colour
    return QColor(raw)


def _open_fill(palette: dict, highlighted: bool) -> QColor:
    """An undefined centre's fill. The dark theme states it as rgba(); light is opaque."""
    return qcolor(palette["open_fill_hover" if highlighted else "open_fill"])


def paint_terminals(painter: QPainter, state: HDGraphState) -> None:
    """Ringed pads on the 64 gate seats, vias at the 30 ordinary midpoints, and the
    braid's two junctions.

    The braid channels get no via of their own: their midpoints ARE the junctions.
    """
    palette = state.palette
    plate = QColor(palette["plate"])
    copper = QColor(palette["dead_trace"])

    for key in G.CHANNEL_KEYS:
        if G.is_braid(key):
            continue
        lit = state.channel_defined(key)
        gate_state = state.gate_state(G.CHANNEL_ENDS[key][0]) if lit else "none"
        focused = _focused(state, key, False)
        factor = 1.0 if focused else state.dim["terminal"]
        stroke = _colour(gate_state, palette) if lit else copper
        if focused and state.focusing:
            # the mockup's .via.hl: a focused terminal is ringed in INK, not in its own
            # colour, so the circuit under the pointer reads as picked out rather than
            # merely undimmed
            stroke, width = QColor(palette["ink"]), 1.9
        else:
            width = 1.6 if lit else 1.3
        painter.setBrush(QBrush(_alpha(plate, factor)))
        painter.setPen(QPen(_alpha(stroke, factor), width))
        painter.drawEllipse(QPointF(*G.via_point(key)), VIA_RADIUS, VIA_RADIUS)

    for gate in G.GATES:
        gate_state = state.gate_state(gate)
        focused = (not state.focusing) or gate in state.focus_gates
        factor = 1.0 if focused else state.dim["terminal"]
        if gate_state == "none":
            stroke, fill = copper, plate
        else:
            stroke = _colour("personality" if gate_state in ("personality", "both")
                             else "design", palette)
            tint = _colour("design" if gate_state in ("design", "both")
                           else "personality", palette)
            fill = _mix(tint, plate, 0.30 if gate_state == "both" else 0.22)
        width = 1.3
        if focused and state.focusing:
            stroke, width = QColor(palette["ink"]), 1.9
        painter.setBrush(QBrush(_alpha(fill, factor)))
        painter.setPen(QPen(_alpha(stroke, factor), width))
        painter.drawEllipse(QPointF(*G.gate_anchor(gate)), PAD_RADIUS, PAD_RADIUS)

    # BOTH junctions follow the TRUNK, and a live one is stroked in the Design colour
    # whichever set actually lit it. That is mockup 27's own rule, verbatim:
    #
    #     $$(".junc").forEach(n => n.classList.toggle("on", trackState("trunk") !== "off"))
    #     .junc.on circle { stroke: var(--rail-d) }
    #
    # It is arguably wrong on two counts -- a defined 10-20 merge terminates at junction A
    # without using the trunk, so A stays dead; and a Personality-only integration channel
    # still paints both rings amber. Both are visible on real charts. It is NOT changed
    # here: this port is pixel-faithful to the approved design and has spent its one
    # allowed deviation on the 33/45 numerals. Raised with session 50 as a design
    # question rather than fixed as a port bug.
    for name, point in G.INTEG_JUNCTION.items():
        live = _track_state(state, "trunk") != "none"
        focused = (not state.focusing) or bool(state.focus_tracks)
        factor = 1.0 if focused else state.dim["junction"]
        stroke = QColor(palette["design"]) if live else copper
        painter.setBrush(QBrush(_alpha(plate, factor)))
        painter.setPen(QPen(_alpha(stroke, factor), 1.6 if live else 1.3))
        painter.drawEllipse(QPointF(*point), JUNCTION_RADIUS, JUNCTION_RADIUS)
        # the letter beside each junction: the reading card and the braid hint both
        # name them "A" and "B", so the graph has to say which is which
        letter = QFont(painter.font())
        letter.setPixelSize(8)
        letter.setBold(True)
        _draw_haloed_text(painter, QPointF(point[0] - 10.0, point[1]), name, letter,
                          _alpha(QColor(palette["ink3"]), factor),
                          _alpha(QColor(qcolor(palette["halo"])), factor),
                          halo_width=1.6)


def _mix(colour: QColor, into: QColor, amount: float) -> QColor:
    return QColor(
        round(into.red() + (colour.red() - into.red()) * amount),
        round(into.green() + (colour.green() - into.green()) * amount),
        round(into.blue() + (colour.blue() - into.blue()) * amount),
    )


#: U+4DC0 is hexagram 1. The gates are NOT in hexagram order, so the glyph for a gate is
#: found by its King Wen number, which is exactly what the gate number is.
HEXAGRAM_BASE = 0x4DC0


def gate_glyph(gate: int, label_mode: str) -> str:
    if label_mode == "hexagrams":
        return chr(HEXAGRAM_BASE + gate - 1)
    return str(gate)


def _draw_haloed_text(painter: QPainter, centre: QPointF, text: str, font: QFont,
                      ink: QColor, halo: QColor, halo_width: float) -> None:
    """Draw a glyph with a halo BEHIND it, the way SVG's ``paint-order: stroke`` does.

    A numeral sits straight on a centre fill with traces and vias passing under it, so
    without the halo it breaks up wherever something crosses. Painting the outline first
    and the fill over it keeps the glyph's own weight: stroking on top would thin it.
    """
    path = QPainterPath()
    path.addText(0, 0, font, text)
    box = path.boundingRect()
    path.translate(centre.x() - box.center().x(), centre.y() - box.center().y())

    if halo.alpha() > 0 and halo_width > 0:
        pen = QPen(halo, halo_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(ink))
    painter.drawPath(path)


def paint_gates(painter: QPainter, state: HDGraphState,
                plain_font: QFont, disc_font: QFont) -> None:
    """The 64 numerals, each inside its own centre on the correct face.

    An activated gate gets a filled disc ringed in its activation colour, with white ink.
    An unlit gate sits straight on the centre fill, so its ink follows THAT fill rather
    than the theme: dark on the two yellow centres, light on green, brown and red, theme
    ink on an open one. Getting this wrong is not subtle -- light-grey numerals on the
    pale yellow G are unreadable.

    Never a disc on the channel. The discs out on the traces are vias, and they mean
    something else entirely.
    """
    palette = state.palette

    for gate in G.GATES:
        gate_state = state.gate_state(gate)
        focused = (not state.focusing) or gate in state.focus_gates
        factor = 1.0 if focused else state.dim["gate"]
        x, y = G.gate_label(gate)
        point = QPointF(x, y)
        text = gate_glyph(gate, state.label_mode)

        if gate_state == "none":
            centre = G.centre_of_gate(gate)
            if not state.centre_defined(centre):
                ink, halo = QColor(palette["ink"]), qcolor(palette["halo"])
            elif palette[f"fill_{centre}"] == palette["yellow"]:
                ink, halo = QColor(palette["gate_ink_yellow"]), qcolor(palette["gate_halo_yellow"])
            else:
                ink, halo = QColor(palette["gate_ink_solid"]), qcolor(palette["gate_halo_solid"])
            _draw_haloed_text(painter, point, text, plain_font,
                              _alpha(ink, factor), _alpha(halo, factor), 1.9)
            continue

        ring = _colour("personality" if gate_state in ("personality", "both")
                       else "design", palette)
        glow = QRadialGradient(point, DISC_GLOW_RADIUS)
        glow.setColorAt(0.0, _alpha(ring, 0.24 * factor))
        glow.setColorAt(1.0, _alpha(ring, 0.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        painter.drawEllipse(point, DISC_GLOW_RADIUS, DISC_GLOW_RADIUS)

        painter.setBrush(QBrush(_alpha(QColor(palette["disc"]), factor)))
        painter.setPen(QPen(_alpha(ring, factor), 1.5))
        painter.drawEllipse(point, DISC_RADIUS, DISC_RADIUS)

        if gate_state == "both":
            # the ring is drawn in Personality; half of it is redrawn in Design, so a
            # gate carried by both sides says so at numeral size
            painter.setPen(QPen(_alpha(_colour("design", palette), factor), 1.5))
            painter.drawArc(QRectF(x - DISC_RADIUS, y - DISC_RADIUS,
                                   DISC_RADIUS * 2, DISC_RADIUS * 2),
                            90 * 16, 180 * 16)

        _draw_haloed_text(painter, point, text, disc_font,
                          _alpha(QColor(palette["disc_ink"]), factor),
                          _alpha(QColor(palette["disc"]), factor), 1.7)
