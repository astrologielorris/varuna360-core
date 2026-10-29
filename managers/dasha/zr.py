# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Zodiacal Releasing renderer for one dasha side (SPEC-ZR-001, SPEC-DSH-004).

Bodies moved verbatim from the retired right-only `DashaManager.update_zr_dasha`
and its helpers; now bound to whichever side shows ZR. The ZR options
(`dasha.zr.*`) are shared by both sides (D-4); their leaf owner is
ZodiacSettingsManager, which re-lists every side in ZR mode on a change, so the
title-menu handlers only persist (SPEC-DSH-004 §4.5).
"""

from PySide6.QtWidgets import QListWidgetItem, QMenu
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtCore import Qt


class ZRRenderer:
    """One side's ZR list: one level at a time, drill by double-click, the
    context strip shows the parents, prev = back one level."""

    def __init__(self, manager, side_name):
        self.manager = manager
        self.side_name = side_name

    @property
    def side(self):
        return self.manager.sides[self.side_name]

    @property
    def zr(self):
        return self.manager.dasha_state.side(self.side_name).zr

    @property
    def panel(self):
        return self.manager.panel(self.side_name)

    # -- protocol ----------------------------------------------------------- #

    def invalidate(self):
        pass

    def enter(self, panel):
        """Clear EVERY delegate channel before the ZR list fills the period one
        (verbatim of the old per-mode ZR configure step)."""
        from managers.dasha.common import clear_all_channels
        clear_all_channels(panel)

    def checked_level(self):
        return self.zr.level

    def capture_options(self):
        """get_zodiacal_releasing options of what this side lists: releaser
        settings, and the opened periods as the indices the capability takes
        (found in each shown level)."""
        zr = self.zr
        out = {"releaser": zr.releaser, "spirit_shift": bool(zr.spirit_shift),
               "anchor": zr.anchor, "drill": []}
        if zr.result is None:
            return out
        from core.zodiacal_releasing import zr_display_rows
        chain = list(zr.parent_chain)[:max(0, zr.level - 1)]
        for depth, period in enumerate(chain):
            shown = zr_display_rows(zr.result, depth + 1, chain[:depth])
            index = next((i for i, row in enumerate(shown) if row is period
                          or (row.get("pos") == period.get("pos")
                              and row.get("start_jd") == period.get("start_jd"))), None)
            if index is None:
                break
            out["drill"].append(index)
        return out

    def context_cycle_offset(self):
        return 0            # ZR jds are absolute (no 120-year cycling)

    def on_title_clicked(self):
        self._show_releaser_menu()

    def nav_prev(self):
        self.back_one_level()

    def nav_next(self):
        return              # next button hidden in ZR; a stray call is a no-op

    # -- settings ----------------------------------------------------------- #

    def _settings(self):
        opt = self.manager.shared_option       # session pick of a locked option, else stored
        st = self.zr
        st.releaser = opt("dasha.zr.releaser", "spirit")
        st.spirit_shift = bool(opt("dasha.zr.spirit_shift", True))
        st.show_age = bool(opt("dasha.zr.show_age", False))
        st.anchor = opt("dasha.zr.anchor", "birth")
        return st

    # -- render ------------------------------------------------------------- #

    def render(self):
        """Re-list ZR for the current level. Drives the SHARED compute_zr() so
        the panel and the CLI produce identical periods (ZR INV-5)."""
        # ZR replaces the side's list: abort any in-flight Vimshottari render of
        # this side so its stale rows can never land here.
        self.side.invalidate()
        gui = self.manager.gui
        p = self.panel
        lst = p.list_widget
        lst.clear()
        p.mark_rendered(None)
        if p.delegate is not None:
            p.delegate.update_highlights(set())

        chart = gui.current_chart_data
        if not chart:                       # DD8: no chart -> cleared, no notice
            self.zr.result = None
            self._set_title(None)
            return

        st = self._settings()
        mode = gui.state.aditya_mode
        ayan = getattr(gui, 'chart_sidereal_ayanamsa_id', 100)
        use_western = getattr(gui, 'use_western_names', False)

        from AI_tools.AI_main_function.zodiacal_releasing import compute_zr
        try:
            result = compute_zr(
                chart, mode=mode, ayanamsa=ayan, releaser=st.releaser,
                spirit_shift=st.spirit_shift, anchor=st.anchor,
                horizon_years=150, levels=1,
            )
        except ValueError as e:             # DD8: cannot resolve -> one notice row
            self.zr.result = None
            self._set_title(None)
            msg = ("  Zodiacal Releasing needs a birth time"
                   if "birth time" in str(e) else "  Releaser cannot be computed: %s" % e)
            item = QListWidgetItem(msg)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setData(Qt.ItemDataRole.UserRole, {"is_separator": True})
            lst.addItem(item)
            self._update_strip(None, mode, use_western)
            return
        except Exception as e:
            print(f"Error updating ZR dasha: {e}")
            import traceback
            traceback.print_exc()
            return

        self.zr.result = result
        # Drop a parent chain left over from a different chart or zodiac frame
        # before drilling with it (W6 review MAJOR 1).
        self._reset_chain_if_stale(result)
        p.set_level_checked(self.zr.level)
        self._set_title(result, mode=mode, use_western=use_western)

        display_rows = self._display_rows(result)
        meta = self._meta(result, mode, use_western)

        from core.zodiacal_releasing import format_level, zr_tooltip
        birth_jd = result["birth_jd_utc"]
        entries = format_level(
            display_rows, self.zr.level, now_jd=result["target_jd"],
            mode=mode, use_western=use_western, show_age=st.show_age,
            birth_jd=birth_jd, tz_offset_hours=result["tz_offset_hours"],
        )

        highlight_rows = set()
        for i, entry in enumerate(entries):
            item = QListWidgetItem(entry["text"])
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setToolTip(zr_tooltip(entry, meta))
            lst.addItem(item)
            if entry["is_current"]:
                highlight_rows.add(i)

        if p.delegate is not None:
            p.delegate.update_highlights(highlight_rows)
            lst.viewport().update()
        if highlight_rows:
            # side-generation guarded (SPEC-DSH-004 INV-9): a later render or
            # mode switch on this side cancels the scroll.
            self.side.later(100, lambda r=min(highlight_rows):
                            self.manager.scroll_to_row(self.side_name, r))

        self._update_strip(result, mode, use_western)
        # Rows carry their ruler as `lord`: the Karaka/Cusp/House combos
        # highlight on the list now shown (SPEC-DSH-004 §3.6, every mode).
        self.manager.refresh_dasha_lord_highlights(self.side_name)
        p.mark_rendered(gui.state.active_chart)

    def _reset_chain_if_stale(self, result):
        """Reset the ZR drill chain when it no longer belongs to `result` (a
        different chart or zodiac system); a pure label toggle keeps it."""
        st = self.zr
        if st.level <= 1 or not st.parent_chain:
            st.level = 1
            st.parent_chain = []
            return
        l1 = [r for r in result["rows"] if r["level"] == 1]
        top = st.parent_chain[0]
        matches = any(
            r["pos"] == top.get("pos")
            and abs(r["start_jd"] - top.get("start_jd", -1e18)) < 1e-6
            for r in l1)
        if not matches or len(st.parent_chain) < st.level - 1:
            st.level = 1
            st.parent_chain = []

    def _display_rows(self, result):
        """The Period rows to show at the current level, per the parent chain."""
        from core.zodiacal_releasing import zr_display_rows
        return zr_display_rows(result, self.zr.level, self.zr.parent_chain)

    def _meta(self, result, mode, use_western):
        from core.aditya_mode import displayed_sign_name
        return {
            "mode": mode, "use_western": use_western,
            "tz_offset_hours": result["tz_offset_hours"],
            "birth_jd": result["birth_jd_utc"],
            "releaser_token": result["label_token"], "lot_label": result.get("lot_label"),
            "releaser_pos": result["releaser_pos"],
            "releaser_sign_label": displayed_sign_name(result["releaser_pos"], mode, use_western),
            "fortune_pos": result["fortune_pos"],
            "fortune_sign_label": displayed_sign_name(result["fortune_pos"], mode, use_western),
        }

    def _set_title(self, result, mode=None, use_western=False):
        """Title button text from the label_token (DESIGN DECISION 2)."""
        p = self.panel
        if p is None:
            return
        if result is None:
            # BASE renderer order: setEnabled(True) FIRST, then setText -> setToolTip.
            p.title_btn.setEnabled(True)
            p.set_title("Releasing: Spirit ▼", tooltip="Click to choose the releaser")
            return
        from core.aditya_mode import displayed_sign_name
        tok = result["label_token"]
        if tok == "spirit":
            text = "Releasing: Spirit ▼"
        elif tok == "spirit_shifted":
            text = "Releasing: Spirit* ▼"
        elif tok == "fortune":
            text = "Releasing: Fortune ▼"
        elif tok == "lot":
            text = "Releasing: %s ▼" % result.get("lot_label", "Lot")
        else:
            text = "Releasing: %s ▼" % displayed_sign_name(
                result["releaser_pos"], mode or self.manager.gui.state.aditya_mode, use_western)
        tip = "Click to choose the releaser"
        if tok == "spirit_shifted":
            tip += ". Spirit was shifted out of Fortune's sign."
        p.title_btn.setEnabled(True)          # enable BEFORE setText/setToolTip
        p.set_title(text, tooltip=tip)

    def _update_strip(self, result, mode, use_western):
        """Context strip (DESIGN DECISION 3): prev-btn visibility + cycle label."""
        p = self.panel
        if p is None:
            return
        st = self.zr
        from core.aditya_mode import displayed_sign_name
        if st.level == 1 or result is None:
            fsign = (displayed_sign_name(result["fortune_pos"], mode, use_western)
                     if result else "")
            text = ("Peaks from Fortune in %s" % fsign) if result else ""
        else:
            crumbs = [displayed_sign_name(pp["pos"], mode, use_western)
                      for pp in st.parent_chain]
            text = " › ".join(crumbs)
        p.set_strip(prev_visible=(st.level > 1), text=text)

    # -- navigation --------------------------------------------------------- #

    def set_level(self, level):
        """Jump to a level via the level buttons. Going deeper without an
        explicit drill builds the chain from the current period at each depth."""
        level = max(1, min(4, int(level)))
        st = self.zr
        result = st.result
        if result is None:
            st.level = 1
            self.manager.update_side(self.side_name)
            return
        if level == 1:
            st.level = 1
            st.parent_chain = []
        else:
            chain = self._auto_chain(result, level)
            if len(chain) < level - 1:
                level = len(chain) + 1      # not enough context; stay where valid
            st.parent_chain = chain[:level - 1]
            st.level = level
        self.manager.update_side(self.side_name)

    def _auto_chain(self, result, target_level):
        """Parent chain to target_level from the CURRENT period at each depth."""
        from core.zodiacal_releasing import find_current, drill
        rows = result["rows"]
        now = result["target_jd"]
        chain = []
        l1 = [r for r in rows if r["level"] == 1]
        i1 = find_current(l1, now, 1)
        if i1 < 0:
            return chain
        chain.append(l1[i1])
        if target_level == 2:
            return chain
        l2 = [r for r in rows if r["level"] == 2
              and r["parent_pos"] == l1[i1]["pos"]
              and l1[i1]["start_jd"] <= r["start_jd"] < l1[i1]["end_jd"]]
        i2 = find_current(l2, now, 2)
        if i2 < 0:
            return chain
        chain.append(l2[i2])
        if target_level == 3:
            return chain
        drilled = drill(l2[i2], result["fortune_pos"])
        l3 = [r for r in drilled if r["level"] == 3]
        i3 = find_current(l3, now, 3)
        if i3 < 0:
            return chain
        chain.append(l3[i3])
        return chain

    def on_drill(self, item):
        """Drill one level deeper into the double-clicked row."""
        st = self.zr
        if st.level >= 4 or st.result is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not entry or entry.get("is_separator"):
            return
        display_rows = self._display_rows(st.result)
        row = next((r for r in display_rows
                    if r["level"] == entry["level"] and r["pos"] == entry["pos"]
                    and abs(r["start_jd"] - entry["start_jd"]) < 1e-6), None)
        if row is None:
            return
        st.parent_chain = st.parent_chain[:st.level - 1] + [row]
        st.level += 1
        if self.panel is not None:
            self.panel.set_level_checked(st.level)
        self.manager.update_side(self.side_name)

    def on_select(self, item):
        """Single click: move the ▶ current-marker to the clicked row (no drill)."""
        from core.zodiacal_releasing import _MARK_CURRENT
        from managers.dasha.common import move_current_marker
        move_current_marker(self.panel, item, _MARK_CURRENT)

    def back_one_level(self):
        """Pop one ancestor off the chain and go up a level (DD3 back button)."""
        st = self.zr
        if st.level <= 1:
            return
        st.level -= 1
        st.parent_chain = st.parent_chain[:st.level - 1]
        if self.panel is not None:
            self.panel.set_level_checked(st.level)
        self.manager.update_side(self.side_name)

    # -- title menu --------------------------------------------------------- #

    def _show_releaser_menu(self):
        """Releaser QMenu on this side's title button (DESIGN DECISION 2)."""
        from ui.qt_theme import get_theme_colors
        from managers.settings_manager import get_settings
        gui = self.manager.gui
        s = get_settings()
        from core.settings_registry import default as _registry_default
        cur_releaser = s.get("dasha.zr.releaser", _registry_default("dasha.zr.releaser"))
        mode = gui.state.aditya_mode
        use_western = getattr(gui, 'use_western_names', False)
        from core.aditya_mode import displayed_sign_name

        theme = get_theme_colors()
        btn = self.panel.title_btn
        menu = QMenu(btn)
        from managers.dasha.common import menu_style
        menu.setStyleSheet(menu_style(theme))
        group = QActionGroup(menu)
        group.setExclusive(True)

        def _releaser_action(parent, label, key):
            act = QAction(label, parent)
            act.setCheckable(True)
            act.setChecked(cur_releaser == key)
            group.addAction(act)
            act.triggered.connect(lambda _=False, k=key: self._pick_releaser(k))
            return act

        menu.addAction(_releaser_action(menu, "Spirit", "spirit"))
        menu.addAction(_releaser_action(menu, "Fortune", "fortune"))
        from core.lots import LOT_REGISTRY, LOT_ORDER
        lots_menu = menu.addMenu("From a lot")
        lots_menu.setStyleSheet(menu.styleSheet())
        for name in LOT_ORDER:
            lots_menu.addAction(_releaser_action(
                lots_menu, LOT_REGISTRY[name]["label"], f"lot:{name}"))
        submenu = menu.addMenu("From a sign")
        submenu.setStyleSheet(menu.styleSheet())
        for i in range(12):
            submenu.addAction(_releaser_action(
                submenu, displayed_sign_name(i, mode, use_western), f"sign:{i}"))
        menu.addSeparator()

        shift_act = QAction("Shift Spirit out of Fortune's sign", menu)
        shift_act.setCheckable(True)
        shift_act.setChecked(bool(s.get("dasha.zr.spirit_shift",
                                         _registry_default("dasha.zr.spirit_shift"))))
        shift_act.triggered.connect(
            lambda checked: self._set_option("dasha.zr.spirit_shift", checked))
        menu.addAction(shift_act)

        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _pick_releaser(self, key):
        self.manager.write_shared_option("dasha.zr.releaser", key)

    def _set_option(self, settings_key, value):
        self.manager.write_shared_option(settings_key, bool(value))
