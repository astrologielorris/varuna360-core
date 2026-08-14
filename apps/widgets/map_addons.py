# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Map add-ons: the extension surface hosts ADD to the shared map component.

SPEC-MAP-004 §4.3/§4.4. The unifying rule of the whole refactor is that a host
panel only ever ADDS to `EditMapSubTab`; it never subtracts and never reaches
into the component's internals. An add-on is that "add": a small object the
subtab owns, cascades theme and selection deliveries to, and tears down.

`MapAddon` is the protocol every add-on satisfies. `ApplyBarAddon` is the first
one, carved out of the subtab's own inline apply-bar so the "Apply & Return"
chrome becomes a licensed extension rather than a `show_apply_bar` boolean that
subtracts by default. In this wave (W3b) the SUBTAB attaches it from its own
flag branch — exactly one bar everywhere, by construction — and the flag is not
deleted until W3c, where Edit Chart attaches the add-on explicitly instead.
"""

from typing import Protocol, runtime_checkable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton


@runtime_checkable
class MapAddon(Protocol):
    """What the subtab requires of every add-on (SPEC-MAP-004 §4.3).

    Four methods, mirroring the four moments the subtab owns an add-on for:
    build, a routed selection arrives, the theme changes, teardown.
    """

    def attach(self, subtab, parent_layout) -> None:
        """Build UI into `parent_layout` and wire to `subtab`. Called once."""
        ...

    def on_selection(self, routed) -> None:
        """A `RoutedSelection` was delivered. Fan-out from `selection_routed`."""
        ...

    def refresh_theme(self) -> None:
        """Re-apply colours under the current palette (live theme switch)."""
        ...

    def detach(self) -> None:
        """Tear down. Called from the subtab's `shutdown()`."""
        ...


class ApplyBarAddon:
    """The bottom "✓ Apply & Return to Edit Info" bar, as an add-on.

    Owns the frame, the status label and the button, plus their theming — the
    widgets are NOT registered in the subtab's `_register_themed` registry, so
    the subtab's replay does not touch them and this add-on's `refresh_theme`
    is the ONLY thing that re-styles them. That is deliberate: it makes the
    subtab's add-on theme cascade load-bearing (remove the cascade loop and
    these three widgets go stale on a switch — the T-8 mutation).

    The button's click routes to the subtab's existing
    `_apply_location_and_return`, and the subtab keeps driving the label text and
    the enabled state through the back-references set in `attach` — because the
    programmatic `set_marker` path (chart restore, Edit-Info coordinate typing)
    is a real selection that deliberately does NOT emit `selection_routed`, so a
    fan-out-only driver would leave the bar dead on exactly that path.
    """

    def __init__(self):
        self._subtab = None
        self._parent_layout = None
        self.frame = None
        self.status = None
        self.button = None

    def attach(self, subtab, parent_layout) -> None:
        self._subtab = subtab
        self._parent_layout = parent_layout

        self.frame = QFrame()
        bar_layout = QHBoxLayout(self.frame)
        bar_layout.setContentsMargins(12, 8, 12, 8)

        self.status = QLabel("Click on the map to select a location")
        bar_layout.addWidget(self.status)
        bar_layout.addStretch()

        self.button = QPushButton("✓ Apply && Return to Edit Info")
        self.button.setToolTip("Apply selected location and return to Edit Info tab")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setEnabled(False)  # until a location is selected
        self.button.clicked.connect(subtab._apply_location_and_return)
        bar_layout.addWidget(self.button)

        parent_layout.addWidget(self.frame)

        # Back-references: the subtab's selection code (`_show_selection`, the
        # marker path) reads `apply_btn`/`selection_status` by name and is
        # guarded by `hasattr`. Exposing the add-on's widgets under those names
        # keeps every existing selection surface working without the subtab
        # knowing an add-on now owns them. Removed in `detach`.
        subtab.apply_btn = self.button
        subtab.selection_status = self.status
        subtab.apply_bar_frame = self.frame

        self.refresh_theme()

    def on_selection(self, routed) -> None:
        # A delivered selection means the user has a point to apply. Idempotent
        # with the subtab's inline enable; harmless if it already ran.
        if self.button is not None and routed is not None:
            self.button.setEnabled(True)

    def refresh_theme(self) -> None:
        if self._subtab is None:
            return
        # Style logic stays on the subtab (DRY, and it re-reads the palette on
        # every call per the ThemedStyleMixin contract); ownership of WHEN it is
        # applied is the add-on's.
        if self.frame is not None:
            self.frame.setStyleSheet(self._subtab._apply_bar_frame_style())
        if self.status is not None:
            self.status.setStyleSheet(self._subtab._selection_status_style())
        if self.button is not None:
            self.button.setStyleSheet(self._subtab._apply_btn_style())

    def detach(self) -> None:
        subtab = self._subtab
        if subtab is not None:
            for name in ("apply_btn", "selection_status", "apply_bar_frame"):
                if getattr(subtab, name, None) in (self.button, self.status,
                                                   self.frame):
                    try:
                        delattr(subtab, name)
                    except AttributeError:
                        pass
        if self.frame is not None:
            try:
                self.frame.setParent(None)
                self.frame.deleteLater()
            except RuntimeError:
                pass
        self.frame = self.status = self.button = None
        self._subtab = self._parent_layout = None


