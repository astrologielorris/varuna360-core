# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Shared Pro/Lite AI Settings settings component."""
import logging
import re
import threading
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QScrollArea, QFrame, QGroupBox, QSizePolicy, QPushButton, QLineEdit, QMessageBox, QComboBox, QFormLayout, QApplication)
from PySide6.QtCore import Signal, Qt, QThread, QTimer
from ui.qt_theme import (get_theme_colors, get_primary_button_style, get_secondary_button_style, scaled_area_px)
from ui.accent_ink import on_accent_ink  # SPEC-THM-001 §13
from ui.qss_fit import fit_width
from ui.combo_values import add_valued_items, select_by_data
from managers.settings_manager import get_settings, EnvUnreadableError
from ui.ai_provider_backend import default_provider_backend
from core import settings_registry as _registry
try:
    from utils.debug import debug_print
except ImportError:
    debug_print = print
_LOG = logging.getLogger(__name__)
# SPEC-SET-003 D-14: the key of the "Let the AI change the app's settings" row.
APP_SETTINGS_TOGGLE = "ai.allow_app_settings_changes"


def _own_write(fn):
    """A row that saves as it changes: the page's own write (AI setting
    redesign item 4, ``ui/settings_page_sync.page_write``)."""
    from ui.settings_page_sync import page_write
    return page_write(fn)

def _cap_w(owner, w, legacy, text=None):
    """FIX-H width cap on ``w`` at the content-rect fit, floored at ``legacy``;
    registered on ``owner._width_caps`` for live re-derivation. ``text`` defaults
    to ``w.text()`` (pass it for widgets whose text changes).

    ensurePolished() first: at construction (before the widget is shown) the
    QSS-driven font + padding are NOT yet resolved, so fontMetrics()/chrome_h
    read the DEFAULT font and the cap comes out too narrow (clips on a FRESH
    build at large fonts). Polishing forces the style to resolve them so the cap
    is correct at construction, not only after the first live refresh."""
    w.ensurePolished()
    t = w.text() if text is None else text
    w.setProperty('_td2o8u_cap_text', t)
    w.setProperty('_td2o8u_cap_legacy', int(legacy))
    w.setFixedWidth(fit_width(w, t, int(legacy)))
    if not hasattr(owner, '_width_caps'):
        owner._width_caps = []
    owner._width_caps.append(w)


def _rederive_width_caps(owner):
    """Re-run every registered width cap on the live font path (call from the
    section's refresh_theme)."""
    for w in getattr(owner, '_width_caps', ()):
        lw = w.property('_td2o8u_cap_legacy')
        if lw is None:
            continue
        w.ensurePolished()
        t = w.property('_td2o8u_cap_text')
        w.setFixedWidth(fit_width(w, t if t is not None else w.text(), int(lw)))

# Finding 6(c): the stale-default combo sentinel is identified by a private
# item-data role, NOT by its display text, so a real provider named
# "<x> (unavailable)" can never be mistaken for it.
_SENTINEL_ROLE = Qt.ItemDataRole.UserRole + 1
_SENTINEL_MARKER = "unavailable-default-sentinel"
# Dynamic property set on a provider row's status label while its probe is in
# flight, so "still checking" is read from state, never from the label text
# (SPEC-LOC-002 INV-3).
_CHECKING_PROP = "v360_status_checking"

# Finding 1: workers that are STILL running when their section is destroyed are
# moved here so neither Qt parentage nor Python GC can destroy a live QThread
# (which aborts the process with "QThread: Destroyed while thread is still
# running"). Each abandoned worker removes itself once its run() actually
# returns (finished -> deleteLater + discard). Module-level so the reference
# outlives the section.
_ABANDONED_WORKERS = set()


def _abandon_worker(worker):
    """Detach a still-running worker from the section and let it die on its own.

    Disconnects every slot (so late signals can't touch dead widgets), holds a
    module-level Python reference (GC-safe), then hooks the NATIVE Qt slot chain
    ``finished -> deleteLater`` and ``destroyed -> discard`` so the worker is
    only destroyed AFTER its run() has genuinely returned, and self-removes from
    the registry when the C++ object is finally deleted.

    A native QObject slot (``deleteLater``) is used rather than a bare Python
    callback on ``finished``: a bare-function slot is not reliably delivered on
    a cross-thread queued connection here, whereas ``deleteLater`` is. The set
    is cleaned from ``destroyed`` (emitted on the GUI thread during deferred
    deletion, so its bare lambda IS delivered directly).
    """
    try:
        worker.disconnect()          # drop ALL connections to section slots
    except (RuntimeError, TypeError):
        pass
    _ABANDONED_WORKERS.add(worker)
    try:
        worker.finished.connect(worker.deleteLater)
        worker.destroyed.connect(
            lambda *a: _ABANDONED_WORKERS.discard(worker))
    except (RuntimeError, TypeError):
        # Could not hook the chain — keep the ref forever (leak one thread
        # object at shutdown, never abort the process by destroying it live).
        pass
    # Race: run() may already have returned (interruption at the top of the
    # loop) so finished won't fire again — delete now; destroyed still cleans
    # the set once the deferred deletion is processed.
    try:
        if worker.isFinished():
            worker.deleteLater()
    except RuntimeError:
        pass
    _LOG.warning(
        "AI providers: probe worker still running at teardown; abandoned "
        "(will self-reap on completion) to avoid destroying a live QThread.")


# --- INV-4 secret redaction (finding 3) ------------------------------------
# Token shapes scrubbed from any error text before it reaches a status row.
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),        # OpenAI/DeepSeek-style keys
    re.compile(r"[A-Za-z0-9_-]{20,}"),          # any long unbroken token run
)


def _redact_secrets(text, settings=None):
    """Replace stored key values + common token shapes with ``***`` (INV-4).

    (a) Every CURRENTLY-STORED provider key value (>=8 chars) is substituted
        so a driver error echoing a real key never renders it verbatim.
    (b) Common token shapes (sk-… and any 20+ char [A-Za-z0-9_-] run) are
        regex-redacted as a backstop for keys we don't have on hand.
    """
    if not text:
        return text
    s = str(text)
    if settings is not None:
        try:
            for val in settings.all_api_key_values():
                if val and len(val) >= 8:
                    s = s.replace(val, "***")
        except Exception as exc:
            # Finding 1 (round-3): do NOT silently swallow — losing value-based
            # redaction is a security-relevant degradation. The regex fallback
            # below still runs, but one warning records the lost coverage.
            #
            # Round-5 F3: NEVER interpolate the exception BODY into the log. The
            # token-shape regex only catches sk-/20+char runs, so a SHORT
            # non-token secret embedded in the exception message (e.g.
            # "auth failed for shortsecretkey") would slip through verbatim.
            # Log ONLY the exception CLASS name — never its message text. (The
            # regex backstop on the actual detail text below is unchanged.)
            debug_print(
                "[settings] AI providers: could not read stored key values "
                f"during redaction ({type(exc).__name__}); value-based scrub "
                "skipped, regex backstop only")
    for pat in _SECRET_PATTERNS:
        s = pat.sub("***", s)
    return s


# ============================================================================
# Per-setting padlock control (SPEC-SET-002 §6.1)
# ============================================================================
_PROV_GREEN = "#43A047"   # semantic: Ready
_PROV_AMBER = "#FB8C00"   # semantic red-family (warm): degraded / warning tier
_PROV_RED = "#E53935"     # semantic: unavailable / not installed


def _provider_card_style() -> str:
    """Card chrome for one provider row (theme-driven — replayed on refresh).

    Only the 8-key palette is used; status colours stay semantic. The selector
    is scoped to the ``providerCard`` objectName so the rule never bleeds into
    child widgets (labels/edits/buttons carry their own styles).
    """
    theme = get_theme_colors()
    return f"""
        QFrame#providerCard {{
            background-color: {theme['secondary']};
            border: 1px solid {theme['secondary_light']};
            border-radius: 8px;
        }}
    """


def _provider_name_lbl_style() -> str:
    """Provider-row NAME label: font-bearing fragment composed at BOTH
    construction and refresh so a color-only rewrite can't drop the size/weight
    (B2 HIGH-2). QSS-styled label -> setFont is inert (O-5)."""
    theme = get_theme_colors()
    return (f"color: {theme['primary_text']}; "
            f"font-size:{scaled_area_px('info_text')}px; font-weight: bold;")


def _provider_detail_lbl_style() -> str:
    """Provider-row DETAIL/subtitle label: font-bearing fragment (info->status
    area), composed at construction and refresh alike."""
    theme = get_theme_colors()
    return (f"color: {theme['secondary_text']}; "
            f"font-size:{scaled_area_px('status')}px;")


def _status_tier_style(color: str) -> str:
    """Provider-row status INDICATOR (dot glyph + status word): the COLOUR is
    semantic (probe tier), the SIZE follows the 'status' area. ONE fragment for
    the dot AND the status word across all three sites (construction,
    checking-reset, terminal render) so a colour rewrite can't drop the size
    (B2 HIGH-2). Replayed in refresh_theme from refs['status_color']."""
    return f"color: {color}; font-size: {scaled_area_px('status')}px;"


def _prov_group_head_style() -> str:
    """AI-providers subgroup HEADING (Local / Cloud etc.): info_text area,
    font-bearing so a theme replay can't strand it at the qt-material default."""
    theme = get_theme_colors()
    return (f"color:{theme['secondary_text']}; "
            f"font-size: {scaled_area_px('info_text')}px; "
            f"font-weight:700; letter-spacing:1px; margin-top:6px;")


def _prov_group_help_style() -> str:
    """AI-providers subgroup HELP line: info_text area, font-bearing fragment."""
    theme = get_theme_colors()
    return (f"color:{theme['secondary_text']}; "
            f"font-size: {scaled_area_px('info_text')}px;")


def _prov_models_caption_style() -> str:
    """Provider-row MODELS caption (dot-separated model list): status area,
    font-bearing fragment replayed in refresh_theme."""
    theme = get_theme_colors()
    return (f"color: {theme['secondary_text']}; "
            f"font-size: {scaled_area_px('status')}px;")


def _title_font_qss(widget):
    """panel_titles font-size for a settings header/group-title, as a STYLESHEET
    fragment. B3: under qt-material, setFont at construction (before show) is
    wiped by the polish at show, so the reliable mechanism is stylesheet
    font-size (survives construction AND refresh). QGroupBox needs the size on
    the QGroupBox selector (font-size on ::title is ignored by Qt); the per-
    widget rule merges per-property with qt-material's box styling, so the
    border/title placement are preserved."""
    px = scaled_area_px('panel_titles')
    if isinstance(widget, QGroupBox):
        return f"QGroupBox {{ font-size: {px}px; font-weight: bold; }}"
    return f"font-size: {px}px; font-weight: bold;"


