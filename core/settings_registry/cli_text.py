# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The words the command-line settings surface prints (SPEC-SET-003 D-21).

``TEXT`` holds only wording Lorris approved: the D-15 advanced-mode
permission message, the D-14 refusal of ``settings.py set --app`` and the
D-17 protected-key message, verbatim from the spec (§4.5, INV-17), and the
D-21 drafts he approved on 2026-10-08 (the W6 settings.py texts and store
messages, the W6b endpoint and request texts), verbatim from
``proprietary_docs/docs/plans/set003_sessions/D21-help-drafts.md``. Every
other drafted key is PENDING: it is in ``PENDING_TEXT`` with the marker,
never the draft, and the CLI prints the structured form instead (the column
KEY as a header cell, the source KEY, ``<key>: <field>=<value> ...`` for a
message) so neither a marker nor an empty string ever reaches a screen. When
a section is approved, its lines move into ``TEXT`` under the same keys and
the gate renders them.

Qt-free, data only.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

COPY_PENDING = "[COPY PENDING]"

# Approved wording (verbatim; spec §4.5 D-15, D-14 and INV-17 D-17).
D15_ADVANCED_PERMISSION = (
    "Advanced mode lets any command change settings with --set. You may turn it on "
    "only if the user asked you to, in writing or by voice, in this conversation. If "
    "the user's request does not mention advanced mode, you do not have permission: "
    "ask the user and wait for a clear yes. Never turn it on by yourself.")
D14_APP_REFUSED = ("Changing the app's settings is switched off in the app. Only the "
                   "user can switch it on, in Settings.")
D17_PROTECTED = "This setting can only be changed by the user, in Settings."

TEXT: Dict[str, str] = {
    "advanced.permission": D15_ADVANCED_PERMISSION,
    "set.app_refused": D14_APP_REFUSED,
    "set.protected": D17_PROTECTED,
}

