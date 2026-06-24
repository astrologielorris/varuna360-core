"""SPEC-SET-002 Phase 2: single startup-apply pass for persisted UI state."""
VIEW_INDEX = {"south_indian": 0, "wheel": 1, "north_indian": 2}


def apply_persisted_ui_state(gui, settings):
    # --- chart view: switch FIRST via the existing helper (syncs toolbar+state) ---
    view = settings.get("chart.view_type", "south_indian")
    if view not in VIEW_INDEX:
        view = "south_indian"                      # AC9: invalid -> safe default
    gui._switch_to_chart_index(VIEW_INDEX[view])

    # --- wheel-only settings, applied DIRECTLY to the always-constructed wheel ---
    # Apply UNCONDITIONALLY: the setters only store state on gui.wheel_view.
    # At boot the chart isn't loaded yet (session restore loads it ~500ms later);
    # storing the values now means they take effect when the chart first draws.
    # Gating on a loaded chart for the SETTERS would silently never restore cusp
    # glow / retinue rings / element pies. draw_wheel() itself is empty-safe, but
    # is skipped here when no chart exists to avoid the overhead of clearing the
    # scene and rebuilding an empty grid that will be rebuilt ~500ms later anyway.
    # Sync the toolbar actions too so the menu reflects the restored state and
    # F5/Shift+F5 toggle from the correct value (.triggered connection => a
    # programmatic setChecked does NOT re-fire the toggle handler).
    want_cusp = settings.get("chart.cusp_glow_mode", 0)
    want_retinue = settings.get("chart.show_retinue_rings", False)
    want_pies = settings.get("chart.show_element_pies", True)
    want_house_display = settings.get("chart.wheel_house_display", "sign_based")
    gui.wheel_view.set_cusp_glow_mode(want_cusp)
    gui.wheel_view.set_show_retinue_rings(want_retinue)
    if hasattr(gui.wheel_view, "set_house_display_mode"):
        gui.wheel_view.set_house_display_mode(want_house_display)
    gui.wheel_view.show_element_pies = want_pies
    want_trim_deg = settings.get("chart.show_trimsamsha_degrees", False)
    gui.wheel_view.show_trimsamsha_degrees = want_trim_deg
    if hasattr(gui, "retinue_rings_action"):
        gui.retinue_rings_action.setChecked(bool(want_retinue))
    if hasattr(gui, "trimsamsha_degrees_action"):
        gui.trimsamsha_degrees_action.setChecked(bool(want_trim_deg))
    if hasattr(gui, "pie_charts_action"):
        gui.pie_charts_action.setChecked(bool(want_pies))
    if gui.wheel_view._chart:
        gui.wheel_view.draw_wheel()

    # --- outer planets: sync the action then toggle only if needed ---
    want_outer = settings.get("chart.show_outer_planets", True)
    if gui.outer_planets_action.isChecked() != want_outer:
        gui.outer_planets_action.setChecked(want_outer)
        gui._toggle_outer_planets()
    # NOTE: do NOT touch zodiac.mode here (owned by core_gui_qt.py:286-292).

    # --- planet labels: sync the action then toggle only if needed ---
    want_names = settings.get("chart.show_planet_names", False)
    if hasattr(gui, 'planet_names_action'):
        if gui.planet_names_action.isChecked() != want_names:
            gui.planet_names_action.setChecked(want_names)
            gui._toggle_planet_names()

    # --- Chart-tab sub-panel toggle groups (SPEC-SET-002 Phase 5) ---
    _apply_panel_tabs(gui, settings)


def _call_indexed(funcs, idx):
    """Call funcs[idx]() if idx is a valid int in range and the entry is callable.

    Defensive: a missing/None switcher or an out-of-range index is a silent
    no-op so startup can't crash on a panel that isn't fully wired yet.
    """
    if not isinstance(idx, int) or idx < 0 or idx >= len(funcs):
        return
    func = funcs[idx]
    if callable(func):
        func()


def _relabel(gui, t1, t2, t3):
    """Relabel the three shared aspects tab buttons (guarded by hasattr).

    The same three buttons are reused for both Vedic and Tajika modes, so the
    restore path must set their text to match the persisted mode before the
    mode-aware switcher runs.
    """
    if hasattr(gui, "aspects_tab_btn"):
        gui.aspects_tab_btn.setText(t1)
    if hasattr(gui, "avastha_tab_btn"):
        gui.avastha_tab_btn.setText(t2)
    if hasattr(gui, "shame_tab_btn"):
        gui.shame_tab_btn.setText(t3)


def _apply_panel_tabs(gui, settings):
    """Restore the three Chart-tab sub-panel toggle groups from settings.

    Uses the EXPOSED gui.switch_to_* closures (they do the lazy controller
    set_visible() work), with defensive bounds and falsy-zero-safe defaults.
    Guarded as a whole so a missing attribute can't crash startup.
    """
    try:
        # Karakas
        karakas = [getattr(gui, n, None) for n in
                   ("switch_to_karakas_tab", "switch_to_hora_tab",
                    "switch_to_trimsamsa_tab", "switch_to_graph_tab")]
        _call_indexed(karakas, settings.get("ui.panel.karakas_tab", 0))
        # Strength
        strength = [getattr(gui, n, None) for n in
                    ("switch_to_strength_tab", "switch_to_elements_tab",
                     "switch_to_modality_tab", "switch_to_dignities_tab")]
        _call_indexed(strength, settings.get("ui.panel.strength_tab", 0))
        # Aspects: set mode + relabel ONCE, then call the mode-aware switcher
        mode = settings.get("ui.panel.aspects_mode", "vedic")
        tab = settings.get("ui.panel.aspects_tab", 0)
        gui._aspects_mode = mode
        if mode == "tajika":
            if not isinstance(tab, int) or tab < 0 or tab > 2:
                tab = 0
            _relabel(gui, "Aspects T", "Relations", "Yogas")
            if hasattr(gui, 'exchange_tab_btn'):
                gui.exchange_tab_btn.setVisible(False)
            if hasattr(gui, '_asp_sep3'):
                gui._asp_sep3.setVisible(False)
            switchers = [getattr(gui, "switch_to_tajika_matrix_tab", None),
                         getattr(gui, "switch_to_tajika_relationships_tab", None),
                         getattr(gui, "switch_to_tajika_yogas_tab", None)]
        else:
            if not isinstance(tab, int) or tab < 0 or tab > 3:
                tab = 0
            _relabel(gui, "Aspects V", "Avastha", "Shame")
            if hasattr(gui, 'exchange_tab_btn'):
                gui.exchange_tab_btn.setVisible(True)
            if hasattr(gui, '_asp_sep3'):
                gui._asp_sep3.setVisible(True)
            switchers = [getattr(gui, "switch_to_aspects_tab", None),
                         getattr(gui, "switch_to_avastha_tab", None),
                         getattr(gui, "switch_to_shame_tab", None),
                         getattr(gui, "switch_to_exchange_tab", None)]
        _call_indexed(switchers, tab)
    except Exception:
        pass  # never let panel restore crash startup