def _reapply_title_fonts(widgets):
    """(Re)apply the panel_titles stylesheet over the settings page's own
    headers / QGroupBox titles, at construction and on every LIVE font change.
    B3 exception to the freeze deferral (orchestrator ruling): the user is on
    THIS page when they Apply a font change, so its own headers must not stay
    frozen while other panels update."""
    for w in widgets:
        w.setStyleSheet(_title_font_qss(w))


def _settings_combo_style() -> str:
    """Combo styling for the AI-provider selectors. Without an explicit
    ``QComboBox::drop-down`` rule the arrow button falls back to whatever the
    cascading stylesheet leaves it and renders clipped ('cut off'); this pins a
    comfortable arrow width + height so the button is never truncated. Theme
    driven (replayed on refresh)."""
    theme = get_theme_colors()
    return f"""
        QComboBox {{
            background-color: {theme['secondary']};
            color: {theme['secondary_text']};
            border: 1px solid {theme['secondary_light']};
            border-radius: 6px;
            padding: 4px 10px;
            font-size: {scaled_area_px('info_text')}px;
            min-height: 26px;
        }}
        QComboBox:hover {{ border: 1px solid {theme['primary']}; }}
        QComboBox::drop-down {{
            subcontrol-origin: padding;
            subcontrol-position: center right;
            border: none;
            width: 26px;
            margin-right: 2px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {theme['secondary']};
            color: {theme['secondary_text']};
            selection-background-color: {theme['primary']};
            selection-color: {on_accent_ink(theme['primary'], theme['primary_text'])};
            border: 1px solid {theme['secondary_light']};
            outline: none;
        }}
        QComboBox QAbstractItemView::item {{
            min-height: 26px;
            padding: 4px 10px;
        }}
    """


def _provider_status_color(status) -> str:
    """Semantic colour for an INV-3 ProviderStatus (green/amber/red)."""
    value = getattr(status, "value", status)
    return {
        "ready": _PROV_GREEN,
        "logged_out": _PROV_AMBER,
        "not_installed": _PROV_RED,
        "installed_unverified": _PROV_AMBER,
        "missing_key": _PROV_AMBER,
    }.get(value, _PROV_AMBER)


def _provider_status_label(status, is_session: bool = False) -> str:
    """Short human label for an INV-3 ProviderStatus (SPEC-PMT-001 §4.3).

    ``is_session`` splits READY, because the two account kinds mean different
    things by it: a CLI login is "Logged in", an API key is "Key set". One word
    for both told the user nothing about which of their two credentials was
    actually working.
    """
    value = getattr(status, "value", status)
    if value == "ready":
        return "Logged in" if is_session else "Key set"
    return {
        "logged_out": "Not logged in",
        "not_installed": "Not installed",
        "installed_unverified": "Installed, not checked",
        "missing_key": "No key",
    }.get(value, str(value))


# The vendor's own word for an auth kind, translated to ours (INV-4). The SDK
# reports apiKeySource='none' for a healthy subscription login; printed raw as
# "Auth: none" it read as NOT AUTHENTICATED on a working account.
_AUTH_KIND_LABELS = {
    "none": "Subscription login",
    "chatgpt": "ChatGPT subscription",
    "apikey": "API key",
    "api_key": "API key",
    "oauth": "Subscription login",
}


def _vendor_label(env_key, backend=None) -> str:
    """The vendor that issues an API key, for an account row's title.

    Accepts the canonical name or a legacy alias, because the registry stores
    legacy names (``Deepseek_API_KEY``) while the settings section works in
    canonical ones (``DEEPSEEK_API_KEY``).
    """
    if not env_key:
        return ""
    backend = backend or default_provider_backend()
    direct = backend.KEY_ACCOUNT_LABELS.get(env_key)
    if direct:
        return direct
    for legacy, canonical in backend.LEGACY_ENV_KEY_ALIASES.items():
        if canonical == env_key:
            got = backend.KEY_ACCOUNT_LABELS.get(legacy)
            if got:
                return got
    return ""


def _auth_kind_label(auth_kind) -> str:
    """Our word for a vendor auth kind, or '' when there is nothing to say."""
    if not auth_kind:
        return ""
    return _AUTH_KIND_LABELS.get(str(auth_kind).strip().lower(),
                                 str(auth_kind))


def _ready_detail(snapshot) -> str:
    """Compose a READY row's detail line from the account + models (INV-3).

    Claude exposes no email in this SDK version, so plan / auth_kind / model are
    shown instead; falls back to the snapshot's own detail_msg.
    """
    parts = []
    acct = getattr(snapshot, "account", None)
    if acct is not None:
        if getattr(acct, "plan", None):
            parts.append(f"Plan: {acct.plan}")
        if getattr(acct, "email", None):
            parts.append(str(acct.email))
        # NEVER the raw vendor word (INV-4): apiKeySource='none' means "no API
        # key, subscription login" and printed verbatim as "Auth: none" it made
        # a healthy login read as unauthenticated.
        kind = _auth_kind_label(getattr(acct, "auth_kind", None))
        if kind:
            parts.append(kind)
    models = getattr(snapshot, "models", None) or []
    if models:
        parts.append(f"Model: {models[0]}")
    if parts:
        return "  ·  ".join(parts)
    return getattr(snapshot, "detail_msg", "") or "Ready."


def _sanitize_detail(msg: str, limit: int = 120, settings=None) -> str:
    """Collapse an error to a single safe line for a status detail (INV-3/INV-4).

    Secrets are redacted FIRST (stored key values + token shapes), then
    newlines/tabs are flattened and the text is length-capped so a multi-line
    or secret-bearing exception can never sprawl into (or leak through) a row.
    Pass ``settings`` so stored key values can be scrubbed by value.
    """
    if not msg:
        return ""
    redacted = _redact_secrets(msg, settings=settings)
    one_line = " ".join(str(redacted).split())
    if len(one_line) > limit:
        one_line = one_line[:limit - 1].rstrip() + "…"
    return one_line


def render_provider_row(name: str, snapshot, is_session: bool,
                        settings=None, is_local: bool = False) -> dict:
    """Pure snapshot -> row-text mapping (SPEC-PROV-001 INV-3, T-1 matrix).

    Qt-free and side-effect-free so the detection matrix asserts row text and
    hint per status without a widget. Returns:
        {status_label, color, detail, hint}

    Finding 1 (round-3): drivers do NOT raise — they catch their own errors and
    RETURN a snapshot whose ``detail_msg`` carries raw text (e.g. an auth error
    echoing a key). Every driver-originated string that lands in ``detail`` or
    ``hint`` is therefore routed through ``_sanitize_detail`` here (redaction +
    single-line + length cap) so a returned snapshot can never leak a secret at
    the render site, mirroring the exception/synthetic paths. Pass ``settings``
    so stored key VALUES are scrubbed too (not just token shapes).
    """
    status = getattr(snapshot, "status", None)
    value = getattr(status, "value", status)
    detail_msg = getattr(snapshot, "detail_msg", "") or ""
    out = {
        "status_label": _provider_status_label(status, is_session),
        "color": _provider_status_color(status),
        "detail": "",
        "hint": "",
    }
    if value == "ready":
        out["detail"] = _ready_detail(snapshot)
        if is_local:
            out.update(status_label="No API key required", color=_PROV_AMBER,
                       detail="Server connection not checked.")
    elif value == "logged_out":
        out["hint"] = detail_msg or (
            f"Run `{name.lower()} login`" if is_session else "Not logged in.")
    elif value == "not_installed":
        # A spawn failure here is as often PATH as a missing install: the app
        # launched from a desktop entry does not inherit a shell's PATH, so a
        # CLI that runs fine in a terminal is invisible to it. Say so, rather
        # than reporting only the errno.
        out["hint"] = (detail_msg or f"{name} CLI not installed.")
        if is_session:
            out["hint"] += (f"  Install it, or — if `{name.lower()}` works in a "
                            f"terminal — the app's PATH is missing its "
                            f"directory; launch Varuna360 from a shell to "
                            f"confirm.")
    elif value == "installed_unverified":
        out["detail"] = detail_msg or "Installed; login state not probed."
    elif value == "missing_key":
        out["hint"] = detail_msg or "No API key set."
    else:
        out["detail"] = detail_msg
    # Redact + flatten EVERY driver-originated string before it reaches a widget.
    out["detail"] = _sanitize_detail(out["detail"], settings=settings)
    out["hint"] = _sanitize_detail(out["hint"], settings=settings)
    return out


class _SnapshotWorker(QThread):
    """Probe provider snapshots OFF the GUI thread (SPEC-PROV-001 INV-5).

    Session-driver ``snapshot()`` calls spawn the vendor CLI / a short SDK
    session and can block for seconds; running them here keeps the settings
    screen responsive. ``snapshot()`` is contracted never to raise, but the
    call is still guarded (belt-and-braces) so one bad probe cannot kill the
    worker or leave a row stuck on "Checking...".
    """

    # provider name, ProviderSnapshot, worker generation (finding F3 round-3).
    result_ready = Signal(str, object, int)
    finished_all = Signal()

    def __init__(self, probes, parent=None, settings=None, generation=0,
                 backend=None):
        super().__init__(parent)
        # probes: list of (name, ProviderInstance)
        self._probes = list(probes)
        # Settings ref so a raised probe error can be redacted (INV-4) before
        # it is emitted to a row. Read-only use; never mutated off-thread.
        self._settings = settings
        self._backend = backend or default_provider_backend()
        # Finding F3 (round-3): the section's worker generation at the time this
        # worker was created. Emitted with every result so a stale delivery
        # (already posted before disconnect, arriving after close/reopen minted
        # a new worker) is rejected by _on_snapshot_result's generation check.
        self._generation = generation
        # name -> thread ident the probe ran on (test asserts != GUI thread).
        self.thread_idents = {}

    def run(self):
        for name, instance in self._probes:
            # Exit promptly if teardown asked us to stop (section/app closing).
            # This between-provider check is the only interruption granularity
            # the driver contract exposes — snapshot() takes no timeout param,
            # so a single probe still runs to its own internal completion.
            if self.isInterruptionRequested():
                return
            try:
                snap = instance.snapshot()
            except Exception as exc:  # pragma: no cover - snapshot() never raises
                snap = self._backend.ProviderSnapshot(
                    status=self._backend.ProviderStatus.INSTALLED_UNVERIFIED,
                    detail_msg=_sanitize_detail(
                        f"probe error: {exc}", settings=self._settings))
            if self.isInterruptionRequested():
                return
            self.thread_idents[name] = threading.get_ident()
            self.result_ready.emit(name, snap, self._generation)
        self.finished_all.emit()