# Approved by Lorris on 2026-10-08 (D-21, section "APPROVAL" of
# D21-help-drafts.md): the W6 settings.py texts and store messages and the
# W6b endpoint and request texts, verbatim from the draft tables (SET-003
# W6d, td-gbiup). ``app.refused.<reason>`` is the sentence shown after the
# main ``app.refused`` line for that reason (``_FOLLOW_UPS``).
TEXT.update({
    'help.settings': "Shows and changes the calculation settings the command-line tools use. By default every tool follows the app's settings; a value set here outranks the app for the tools only, never for the app itself.",
    'help.list': "Lists every calculation setting with its allowed values, the app's value, the value the tools will use and where that value comes from.",
    'help.show': "Shows one setting in full: help, allowed values, the app's value, the tools' value and its source.",
    'help.set': "Sets a value for the command-line tools only. The app's own settings are not changed.",
    'help.unset': "Drops the tools' value for a setting; the tools follow the app again for it.",
    'help.reset': "Drops every tools' value, turns advanced mode off and repairs a damaged settings file.",
    'help.status': "Shows whether advanced mode is on, where the tools' settings file is, and any stored value that is being ignored.",
    'column.key': 'Setting',
    'column.choices': 'Allowed values',
    'column.app': 'App',
    'column.effective': 'Tools use',
    'column.source': 'From',
    'source.command': 'this command (--set)',
    'source.cli': "tools' settings",
    'source.live': 'app, running now',
    'source.settings': 'app, saved',
    'source.default': 'factory default',
    'store.bad_file': "The tools' settings file is damaged: {path}. Run `settings.py reset` to repair it; the damaged file is kept next to it.",
    'store.newer_version': "The tools' settings file was written by a newer version of the app: {path}. Update the app, or run `settings.py reset --discard-newer` to set it aside and start again.",
    'store.ignored_value': 'Ignored stored value for {key}: {reason}. The tools use the next value down instead.',
    'store.reset_done': "Tools' settings cleared. Advanced mode is off. {moved}",
    'store.reset_moved': 'The damaged file was moved to {path}.',
    'set.not_calculation': '{key} is not a calculation setting. settings.py only changes settings that change calculations and what the tools print.',
    'set.unknown_key': 'Unknown setting: {key}. Run `settings.py list` to see the settings.',
    'set.bad_value': '{value} is not allowed for {key}. Allowed: {choices}.',
    'set.unused_key': 'This command does not use {key}, so --set {key} would change nothing. It was refused.',
    'set.advanced_off': "--set needs advanced mode. Run `settings.py advanced on` first (it will ask the user's permission).",
    'advanced.on': 'Advanced mode is on since {since}. Every tool accepts --set key=value for one run.',
    'advanced.off': 'Advanced mode is off.',
    'set.app_context': "--set is not available inside the app: this command runs with the app's own settings. Change them in Settings, or run the command from a terminal.",
    'set.replay': '--set cannot be combined with a saved capture: a replay uses the settings frozen in the capture.',
    'settings.bad_app_block': 'The app passed this command a damaged settings block ({reason}). Nothing was computed. Restart the app and try again.',
    'store.busy': "The tools' settings file is in use by another command: {path}. Try again in a moment.",
    'store.write_failed': "The tools' settings file could not be written: {path} ({reason}). Nothing was changed. Check the free space and the permissions of that folder, then try again.",
    'set.factory': '--set cannot be combined with --factory-defaults: --factory-defaults uses the factory values only. Leave out one of the two.',
    'app.no_app': "No running copy of the app answered. Start the app, or run the command again without --app to change the tools' settings only.",
    'app.not_saved': 'The app accepted the change but could not save its settings file. Nothing was changed.',
    'app.stale': '{key} has changed in the app since you read it (now {current}). Read it again before changing it.',
    'app.applied': 'Changed {key} in the app to {value}.',
    'app.locked': '{key} is locked in the app. Only the user can unlock it, in Settings.',
    'app.window_closed': 'The window this conversation belongs to has closed. The setting was not changed.',
    'app.offline_applied': 'The app is not running: changed {key} to {value} in the saved settings. The app will use it when it starts.',
    'app.busy': "Another change to the app's settings is in progress. Try again in a moment.",
    'app.refused': 'The app refused the change ({reason}).',
    'app.refused.target_gone': 'The copy of the app that was running when the command started has closed.',
    'app.refused.timeout': 'The app did not answer within 10 seconds. It may or may not have applied the change: read the setting again before retrying.',
    'app.refused.bad_request': 'The request was not understood.',
    'app.refused.duplicate_id': 'This request was already answered.',
    'app.refused.seen_without_app': '--seen only makes sense with --app.',
    'app.endpoint_unavailable': 'The app is running but cannot take requests right now. Change the setting in the app, or close the app and run the command again.',
    'toggle.save_failed': 'The change could not be saved. The switch shows the saved value.',
    'startup.waiting_for_settings_lock': 'Waiting for another program to finish writing the settings file.',
})

# Approved by Lorris on 2026-10-10 (D-21, section "W6c in-app AI settings
# pill" of D21-help-drafts.md): the pill and its text-only panel, verbatim.
# ``panel.ai_settings.engine_failed`` has no placeholder: the engine's error
# is data (the panel's ``errors`` and the log), never part of the sentence.
TEXT.update({
    'pill.ai_settings': 'AI setting',
    'pill.ai_settings_tip': "Ask the AI to change one of the app's settings",
    'panel.ai_settings.title': 'Ask the AI to change a setting',
    'panel.ai_settings.prompt_placeholder': 'What do you want changed? (for example: show the outer planets, switch to sidereal with Lahiri)',
    'panel.ai_settings.send': 'Ask',
    'panel.ai_settings.answer': 'The AI answered:',
    'panel.ai_settings.no_engine': 'No AI engine is set up. Choose one in Settings, AI tab.',
    'panel.ai_settings.engine_failed': 'The AI could not answer. Nothing was changed.',
})

