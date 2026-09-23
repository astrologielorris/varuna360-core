"""Apply zodiac settings through one runtime boundary, in Core and Pro.

Settings notifications are coalesced so an Apply/Reset cannot render a mixture
of old and new fields. Runtime controls respect write-back locks; Settings
commands deliberately replace the pinned value. Dasha calculation stays owned
by DashaManager and has a separate notification channel.
"""
import weakref

from PySide6.QtCore import QObject, QTimer, Signal

from managers.settings_manager import get_settings
from state.events import SetHouseSystem, SetZodiacMode


class ZodiacSettingsManager(QObject):
    frame_changed = Signal(object)
    dasha_changed = Signal(object)

    DEFAULTS = {
        "zodiac.mode": "aditya",
        "zodiac.ayanamsa_id": 100,
        "zodiac.house_system": "campanus",
        "zodiac.use_western_names": False,
        "zodiac.sign_language": "en",
        "zodiac.nakshatra_coords": "neither",
        "dasha.zr.releaser": "spirit",
        "dasha.zr.spirit_shift": True,
        "dasha.zr.show_age": True,
        "dasha.zr.anchor": "birth",
    }
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

    def start(self):
        self._ready = True
        if self._pending:
            self._timer.start(0)

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
            if g.dasha_manager.right_mode == "zr":
                g.dasha_manager.update_right_panel()
            g.sign_names_changed.emit(mode)
        if "zodiac.nakshatra_coords" in changed:
            g.dasha_manager.update_vedanga_dasha()
            g.dasha_manager.update_right_panel()
            self.dasha_changed.emit(frozenset({"zodiac.nakshatra_coords"}))
        if any(k.startswith("dasha.zr.") for k in changed) and g.dasha_manager.right_mode == "zr":
            g.dasha_manager.reset_mode_entry("zr")
            g.dasha_manager.update_right_panel()
        if changed:
            g._update_title()
            g.statusBar().showMessage("Zodiac settings applied")

    def notify_dasha(self, key):
        if key == "dasha.left.ayanamsa_id":
            self.gui._update_title()
        self.dasha_changed.emit(frozenset({key}))
