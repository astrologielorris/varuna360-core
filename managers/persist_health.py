# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Chart-write health (SPEC-PERSIST-001 INV-6, td-rx09).

Under INV-1 every chart creation writes a file, so a folder that has become
unwritable stops being a one-off annoyance and becomes a standing condition:
every chart the user makes from now on exists only in the session. They have
to find out, and they have to still know after they restart.

Two channels, and they answer different questions:

* The status bar answers "did THIS chart save?" — immediate, in the moment,
  and gone afterwards (`ui.sticky_status`).
* This module answers "is my chart database still working?" — it is
  PERSISTED, so it survives the restart the status bar cannot.

SPEC-SES-001's health banner deliberately lives in memory: a session-save
failure is about the run you are in. This one is the opposite case, which is
why it does not reuse that state.

Written by `persist_birth_data()` at both of its exits, so a path cannot
record a failure and forget to clear it — success clears, failure records,
and there is no third exit.
"""

from typing import Any, Dict, Optional

#: Settings key. Under `paths` because that is the section that owns the
#: folder the user has to fix.
HEALTH_KEY = "paths.last_chart_write_error"


def _settings():
    from managers.settings_manager import get_settings
    return get_settings()


def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def record_write_failure(message: str, folder: Optional[str] = None,
                         chart_name: Optional[str] = None) -> None:
    """Remember that a chart could not be written, across restarts.

    Never raises: this runs on the failure path, and a warning system that
    can itself fail loudly turns one problem into two.
    """
    try:
        # set() writes the file itself (save=True by default) — there is no
        # separate save() on SettingsManager, and calling one would have made
        # every record log a false failure.
        _settings().set(HEALTH_KEY, {
            "message": str(message),
            "folder": str(folder) if folder else "",
            "chart_name": str(chart_name) if chart_name else "",
            "when": _utc_now_iso(),
        })
    except Exception as e:          # noqa: BLE001
        print(f"[PERSIST] Could not record the write failure: {e}")


def record_write_success() -> None:
    """A successful write RESOLVES the warning.

    Deliberately cheap when there is nothing to clear (the overwhelming
    case): read first, and only touch settings when a record exists, so the
    common path does not rewrite the settings file on every chart.
    """
    try:
        s = _settings()
        if not s.get(HEALTH_KEY, None):
            return
        s.set(HEALTH_KEY, {})
    except Exception as e:          # noqa: BLE001
        print(f"[PERSIST] Could not clear the write failure: {e}")


def last_write_failure() -> Optional[Dict[str, Any]]:
    """The unresolved failure, or None. Shape-checked, never raises."""
    try:
        raw = _settings().get(HEALTH_KEY, None)
    except Exception:
        return None
    if not isinstance(raw, dict) or not raw.get("message"):
        # A missing key, a cleared {}, or something hand-edited into the
        # settings file. Anything we cannot describe is not a warning we can
        # show, and must not become a crash on the Settings page.
        return None
    return dict(raw)


def clear_write_failure() -> None:
    """Explicit dismissal, for a user who fixed it outside the app."""
    record_write_success()


def probe_chart_folder(folder: Optional[str] = None):
    """Try to write and remove a small file in the chart folder.

    Powers the banner's "Check again" button: the warning otherwise stays up
    until the user happens to create another chart, which is a poor way to
    learn that a permissions fix worked.

    Returns (ok, message). A success clears the persisted record.
    """
    import os
    import uuid
    from pathlib import Path
    try:
        from managers.chart_creation_pipeline import resolve_chart_target_folder
        target = folder or resolve_chart_target_folder()
        if not target:
            return False, "No chart folder could be resolved or created."
        probe = Path(target) / f".varuna_write_probe_{uuid.uuid4().hex}"
        fd = os.open(str(probe), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
        try:
            os.unlink(str(probe))
        except OSError:
            pass                    # the write is what was being tested
        record_write_success()
        return True, f"{target} is writable."
    except Exception as e:          # noqa: BLE001
        return False, str(e)