# AI setting redesign (td-bztjj, 2026-10-11): the panel's texts, approved by
# the orchestrator in the redesign brief (``proprietary_docs/docs/plans/
# set003_sessions/ai-setting-redesign.md``, section "Texts"), verbatim, and
# replacing the W6c placeholder. The four pop-up paragraphs are one text,
# separated by blank lines.
SCREENSHOT_POPUP_BODY = "\n\n".join((
    "Your screenshot is sent to the AI company you chose, for example Anthropic or "
    "OpenAI, so the AI can see what you mean.",
    "This is what already happens every day with the services you use: your emails go "
    "through Gmail or Outlook, your photos to Google Photos or iCloud, your files to "
    "Dropbox or OneDrive, your messages through WhatsApp or Messenger. All of them are "
    "kept on the servers of large companies, and most people stopped thinking about it "
    "long ago.",
    "Sending a picture to an AI works the same way. The word \"AI\" does not change "
    "where your data goes or who can see it.",
    "If you prefer not to share a chart, skip the screenshot and describe the change in "
    "words."))
TEXT.update({
    'panel.ai_settings.prompt_placeholder': 'What do you want changed? Type for suggestions, or paste a screenshot.',
    'panel.ai_settings.screenshot': 'Screenshot',
    'panel.ai_settings.screenshot_tip': 'Select an area of the screen to show the AI',
    'panel.ai_settings.screenshot_note': 'The screenshot goes to your AI provider, like a file you send by email.',
    'panel.ai_settings.screenshot_remove_tip': 'Remove the screenshot',
    'panel.ai_settings.screenshot_popup_title': 'About sending a screenshot',
    'panel.ai_settings.screenshot_popup_body': SCREENSHOT_POPUP_BODY,
    'panel.ai_settings.screenshot_popup_dont_show': "Don't show this again",
    'panel.ai_settings.ok': 'OK',
    'panel.ai_settings.model': 'Model',
    'settings.ai.panel_model': 'AI setting model',
    'app.changed': 'Changed {label} to {value}.',
    'panel.ai_settings.ask_first': 'The AI wants to change {label} to {value}.',
    'panel.ai_settings.allow': 'Allow',
    'panel.ai_settings.cancel': 'Cancel',
    'panel.ai_settings.nothing_changed': 'Nothing was changed.',
    'app.next_start': 'This applies the next time the app starts.',
})
# AI setting redesign: texts the brief did not give, written by the
# implementer, short and plain (listed in ai-setting-redesign-report.md for
# Lorris's review). ``app.ask_first`` is the reply to an ask-first change on
# any route but the panel's Allow (the AI reads it; a task window shows it).
TEXT.update({
    'app.ask_first': "This change needs the user's OK, given in the AI setting panel.",
    'panel.ai_settings.model_auto': 'Automatic',
    # item 6: the sentence a picked suggestion puts in the text box (the
    # user finishes it; nothing applies before Ask)
    'panel.ai_settings.suggest_change': 'Change {label} to',
    'panel.ai_settings.suggest_to': 'Change {label} to {value}',
})
# The AI setting conversation (td-80vqm, 2026-10-12): written by the
# implementer, short and plain, listed in ai-setting-conversation-report.md
# for Lorris's review. The busy Ask button, Stop, the conversation's history
# lines and its reset.
TEXT.update({
    'panel.ai_settings.working': 'Working...',
    'panel.ai_settings.stop': 'Stop',
    'panel.ai_settings.stopped': 'Stopped. Changes already made stay.',
    'panel.ai_settings.new_conversation': 'New conversation',
    'panel.ai_settings.new_conversation_tip': 'Forget the earlier requests and start again',
    # SPEC-AIR-001 wave 2 (drafted 2026-10-22 for Lorris's review).
    'panel.ai_settings.report': 'Report a problem',
    'panel.ai_settings.report_tip': 'Something went wrong? The AI can look into it and write a report for the developer',
    'panel.ai_settings.you_asked': 'You: {text}',
    'panel.ai_settings.ai_said': 'AI: {text}',
    # Voice feedback in the text box (drafted 2026-10-29 for Lorris's
    # review): the stage and its seconds while the microphone works; Stop
    # reuses ``panel.ai_settings.stop``.
    'panel.ai_settings.listening': 'Listening {seconds} s',
    'panel.ai_settings.transcribing': 'Writing what you said {seconds} s',
    'panel.ai_settings.stop_listening_tip': 'Stop listening and write what you said in the box',
})

