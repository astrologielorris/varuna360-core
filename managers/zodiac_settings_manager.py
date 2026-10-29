"""Apply zodiac settings through one runtime boundary, in Core and Pro.

Settings notifications are coalesced so an Apply/Reset cannot render a mixture
of old and new fields. Runtime controls respect write-back locks; Settings
commands deliberately replace the pinned value. Dasha calculation stays owned
by DashaManager and has a separate notification channel.
"""
import weakref

from PySide6.QtCore import QObject, QTimer, Signal

from core.settings_registry import default as _registry_default
from managers.settings_manager import get_settings
from state.events import SetHouseSystem, SetZodiacMode


class ZodiacSettingsManager(QObject):
    frame_changed = Signal(object)
    dasha_changed = Signal(object)

    # SPEC-SET-003 W3e: the factory values come from the settings registry (the
    # retyped literals said dasha.zr.show_age True against the registry's False).
    DEFAULTS = {key: _registry_default(key) for key in (
        "zodiac.mode", "zodiac.ayanamsa_id", "zodiac.house_system",
        "zodiac.use_western_names", "zodiac.sign_language", "zodiac.nakshatra_coords",
        "dasha.zr.releaser", "dasha.zr.spirit_shift", "dasha.zr.show_age",
        "dasha.zr.anchor")}
    FRAME_KEYS = frozenset(("zodiac.mode", "zodiac.ayanamsa_id", "zodiac.house_system"))

    def __init__(self, gui):
        super().__init__(gui)
        self.gui = gui
        self._pending = set()
        self._writing = False
        self._ready = False
        self._extra_values = {k: get_settings().get(k, v) for k, v in self.DEFAULTS.items()
                              if k.startswith("dasha.zr.")}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.apply_settings)
        ref = weakref.ref(self)
        settings = get_settings()
        for key in self.DEFAULTS:
            def changed(_key, _value, leaf=key, ref=ref):
                obj = ref()
                if obj is not None and not obj._writing:
                    obj._pending.add(leaf)
                    if obj._ready:
                        obj._timer.start(0)
            settings.on_changed(key, changed)
            self.destroyed.connect(
                lambda *_args, key=key, cb=changed, s=settings: s.remove_on_changed(key, cb))
        # The custom ayanamsa (id 255) is engine state: install it now and on every edit.
        from core import custom_ayanamsa_settings as _custom
        from libaditya.custom_ayanamsa import get_custom_ayanamsa
        _custom.install_from(settings)
        self._custom_drawn = get_custom_ayanamsa()   # the definition on screen
        self._custom_timer = QTimer(self)            # one redraw for the three keys
        self._custom_timer.setSingleShot(True)
        self._custom_timer.timeout.connect(self._on_custom_ayanamsa_changed)

        def custom_changed(_key, _value, ref=ref):
            obj = ref()
            if obj is not None:
                obj._custom_timer.start(0)
        for key in _custom.KEYS:
            settings.on_changed(key, custom_changed)
            self.destroyed.connect(
                lambda *_args, key=key, cb=custom_changed, s=settings: s.remove_on_changed(key, cb))

    def _on_custom_ayanamsa_changed(self):
        """Redraw whatever uses id 255 once its definition really changed."""
        from core import custom_ayanamsa_settings as _custom
        from libaditya.custom_ayanamsa import CUSTOM_AYANAMSA_ID, get_custom_ayanamsa
        _custom.install_from(get_settings())
        if get_custom_ayanamsa() == self._custom_drawn:
            return
        self._custom_drawn = get_custom_ayanamsa()
        g = self.gui
        if (g.chart_sidereal_ayanamsa_id == CUSTOM_AYANAMSA_ID
                and g.state.aditya_mode == "sidereal" and g.state.active_chart is not None):
            g._recalculate_chart()
        dm = getattr(g, "dasha_manager", None)
        if dm is not None and CUSTOM_AYANAMSA_ID in (dm.ayanamsa("left"), dm.ayanamsa("right")):
            dm.update_all_sides()
        g._update_title()
        self.frame_changed.emit(frozenset({"zodiac.ayanamsa_id"}))

    def start(self):
        self._ready = True
        if self._pending:
            self._timer.start(0)
        # The tools calculate in the frame on screen (AIC plan 2): publish it.
        # Owned here, the manager of the zodiac frame (Rule 4b: not on ChartGUI).
        from managers.live_frame_manager import LiveFrameManager
        self.live_frame = LiveFrameManager(self.gui)
        self.live_frame.start()
        # The Core app endpoint (SPEC-SET-003 §4.5b), in the live frame's folder
        # so its discovery order follows the live frame's activation order.
        from core.app_endpoint.server import AppEndpointServer
        self.app_endpoint = AppEndpointServer.start_in(self.gui, self.live_frame.diagnostics()["folder"])
        # Its AI ops, owned here, Pro and up (SPEC-EDN-002 P4): set_app_setting,
        # the request service (§4.5b, W6b), and the desktop MCP server's two
        # ops (SPEC-LMCP-001 §4.4). Lite answers neither.
        from core.edition_features import ai_features
        features = ai_features()
        self.app_requests, self.mcp_link = (
            features.install_endpoint_services(self.gui, self.app_endpoint)
            if features is not None else (None, None))

    def apply_settings(self, keys=()):
        """Flush a Settings transaction. Unrelated locked runtime choices survive."""
        self._timer.stop()
        keys = self._pending | set(keys)
        self._pending.clear()
        s = get_settings()
        values = {k: s.get(k, self.DEFAULTS[k]) for k in keys if k in self.DEFAULTS}
        self._apply(values)

    def set_mode(self, mode, *, toggle_names=False):
        if mode not in ("aditya", "tropical_classic", "sidereal"):
            raise ValueError(f"Unknown zodiac mode: {mode!r}")
        g = self.gui
        if mode == g.state.aditya_mode:
            if toggle_names and not g._is_beginner_mode():
                self._apply({"zodiac.use_western_names": not g.use_western_names}, runtime=True)
            return
        self._apply({"zodiac.mode": mode, "zodiac.use_western_names": mode != "aditya"}, runtime=True)

    def set_runtime(self, key, value):
        self._apply({key: value}, runtime=True)

    def _apply(self, values, *, runtime=False):
        if not values:
            return
        g = self.gui
        mode = values.get("zodiac.mode", g.state.aditya_mode)
        if mode not in ("aditya", "tropical_classic", "sidereal"):
            raise ValueError(f"Unknown zodiac mode: {mode!r}")
        old = {
            "zodiac.mode": g.state.aditya_mode,
            "zodiac.ayanamsa_id": g.chart_sidereal_ayanamsa_id,
            "zodiac.house_system": g.state.house_system,
            "zodiac.use_western_names": g.use_western_names,
            "zodiac.sign_language": g.sign_language,
            "zodiac.nakshatra_coords": g.nakshatra_coords,
        }
        if "zodiac.mode" in values or "zodiac.use_western_names" in values:
            if g._is_beginner_mode():
                values["zodiac.use_western_names"] = mode != "aditya"
        old.update(self._extra_values)
        changed = {k for k, v in values.items() if k not in old or old[k] != v}
        self._extra_values.update({k: v for k, v in values.items() if k.startswith("dasha.zr.")})
        # Adopt the whole frame before any callbacks or chart construction.
        with g.state.batching():
            if "zodiac.ayanamsa_id" in values:
                g.chart_sidereal_ayanamsa_id = values["zodiac.ayanamsa_id"]
            if "zodiac.mode" in values:
                g.chart_zodiac = "sidereal" if mode == "sidereal" else "tropical"
                g.state.dispatch(SetZodiacMode(mode=mode))
            if "zodiac.house_system" in changed:
                g.state.dispatch(SetHouseSystem(house_system=values["zodiac.house_system"]))
            if "zodiac.use_western_names" in values:
                g.use_western_names = values["zodiac.use_western_names"]
            if "zodiac.sign_language" in values:
                g.sign_language = values["zodiac.sign_language"]
            if "zodiac.nakshatra_coords" in values:
                g.nakshatra_coords = values["zodiac.nakshatra_coords"]
            if runtime:
                self._writing = True
                try:
                    for k, v in values.items():
                        get_settings().persist_runtime_change(k, v)
                        self._pending.discard(k)
                finally:
                    self._writing = False
            frame = changed & self.FRAME_KEYS
            rebuild = bool(frame - {"zodiac.ayanamsa_id"}) or (
                "zodiac.ayanamsa_id" in frame and mode == "sidereal")
            if rebuild and g.state.active_chart is not None:
                g._recalculate_chart()
            elif "zodiac.use_western_names" in changed:
                g._apply_current_varga()
        if frame:
            g._update_toggle_button_styles()
            g._sync_dual_rim_button_text()
            # Refresh the title pill: its ayanamsha token can change on a
            # frame/ayanamsa change even when no chart rebuild fires (e.g. a
            # zodiac.ayanamsa_id change in Aditya/Tropical mode, which the
            # Nakshatra-view pill still reflects) (td-bu8s BUG4).
            g._update_title()
            # Compatibility signal retained for existing predictive consumers.
            # Ayanamsa also feeds nakshatras in non-Sidereal display modes.
            g.aditya_mode_changed.emit(mode)
            self.frame_changed.emit(frozenset(frame))
        names = changed & {"zodiac.use_western_names", "zodiac.sign_language"}
        if names:
            for attr in ("chart_view", "wheel_view", "north_indian_view"):
                view = getattr(g, attr, None)
                if view is not None:
                    view.sign_language = g.sign_language
            if g.state.active_chart is not None:
                g._apply_current_varga()
            g._update_toggle_button_styles()
            # Sign labels in the sign dashas follow the names (both sides).
            g.dasha_manager.on_view_input_changed("view.sign_names")
            g.sign_names_changed.emit(mode)
        if "zodiac.nakshatra_coords" in changed:
            g.dasha_manager.update_all_sides()
            self.dasha_changed.emit(frozenset({"zodiac.nakshatra_coords"}))
        # dasha.zr.* leaf owner (SPEC-DSH-004 §4.5): every side whose mode
        # reads a changed leaf, once, from that mode's entry state.
        zr_changed = {k for k in changed if k.startswith("dasha.zr.")}
        if zr_changed:
            g.dasha_manager.relist_sides_reading(zr_changed, reset=True)
        if changed:
            g._update_title()
            g.statusBar().showMessage("Zodiac settings applied")
            self.publish_live()

    def notify_dasha(self, key):
        if key == "dasha.left.ayanamsa_id":
            self.gui._update_title()
        self.dasha_changed.emit(frozenset({key}))
        self.publish_live()

    def publish_live(self):
        """Hand a frame change to the tools at once (writes only on change)."""
        live = getattr(self, "live_frame", None)
        if live is not None:
            live.publish()