class _AnthropicKeyProbe:
    """Status of the Anthropic row: the key is present or not. It is used
    only when there is no Claude login, and the row says so either way."""

    def __init__(self, settings, backend):
        self._settings = settings
        self._backend = backend

    def snapshot(self):
        from core.ai_engines.catalog import ANTHROPIC_KEY
        status = self._backend.ProviderStatus
        # True for both uses: AI Tools Claude falls back to the key without
        # a login; the "Anthropic API" image reader, chosen by name, always
        # uses it (td-hblfz review).
        use = ("Claude uses this key only when there is no Claude login. "
               "The Anthropic API image reader always uses it.")
        if self._settings.get_api_key(ANTHROPIC_KEY):
            return self._backend.ProviderSnapshot(status=status.READY,
                                                  detail_msg=use)
        return self._backend.ProviderSnapshot(status=status.MISSING_KEY,
                                              detail_msg="No key. " + use)


class _GlmPayPerUseProbe:
    """Status of the GLM pay-per-use row (td-hblfz): is a Z.ai / BigModel
    key saved, and does the GLM route use it (a Coding Plan goes first)."""

    def __init__(self, settings, backend):
        self._settings = settings
        self._backend = backend

    def snapshot(self):
        from core.ai_engines import catalog as _catalog
        status = self._backend.ProviderStatus
        env = {n: self._settings.get_api_key(n)
               for kind, n, _u, _s in _catalog.GLM_ROUTES if kind == "env"}
        _choice, held_in, source = _catalog.glm_payg_state(env)
        if not held_in:
            return self._backend.ProviderSnapshot(
                status=status.MISSING_KEY,
                detail_msg="No key. Enter a Z.ai or BigModel API key to pay per token.")
        held_source = next(s for kind, n, _u, s in _catalog.GLM_ROUTES
                           if kind == "env" and n == held_in)
        if source == held_source:
            detail = f"In use ({held_source})."
        else:
            detail = f"Saved. Your {source} is used first."
        return self._backend.ProviderSnapshot(status=status.READY,
                                              detail_msg=detail)


def _build_default_registry(backend=None):
    """register_builtin_drivers() then return the process-wide registry.

    Isolated so tests can inject a fake registry instead (no real CLIs).
    """
    return (backend or default_provider_backend()).registry()


