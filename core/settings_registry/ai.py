# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""AI provider, vision and transit preferences (SPEC-SET-003). Defaults moved from
DEFAULT_SETTINGS["ai"], ["vision"], ["transit"]; values unchanged. The provider and
vision keys are Core (D-17, D-24: the Core and Lite AI Settings page shows them);
the transit key is Pro (plain data: the factory table holds every key in Core)."""
from dataclasses import replace

from core.settings_registry.rules import APP, APP_AI, APP_PROTECTED
from core.settings_registry.schema import Choice, ChoicesRef, NoneType, Setting

# Provider and model names come from the provider registry at run time: checked
# there at use, never by a copied list (spec §3.1).
_V = "core.settings_registry.validators:"
_CATALOG = replace(APP_AI, validate=_V + "catalog_name")
# The values the live endpoints accept, labels as in the AI Settings combos
# ("minimal" is gone: every current model rejects it).
_EFFORTS = (Choice("none", "None"), Choice("low", "Low"), Choice("medium", "Medium"),
            Choice("high", "High"), Choice("xhigh", "Extra high"))

SETTINGS = (
    # Transit panel (Pro) preferences.
    #   reading_date_use_ai (SPEC-TRN-005 B2): the ✨ engine selector on the
    #     reading-date paste field. False (default) = offline regex engine only
    #     (INV-1, hermetically offline, images refused); True = LLM engine only
    #     (INV-2). Persisted so the operator's engine choice survives restart.
    Setting("transit.reading_date_use_ai", bool, False, edition="pro", rules=APP_AI),
    # AI provider layer (Pro) — SPEC-PROV-001 §4 / plan task A5.
    #   default_provider: the provider the AI Tools chat (and the reading-date
    #     LLM path) are INTENDED to select by default. Persisted so the
    #     operator's choice survives restart. The value is a REGISTRY PROVIDER
    #     NAME (e.g. "DeepSeek", "Claude", "Codex"), NOT an env-key. NOTE: as of
    #     A5 this setting is written by the settings UI but NOT yet consumed at
    #     runtime — exploration_chat_manager still hardcodes its default. Wiring
    #     it as the chat manager's initial provider is C1 (registry cutover)
    #     scope (bead td-dnbs C1). When the stored name is no longer registered
    #     the settings section surfaces it EXPLICITLY as a disabled
    #     "<name> (unavailable)" combo entry (not a silent first-item fallback),
    #     leaving the stale value persisted until the user picks a real one.
    Setting("ai.default_provider", str, "DeepSeek", label="Default chat model",
            help="The provider used by default for AI chat and reading-date parsing.",
            rules=_CATALOG),
    Setting("ai.local_server", dict,
            {"url": "http://localhost:1234/v1", "model": "qwen/qwen3.5-9b"},
            persisted=False, label="Local AI server",
            help="Server address and model ID for LM Studio or another OpenAI-compatible local server.",
            rules=replace(APP_PROTECTED, validate="core.local_ai_config:local_ai_server")),
    # Vision model for IMAGE extraction (SPEC-TRN-005 reading-date paste) —
    # deliberately SEPARATE from ai.default_provider (the chat/text provider):
    # image extraction is a simple OCR-ish task (read a birth date/time/place
    # off a screenshot) best served by a dedicated cheap keyed vision model,
    # while chat may run on a session provider (Claude CLI) that cannot take
    # images at all.
    #   provider: a vision-capable provider name from
    #     pro.providers.registry.vision_provider_configs() (e.g. "GPT-5.4
    #     Mini", "Kimi K2.6", "Anthropic API"). Default is a keyed OpenAI
    #     vision model — NOT Anthropic, whose key is typically absent.
    #   model: explicit model id override; "" = the provider's registry
    #     vision_model default.
    #   effort: reasoning effort for providers that support the knob
    #     (minimal|low|medium|high). "medium" is plenty for extraction.
    Setting("vision.provider", str, "GPT-5.4 Mini", label="Vision Model (image extraction)",
            help="The model that reads pasted images and screenshots (chart import). "
                 "Separate from the chat provider above.", rules=_CATALOG),
    Setting("vision.model", str, "", rules=_CATALOG),
    Setting("vision.effort", str, "medium", label="Reasoning effort:",
            help="How hard the vision model thinks before answering. Applies to the "
                 "GPT-5 family; ignored by Claude/Kimi vision. Medium is plenty for "
                 "reading a date from a screenshot.", choices=_EFFORTS, widget="combo",
            rules=APP_AI),
    # Chat and reading reasoning effort (AI Settings page). In
    # DEFAULT_SETTINGS since SPEC-SET-003 W11 (V-6): its factory value is the
    # "medium" every reader fell back to (canonical_effort).
    Setting("ai.effort", str, "medium", label="Reasoning effort:",
            help="How hard the chat/reading model thinks before answering. Applies "
                 "to the GPT-5 family; ignored by Claude/Codex sessions.",
            choices=_EFFORTS, widget="combo", rules=APP_AI),
    # AI capture (SPEC-AIC-001, Core). Absent from DEFAULT_SETTINGS, so fallback-
    # only with each reader's own fallback (no saved file changes):
    #   capture_hotkey: apps/ai_capture/entry_points.py (checked against the app's
    #     shortcuts when set); task.engine: the remembered engine, None = the
    #     default provider's family, else the first installed (core/ai_capture/
    #     models.py); task.<engine>.model / .effort: the remembered pick. Claude's
    #     lists are fixed tables; Codex's come from the installed Codex at run time.
    Setting("ai.capture_hotkey", str, "Ctrl+Alt+S", persisted=False,
            rules=replace(APP_AI, validate=_V + "shortcut")),
    Setting("ai.task.engine", (str, NoneType), None, persisted=False,
            choices=(Choice(None), Choice("claude", "Claude"), Choice("codex", "Codex"),
                     Choice("glm", "GLM"), Choice("api", "API"), Choice("local", "Local LLM")),
            rules=APP_AI),
    Setting("ai.task.claude.model", str, "opus", persisted=False,
            choices=ChoicesRef("core.ai_capture.models:CLAUDE_MODELS"), rules=APP_AI),
    Setting("ai.task.claude.effort", str, "medium", persisted=False,
            choices=ChoicesRef("core.ai_capture.models:CLAUDE_EFFORTS"), rules=APP_AI),
    Setting("ai.task.codex.model", (str, NoneType), None, persisted=False, rules=_CATALOG),
    Setting("ai.task.codex.effort", str, "medium", persisted=False, rules=_CATALOG),
    # The GLM Coding Plan's and the API-key models' remembered pick (td-2nxmo):
    # a model name of core/ai_engines/catalog; the list depends on the keys
    # present, so it is read at run time.
    Setting("ai.task.glm.model", (str, NoneType), None, persisted=False, rules=_CATALOG),
    Setting("ai.task.api.model", (str, NoneType), None, persisted=False, rules=_CATALOG),
    # The Local LLM's pick: "configured" (the ai.local_server model), a fixed
    # local setup of core/local_ai_config.LOCAL_PRESETS (Bionic Qwen 80K), or a
    # model found on a local server, "<server>:<model>" (core/local_ai_discovery).
    Setting("ai.task.local.model", (str, NoneType), None, persisted=False, rules=_CATALOG),
    # Other dynamic writers' keys (W3e census), app preferences absent from
    # DEFAULT_SETTINGS: the HD frame notice mute (apps/widgets/hd/hd_frame_notice.py),
    # the New & Edit and Transit reading-date AI toggles' siblings.
    Setting("ui.hd_frame_notice_hidden", bool, False, persisted=False, rules=APP),
    # AI setting redesign (td-bztjj): the AI setting panel's model (item 7,
    # "<engine>:<model>", "" = automatic; core/ai_capture/setting_panel_model)
    # and the screenshot pop-up's "Don't show this again" (item 8: the user's
    # own answer, never the AI's to change).
    Setting("ai.setting_panel.model", str, "", persisted=False, label="AI setting model",
            rules=_CATALOG),
    # The Find Chart AI search's model (SPEC-FIND-006 §4.1,
    # core/ai_capture/find_chart_model): "claude:<model>", "glm:<model>",
    # "api:<model>", "local:", "" = automatic.
    Setting("ai.find_chart.model", str, "", persisted=False, label="AI search model",
            rules=_CATALOG),
    Setting("ui.ai_settings_screenshot_notice_hidden", bool, False, persisted=False,
            rules=APP),
    # The AI coach and hub (SPEC-COACH-001 §4.9): the hub's "Working with AI"
    # introduction seen once (then it starts closed), the coach's tones and
    # its step speed (the card's speed button).
    Setting("ai.hub_intro_seen", bool, False, persisted=False, rules=APP),
    Setting("ai.coach_sound", bool, True, persisted=False, rules=APP),
    # The coach's advanced mode (beta, the AI menu's switch, Lorris 2026-10-29):
    # every engine tool and the calculation commands; off = simple mode.
    Setting("ai.coach_advanced", bool, False, persisted=False, rules=APP),
    Setting("ai.coach_speed", float, 1.0, persisted=False,
            choices=(Choice(0.75, "0.75×"), Choice(1.0, "1×"), Choice(1.5, "1.5×")),
            rules=APP_AI),
    Setting("newedit.reading_use_ai", bool, False, persisted=False, rules=APP_AI),
    Setting("transit.reading_date_auto_confirm", bool, False, persisted=False,
            edition="pro", rules=APP_AI),
    # Protected keys (SPEC-SET-003 INV-17, D-17): written only by their own
    # control, never by settings.py, --set, the request service or an AI Reset.
    # Absent from DEFAULT_SETTINGS, so fallback-only (no saved file changes).
    #   consent_acknowledged: the AI capture window's one-time consent
    #     (apps/ai_capture/task_window.py CONSENT_SETTING).
    #   allow_app_settings_changes: the AI Settings toggle (D-14), off by
    #     default; its row is built in W6b.
    Setting("ai.consent_acknowledged", bool, False, persisted=False, rules=APP_PROTECTED),
    # Label and help approved by Lorris 2026-10-05 (SPEC-SET-003 §4.5, D-14):
    # the row on the AI Settings page (ui/ai_provider_settings.py, W6b).
    Setting("ai.allow_app_settings_changes", bool, False, persisted=False,
            label="Let the AI change the app's settings",
            help="Off: an AI can read your settings but not change them. On: an AI "
                 "you ask can change them for you.",
            widget="check", rules=APP_PROTECTED),
    # AI apps outside Varuna360 (SPEC-LMCP-001 §4.8, D-7): the switches of the
    # AI → Connect AI apps dialog. Protected: an AI can never widen its own
    # access. Draft wording, for Lorris's review.
    Setting("ai.mcp.enabled", bool, False, persisted=False,
            label="Let AI apps on this computer use Varuna360",
            help="Claude Desktop, Claude Code, Codex and other AI apps you connect can "
                 "calculate charts with Varuna360.",
            widget="check", rules=APP_PROTECTED),
    Setting("ai.mcp.library_access", bool, False, persisted=False,
            label="Let them search and read my chart library",
            widget="check", rules=APP_PROTECTED),
    Setting("ai.mcp.allow_show_charts", bool, False, persisted=False,
            label="Let them show charts in the Varuna360 window",
            widget="check", rules=APP_PROTECTED),
    # SPEC-LMCP-001 §4.10, D-23: the window actions (tabs, chart style,
    # divisional charts, transits, dashas). Changes the app remembers also
    # need ai.allow_app_settings_changes (D-26).
    Setting("ai.mcp.allow_window_control", bool, False, persisted=False,
            label="Let them work the Varuna360 window: tabs, chart style, "
                  "divisional charts, transits, dashas",
            widget="check", rules=APP_PROTECTED),
)
