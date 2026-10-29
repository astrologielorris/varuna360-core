"""No South Indian chain while the centre shows another chart (SPEC-EXCH-002 3.4.3,
td-946ni). The setting is never touched: the chains are only held back on that view
and come back when its centre is free."""
from apps.widgets.exchange_chain_items import clear_chains, register_chain_pass, si_pass
from apps.widgets import exchange_chain_classic as xcc

HELD = "xc_centre_held"          # scene property: the chains are held back by the centre

__all__ = ["register_chain_pass", "vector_si_pass", "classic_si_pass", "classic_centre_sync"]


def vector_taken(view):
    """Transit / overlay, varga or a center drawing in the centre, time adjust; never box off."""
    c = view.center
    return bool(view.center_box_enabled
                and (c.time_adjust_mode or c._transit_overlay_active or c._center_varga_code is not None or bool(view.scene.property("center_drawing_shown"))))  # SPEC-VAC-001 §4.0


def classic_taken(view):
    """The same, plus the mini North Indian of a Z6b selection and the hover preview."""
    return bool(view.center_box_enabled and (view.time_adjust_mode or view._transit_overlay_active or {
        view._center_varga_code, view.selected_z6b_sign, view.current_hover_sign} != {None}))


def centre_pass(view, run, taken):
    """THE rule: centre taken -> no chain on this view (items removed), else ``run``."""
    view.scene.setProperty(HELD, held := taken(view))
    if held:
        clear_chains(view.scene)
        return 0
    return run(view)


def vector_si_pass(view, get=None):
    return centre_pass(view, lambda v: si_pass(v, get), vector_taken)


def classic_si_pass(view, get=None):
    return centre_pass(view, lambda v: xcc.classic_si_pass(v, get), classic_taken)


def classic_centre_sync(view):
    """Called on every classic centre change (``_apply_center_precedence``): re-runs
    the pass only when taken / free changed, so a no-change call is one comparison."""
    if getattr(view, "_chart", None) is None or classic_taken(view) == bool(view.scene.property(HELD)):
        return False
    classic_si_pass(view)
    return True