# Keyed exactly as the D-21 draft section (W6 settings.py texts and store
# messages); the value is the marker, never the draft sentence.
_DRAFT_KEYS = (
    "help.settings", "help.list", "help.show", "help.set", "help.unset", "help.reset",
    "help.status",
    "column.key", "column.choices", "column.app", "column.effective", "column.source",
    "source.command", "source.cli", "source.live", "source.settings", "source.default",
    "store.bad_file", "store.newer_version", "store.ignored_value", "store.reset_done",
    "store.reset_moved",
    "set.not_calculation", "set.unknown_key", "set.bad_value", "set.unused_key",
    "set.advanced_off",
    "advanced.on", "advanced.off",
)
# Needed by W6 but absent from the draft section: the orchestrator drafts them
# (W6 report, questions). Pending like the rest.
_EXTRA_KEYS = (
    "set.app_context",        # --set given to a child process of the app
    "set.replay",             # --set given to a capture replay (frozen context)
    "settings.bad_app_block",  # VARUNA360_APP_SETTINGS present but incomplete
    "store.busy",             # the store's lock was held for 10 s
    "store.write_failed",     # the file system refused a store write (W6 review F3)
    "set.factory",            # --set given with --factory-defaults (W6 review F4)
    # SPEC-SET-003 W9: reverse_chart refuses Western sign names in the Aditya
    # Circle while the label set is Aditya (fields: position, value, keys).
    "reverse_chart.western_in_aditya",
    # SPEC-SET-003 W9 fix F1: the --help line of --input-zodiac (reverse_chart,
    # chtk_from_image): the coordinate system of the observed positions, an
    # input (D-9); omitted, the settings' frame.
    "help.input_zodiac",
    # SPEC-SET-003 W7 (V-17): show_dasha --from/--to while the side's panel
    # shows another dasha than Vimshottari (dasha.<side>.mode).
    "dasha.vimshottari_only",
    # SPEC-SET-003 W7 fix round 2: the --help line of show_zodiacal_releasing
    # --jd (the exact UT instant the deeper levels are expanded at, review N3).
    "help.zr_jd",
    # SPEC-SET-003 W7 fix round 2: the analysis report's entry for a dasha
    # side whose child gave no usable output (review N1; fields: side, mode,
    # child, reason, exit, timeout, status, stderr).
    "report.dasha_unavailable",
)
# W6b: the app settings request replies, keyed exactly as the D-21 draft
# section "W6b endpoint and request texts" (PENDING): printed by
# ``settings.py set --app`` and returned by the ``set_app_setting`` task tool
# in structured form until approved (core/settings_registry/app_requests.py).
_W6B_DRAFT_KEYS = (
    "app.no_app", "app.not_saved", "app.stale", "app.applied", "app.locked",
    "app.window_closed", "app.offline_applied", "app.busy",
)
# Needed by W6b but absent from that draft section (W6b report, questions):
# a refusal whose reason has no message of its own (duplicate request id,
# the chosen instance gone, timeout, a malformed request...).
_W6B_EXTRA_KEYS = (
    "app.refused",
    # W6b fix round 1: the toggle row's own save failed (F4; the GUI shows
    # nothing while pending, the structured state is on the row).
    "toggle.save_failed",
    # W6b fix F7: an app instance is running but its endpoint is not
    # reachable; settings.py set --app refuses instead of writing offline.
    "app.endpoint_unavailable",
    # W6b fix round 2: app startup waits for the settings-file lock longer
    # than 5 s (the startup signal shows no words while pending).
    "startup.waiting_for_settings_lock",
)
# SPEC-SET-003 W8 (the chart and render CLIs, td-dd193.15): messages that
# named a retired flag (--style, --si-style) now name the settings instead.
_W8_EXTRA_KEYS = (
    # render_chart: the app shows a view render_chart does not draw (fields:
    # view_type, drawn: the view drawn instead).
    "render.view_not_drawn",
    # render_chart / render_teaching_chart: an input option the resolved chart
    # view cannot draw (fields: option, view_type, south_indian_style).
    "render.needs_view",
    # SPEC-SET-003 W8 fix F2: show_avastha --birth-json names a setting in
    # the JSON (fields: fields, the JSON fields; settings, the keys they name).
    "avastha.birth_json_setting",
    # SPEC-SET-003 W8 fix F3: generate_analysis_report refuses a --set item
    # or tools' setting that a child not on the registry cannot take (fields:
    # keys, the frame entries that would differ; children).
    "report.set_not_forwardable",
    # SPEC-SET-003 W8 fix F9: the analysis report's entry for any child that
    # gave no usable output (fields: section, child, reason, exit, timeout,
    # status, stderr).
    "report.child_unavailable",
    # SPEC-SET-003 W8 fix F11: the --help line of batch_elements_extractor
    # --human-design (each chart's -88 Design chart).
    "help.batch_human_design",
    # SPEC-SET-003 W8 fix round 2, N4: an image CLI (render_chart,
    # render_teaching_chart, render_cards_of_truth) whose image write the file
    # system refused; exit 1 (fields: path, format).
    "render.image_not_written",
)
# SPEC-SET-003 W11 (compatibility, export and the remaining CLIs): structured
# failures of commands that no longer write or default a setting themselves.
_W11_EXTRA_KEYS = (
    # export_session_charts --write with no chart folder configured or
    # existing (V-1: the command never creates one and never saves a
    # setting; fields: keys, the settings that name the folder).
    "export.no_chart_folder",
)
# W6c: the in-app "AI settings" pill and its panel, keyed exactly as the D-21
# draft section "W6c in-app AI settings pill"; all approved on 2026-10-10
# (``TEXT`` above), so none is pending. The manual picker's two keys
# (``panel.ai_settings.pick_key``, ``panel.ai_settings.apply``) were dropped
# with the picker (the panel is text only). The panel's replies reuse the
# W6b ``app.*`` keys.
_W6C_DRAFT_KEYS = (
    "pill.ai_settings", "pill.ai_settings_tip",
    "panel.ai_settings.title", "panel.ai_settings.prompt_placeholder",
    "panel.ai_settings.send", "panel.ai_settings.answer",
)
# Needed by W6c but absent from that draft section (W6c report, questions).
_W6C_EXTRA_KEYS = (
    # The typed request cannot be sent: no AI engine (Claude, Codex) installed.
    "panel.ai_settings.no_engine",
    # The typed request's engine turn failed (the error is data, not shown).
    "panel.ai_settings.engine_failed",
)
# W6d fix round 1 (review F2): the approved ``set.bad_value`` sentence ends
# "Allowed: {choices}.", so the two refusals with no fixed list of values
# get their OWN keys, pending (structured) until Lorris approves their
# drafts (D21-help-drafts.md, "W6d fix round"). The approved
# ``set.bad_value`` is never printed without ``choices``.
_W6D_FIX_KEYS = (
    "set.bad_value.free_form",  # a bad value for a key without a fixed list (fields: key, value)
    "set.malformed_item",       # a --set item that is not key=value (field: item)
)
# Every key drafted for these surfaces is listed above; the ones with
# approved wording are in ``TEXT`` and so leave the pending table (W6d).
PENDING_TEXT: Dict[str, str] = {key: COPY_PENDING for key in (
    _DRAFT_KEYS + _EXTRA_KEYS + _W6B_DRAFT_KEYS + _W6B_EXTRA_KEYS + _W8_EXTRA_KEYS
    + _W6D_FIX_KEYS + _W6C_DRAFT_KEYS + _W6C_EXTRA_KEYS + _W11_EXTRA_KEYS)
    if key not in TEXT}


