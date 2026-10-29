from state.chart_state import ChartState
from state.events import (
    SetActiveChart,
    SetVarga,
    SetZodiacMode,
    SetTimeAdjustMode,
    SetChartViewStyle,
)
from state.prefs_store import PrefsStore
from state.profile_store import ProfileStore


def __getattr__(name):
    # PanelControllerBase needs Qt (QTimer). Loaded on first use so that
    # Qt-free code importing ``state.user_data`` or ``state.chart_state`` (the
    # headless ``--tool`` mode, AIC plan 2) never pulls in PySide6 (PEP 562).
    if name == "PanelControllerBase":
        from state.panel_mixin import PanelControllerBase
        return PanelControllerBase
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
