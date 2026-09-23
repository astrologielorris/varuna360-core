"""SPEC-BAR-001 M2 — ActionBarLayoutController: the d0-d5 ladder, applied.

Design: 12_opus_m2_ladder.md (§1.6 apply list, §2.3 arithmetic selection,
§3 hysteresis, §4 overflow menu) + the D-22 rulings. Division of labor:

- ``TierEngine`` (tier_engine.py) DECIDES — pure logic, oscillation-proven.
- This controller MEASURES (required(d) from BarMetrics + the ladder table,
  never from live layout — the mockup's apply-and-measure loop is a
  re-entrancy hazard in Qt, doc §2.2) and APPLIES (the one batch that may
  touch geometry outside construction).

required(d) is a LIVE table (D-22h): it reads app-visibility flags (HD
setting, D-51 wheel-only dual rim), so any flag change rebuilds the table
and force-refits with no hysteresis (D-22e). "Folded by the tier" and
"hidden by the app" are distinct: only tier-folded controls surface in the
overflow menu.

The table-vs-reality equivalence test (T-1, report 01's proof obligation)
holds this file's arithmetic to the real layout's minimumSize at every tier.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QIcon

from ui.themed_style import ThemedStyleMixin

from . import paint_controls
from .bar_types import BarMetrics
from .ladder import (LADDER, META_HIDDEN_FROM, MODSPLIT_GONE_FROM, N_TIERS,
                     OVERFLOW_PAD_PX, OVERFLOW_VISIBLE_FROM,
                     TOGGLES_CLUSTER_GONE_FROM, TRAY_GAP_ZERO_FROM)
from .tier_engine import TierEngine

_HYSTERESIS_PX = 16.0        # D-9: logical px, NOT fs-scaled (pointer jitter)

# The three tier-folded controls, in mockup DOM order (:644-648): menu rows.
_OVERFLOW_ROWS = (("birth", "Birth time ±", "time"),
                  # C7: "hd" left the fold-at-d3 toggles cluster for the always-
                  # visible left group, so it no longer folds into the overflow menu.
                  ("dual", "Modifier · + Tropical rim", "rim"))


def _menu_style() -> str:
    """QSS for the overflow QMenu — the ONE sanctioned QSS surface (INV-4);
    routed through ThemedStyleMixin so theme refresh replays it."""
    from ui.qt_theme import get_theme_colors
    t = get_theme_colors()
    return (f"QMenu {{ background-color: {t['secondary_dark']};"
            f" color: {t['primary_text']};"
            f" border: 1px solid {t['secondary_light']};"
            f" padding: 4px; }}"
            f"QMenu::item {{ padding: 5px 12px 5px 8px;"
            f" border-radius: 6px; }}"
            f"QMenu::item:selected {{ background-color: {t['secondary']}; }}"
            f"QMenu::item:disabled {{ color: {t['secondary_text']}; }}")


class ActionBarLayoutController(ThemedStyleMixin):
    def __init__(self, bar, gui, metrics: BarMetrics, tokens_fn, *,
                 buttons: dict, toggles_cluster, zod_cluster, sep_s3,
                 tray, title_well, meta, overflow_btn,
                 hd_visible: bool):
        self._bar = bar
        self._gui = gui
        self._m = metrics
        self._tokens_fn = tokens_fn
        self._buttons = dict(buttons)            # key -> SegmentButton
        self._toggles_cluster = toggles_cluster  # right_seg2 (.lvl3)
        self._zod_cluster = zod_cluster
        self._sep_s3 = sep_s3                    # the ONLY sep that hides
        self._tray = tray
        self._title_well = title_well
        self._meta = meta
        self._overflow_btn = overflow_btn
        self._menu = None
        self._meta_shown = True

        # D-22h: app-level visibility, orthogonal to the tier's folding.
        self._app_visible = {key: True for key in self._buttons}
        # C8 (Lorris): the D-5 HD<->Sidereal swap is GONE. All three zodiac
        # pills stay visible at once, and the left HD button is always shown;
        # the classic pill never morphs into SIDEREAL.
        self._app_visible["hd"] = True
        self._app_visible["sidereal"] = True
        self._buttons["classic"].set_dual_role(False)

        self._engine = TierEngine(hysteresis_px=_HYSTERESIS_PX)
        self._required: list[int] = []
        self._applied_tier = -1                  # force the first apply
        # doc §1.5: meta re-evaluates on well resize AND name/meta rewrites
        title_well.on_content_changed = self._update_meta

    # ------------------------------------------------------------------ table
    def required(self, d: int) -> int:
        """Min bar width (bar.width() convention, side pads included) at
        which tier d fits. Pure arithmetic over BarMetrics + the ladder +
        live app_visible flags (doc §2.3); the T-1 equivalence test pins it
        to the real layout's minimumSize."""
        m = self._m

        def w(key):
            if not self._app_visible[key] or not LADDER[key].visible_at(d):
                return None
            # the BUTTON's own box function (dual-role extras included) —
            # one source, so the table cannot drift from reality
            return self._buttons[key].width_at(d)

        SEP = 1
        # C7: left_seg1 is transit + north + CARDS + HUMAN DESIGN (the new 4th
        # cell — HD moved here from the right toggles cluster); left_seg2 stays
        # kala + info. HD carries app_visible["hd"] (hide-HD swap), so guard it.
        left_seg1 = w("transit") + w("north") + w("cards")
        _hd = w("hd")
        if _hd is not None:
            left_seg1 += _hd
        left = left_seg1 + m.grp_gap + (w("kala") + w("info"))

        right_items = [w("now") + w("add")]
        if d < TOGGLES_CLUSTER_GONE_FROM:
            # C7: the toggles cluster is now BIRTH TIME alone (HD moved left).
            toggles = sum(x for x in (w("birth"),) if x is not None)
            right_items += [SEP, toggles]        # .sep.s3 + .lvl3 cluster
        tray = sum(x for x in (w("aditya"), w("classic"), w("sidereal"))
                   if x is not None)
        if d < MODSPLIT_GONE_FROM and self._app_visible["dual"]:
            gap = round(3 * m.fs)
            tray += gap + 1 + gap + w("dual")   # modsplit stays 1px (D-22i
            #                                     refuted by the gate)
        tray += 2 * m.tray_pad
        right_items += [SEP, tray]
        if d >= OVERFLOW_VISIBLE_FROM:
            right_items += [m.button_width([], with_icon=True,
                                           pad_x=OVERFLOW_PAD_PX)]
        right = sum(right_items) + m.grp_gap * (len(right_items) - 1)

        # track (C8): grp [sep] well(hug) [spacer] [sep] grp. Measured (T-1
        # equivalence): the mid surplus-spacer keeps the layout at 4 track gaps
        # (the spacer suppresses only its own extra spacing, not an existing
        # widget<->widget gap), same as the rev2 uncapped-well layout.
        return round(2 * m.side_pad + 4 * m.track_gap
                     + m.grp_margin + left
                     + SEP + m.title_min_w + SEP
                     + m.grp_margin + right)

    def _compute_table(self):
        self._required = [self.required(d) for d in range(N_TIERS)]
        assert all(a > b for a, b in zip(self._required, self._required[1:])), \
            f"required(d) must strictly decrease: {self._required}"
        if hasattr(self._bar, "set_min_hint_width"):
            self._bar.set_min_hint_width(self._required[-1])   # D-22a floor

    def apply_initial(self):
        """Construction-time: the bar has no realized width yet, so tier
        selection from bar.width() would land d5 (Qt default ~100px). Boot
        pinned at d0 — the mockup boots `class="bar d0"` too — and the first
        real resizeEvent selects the true tier."""
        self._compute_table()
        self._engine.fit_widths = [float(r) for r in self._required]
        self._engine.tier = 0
        self._apply(0)

    def rebuild_table(self, force_refit: bool = True):
        """(Re)compute required(0..5); on any app_visible / metrics change.
        Forced refit bypasses the hysteresis band (D-22e: the band is
        meaningless across tables)."""
        # C8: hd and sidereal are independent now (the D-5 swap is gone);
        # both are permanently visible.
        self._compute_table()
        width = float(self._bar.width())
        tier = self._engine.set_table([float(r) for r in self._required],
                                      width=width if force_refit else None)
        # force=True: an app_visible change must re-apply EVEN at the same
        # tier — at 1920/d0 the HD<->Sidereal swap otherwise never reaches
        # the widgets (M2 Sol gate, MAJOR 1)
        self._apply(tier, force=True)

    def set_app_visible(self, key: str, visible: bool):
        """D-22h: the app's own hide (HD setting, D-51 non-wheel dual rim).
        Distinct from tier folding; rebuilds the table, forced refit.
        C8: hd and sidereal are independent — no swap redirect."""
        if self._app_visible.get(key) == bool(visible):
            return
        self._app_visible[key] = bool(visible)
        self.rebuild_table(force_refit=True)

    def set_hd_visible(self, visible: bool):
        """C8: toggles ONLY the left HD button. Sidereal is independent now
        (the D-5 swap is gone), so this no longer touches the sidereal flag or
        the classic dual role. In practice HD stays visible; kept for the
        (now inert) ui.hide_human_design plumbing."""
        if self._app_visible["hd"] == bool(visible):
            return
        self._app_visible["hd"] = bool(visible)
        self.rebuild_table(force_refit=True)

    def app_visible(self, key: str) -> bool:
        """Read-only flag access for render_state (Dm3-21)."""
        return bool(self._app_visible.get(key, True))

    def base_label(self, key: str) -> str:
        """The logical (full-form) label of a control — the label-literal
        tests' migration target (spec T-5 / Q6): stable across tiers, unlike
        the painted text."""
        return self._buttons[key].base_label()

    def set_metrics(self, metrics: BarMetrics):
        self._m = metrics
        self._applied_tier = -1                  # boxes change: full re-apply
        self.rebuild_table(force_refit=True)

    def force_tier(self, d: int):
        """Bypass selection and apply tier d — the T-1 equivalence test and
        the CP-2 capture harness need to pose a tier regardless of width."""
        self._engine.tier = d
        self._apply(d)

    # -------------------------------------------------------------- selection
    def on_bar_resized(self, width: int):
        self._apply(self._engine.on_width(float(width)))
        self._update_meta()                      # well width moved either way

    @property
    def tier(self) -> int:
        return self._engine.tier

    # ------------------------------------------------------------------ apply
    def _apply(self, d: int, force: bool = False):
        if d == self._applied_tier and not force:
            return
        self._applied_tier = d
        bar = self._bar
        if self._menu is not None:
            self._menu.close()                   # mockup :837
        bar.setUpdatesEnabled(False)
        try:
            # Dm4-27: a tier apply reboxes and hides children — every
            # in-flight bar animation is cancelled and snapped BEFORE the
            # boxes move (a rect captured before the rebox is fiction).
            snap = getattr(bar, "snap_motion", None)
            if callable(snap):
                snap()
            for key, btn in self._buttons.items():
                row = LADDER[key]
                btn.apply_tier(d)
                target = self._app_visible[key] and row.visible_at(d)
                if btn.isHidden() == target:     # only true changes restripe
                    parent = btn.parentWidget()
                    if hasattr(parent, "set_button_visible"):
                        parent.set_button_visible(btn, target)
                    else:
                        btn.setVisible(target)
            self._toggles_cluster.setVisible(d < TOGGLES_CLUSTER_GONE_FROM)
            self._sep_s3.setVisible(d < TOGGLES_CLUSTER_GONE_FROM)
            self._tray.set_modsplit_visible(
                d < MODSPLIT_GONE_FROM and self._app_visible["dual"])
            self._tray.set_gap(0 if d >= TRAY_GAP_ZERO_FROM
                               else round(3 * self._m.fs))
            self._overflow_btn.setVisible(d >= OVERFLOW_VISIBLE_FROM)
            self._update_meta()
            self._update_overlay_info()
        finally:
            bar.setUpdatesEnabled(True)
        ov = getattr(bar, "focus_overlay", None)
        if ov is not None:
            ov.raise_()      # Dm4-34: a sibling setVisible can re-stack
        bar.update()

    # ------------------------------------------------------------- title meta
    def _update_meta(self):
        """D-22f: the d0 meta is all-or-nothing (mockup trimMeta) with its
        own one-sided 16px band so a drag cannot park it on a flicker edge."""
        meta, well = self._meta, self._title_well
        # D-23(b) / F2: an active overlay chip carries the identity, so the
        # meta yields to it entirely (the mockup's trimMeta hides #chartMeta
        # once the chip is present) — regardless of tier or fit.
        if getattr(self._gui, "_overlay_chip_active", False):
            meta.setVisible(False)
            self._meta_shown = False
            return
        if self._applied_tier >= META_HIDDEN_FROM:
            meta.setVisible(False)
            self._meta_shown = False
            return
        lay = well.layout()
        margins = lay.contentsMargins()
        available = (well.width() - margins.left() - margins.right()
                     - well.name_btn.width()
                     - 3 * lay.spacing()          # name|meta, meta|chev slot,
                     - well.close_btn.width())    #   chev|close
        if self._meta_shown:
            show = meta.width() <= available          # hide the moment it hits
        else:
            show = meta.width() + _HYSTERESIS_PX <= available
        if show != self._meta_shown:
            self._meta_shown = show
            meta.setVisible(show)

    # ---------------------------------------------------- overlay chip info
    def _update_overlay_info(self):
        """D-23(b) / F2: the overlay chip's birth-info span shares the meta's
        d1 breakpoint — it VANISHES at tier >= 1 (leaving `◇ Name`), letting
        the name elide last. The writer owns the TEXT; this owns the tier
        gate. Only ever hides (never forces-on) a span the writer emptied."""
        view = getattr(self._gui, "overlay_chip_view", None)
        if view is None:
            return
        # d1+ collapses the info span (mockup `.ovl-info{display:none}`); the
        # painted chip then elides the name alone. Only the tier gate lives here.
        view.set_collapsed(self._applied_tier >= META_HIDDEN_FROM)

    # ---------------------------------------------------------- overflow menu
    def _rebuild_overflow_actions(self):
        """INV-5's letter (Dm3-37): rebuild from live widget state on
        aboutToShow, so EVERY popup path — the capsule click, a future
        shortcut, a test's menu.popup() — gets a fresh menu, not just the
        click path. Rebuilt wholesale: the widgets are the single source of
        truth (INV-5/INV-7); no live update while open (Dm3-41)."""
        menu = self._menu
        menu.clear()
        tokens = self._tokens_fn()
        dpr = self._bar.devicePixelRatioF()
        for key, text, icon_id in _OVERFLOW_ROWS:
            if not self._app_visible[key]:
                continue                          # app-hidden: NOT in the menu
            btn = self._buttons[key]
            pm = paint_controls.icon_pixmap(icon_id, 13.0 * self._m.fs,
                                            tokens["primary_text"], dpr)
            act = menu.addAction(QIcon(pm) if pm is not None else QIcon(),
                                 text)
            act.setCheckable(True)
            act.setChecked(btn.lit or btn.isChecked())     # INV-7: lit first
            act.setEnabled(btn.isEnabled())                # D-12 mirroring
            act.setToolTip(btn.toolTip())      # Dm3-39: disabled reason rides
            act.triggered.connect(btn.click)     # proxy — single handler path

    def _ensure_menu(self):
        from PySide6.QtWidgets import QMenu
        if self._menu is None:
            self._menu = QMenu(self._bar)
            self._register_themed(self._menu, _menu_style)
            self._menu.aboutToShow.connect(self._rebuild_overflow_actions)
        return self._menu

    def show_overflow_menu(self):
        """Explicit popup (never QPushButton.setMenu — the platform arrow
        would change the capsule's sizeHint, INV-1)."""
        menu = self._ensure_menu()
        # popup() fires aboutToShow, but the empty-menu refusal needs the
        # rows NOW — rebuilding twice is harmless (idempotent, cheap).
        self._rebuild_overflow_actions()
        if not menu.actions():
            return                               # never pop an empty menu
        h = self._overflow_btn.height()
        menu.popup(self._overflow_btn.mapToGlobal(QPoint(0, h + 6)))