def is_pending(key: str) -> bool:
    return key not in TEXT


def bad_value_key(choices: Any) -> str:
    """The message key of a refused value: ``set.bad_value`` (approved, it
    names the allowed values) when there is a fixed list of them, else
    ``set.bad_value.free_form`` (W6d fix F2: the approved sentence is never
    printed without its ``{choices}``)."""
    return "set.bad_value" if choices else "set.bad_value.free_form"


def _field(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def structured(key: str, /, **fields: Any) -> str:
    """``<key>: <field>=<value> ...``: the machine form of a message."""
    parts = [f"{name}={_field(value)}" for name, value in fields.items() if value is not None]
    return key + (": " + " ".join(parts) if parts else "")


# A sentence shown after an approved line, chosen by one of its fields:
# ``app.refused`` is followed by ``app.refused.<reason>`` when that reason
# has a sentence of its own (D-21 W6b).
_FOLLOW_UPS = {"app.refused": "reason"}


# A field that lists the allowed values: its list is the enumeration
# "a,b,c" inside the approved words ("Allowed: {choices}."), never a value.
_ENUMERATION_FIELDS = frozenset({"choices"})


def _shown(value: Any) -> str:
    """A field value inside approved words: text as is, ``true``/``false``
    (the spelling settings.py accepts), ``null`` for None, a list in its
    JSON form with its items shown the same way (``[]`` for an empty list,
    ``[a, b]`` otherwise: W6d fix R2-F1, an empty list never vanishes), a
    dictionary as JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_shown(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _shown_field(name: str, value: Any) -> str:
    """``_shown`` for a field, except the list of allowed values
    (``{choices}``), which stays the approved comma-joined enumeration."""
    if name in _ENUMERATION_FIELDS and isinstance(value, (list, tuple)):
        return ",".join(_shown(v) for v in value)
    return _shown(value)


def message(key: str, /, **fields: Any) -> str:
    """The approved wording of ``key`` (``{field}`` filled), else its
    structured form. Never the marker, never an unfilled placeholder,
    never empty.

    A field that is ABSENT (not passed) and named by the text takes the
    structured fallback (the safety net). A field PRESENT with the value
    None is a fact, not a missing field: it is shown as the JSON word
    ``null`` inside the approved words (W6d fix F1/F3: a tool request with
    ``value: null``, a saved ``current`` that is null). Callers that mean
    "absent" leave the field out."""
    text = TEXT.get(key)
    if not text:
        return structured(key, **fields)
    shown = {name: _shown_field(name, value) for name, value in fields.items()}
    try:
        line = text.format(**shown)
    except (KeyError, IndexError, ValueError):
        # An approved text naming a field the caller does not pass: the
        # structured form, never the raw template with its placeholder
        # (W6b fix round 1, leftover).
        return structured(key, **fields)
    follow_field = _FOLLOW_UPS.get(key)
    if follow_field is not None and isinstance(fields.get(follow_field), str):
        follow = TEXT.get(f"{key}.{fields[follow_field]}")
        if follow:
            line = f"{line} {follow}"
    return line.rstrip()


def is_structured(key: str, line: str) -> bool:
    """Whether ``line`` is the structured form of ``key`` (``<key>`` or
    ``<key>: <field>=<value> ...``)."""
    line = line.strip()
    return line == key or line.startswith(key + ":")


def prose_fields(key: str, line: str) -> Optional[list]:
    """The ``(field, value text)`` pairs of ``line`` read as the approved
    words of ``key`` (a follow-up sentence allowed after ``app.refused``),
    or None when ``line`` is not those words (or ``key`` has none). For
    tests and probes: a brace inside a field value is supplied data, a brace
    in the fixed words is an unfilled placeholder."""
    import re
    text = TEXT.get(key)
    if not text:
        return None
    names = re.findall(r"\{(\w+)\}", text)
    pattern = "(.+?)".join(re.escape(piece) for piece in re.split(r"\{\w+\}", text))
    if key in _FOLLOW_UPS:
        pattern += "( .+)?"
    found = re.fullmatch(pattern, line.strip(), flags=re.S)
    if found is None:
        return None
    return list(zip(names, found.groups()[:len(names)]))


def matches(key: str, line: str) -> bool:
    """Whether ``line`` is the right rendering of ``key``: for a key with
    approved words, those words only (field values and any follow-up
    sentence filled in); a structured line of an approved key is a defect,
    never a match (W6d fix F4). For a still-pending key, its structured
    form (the only form it has). For tests and probes."""
    if key in TEXT and TEXT[key]:
        return prose_fields(key, line) is not None
    return is_structured(key, line)


def column(name: str) -> str:
    """A table header cell: the approved title, else the column key."""
    return TEXT.get("column." + name) or name


def source_label(source: str) -> str:
    """How a source is shown in a table: the approved label, else its key."""
    return TEXT.get("source." + source) or source


def help_text(key: str) -> Optional[str]:
    """An approved ``--help`` description, else None (argparse prints none)."""
    return TEXT.get(key) or None
