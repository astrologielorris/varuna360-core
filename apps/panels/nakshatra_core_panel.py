"""Restricted Core/Lite Nakshatra wheel panel (SPEC-NAK-LITE-001).

A thin host for the shared ``NakshatraWheelView`` used as a normal F2 chart
view (cycled with Wheel / South Indian), NOT a Pro tab. It is deliberately
minimal:

- No toolbar / header row. The frame (Aditya Circle / Tropical Classic /
  Sidereal) is driven by the main chart-tab zodiac buttons; the ayanamsa comes
  from Settings (``zodiac.ayanamsa_id``, the single source of truth). The wheel
  redraws on the ``zodiac_settings.frame_changed`` signal (mode OR ayanamsa),
  and NOT on ``dasha.left`` changes — that binding is Pro's alone.
- Sidereal nakshatras by default (the view's native frame).
- Sector click is inert. No teacher-content descriptions, no info dialog, no
  property outer ring: the view is constructed with ``summary_provider=None``.
- Planet click opens the shared Core planet dialog, via the same conversion the
  Pro panel uses (``show_planet_from_nakshatra_click``) so the two never drift.

The Pro edition keeps its own full nakshatra panel with the toolbar, transit,
Danishta and info dialog.
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import QTimer

from apps.widgets.nakshatra_wheel_view import NakshatraWheelView


def show_planet_from_nakshatra_click(gui, wheel_view, name, info):
    """Shared planet-click handler for both nakshatra panels.

    The wheel's click metadata is nakshatra-only; resolve the body's natal (or
    transit) rashi position and hand it to the shared Core planet dialog, then
    redraw the wheel. Single source so Core and Pro cannot diverge here."""
    chart = (wheel_view._transit_chart if info.get("name", "").startswith("T.")
             else wheel_view._chart)
    if chart is None:
        return
    planet = chart.rashi().planets().planets().get(name)
    if planet is None:
        return
    longitude = planet.real_in_sign_longitude()
    gui._show_planet_dialog(name, {
        "sign": planet.sign_name(), "sign_index": planet.sign() - 1,
        "degrees": int(longitude), "minutes": int((longitude % 1) * 60),
        "decimal_degrees": planet.ecliptic_longitude(),
        "retrograde": planet.retrograde(),
    })
    if wheel_view._chart is not None:
        wheel_view.update_from_chart(wheel_view._chart)


class NakshatraCorePanel(QWidget):
    """Restricted nakshatra wheel view for the Core/Lite F2 cycle."""

    def __init__(self, gui, parent=None):
        super().__init__(parent)
        self.gui = gui
        self._initial_fit_pending = True

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Core binding: ayanamsa from zodiac.ayanamsa_id (mirrored on the gui as
        # chart_sidereal_ayanamsa_id), NO teacher-content summary provider.
        self.wheel_view = NakshatraWheelView(
            gui=gui,
            ayanamsa_source=lambda: getattr(gui, "chart_sidereal_ayanamsa_id", 100),
            summary_provider=None,
        )
        # Planet click -> shared Core planet dialog. Sector click stays inert:
        # nakshatra_click_signal is intentionally NOT connected in Core.
        self.wheel_view.planet_click_signal.clicked.connect(self._on_planet_clicked)

        # Redraw on any zodiac frame change (mode from the main-tab buttons, or
        # zodiac.ayanamsa_id from Settings). frame_changed does NOT fire for
        # dasha.left, so a dasha ayanamsa change never redraws this view.
        zs = getattr(gui, "zodiac_settings", None)
        if zs is not None:
            zs.frame_changed.connect(self._on_frame_changed)

        layout.addWidget(self.wheel_view)

    # ── Signals ───────────────────────────────────────────────────

    def _on_planet_clicked(self, name, info):
        show_planet_from_nakshatra_click(self.gui, self.wheel_view, name, info)

    def _on_frame_changed(self, _keys):
        """Zodiac mode or ayanamsa changed -> redraw with the new frame."""
        chart = getattr(self.gui.state, "active_chart", None)
        if chart is not None:
            self.wheel_view.update_from_chart(chart)

    # ── Lifecycle (mirrors the other F2 view panels) ──────────────

    def showEvent(self, event):
        super().showEvent(event)
        # The F9 cusp mode is re-seeded by NakshatraWheelView.showEvent (shared
        # by the Core panel and the Pro tab), so the panel no longer seeds it
        # here (td-yi23 finding 2).
        self.update_chart(getattr(self.gui.state, "active_chart", None))
        if self._initial_fit_pending:
            self._initial_fit_pending = False
            QTimer.singleShot(0, self.wheel_view.reset_zoom)

    def fullscreen_target(self):
        """SPEC-FSV-001 universal fullscreen: the wheel fills the screen."""
        return {
            "widget": self.wheel_view,
            "layout": self.layout(),
            "views": lambda: [self.wheel_view],
            "refit": True,
            "cycle": False,
            "refit_signals": [],
            "on_enter": None,
            "on_exit": None,
        }

    def refresh_theme(self):
        self.wheel_view.refresh_theme()

    # ── F9 house-cusp toggle (td-bu8s BUG3) ───────────────────────
    # core_gui_qt._cycle_cusp_glow reads current.cusp_glow_mode and calls
    # current.set_cusp_glow_mode / current.ensure_visible, where `current` is
    # this panel (the chart-stack widget). Forward to the wheel so F9 drives the
    # Nakshatra view exactly like the main Wheel.

    @property
    def cusp_glow_mode(self):
        return self.wheel_view.cusp_glow_mode

    @cusp_glow_mode.setter
    def cusp_glow_mode(self, mode):
        # Symmetric with the wheels, which assign this attribute directly
        # (e.g. render_chart CLI, dual-panel F9 catch-up). Delegate to the
        # normalising setter so a raw assignment can't desync (td-yi23 finding 3).
        self.wheel_view.set_cusp_glow_mode(mode)

    def set_cusp_glow_mode(self, mode):
        self.wheel_view.set_cusp_glow_mode(mode)

    def ensure_visible(self):
        self.wheel_view.ensure_visible()

    def update_from_chart(self, chart, **_kw):
        self.update_chart(chart)

    def update_chart(self, chart_or_data):
        """Update the wheel from a libaditya Chart (or None to clear)."""
        from libaditya.charts.chart import Chart
        if chart_or_data is not None and not isinstance(chart_or_data, Chart):
            raise TypeError(
                "nakshatra_core_panel.update_chart expects a libaditya Chart or "
                f"None, got {type(chart_or_data).__name__}"
            )
        if chart_or_data:
            self.wheel_view.update_from_chart(chart_or_data)
        else:
            self.wheel_view.clear_chart()