class _AIProvidersSection(QWidget):
    """AI provider status rows + masked key entry + default-provider selector.

    - One row per registered provider (registry). Session drivers show
      install/login/plan state + a fix hint; key drivers add a masked key field.
    - Two key rows that are credentials, not models: GLM pay-per-use and
      Anthropic (used only when there is no Claude login), SPEC-PMT-001 §4.7.
    - Snapshots are probed on a background QThread; "Refresh" clears the
      detection cache and re-probes.
    - Default-provider combo persists to ``ai.default_provider``.
    """

    def __init__(self, parent=None, registry=None, settings=None,
                 auto_probe=True, backend=None):
        super().__init__(parent)
        self.section_key = "ai_providers"
        self._settings = settings if settings is not None else get_settings()
        self._backend = backend or default_provider_backend()
        self._registry = registry if registry is not None else \
            _build_default_registry(self._backend)
        self._rows = {}            # account id -> row-widget refs
        self._group_labels = []    # (widget, style_fn) group headers/help — replayed in refresh_theme
        self._title_widgets = []   # group titles wired for live font refresh (B3)
        # list of (name, instance, is_session, create_error)
        self._instances = []
        self._secondary_buttons = []
        self._primary_buttons = []
        self._worker = None
        self._worker_generation = 0    # stale-delivery guard (finding F3)
        self._closed = False           # teardown guard (finding 1)
        self._refresh_pending = False  # coalesced refresh (finding 2)
        self._unavailable_default = None  # stale-default sentinel (finding 7)
        self._suppress_default_save = False
        self._build_ui()
        # AI setting redesign (td-bztjj) item 4/7: the rows follow a change
        # made outside the page (the AI setting panel, its Model dropdown).
        from ui import settings_page_sync as _page_sync
        _page_sync.attach(self, self._read_from_settings,
                          _registry.owner_set("ai_providers", "core")
                          | {APP_SETTINGS_TOGGLE, "ai.setting_panel.model"},
                          settings=self._settings)
        # Stop the worker cleanly if the whole app quits mid-probe (the widget
        # may never receive a closeEvent when the process tears down).
        try:
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._teardown_worker)
        except Exception:
            pass
        if auto_probe:
            self.refresh_snapshots()

    # -------------------------------------------------------------- build ---

    def _canonical_key_for(self, driver):
        """Canonical .env key name for a key driver (legacy alias -> canonical).

        The registry stores legacy env-key names (Deepseek_API_KEY, ...); the
        settings section reads/writes the CANONICAL name so key entry and the
        snapshot agree (resolve_env_key resolves both).
        """
        env_key = getattr(driver, "env_key", None)
        if not env_key:
            return None
        return self._backend.LEGACY_ENV_KEY_ALIASES.get(env_key, env_key)

    def _is_session(self, driver) -> bool:
        fam = getattr(driver, "family", None)
        return fam is self._backend.ProviderFamily.SESSION or \
            getattr(fam, "value", None) == "session"

    # ---- accounts (SPEC-PMT-001 INV-1) -----------------------------------

    def _account_groups(self):
        """The registry's drivers, collapsed to ACCOUNTS and split into the
        three groups (SPEC-PMT-001 §4.1).

        Grouping is derived from the REGISTRY rather than read from the static
        builtin table, so an injected registry (tests, and any future dynamic
        provider) still drives the panel.

        Identity is the credential, never the label (D-6): session drivers key
        on the driver name, keyed drivers on the CANONICAL env key — which is
        what makes six OpenAI models one row with one field instead of six
        rows asking for the same key. A key driver with no env key at all is
        LOCAL (it runs on this machine), not a keyless remote.

        Returns [(kind, header, help_text, [account, ...]), ...] where each
        account is a dict: id, label, drivers, env_key, is_session, models.
        """
        from collections import OrderedDict
        ACCOUNT_KEY = self._backend.ACCOUNT_KEY
        ACCOUNT_LOCAL = self._backend.ACCOUNT_LOCAL
        ACCOUNT_SUBSCRIPTION = self._backend.ACCOUNT_SUBSCRIPTION
        _SESSION_LABELS = {"Claude": "Claude Code", "Codex": "Codex CLI"}
        from core.ai_engines.catalog import SUBSCRIPTION_ENV_KEYS as _SUBSCRIPTION_KEYS
        # Model inventory per credential, from the builtin table. Absent for an
        # injected test registry — the row simply shows no inventory line.
        _KEY_ACCOUNT_LABELS_LOCAL = self._backend.KEY_ACCOUNT_LABELS.get(None, "")
        inventory, session_inventory, local_inventory = {}, {}, ()
        for a in self._backend.builtin_accounts():
            if a.kind == ACCOUNT_SUBSCRIPTION and a.driver_name:
                session_inventory[a.driver_name] = a.models
            elif a.kind == ACCOUNT_LOCAL:
                local_inventory = a.models
            inventory[a.id] = a.models
            canonical = self._backend.LEGACY_ENV_KEY_ALIASES.get(a.id)
            if canonical:
                inventory[canonical] = a.models

        buckets = OrderedDict()
        for driver in self._registry.all():
            name = getattr(driver, "name", "?")
            is_session = self._is_session(driver)
            canonical = None if is_session else self._canonical_key_for(driver)
            if is_session:
                kind, acc_id = ACCOUNT_SUBSCRIPTION, name
            elif canonical in _SUBSCRIPTION_KEYS:
                # A plan login read from its own app (the GLM Coding Plan,
                # ZCode): a subscription row, no key field (td-2nxmo).
                kind, acc_id, is_session = ACCOUNT_SUBSCRIPTION, canonical, True
            elif canonical:
                kind, acc_id = ACCOUNT_KEY, canonical
            else:
                kind, acc_id = ACCOUNT_LOCAL, name
            entry = buckets.setdefault(acc_id, {
                "id": acc_id, "kind": kind, "drivers": [],
                "env_key": canonical, "is_session": is_session,
            })
            entry["drivers"].append(driver)

        for entry in buckets.values():
            drivers = entry["drivers"]
            # One driver -> its own name (keeps every existing single-driver
            # fixture, and any provider we have not given a vendor label).
            # Several -> the vendor that issues the shared key.
            vendor = _vendor_label(entry["env_key"], self._backend)
            if entry["is_session"] and not entry["env_key"]:
                raw = getattr(drivers[0], "name", entry["id"])
                label = _SESSION_LABELS.get(raw, raw)
            elif vendor:
                label = vendor
            elif len(drivers) == 1:
                # Unknown vendor (an injected/test driver): its own name is the
                # best available account name.
                label = getattr(drivers[0], "name", entry["id"])
            else:
                label = entry["id"]
            if entry["is_session"] and not entry["env_key"]:
                models = session_inventory.get(
                    getattr(drivers[0], "name", ""), ())
            elif entry["kind"] == ACCOUNT_LOCAL:
                models = local_inventory
                label = _KEY_ACCOUNT_LABELS_LOCAL or label
            else:
                models = inventory.get(entry["env_key"] or entry["id"], ())
            entry["label"] = label
            entry["models"] = tuple(display for display, _id in models)

        # A GLM pay-per-use key is a second credential for the GLM models:
        # metered, so it is a row under API keys, never a field on the
        # subscription row (td-hblfz, SPEC-PMT-001 §4.7).
        from core.ai_engines import catalog as _catalog
        glm = buckets.get(_catalog.ZAI_CODING_PLAN_KEY)
        payg = None
        if glm is not None:
            payg = {"id": _catalog.GLM_PAYG_ACCOUNT, "kind": ACCOUNT_KEY,
                    "drivers": [], "env_key": None, "is_session": False,
                    "label": "GLM pay-per-use", "models": glm["models"],
                    "key_choices": _catalog.GLM_PAYG_CHOICES,
                    "probe": _GlmPayPerUseProbe(self._settings, self._backend)}

        # The Anthropic API key: Claude without a Claude login (D-10
        # amendment, Lorris 2026-10-20: "yes API key for everyone").
        # Always present: the "Anthropic API" image reader needs it whether
        # or not a Claude login driver is registered (td-hblfz review).
        anthropic = {"id": _catalog.ANTHROPIC_KEY, "kind": ACCOUNT_KEY,
                     "drivers": [], "env_key": _catalog.ANTHROPIC_KEY,
                     "is_session": False, "label": "Anthropic",
                     "models": tuple(display for display, _id
                                     in session_inventory.get("Claude", ())),
                     "probe": _AnthropicKeyProbe(self._settings, self._backend)}

        out = []
        for kind, header, help_text in self._backend.ACCOUNT_GROUPS:
            members = [e for e in buckets.values() if e["kind"] == kind]
            if kind == ACCOUNT_KEY:
                members[0:0] = [e for e in (payg, anthropic) if e is not None]
            if members:
                out.append((kind, header, help_text, members))
        return out

    def _build_ui(self):
        theme = get_theme_colors()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 12)
        layout.setSpacing(18)

        # --- Default provider group ---
        default_group = QGroupBox(_registry.get("ai.default_provider").label)
        default_group.setStyleSheet(_title_font_qss(default_group))
        self._title_widgets.append(default_group)
        dg_layout = QVBoxLayout(default_group)
        dg_layout.setContentsMargins(14, 20, 14, 14)
        dg_layout.setSpacing(8)

        dg_desc = QLabel(_registry.get("ai.default_provider").help)
        dg_desc.setWordWrap(True)
        self._default_desc = dg_desc
        dg_desc.setStyleSheet(f"color: {theme['secondary_text']};")
        dg_layout.addWidget(dg_desc)
        dg_layout.addSpacing(2)

        self.default_combo = QComboBox()
        # Pickers name MODELS (SPEC-PMT-001): a subscription login lists the
        # models it runs ("Claude Opus 5.5", as the AI Tools panel stores
        # it), never the bare driver; the bare name stays only for a profile
        # that still holds it (td-2nxmo).
        stored = self._backend.canonical_provider_name(
            self._settings.get("ai.default_provider", "") or "")
        session_models = {a.driver_name: a.models for a in self._backend.builtin_accounts()
                          if getattr(a, "driver_name", None)}
        names = []
        for driver in self._registry.all():
            models = session_models.get(driver.name) if self._is_session(driver) else None
            if models:
                names += [display for display, _id in models]
                if stored == driver.name:
                    names.append(driver.name)
            else:
                names.append(driver.name)
        # itemData = the provider name that is persisted (SPEC-LOC-002 INV-3);
        # the unavailable sentinel below carries no data.
        add_valued_items(self.default_combo, names)
        for driver in self._registry.all():
            if not self._is_session(driver) and not self._canonical_key_for(driver):
                index = self.default_combo.findData(driver.name)
                self.default_combo.setItemText(index, "Local LLM")
        self._suppress_default_save = True
        if stored in names:
            select_by_data(self.default_combo, stored)
        elif stored:
            # Finding 7: the persisted default is no longer registered. Surface
            # it EXPLICITLY as unavailable and select it, instead of silently
            # showing the first provider while a stale name stays persisted.
            # The persisted value is left untouched until the user actively
            # picks a real provider (_on_default_changed drops the sentinel).
            sentinel = f"{stored} (unavailable)"
            self._unavailable_default = sentinel
            self.default_combo.addItem(sentinel)
            idx = self.default_combo.count() - 1
            # Finding 6(c): tag the sentinel via item userData (a private role)
            # so a REAL provider literally named "<x> (unavailable)" can never
            # collide with it — we check the role, never the display string.
            self.default_combo.setItemData(
                idx, _SENTINEL_MARKER, _SENTINEL_ROLE)
            model = self.default_combo.model()
            item = model.item(idx) if hasattr(model, "item") else None
            if item is not None:
                item.setEnabled(False)
            self.default_combo.setCurrentIndex(idx)
        elif names:
            self.default_combo.setCurrentIndex(0)
        self._suppress_default_save = False
        # Finding F5(a) (round-3): drive from currentIndexChanged, not
        # currentTextChanged — two entries with identical display text (e.g. a
        # real provider and the "<x> (unavailable)" sentinel could coincide)
        # can't misfire on an index-based signal. The handler reads currentText
        # itself and keeps the role-based sentinel checks.
        self.default_combo.currentIndexChanged.connect(self._on_default_changed)
        self.default_combo.setMinimumHeight(32)
        self.default_combo.setMaximumWidth(420)
        self.default_combo.setStyleSheet(_settings_combo_style())
        dg_layout.addWidget(self.default_combo)

        # Resolved model id for the selected chat provider (parity with the
        # vision group). Session providers (Claude/Codex) have no key-table id —
        # their model is chosen by the vendor CLI/subscription.
        self._default_model_label = QLabel("")
        self._default_model_label.setContentsMargins(2, 0, 0, 0)
        self._default_model_label.setStyleSheet(
            f"color: {theme['secondary_text']};")
        dg_layout.addWidget(self._default_model_label)
        self._sync_default_model_label()

        # Chat reasoning-effort selector (persisted under ai.effort — SEPARATE
        # from vision.effort). Applies to GPT-5-family chat providers; ignored
        # by session (Claude/Codex) and non-effort providers. Medium default.
        ce_row = QHBoxLayout()
        ce_row.setContentsMargins(0, 0, 0, 0)
        ce_row.setSpacing(8)
        ce_label = QLabel(_registry.get("ai.effort").label)
        ce_label.setStyleSheet(f"color: {theme['secondary_text']};")
        self._chat_effort_label = ce_label
        ce_row.addWidget(ce_label)

        self.chat_effort_combo = QComboBox()
        # Values the live endpoints accept (registry.REASONING_EFFORTS). The
        # old "Minimal" entry was unusable: every current model rejects
        # 'minimal' with a 400, so picking it failed the whole request rather
        # than thinking less. "None" is its successor — reasoning off.
        for _disp, _val in self._backend.EFFORT_LABELS:
            self.chat_effort_combo.addItem(_disp, _val)
        # canonical_effort, not a bare .lower(): a profile from an older build
        # can hold "minimal", which must restore as its successor "None" —
        # the same value the chat path will send. Falling back to Medium here
        # would show the user one effort while the request used another.
        stored_ce = self._backend.canonical_effort(
            self._settings.get("ai.effort", ""))
        self._suppress_chat_effort_save = True
        _cidx = self.chat_effort_combo.findData(stored_ce)
        self.chat_effort_combo.setCurrentIndex(
            _cidx if _cidx >= 0 else self.chat_effort_combo.findData("medium"))
        self._suppress_chat_effort_save = False
        self.chat_effort_combo.currentIndexChanged.connect(
            self._on_chat_effort_changed)
        self.chat_effort_combo.setMinimumHeight(32)
        self.chat_effort_combo.setMaximumWidth(220)
        self.chat_effort_combo.setStyleSheet(_settings_combo_style())
        self.chat_effort_combo.setToolTip(_registry.get("ai.effort").help)
        ce_row.addWidget(self.chat_effort_combo)
        ce_row.addStretch()
        dg_layout.addLayout(ce_row)

        layout.addWidget(default_group)

        # --- Vision model group (image extraction; vision/chat split) ---
        # Functional-minimal by design: a dedicated restyle pass owns the
        # aesthetics of this section.
        vision_group = QGroupBox(_registry.get("vision.provider").label)
        vision_group.setStyleSheet(_title_font_qss(vision_group))
        self._title_widgets.append(vision_group)
        vg_layout = QVBoxLayout(vision_group)
        vg_layout.setContentsMargins(14, 20, 14, 14)
        vg_layout.setSpacing(8)

        vg_desc = QLabel(_registry.get("vision.provider").help)
        vg_desc.setWordWrap(True)
        self._vision_desc = vg_desc
        vg_desc.setStyleSheet(f"color: {theme['secondary_text']};")
        vg_layout.addWidget(vg_desc)

        self.vision_combo = QComboBox()
        self._vision_configs = {}
        try:
            self._vision_configs = {
                c["name"]: c for c in self._backend.vision_provider_configs()}
            stored_vision = self._backend.canonical_provider_name(
                self._settings.get("vision.provider", ""))
        except Exception:
            stored_vision = self._settings.get("vision.provider", "")
        vnames = list(self._vision_configs.keys())
        if any(c.get("kind") in ("claude_cli", "codex_cli")
               for c in self._vision_configs.values()):
            vg_desc.setText(vg_desc.text() + " The Claude Code and Codex "
                            "entries use your installed subscription, no "
                            "API key.")
        self._suppress_vision_save = True
        add_valued_items(self.vision_combo, vnames)  # itemData = name (INV-3)
        from core.local_ai_config import LOCAL_PROVIDER
        local_index = self.vision_combo.findData(LOCAL_PROVIDER)
        if local_index >= 0:
            self.vision_combo.setItemText(local_index, "Local LLM")
            self.vision_combo.setToolTip("Local LLM uses the server address and model ID below. Load an image-capable model on that server.")
        if stored_vision and stored_vision not in vnames:
            # Surface the stale stored name explicitly (same philosophy as
            # the default-provider sentinel, minimal form). No item data: it
            # is never a value that can be persisted.
            self.vision_combo.addItem(f"{stored_vision} (unavailable)")
            self.vision_combo.setCurrentIndex(self.vision_combo.count() - 1)
        elif stored_vision in vnames:
            select_by_data(self.vision_combo, stored_vision)
        self._suppress_vision_save = False
        self.vision_combo.currentIndexChanged.connect(
            self._on_vision_provider_changed)
        self.vision_combo.setMinimumHeight(32)
        self.vision_combo.setMaximumWidth(420)
        self.vision_combo.setStyleSheet(_settings_combo_style())
        vg_layout.addWidget(self.vision_combo)

        self._vision_model_label = QLabel("")
        self._vision_model_label.setContentsMargins(2, 0, 0, 0)
        self._vision_model_label.setStyleSheet(
            f"color: {theme['secondary_text']};")
        vg_layout.addWidget(self._vision_model_label)
        self._sync_vision_model_label()

        # Reasoning-effort selector (persisted under vision.effort). Applies to
        # providers that accept OpenAI's reasoning_effort knob (the GPT-5
        # family); Claude/Kimi vision ignore it. Medium by default — pulling a
        # birth date/time out of a screenshot is not a hard reasoning task.
        eff_row = QHBoxLayout()
        eff_row.setContentsMargins(0, 0, 0, 0)
        eff_row.setSpacing(8)
        eff_label = QLabel(_registry.get("vision.effort").label)
        eff_label.setStyleSheet(f"color: {theme['secondary_text']};")
        self._vision_effort_label = eff_label
        eff_row.addWidget(eff_label)

        self.vision_effort_combo = QComboBox()
        # Same live-verified value set as the chat combo above — "minimal" is
        # rejected with a 400 by every current model (the registry's choices).
        for _choice in _registry.get("vision.effort").choices:
            self.vision_effort_combo.addItem(_choice.label, _choice.value)
        # Same migration as the chat combo above (see its comment).
        stored_effort = self._backend.canonical_effort(
            self._settings.get("vision.effort", ""))
        self._suppress_effort_save = True
        _eidx = self.vision_effort_combo.findData(stored_effort)
        self.vision_effort_combo.setCurrentIndex(
            _eidx if _eidx >= 0 else self.vision_effort_combo.findData("medium"))
        self._suppress_effort_save = False
        self.vision_effort_combo.currentIndexChanged.connect(
            self._on_vision_effort_changed)
        self.vision_effort_combo.setMinimumHeight(32)
        self.vision_effort_combo.setMaximumWidth(220)
        self.vision_effort_combo.setStyleSheet(_settings_combo_style())
        self.vision_effort_combo.setToolTip(_registry.get("vision.effort").help)
        eff_row.addWidget(self.vision_effort_combo)
        eff_row.addStretch()
        vg_layout.addLayout(eff_row)

        layout.addWidget(vision_group)

        # --- Let the AI change the app's settings (SPEC-SET-003 D-14, W6b) ---
        # The toggle the app settings request service obeys (settings.py
        # set --app and the AI task tool). Written ONLY by this control
        # (INV-17): the service refuses its key as protected. Pro and up:
        # Lite has no AI that writes settings (SPEC-EDN-002 P4).
        from core.edition_features import ai_features
        if ai_features() is not None:
            layout.addWidget(self._build_app_settings_toggle(theme))

        # --- Providers group (status rows) ---
        prov_group = QGroupBox("Providers")
        prov_group.setStyleSheet(_title_font_qss(prov_group))
        self._title_widgets.append(prov_group)
        self._prov_layout = QVBoxLayout(prov_group)
        self._prov_layout.setContentsMargins(14, 20, 14, 14)
        self._prov_layout.setSpacing(10)

        # Account rows, in the three normative groups (SPEC-PMT-001 §4.1).
        # ONE row per credential: the six OpenAI models share one key, and the
        # panel used to render six independent fields for it.
        ACCOUNT_LOCAL = self._backend.ACCOUNT_LOCAL
        for _kind, header, help_text, accounts in self._account_groups():
            head = QLabel(header)
            head.setStyleSheet(_prov_group_head_style())
            self._prov_layout.addWidget(head)
            help_lbl = QLabel(help_text)
            help_lbl.setWordWrap(True)
            help_lbl.setStyleSheet(_prov_group_help_style())
            self._prov_layout.addWidget(help_lbl)
            # (widget, fragment) pairs so refresh_theme can replay font+colour.
            self._group_labels.extend(
                [(head, _prov_group_head_style),
                 (help_lbl, _prov_group_help_style)])

            for account in accounts:
                if account.get("probe") is not None:
                    # A key row with its own probe, not a model driver (GLM
                    # pay-per-use, with its issuer choice; Anthropic).
                    self._instances.append(
                        (account["id"], account["probe"], False, None))
                    self._add_provider_row(
                        account["id"], False, account.get("env_key"),
                        title=account["label"], models=account["models"],
                        key_choices=account.get("key_choices"))
                    continue
                # Probe the FIRST driver of the account: they share the
                # credential, so its auth state is the account's auth state.
                # Probing all six OpenAI rows would have made six identical
                # probes say the same thing.
                driver = account["drivers"][0]
                is_session = account["is_session"]
                canonical = account["env_key"]
                create_error = None
                try:
                    config = {} if is_session else (
                        {"env_key": canonical} if canonical else {})
                    instance = driver.create(config)
                except Exception as exc:
                    instance = None
                    create_error = _sanitize_detail(str(exc),
                                                    settings=self._settings)
                if instance is None and create_error is None:
                    # driver.create() returned None (no exception) — still a
                    # failure to construct a probe-able instance (finding 3).
                    create_error = "driver returned no instance"
                self._instances.append(
                    (account["id"], instance, is_session, create_error))
                self._add_provider_row(
                    account["id"], is_session, None if is_session else canonical,
                    title=account["label"], models=account["models"],
                    is_local=(account["kind"] == ACCOUNT_LOCAL))

        # The ANTHROPIC_API_KEY row is built in the group loop, under API
        # keys (D-10 amendment, 2026-10-20). The 2026-08-06 row was appended
        # AFTER the loop and so rendered under "Local AI"; never again.

        layout.addWidget(prov_group)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        # Bottom button bar
        btn_bar = QHBoxLayout()
        btn_bar.setContentsMargins(24, 8, 24, 12)
        btn_bar.addStretch()

        self._refresh_btn = QPushButton("Refresh Status")
        self._refresh_btn.setStyleSheet(get_secondary_button_style())
        _cap_w(self, self._refresh_btn, 150)  # td-2o8u FIX-H
        self._refresh_btn.clicked.connect(self.refresh_snapshots)
        self._secondary_buttons.append(self._refresh_btn)
        btn_bar.addWidget(self._refresh_btn)

        outer.addLayout(btn_bar)

    def _add_provider_row(self, name, is_session, canonical_key,
                          subtitle=None, title=None, models=(),
                          is_local=False, key_choices=None):
        """Build one ACCOUNT row; register its widget refs in ``self._rows``.

        ``name`` is the row's stable id (driver name or canonical env key);
        ``title`` is what the user reads. They differ wherever several models
        share one credential — the id stays ``OPENAI_API_KEY`` while the title
        reads "OpenAI" — so a rename never moves a row (D-6).

        ``models`` is the inventory this credential unlocks, shown so the
        blast radius of a key is visible without opening a picker.

        ``key_choices`` (``catalog.GLM_PAYG_CHOICES`` shape) gives the key
        field a choice of where the key was issued; the choice picks the env
        name the key is written to, so it reaches that issuer's endpoint.
        """
        choice_owned = ()
        if key_choices:
            from core.ai_engines import catalog as _catalog
            env = {n: self._settings.get_api_key(n)
                   for _k, n, _u, _s in _catalog.GLM_ROUTES if _k == "env"}
            canonical_key, _held, _src = _catalog.glm_payg_state(env)
            choice_owned = tuple(n for _w, _l, names in key_choices for n in names)
        row = QFrame()
        row.setObjectName("providerCard")
        row.setStyleSheet(_provider_card_style())
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(14, 10, 14, 12)
        row_layout.setSpacing(6)

        # Header line: dot + name (prominent) ... status word (right-aligned).
        head = QHBoxLayout()
        head.setSpacing(8)
        dot = QLabel("●")
        dot.setFixedWidth(16)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dot.setStyleSheet(_status_tier_style(_PROV_AMBER))
        head.addWidget(dot)

        name_lbl = QLabel("Local LLM" if is_local else title or name)
        # QSS-styled -> setFont inert (O-5); font in the shared fragment.
        name_lbl.setStyleSheet(_provider_name_lbl_style())
        head.addWidget(name_lbl)

        head.addStretch()

        status_lbl = QLabel("Checking…")
        status_lbl.setProperty(_CHECKING_PROP, True)  # state, not text (INV-3)
        status_lbl.setStyleSheet(_status_tier_style(_PROV_AMBER))
        head.addWidget(status_lbl)
        row_layout.addLayout(head)

        # Detail / hint line, indented to sit under the name (secondary tier).
        models_lbl = None
        if models:
            models_lbl = QLabel(" · ".join(models))
            models_lbl.setWordWrap(True)
            models_lbl.setStyleSheet(_prov_models_caption_style())
        detail_lbl = QLabel(subtitle or "")
        detail_lbl.setWordWrap(True)
        detail_lbl.setContentsMargins(24, 0, 0, 0)
        # QSS-styled -> setFont inert (O-5); font in the shared fragment.
        detail_lbl.setStyleSheet(_provider_detail_lbl_style())
        row_layout.addWidget(detail_lbl)
        if models_lbl is not None:
            row_layout.addWidget(models_lbl)

        key_edit = None
        save_btn = None
        key_lbl = None
        choice_combo = None
        choice_lbl = None
        if canonical_key:
            key_row = QHBoxLayout()
            key_row.setContentsMargins(24, 2, 0, 0)
            key_row.setSpacing(8)
            key_lbl = QLabel("API key:")
            # td-2o8u O-6 rider: this label was never migrated in c038 (it kept
            # qt-material's default font while its sibling form labels use
            # info_text). Migrate it to the info_text area AND cap its width by
            # the content-rect fit so the migrated glyph never clips (was a bare
            # setFixedWidth(70)). refresh_theme replays both (font + width).
            key_lbl.setStyleSheet(f"font-size:{scaled_area_px('info_text')}px;")
            _cap_w(self, key_lbl, 70)
            key_row.addWidget(key_lbl)

            choice_combo = None
            if key_choices:
                # Its own line: beside the key field it left the field a few
                # dozen pixels wide on a narrow page (td-hblfz review).
                choice_row = QHBoxLayout()
                choice_row.setContentsMargins(24, 2, 0, 0)
                choice_row.setSpacing(8)
                choice_lbl = QLabel("Issued by:")
                # Same face as "API key:" below (refresh_theme replays both).
                choice_lbl.setStyleSheet(f"font-size:{scaled_area_px('info_text')}px;")
                choice_row.addWidget(choice_lbl)
                choice_combo = QComboBox()
                choice_combo.setMinimumHeight(28)
                choice_combo.setStyleSheet(_settings_combo_style())
                for write_name, label, _names in key_choices:
                    choice_combo.addItem(label, write_name)
                choice_combo.setCurrentIndex(
                    max(0, choice_combo.findData(canonical_key)))
                choice_combo.setToolTip("Where your GLM API key was issued. "
                                        "The key is sent to that address.")
                choice_combo.currentIndexChanged.connect(
                    lambda _i, n=name: self._on_key_choice_changed(n))
                choice_row.addWidget(choice_combo)
                choice_row.addStretch()
                row_layout.addLayout(choice_row)

            key_edit = QLineEdit()
            key_edit.setMinimumHeight(28)
            key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            # INV-4: never load the stored key into the editable text — the
            # placeholder shows only the MASKED preview.
            existing = (self._stored_row_key({"canonical_key": canonical_key,
                                              "choice_combo": choice_combo})
                        if choice_combo is not None
                        else self._settings.get_api_key(canonical_key))
            if existing:
                key_edit.setPlaceholderText(
                    self._settings._mask_key(existing))
            else:
                key_edit.setPlaceholderText(f"Not set ({canonical_key})")
            key_row.addWidget(key_edit, stretch=1)

            save_btn = QPushButton("Save Key")
            save_btn.setMinimumHeight(28)
            save_btn.setStyleSheet(get_primary_button_style())
            _cap_w(self, save_btn, 90)  # td-2o8u FIX-H
            save_btn.clicked.connect(
                lambda checked=False, n=name: self._on_save_key(n))
            self._primary_buttons.append(save_btn)
            key_row.addWidget(save_btn)
            row_layout.addLayout(key_row)

        self._prov_layout.addWidget(row)
        self._rows[name] = {
            "frame": row,
            "dot": dot,
            "name_lbl": name_lbl,
            "status_lbl": status_lbl,
            "status_color": _PROV_AMBER,   # live semantic tier colour (dot + word)
            "models_lbl": models_lbl,      # may be None (no model list)
            "detail_lbl": detail_lbl,
            "key_edit": key_edit,
            "key_lbl": key_lbl,
            "save_btn": save_btn,
            "canonical_key": canonical_key,
            "choice_combo": choice_combo if canonical_key else None,
            "choice_lbl": choice_lbl,
            # Every env name the row owns: a save writes one and drops the
            # others, so an older key under another name cannot win the route.
            "owned_keys": choice_owned or ((canonical_key,) if canonical_key else ()),
            "is_session": is_session,
            "is_local": is_local,
            "subtitle": subtitle,
        }
        if is_local:
            self._add_local_server_fields(row_layout, self._rows[name])

    def _add_local_server_fields(self, layout, refs):
        from core.local_ai_config import local_server_values
        form = QFormLayout()
        values = local_server_values(self._settings)
        refs["local_saved"] = (values["url"], values["model"])
        refs["url_edit"] = QLineEdit(values["url"])
        refs["url_edit"].setPlaceholderText("http://localhost:1234/v1")
        refs["url_edit"].setToolTip("LM Studio or any OpenAI-compatible server. Enter its root, API base, or full chat/completions URL.")
        refs["model_edit"] = QLineEdit(values["model"])
        refs["model_edit"].setPlaceholderText("Model ID served by your local server")
        refs["local_labels"] = []
        for caption, field in (("Server address:", "url_edit"), ("Model ID:", "model_edit")):
            label = QLabel(caption)
            label.setStyleSheet(_provider_detail_lbl_style())
            refs["local_labels"].append(label)
            refs[field].setMinimumHeight(30)
            form.addRow(label, refs[field])
        layout.addLayout(form)
        button = QPushButton("Save Local Server")
        button.setStyleSheet(get_primary_button_style())
        button.clicked.connect(lambda checked=False: self._on_save_local_server(refs))
        self._primary_buttons.append(button)
        layout.addWidget(button)
        self._update_local_row(refs)

    def _update_local_row(self, refs):
        from core.local_ai_config import local_server_values
        values = local_server_values(self._settings)
        if refs["models_lbl"] is not None:
            refs["models_lbl"].setText(values["model"])
        from core.local_ai_config import local_ai_server
        saved = self._settings.get("ai.local_server", _registry.default("ai.local_server"))
        refs["detail_lbl"].setText(
            "Choose Local LLM in AI Capture, Default chat model, or Vision Model above. Connection not checked."
            if local_ai_server(saved) else "Invalid local server settings. Edit the address and model ID, then save.")

    @_own_write
    def _on_save_local_server(self, refs):
        from core.local_ai_config import local_chat_url, local_ai_server
        value = {"url": refs["url_edit"].text().strip(),
                 "model": refs["model_edit"].text().strip()}
        if not local_ai_server(value):
            refs["detail_lbl"].setText("Enter a valid HTTP or HTTPS server address and a model ID.")
            return
        value["url"] = local_chat_url(value["url"])
        from managers.settings_write import write_or_restore
        ok, error = write_or_restore(self._settings, "ai.local_server", value)
        if not ok:
            refs["detail_lbl"].setText("Could not save local server: " + _sanitize_detail(error, settings=self._settings))
            return
        self._settings._notify_change("ai.local_server", value)
        refs["url_edit"].setText(value["url"])
        refs["local_saved"] = (value["url"], value["model"])
        self._update_local_row(refs)
        self._sync_default_model_label()
        self._sync_vision_model_label()

    # ------------------------------------------------------------- probing ---

    def refresh_snapshots(self):
        """Clear the detection cache and re-probe every provider off-thread."""
        if self._closed:
            return

        # Finding 2: check for an in-flight worker FIRST — never mutate the UI
        # or the detection cache before this guard. A second refresh must not
        # wipe already-arrived rows back to "Checking…" and then bail, which
        # would strand them (the running worker won't re-emit). Instead we
        # remember the request and re-run when the worker finishes.
        if self._worker is not None and self._worker.isRunning():
            self._refresh_pending = True
            return

        # Finding F3 (round-3): mint a new generation for THIS probe cycle. Any
        # result still queued from a previous worker carries an older generation
        # and is rejected by _on_snapshot_result, so a stale delivery arriving
        # after a rapid close/reopen can never update the reopened section.
        self._worker_generation += 1
        gen = self._worker_generation

        try:
            self._backend.clear_detection_cache()
        except Exception:
            pass

        # Reset rows to the transient "checking" state.
        for refs in self._rows.values():
            refs["status_lbl"].setText("Checking…")
            refs["status_lbl"].setProperty(_CHECKING_PROP, True)
            refs["status_color"] = _PROV_AMBER
            refs["status_lbl"].setStyleSheet(_status_tier_style(_PROV_AMBER))
            refs["dot"].setStyleSheet(_status_tier_style(_PROV_AMBER))

        # Finding 3: providers whose driver.create() failed (or returned None)
        # have no instance to probe. Render a synthetic degraded snapshot NOW so
        # their row reaches a terminal INSTALLED_UNVERIFIED state instead of
        # being stranded on "Checking…" forever (INV-3).
        probes = []
        for name, inst, _is_session, create_error in self._instances:
            if inst is None:
                detail = _sanitize_detail(
                    f"Provider unavailable: {create_error}"
                    if create_error else "Provider unavailable.",
                    settings=self._settings)
                synth = self._backend.ProviderSnapshot(
                    status=self._backend.ProviderStatus.INSTALLED_UNVERIFIED,
                    detail_msg=detail)
                self._on_snapshot_result(name, synth, gen)
            else:
                probes.append((name, inst))

        # Retire the previous (finished) worker so children don't accumulate.
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

        if not probes:
            return

        # The button shows the check is running: a login check takes a few
        # seconds, and a row that merely flickers told the user nothing.
        self._set_refresh_busy(True)

        # Finding 1: create the worker with NO Qt parent and hold only a Python
        # reference. A parented QThread would be destroyed by Qt when the
        # section is destroyed; if the probe is still running that aborts the
        # process ("QThread: Destroyed while thread is still running"). Teardown
        # instead ABANDONS a still-running worker to a module-level set.
        self._worker = _SnapshotWorker(probes, settings=self._settings,
                                       generation=gen, backend=self._backend)
        self._worker.result_ready.connect(self._on_snapshot_result)
        # Finding 2: drive the coalesced-refresh drain off the QThread's BUILT-IN
        # finished signal (emitted AFTER run() returns and the thread is
        # stopping) rather than the custom finished_all (emitted INSIDE run()
        # while isRunning() is still True — which stranded _refresh_pending).
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self):
        """Coalesced-refresh drain: re-run once if a refresh arrived mid-flight.

        Driven by QThread.finished (finding 2). If the thread somehow still
        reports running, re-queue this slot via a 0-ms timer instead of parking
        a flag that nothing else will clear.
        """
        if self._closed:
            return
        # Finding F3 (round-3): ignore a stale worker's finished signal. When
        # invoked by a real signal, sender() is the emitting worker; a direct
        # call (test harness / re-queued timer) reports sender()==None and is
        # allowed through so the coalesced-refresh drain still runs.
        sender = self.sender()
        if sender is not None and sender is not self._worker:
            return
        worker = self._worker
        if worker is not None and worker.isRunning():
            QTimer.singleShot(0, self._on_worker_finished)
            return
        if self._refresh_pending:
            self._refresh_pending = False
            self.refresh_snapshots()
            return
        self._set_refresh_busy(False)

    def _set_refresh_busy(self, busy):
        btn = getattr(self, "_refresh_btn", None)
        if btn is None:
            return
        btn.setEnabled(not busy)
        btn.setText("Checking…" if busy else "Refresh Status")

    def _teardown_worker(self):
        """Stop the probe thread and block late signals (finding 1).

        Called from closeEvent and QApplication.aboutToQuit. Requests
        interruption (run() checks it between probes), then waits a bounded 3s.
        If the thread is STILL running after that (a single probe is blocked in
        a driver call that can't be interrupted), the worker is ABANDONED to a
        module-level set instead of being destroyed — neither Qt parentage (it
        has none) nor Python GC can then destroy a live QThread and abort the
        process. ``_closed`` guards any late queued result signals from touching
        now-dead widgets.
        """
        self._closed = True
        worker = self._worker
        if worker is not None:
            try:
                worker.requestInterruption()
                try:
                    worker.result_ready.disconnect(self._on_snapshot_result)
                    worker.finished.disconnect(self._on_worker_finished)
                except (RuntimeError, TypeError):
                    pass
                if worker.isRunning():
                    worker.wait(3000)
                if worker.isRunning():
                    # Bounded wait expired with a probe still blocking run():
                    # detach it so it can never be destroyed while running.
                    _abandon_worker(worker)
                    self._worker = None
            except RuntimeError:
                # Worker C++ object already gone — nothing to stop.
                pass

    def showEvent(self, event):
        """Reset the teardown guard so a reopened section can refresh again.

        Finding 1(d): ``_closed`` used to persist after closeEvent, which
        disabled refresh forever once the section had been closed and then
        shown again (the padlock/settings dialog reuses the same widget). Clear
        it here and re-probe if the rows never reached a terminal state.
        """
        super().showEvent(event)
        if self._closed:
            self._closed = False
            self._refresh_pending = False
            # Re-probe: rows may be stale ("Checking…") or empty after a close
            # that interrupted the previous worker.
            stale = any(
                bool(refs["status_lbl"].property(_CHECKING_PROP))
                for refs in self._rows.values())
            if stale or not self._rows:
                self.refresh_snapshots()

    def closeEvent(self, event):
        self._teardown_worker()
        super().closeEvent(event)

    def _on_snapshot_result(self, name, snapshot, generation=None):
        if self._closed:
            return
        # Finding F3 (round-3): reject a stale worker's already-posted delivery.
        # A queued result emitted before disconnect still arrives; if a rapid
        # close/reopen has since minted a new worker (generation bumped), this
        # older payload must NOT update the reopened section. ``generation`` is
        # None only for legacy/direct callers, which are always current.
        if generation is not None and generation != self._worker_generation:
            return
        refs = self._rows.get(name)
        if refs is None:
            return
        rendered = render_provider_row(name, snapshot, refs["is_session"],
                                       settings=self._settings,
                                       is_local=refs.get("is_local", False))
        refs["status_lbl"].setText(rendered["status_label"])
        refs["status_lbl"].setProperty(_CHECKING_PROP, False)
        refs["status_color"] = rendered["color"]
        refs["status_lbl"].setStyleSheet(_status_tier_style(rendered["color"]))
        refs["dot"].setStyleSheet(_status_tier_style(rendered["color"]))
        detail = rendered["detail"] or rendered["hint"] or refs["subtitle"] or ""
        refs["detail_lbl"].setText(detail)
        if refs.get("is_local"):
            self._update_local_row(refs)
        # Refresh the masked placeholder in case the key changed elsewhere.
        if refs["key_edit"] is not None and refs["canonical_key"]:
            existing = self._stored_row_key(refs)
            if refs.get("override_note"):
                refs["key_edit"].setPlaceholderText(refs["override_note"])
            elif existing:
                refs["key_edit"].setPlaceholderText(
                    self._settings._mask_key(existing))

    def _stored_row_key(self, refs):
        """The key stored for the row's current choice (any name it owns)."""
        names = (refs["canonical_key"],)
        if refs.get("choice_combo") is not None:
            from core.ai_engines import catalog as _catalog
            names = next((owned for w, _l, owned in _catalog.GLM_PAYG_CHOICES
                          if w == refs["canonical_key"]), names)
        return next((v for v in (self._settings.get_api_key(n) for n in names)
                     if v), "")

    def _drop_other_choice_keys(self, refs, canonical):
        """One key per row: remove the row's other env names from .env, so a
        key saved earlier under the other issuer cannot keep winning the GLM
        route. The .env FILE is checked, not the process-overlaid value: an
        empty process variable can mask a disk key that would come back.
        Returns ``(ok, name)``, ``name`` being a process environment variable
        that still outranks the saved key (the app cannot unset it), or ""."""
        import os
        from core.ai_engines import catalog as _catalog
        own = next((names for w, _l, names in _catalog.GLM_PAYG_CHOICES
                    if w == canonical), (canonical,))
        ok = True
        for other in refs.get("owned_keys") or ():
            if other == canonical:
                continue
            try:
                on_disk = self._settings.has_api_key_on_disk(other)
            except EnvUnreadableError:
                on_disk = True
            if on_disk:
                ok = self._settings.set_api_key(other, "") and ok
        env = {n: self._settings.get_api_key(n)
               for kind, n, _u, _s in _catalog.GLM_ROUTES if kind == "env"}
        _choice, held_in, _source = _catalog.glm_payg_state(env)
        overridden = (held_in if held_in and held_in not in own
                      and os.environ.get(held_in) else "")
        return ok, overridden

    def _on_key_choice_changed(self, name):
        """The issuer choice moved: the row now writes that env name."""
        refs = self._rows.get(name)
        if refs is None or refs.get("choice_combo") is None:
            return
        refs["canonical_key"] = refs["choice_combo"].currentData()
        refs["override_note"] = ""
        existing = self._stored_row_key(refs)
        refs["key_edit"].setPlaceholderText(
            self._settings._mask_key(existing) if existing
            else f"Not set ({refs['canonical_key']})")

    # --------------------------------------------------------------- keys ---

    def _on_save_key(self, name):
        refs = self._rows.get(name)
        if refs is None or refs["key_edit"] is None:
            return
        value = refs["key_edit"].text().strip()
        canonical = refs["canonical_key"]
        if not value:
            # Finding F4(b) (round-3): the ONLY reachable clear path. There is
            # no separate clear widget, so a blank Save on a row that HAS a
            # stored key is treated as an explicit clear — set_api_key("") drops
            # the canonical key and every legacy alias atomically. A blank Save
            # with nothing stored is a harmless no-op.
            #
            # Round-4 F2: the "does a stored key exist to clear?" decision must
            # read the ON-DISK .env directly (has_api_key_on_disk), NOT the
            # process-overlaid get_api_key(): a disk secret masked by an
            # empty process var still exists and must remain clearable.
            # Round-5 F2: has_api_key_on_disk now RAISES when the .env exists
            # but is unreadable (permissions / corruption) instead of falsely
            # returning "absent". Surface that rather than silently no-op'ing —
            # otherwise a real on-disk secret would look un-clearable.
            # Catch ONLY EnvUnreadableError — a bare `except Exception` would
            # reclassify unrelated failures (programming bugs, unexpected
            # OSErrors) as ".env unreadable", masking real bugs behind a
            # misleading message. Anything else must propagate.
            try:
                exists = any(self._settings.has_api_key_on_disk(n)
                             for n in refs.get("owned_keys") or (canonical,)
                             if n)
            except EnvUnreadableError:
                refs["key_edit"].setPlaceholderText(
                    "Could not read stored key (.env unreadable)")
                return
            if not exists:
                return
            # Round-4 F1: the key field is always rendered empty (masking), so a
            # blank Save with a stored key would otherwise DELETE the persisted
            # key + all aliases with zero confirmation — a real accidental-loss
            # path. Confirm before the destructive clear. The dialog is
            # transient (no new persistent widget).
            #
            # Round-5 F1: guard _closed BOTH sides of the modal. QMessageBox
            # spins a NESTED event loop; a closeEvent/aboutToQuit during it runs
            # _teardown_worker() (sets _closed). Without the re-check, clicking
            # Yes afterwards would call set_api_key + touch row widgets on an
            # already-torn-down section.
            if self._closed:
                return
            reply = QMessageBox.question(
                self, "Clear API key",
                f"Clear the stored API key for {name}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            if self._closed:
                # The section was torn down while the modal was open — abort
                # before touching set_api_key or any (possibly-deleted) widget.
                return
            ok = all([self._settings.set_api_key(n, "")
                      for n in refs.get("owned_keys") or (canonical,)])
            refs["key_edit"].setText("")
            refs["key_edit"].setPlaceholderText(
                f"Not set ({canonical})" if ok else "Clear failed")
            self.refresh_snapshots()
            return
        ok = self._settings.set_api_key(canonical, value)
        overridden = ""
        if ok and refs.get("choice_combo") is not None:
            ok, overridden = self._drop_other_choice_keys(refs, canonical)
        if ok and not overridden:
            # A system environment variable outranks the .env (read_env):
            # say so by name, or the row would show a key the app ignores.
            import os
            process = os.environ.get(canonical)
            if process and process != value:
                overridden = canonical
        # INV-4 (finding 8): wipe the editable text with setText("") — NOT
        # clear(), which leaves the raw key recoverable via Qt's undo history
        # (Ctrl+Z would restore the secret). setText("") resets undo/redo.
        refs["key_edit"].setText("")
        refs["override_note"] = (
            f"Saved, but {overridden} in your system environment is used first"
            if ok and overridden else "")
        refs["key_edit"].setPlaceholderText(
            "Save failed" if not ok
            else refs["override_note"] or self._settings._mask_key(value))
        # Re-probe just this row's status (key presence changed).
        self.refresh_snapshots()

    # ----------------------------------------------------------- defaults ---

    @_own_write
    def _on_default_changed(self, *args):
        # Driven by currentIndexChanged (finding F5(a)); read the display text
        # directly instead of trusting a text argument.
        if self._suppress_default_save:
            return
        # Finding 7 / 6(c): the "<name> (unavailable)" sentinel must never
        # persist and must never overwrite the stored (stale) value on its own.
        # Detect it by its private item-data role, never by matching text.
        cur = self.default_combo.currentIndex()
        if self.default_combo.itemData(cur, _SENTINEL_ROLE) == _SENTINEL_MARKER:
            return
        name = self.default_combo.currentData()  # the provider name (INV-3)
        if not name:
            return
        # A real pick supersedes the stale persisted value: drop the sentinel
        # entry (so it can't be re-selected) and persist the chosen provider.
        if self._unavailable_default is not None:
            sidx = next(
                (i for i in range(self.default_combo.count())
                 if self.default_combo.itemData(i, _SENTINEL_ROLE)
                 == _SENTINEL_MARKER),
                -1)
            if sidx >= 0:
                self._suppress_default_save = True
                self.default_combo.removeItem(sidx)
                self._suppress_default_save = False
            self._unavailable_default = None
        self._settings.set("ai.default_provider", name)
        self._sync_default_model_label()

    def _sync_default_model_label(self):
        """Show the model id the selected chat provider resolves to. Session
        providers (Claude/Codex) have no key-table id — their model is chosen
        by the vendor CLI/subscription, shown as such."""
        if not hasattr(self, "_default_model_label"):
            return
        cur = self.default_combo.currentIndex()
        unavailable = (self.default_combo.itemData(cur, _SENTINEL_ROLE)
                       == _SENTINEL_MARKER)  # by role, not text (INV-3)
        name = self.default_combo.currentData() or ""
        cfg = None
        try:
            cfg = self._backend.builtin_key_provider_config(
                self._backend.canonical_provider_name(name))
        except Exception:
            cfg = None
        session_id = next((mid for a in self._backend.builtin_accounts()
                           if getattr(a, "driver_name", None)
                           for display, mid in a.models if display == name), None)
        if unavailable:
            self._default_model_label.setText("Model: (unavailable)")
        elif session_id:
            self._default_model_label.setText(f"Model: {session_id}")
        elif cfg is not None:
            if cfg.get("env_key") is None:
                from core.local_ai_config import local_provider_config
                cfg = local_provider_config(cfg, self._settings)
            self._default_model_label.setText(f"Model: {cfg.get('model')}")
        else:
            self._default_model_label.setText(
                "Model: session (set by the provider CLI / subscription)")

    def _build_app_settings_toggle(self, theme):
        """The D-14 toggle row: the approved label and help line (the
        registry entry's), default off. Shared by Core, Lite and Pro."""
        from PySide6.QtWidgets import QCheckBox
        entry = _registry.get(APP_SETTINGS_TOGGLE)
        box = QWidget()
        row = QVBoxLayout(box)
        row.setContentsMargins(2, 0, 0, 0)
        row.setSpacing(4)
        self.app_settings_toggle = QCheckBox(entry.label)
        self.app_settings_toggle.setToolTip(entry.help)
        self.app_settings_toggle.setChecked(self._app_settings_toggle_value())
        # clicked: the user's own click only, never a programmatic re-sync
        self.app_settings_toggle.clicked.connect(self._on_app_settings_toggle)
        row.addWidget(self.app_settings_toggle)
        self._app_settings_help = QLabel(entry.help)
        self._app_settings_help.setWordWrap(True)
        self._app_settings_help.setStyleSheet(f"color: {theme['secondary_text']};")
        row.addWidget(self._app_settings_help)
        # A failed save of the toggle (W6b fix F4): the structured state is
        # ``app_settings_toggle_state``; the line shows only approved words
        # (cli_text gate), and stays hidden while its copy is pending.
        self.app_settings_toggle_state = None
        self._app_settings_status = QLabel("")
        self._app_settings_status.setWordWrap(True)
        self._app_settings_status.setVisible(False)
        row.addWidget(self._app_settings_status)
        # AI setting redesign (td-bztjj) item 7 and SPEC-FIND-006 §4.1: the
        # AI setting panel's model and the Find Chart AI search's model.
        from core.edition_features import ai_features
        ai_features().add_model_rows(self, row)
        return box

    def _app_settings_toggle_value(self) -> bool:
        """What is in effect: the SAVED file's value, read fresh (another
        window may have switched it; the request service reads the file
        too), else this manager's value, else off."""
        from core.settings_registry import app_requests as _ar
        path = getattr(self._settings, "_config_path", None)
        saved = _ar.read_saved(path) if path else None
        if saved is not None:
            return _ar.toggle_on(saved)
        return self._settings.get(APP_SETTINGS_TOGGLE,
                                  _registry.default(APP_SETTINGS_TOGGLE)) is True

    @_own_write
    def _on_app_settings_toggle(self, checked):
        """The ONLY writer of ai.allow_app_settings_changes (INV-17, D-17).

        W6b fix F4: the value is shown only once it is durable. The save is
        synchronous; when it fails, the in-memory value is restored and the
        pending write dropped (a later unrelated save can never flush it),
        the checkbox goes back to the SAVED value (a revocation that did not
        reach the file is not displayed as done) and the failure is recorded
        as a structured state, shown through the pending-copy gate."""
        from managers.settings_write import write_or_restore
        value = bool(checked)
        ok, error = write_or_restore(self._settings, APP_SETTINGS_TOGGLE, value)
        if ok:
            self._settings._notify_change(APP_SETTINGS_TOGGLE, value)
            self._show_app_settings_toggle_state(None)
            return
        saved = self._app_settings_toggle_value()
        self.app_settings_toggle.setChecked(saved)        # setChecked: no clicked signal
        self._show_app_settings_toggle_state(
            {"code": "toggle.save_failed", "requested": value, "saved": saved,
             "error": error})

    def _show_app_settings_toggle_state(self, state):
        """Record the toggle row's last outcome (None = saved). The status
        line carries the approved wording only (``cli_text.TEXT``); while
        the key is pending it stays hidden (never a marker, never a code)."""
        from core.settings_registry import cli_text
        self.app_settings_toggle_state = state
        label = getattr(self, "_app_settings_status", None)
        if label is None:
            return
        if state is None or cli_text.is_pending(state["code"]):
            label.setText("")
            label.setVisible(False)
            return
        label.setText(cli_text.message(state["code"]))
        label.setVisible(True)

    @_own_write
    def _on_chat_effort_changed(self, *args):
        """Persist ai.effort (minimal/low/medium/high). Suppressed during the
        construction-time restore so loading a value never re-writes it."""
        if getattr(self, "_suppress_chat_effort_save", False):
            return
        val = self.chat_effort_combo.currentData()
        if val:
            self._settings.set("ai.effort", val)

    def _sync_vision_model_label(self):
        """Show the model id the current vision selection resolves to."""
        if not hasattr(self, "_vision_model_label"):
            return
        name = self.vision_combo.currentData()  # None on the unavailable row
        cfg = self._vision_configs.get(name)
        override = self._settings.get("vision.model", "")
        if cfg is None:
            self._vision_model_label.setText("Model: (unavailable)")
        else:
            from core.local_ai_config import local_provider_config
            cfg = local_provider_config(cfg, self._settings)
            model = override or cfg.get("vision_model") or cfg.get("model")
            self._vision_model_label.setText(f"Model: {model}")

    @_own_write
    def _on_vision_provider_changed(self, *args):
        """Persist vision.provider; reset vision.model to the provider's
        registry default (empty override)."""
        if getattr(self, "_suppress_vision_save", False):
            return
        name = self.vision_combo.currentData()  # the provider name (INV-3)
        if not name or name not in self._vision_configs:
            return  # never persist the "(unavailable)" surface entry
        self._settings.set("vision.provider", name)
        self._settings.set("vision.model", "")
        self._sync_vision_model_label()

    @_own_write
    def _on_vision_effort_changed(self, *args):
        """Persist vision.effort (minimal/low/medium/high). Suppressed during
        the construction-time restore so loading a value never re-writes it."""
        if getattr(self, "_suppress_effort_save", False):
            return
        val = self.vision_effort_combo.currentData()
        if val:
            self._settings.set("vision.effort", val)

    def _read_from_settings(self):
        """Re-sync the default combo from settings (focus refresh hook)."""
        for refs in self._rows.values():
            for label in refs.get("local_labels", ()):
                label.setStyleSheet(_provider_detail_lbl_style())
            if refs.get("is_local"):
                from core.local_ai_config import local_server_values
                values = local_server_values(self._settings)
                current = (refs["url_edit"].text(), refs["model_edit"].text())
                if current == refs.get("local_saved"):
                    refs["url_edit"].setText(values["url"])
                    refs["model_edit"].setText(values["model"])
                    refs["local_saved"] = (values["url"], values["model"])
                self._update_local_row(refs)
        if hasattr(self, "app_settings_toggle"):
            self.app_settings_toggle.setChecked(self._app_settings_toggle_value())
        names = [self.default_combo.itemData(i)
                 for i in range(self.default_combo.count())]
        stored = self._backend.canonical_provider_name(
            self._settings.get("ai.default_provider", "") or "")
        if stored and stored in names:
            self._suppress_default_save = True
            select_by_data(self.default_combo, stored)
            self._suppress_default_save = False
        self._sync_default_model_label()
        if hasattr(self, "vision_combo"):
            try:
                stored_v = self._backend.canonical_provider_name(
                    self._settings.get("vision.provider", ""))
            except Exception:
                stored_v = self._settings.get("vision.provider", "")
            vnames = [self.vision_combo.itemData(i)
                      for i in range(self.vision_combo.count())]
            if stored_v and stored_v in vnames:
                self._suppress_vision_save = True
                select_by_data(self.vision_combo, stored_v)
                self._suppress_vision_save = False
            self._sync_vision_model_label()

    # ----------------------------------------------------------- theming ---

    def refresh_theme(self):
        """Restyle theme-driven surfaces (semantic status colours untouched)."""
        theme = get_theme_colors()
        if hasattr(self, "_default_desc"):
            self._default_desc.setStyleSheet(
                f"color: {theme['secondary_text']};")
        for _lbl_attr in ("_default_model_label", "_chat_effort_label"):
            if hasattr(self, _lbl_attr):
                getattr(self, _lbl_attr).setStyleSheet(
                    f"color: {theme['secondary_text']};")
        for _combo_attr in ("default_combo", "vision_combo",
                            "chat_effort_combo", "vision_effort_combo"):
            if hasattr(self, _combo_attr):
                getattr(self, _combo_attr).setStyleSheet(_settings_combo_style())
        if hasattr(self, "_vision_desc"):
            self._vision_desc.setStyleSheet(
                f"color: {theme['secondary_text']};")
        if hasattr(self, "_vision_model_label"):
            self._vision_model_label.setStyleSheet(
                f"color: {theme['secondary_text']};")
        if hasattr(self, "_vision_effort_label"):
            self._vision_effort_label.setStyleSheet(
                f"color: {theme['secondary_text']};")
        if hasattr(self, "_app_settings_help"):
            self._app_settings_help.setStyleSheet(
                f"color: {theme['secondary_text']};")
        for refs in self._rows.values():
            # Card chrome is theme-driven (secondary/secondary_light) — replay
            # it like the labels below so a live theme switch can't strand the
            # old palette on the row boxes.
            frame = refs.get("frame")
            if frame is not None:
                frame.setStyleSheet(_provider_card_style())
            refs["name_lbl"].setStyleSheet(_provider_name_lbl_style())
            # Detail label only carries the theme colour when it's a subtitle /
            # detail; status colours on status_lbl/dot are semantic — but their
            # SIZE (status area) must still be replayed, preserving the live
            # semantic colour stored in refs['status_color'] (MED-1).
            refs["detail_lbl"].setStyleSheet(_provider_detail_lbl_style())
            for label in refs.get("local_labels", ()):
                label.setStyleSheet(_provider_detail_lbl_style())
            _status_qss = _status_tier_style(refs.get("status_color", _PROV_AMBER))
            refs["dot"].setStyleSheet(_status_qss)
            refs["status_lbl"].setStyleSheet(_status_qss)
            models_lbl = refs.get("models_lbl")
            if models_lbl is not None:
                models_lbl.setStyleSheet(_prov_models_caption_style())
            # td-2o8u O-6 rider: replay the migrated "API key:" label font so a
            # live font/scale change re-sizes it (width re-derived below).
            key_lbl = refs.get("key_lbl")
            if key_lbl is not None:
                key_lbl.setStyleSheet(f"font-size:{scaled_area_px('info_text')}px;")
            if refs.get("choice_combo") is not None:
                refs["choice_combo"].setStyleSheet(_settings_combo_style())
            if refs.get("choice_lbl") is not None:
                refs["choice_lbl"].setStyleSheet(
                    f"font-size:{scaled_area_px('info_text')}px;")
        # Subgroup headings/help (info_text area) — replay font+colour (MED-2).
        for _w, _fn in self._group_labels:
            _w.setStyleSheet(_fn())
        for btn in self._secondary_buttons:
            btn.setStyleSheet(get_secondary_button_style())
        for btn in self._primary_buttons:
            btn.setStyleSheet(get_primary_button_style())
        _rederive_width_caps(self)  # td-2o8u FIX-H live re-derivation
        _reapply_title_fonts(self._title_widgets)


# Public shared name used by the Lite settings navigator.  Pro keeps the
# historical private alias for compatibility with its focused tests.
AIProviderSettings = _AIProvidersSection
