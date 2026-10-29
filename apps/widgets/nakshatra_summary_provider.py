"""Summary provider for the nakshatra wheel's property outer ring (Core and Lite).

The shared ``NakshatraWheelView`` (apps/widgets) draws the Symbol / Yoni / Gana /
deity / Gunas outer ring through an injected provider exposing this two-method
protocol (SPEC-NAK-LITE-001):

    valid_modes  -> the set of property_mode keys the ring understands
    draw(scene, center, inner, outer, rotation, mode) -> render the ring

Both editions inject it (the Core F2 nakshatra panel and the Pro tab). The
content is the nakshatra descriptions by Ernst Wilhelm and Michael Reed, used
with permission; the credit shows in the info dialog the ring opens.
"""
from core.nakshatra_properties import PROPERTY_OPTIONS
from apps.widgets.nakshatra_summary_layer import draw_summaries


class NakshatraSummaryProvider:
    """Wraps the nakshatra property options + summary renderer."""

    @property
    def valid_modes(self):
        return frozenset(key for key, _label in PROPERTY_OPTIONS)

    def draw(self, scene, center, inner, outer, rotation, mode):
        draw_summaries(scene, center, inner, outer, rotation, mode)