class AscendantAddon:
    """The map's Ascendant preview layer, as an opt-in add-on (SPEC-MAP-004 W4).

    Only Edit Chart wants it: it is the sole host that edits a birth instant,
    which is what makes an Ascendant computable at all (SPEC-MAP-002 INV-4). The
    other map hosts (Birth Finder, Eclipse, Lunar New Year) never pushed a time
    basis, so before Wave 4 the controller sat constructed-but-dead in every one
    of them. As an add-on the controller exists ONLY where a host asked for the
    preview, and the subtab constructs nothing Ascendant-shaped on its own.

    Unlike ApplyBarAddon this adds no widget to the layout — the Ascendant draws
    on the map itself (the twelve sign bands) and on the info card (the readout),
    both already subtab-owned. The add-on's whole job is LIFECYCLE: build the
    QObject controller from the subtab's map widget + card, publish it as
    `subtab.asc_controller` so the subtab's existing hover/selection code (every
    reference None-guarded) drives it, and shut it down on detach.

    A wrapper rather than making `MapAscendantController` itself satisfy
    `MapAddon`, because the controller needs `(map_widget, card)` at
    construction and those exist only at attach() time — a no-arg `MapAddon()`
    the host constructs before handing to `add_addon` cannot carry them.
    """

    def __init__(self):
        self._subtab = None
        self.controller = None

    def attach(self, subtab, parent_layout) -> None:
        self._subtab = subtab
        # No inner map means no preview surface (bands draw on the tile widget,
        # the readout needs the card): leave `asc_controller` None so a
        # tile-less fallback host does not construct a controller around widgets
        # that are not there. The subtab's guards already no-op on None.
        if not getattr(subtab, "has_map", False) or subtab.map_widget is None:
            return
        # Attach-once hardening (review finding): if a controller already exists
        # — a duplicate add-on, or a re-attach — shut it down before replacing
        # it, or its live band scan would keep running untracked until some
        # later detach (which happens AFTER map teardown).
        existing = getattr(subtab, "asc_controller", None)
        if existing is not None:
            try:
                existing.shutdown()
            except Exception:
                pass
        from apps.widgets.map_ascendant_controller import MapAscendantController
        self.controller = MapAscendantController(
            subtab.map_widget, subtab.info_card, parent=subtab)
        subtab.asc_controller = self.controller

        # Replay any state the host pushed BEFORE this add-on attached, so late
        # attachment is not state-lossy (review finding). set_time_basis retains
        # its last args on the subtab even when no controller existed; a marker
        # already placed lives in current_lat/current_lon. Edit Chart attaches
        # first, so both are no-ops there — this keeps the late-attach contract
        # the subtab documents actually true.
        pending = getattr(subtab, "_pending_time_basis", None)
        if pending is not None:
            try:
                subtab.set_time_basis(*pending)
            except Exception:
                pass
        lat = getattr(subtab, "current_lat", None)
        lon = getattr(subtab, "current_lon", None)
        if lat is not None and lon is not None:
            try:
                self.controller.request_bands(lat, lon)
            except Exception:
                pass

    def on_selection(self, routed) -> None:
        # No-op by design. The subtab already drives request_bands() on its own
        # click/selection path and apply_readout_to_card() on hover, both
        # through `self.asc_controller`. Re-triggering here would run a second
        # band scan for the one selection.
        pass

    def refresh_theme(self) -> None:
        # No-op: the controller owns no styled widgets. The band colours belong
        # to the map widget and the readout to the info card; each is re-themed
        # by its own refresh, not by the controller.
        pass

    def detach(self) -> None:
        if self.controller is not None:
            try:
                self.controller.shutdown()          # idempotent; safe if the
            except Exception:                        # subtab already shut it
                pass
        subtab = self._subtab
        if subtab is not None and getattr(subtab, "asc_controller", None) \
                is self.controller:
            subtab.asc_controller = None
        self.controller = None
        self._subtab = None
