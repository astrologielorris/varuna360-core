# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The take flow (SPEC-REC-001 §3.1): hotkey -> dialog -> (rectangle) ->
privacy + overlays painted -> ffmpeg -> ... -> ffmpeg exited -> overlays off.

Privacy (v0.4): chart names are blurred IN THE VIDEO by ffmpeg boxes that
follow the panel and title (``video_masks``); the screen stays sharp, with a
dashed frame marking each hidden area.

Privacy and overlays span the CAPTURE, not the phase (review R1 F3): they go
up before ffmpeg starts and come down on ``capture_ended`` (or when the take
returns to idle without ever capturing). Nothing pops up after a take (INV-1).
One controller per main window, found with ``for_gui``; ChartGUI gains no
attribute (Rule 4b).

D-22 (Lorris 2026-10-24): while a take runs, a bar in the menu bar shows the
time and Pause/Resume, Stop and Delete (``record_bar``). D-23: every take
writes an action log for AI beside the video (``action_log``).
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import errno
import os
import time
import weakref
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import QObject, QRect, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QMessageBox

from core.recorder import encoders, macos, output, presets
from core.recorder.ffmpeg_command import RecordingConfig
from core.recorder.region import Rect, clip_even
from managers import screen_recorder_manager as srm

PAINT_BARRIER_MS = 120          # >= two event-loop turns after the overlays repaint

# Draft wording (orchestrator draft, for Lorris's review).
TEXT = {
    "title": "Screen recording",
    "too_small": "The area to record is too small or outside the screen.",
    "folder_failed": "The folder {folder} cannot be written to.",
    "delete_title": "Delete this recording?",
    "delete_body": "The {time} recorded so far will be moved to the trash and this "
                   "recording will not be saved.",
    "delete_yes": "Delete the recording",
    "delete_no": "Keep recording",
}


def _name_popups() -> tuple:
    """Windows that list chart names, blurred with the memory panel: the
    memory panel's Search Charts window (Lorris 2026-10-24)."""
    from apps.widgets.chart_title_widget import ChartSearchDialog
    return (ChartSearchDialog,)


def _settings():
    from managers.settings_manager import get_settings
    return get_settings()


class RecorderController(QObject):
    def __init__(self, gui, manager: Optional[srm.ScreenRecorderManager] = None, store=None):
        super().__init__(gui)
        self._gui_ref = weakref.ref(gui)
        from core.recorder.notification_silencer import Silencer
        from core.recorder.state_store import StateStore
        self.store = store or StateStore()
        self.manager = manager or srm.for_gui(gui)
        self.manager.set_persist(lambda d: self.store.set("last_result", d))
        self.manager.set_last_result(srm.result_from_dict(self.store.get("last_result")))
        self.silencer = Silencer(lambda: self.store.get("saved_notification"),
                                 lambda v: self.store.set("saved_notification", v))
        from apps.recorder.privacy_blur import PrivacyGuard
        from apps.recorder.tray import RecorderTray
        from apps.recorder.video_masks import VideoMasks
        self.privacy = PrivacyGuard()
        self.masks = VideoMasks(self)
        self.tray = RecorderTray(self)
        self.tray.stop_requested.connect(self.stop)
        self.tray.pause_requested.connect(self.pause_or_resume)
        self.tray.open_folder_requested.connect(self.open_folder)
        from apps.recorder.action_log import ActionLog
        self.log = ActionLog(self.manager.video_time, lambda: self.manager.phase == srm.PAUSED, self)
        self._log_path: Optional[str] = None     # closed log waiting for the take's result
        self._result_before = None
        self._bar = None
        self._logical: Optional[QRect] = None
        self.highlight = None
        self.bubble = None
        self._dialog_open = False
        self._capturing = False
        self._choices = None
        self._started = False
        # A take is RESERVED from preparation to launch (review R2 F1): no
        # second take can start, the hotkey cancels it, and the delayed
        # launch only runs for the generation that scheduled it.
        self._pending = False
        self._gen = 0
        self._pending_part: Optional[str] = None
        self._launch_timer = QTimer(self)
        self._launch_timer.setSingleShot(True)
        self._launch_timer.timeout.connect(self._launch_due)
        self._pending_cfg = None
        self._picker = None
        self._tick = QTimer(self)
        self._tick.setInterval(500)
        self._tick.timeout.connect(self._refresh_tray)
        self.manager.snapshot_changed.connect(self._on_snapshot)
        self.manager.capture_ended.connect(self._teardown)
        self.manager.quiet_changed.connect(self.tray.set_quiet)

    @property
    def gui(self):
        return self._gui_ref()

    # ---------------------------------------------------------- start-up

    def ensure_started(self) -> None:
        """Once per window, before the first take (review R2 F5)."""
        if self._started:
            return
        self._started = True
        self.on_app_start()

    def on_app_start(self) -> None:
        """Crash recovery: notification value left saved, part files left behind.
        Never while a take is being prepared or runs."""
        if self._capturing or self._pending or self.manager.busy:
            return
        try:
            self.silencer.restore()
        except Exception:
            pass
        from apps.recorder.record_dialog import RecordChoices, output_folder
        try:
            self.manager.recover(output_folder(RecordChoices.load(_settings())))
        except Exception:
            pass
        choices = self._load_choices()
        if choices.highlight_enabled and choices.highlight_always:
            self._show_highlight(choices)

    def _load_choices(self):
        from apps.recorder.record_dialog import RecordChoices
        return RecordChoices.load(_settings())

    # ---------------------------------------------------------- toggle

    def toggle(self) -> None:
        self.ensure_started()
        phase = self.manager.phase
        if self._pending:
            self.cancel_pending()
        elif phase in (srm.STARTING, srm.RECORDING, srm.PAUSED):
            self.stop()
        elif (phase == srm.IDLE and not self._dialog_open and not self.manager.busy
              and not self._capturing):
            self.open_dialog()

    def stop(self) -> None:
        if self._pending:
            self.cancel_pending()
        else:
            self.manager.stop()

    def pause_or_resume(self) -> None:
        if self.manager.phase == srm.PAUSED:
            self.resume()
        else:
            self.pause()

    def pause(self) -> None:
        if self.manager.pause():
            self.log.mark("pause")

    def resume(self) -> None:
        if self.manager.resume():
            self.log.mark("resume")

    def confirm_delete(self) -> None:
        """Delete the running take after a warning (D-22)."""
        from apps.recorder.record_bar import format_time
        if self.manager.phase not in (srm.STARTING, srm.RECORDING, srm.PAUSED):
            return
        box = QMessageBox(QMessageBox.Icon.Warning, TEXT["delete_title"],
                          TEXT["delete_body"].format(time=format_time(self.manager.snapshot.elapsed)),
                          parent=self.gui)
        yes = box.addButton(TEXT["delete_yes"], QMessageBox.ButtonRole.DestructiveRole)
        no = box.addButton(TEXT["delete_no"], QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(no)
        box.setEscapeButton(no)
        box.exec()
        clicked = box.clickedButton()
        box.deleteLater()
        if clicked is yes:
            self.delete_take()

    def delete_take(self) -> bool:
        """No question asked: the take and its action log go to the trash."""
        if not self.manager.delete():
            return False
        path = self.log.stop() or self._log_path
        self._log_path = None
        srm._trash(path)
        return True

    def cancel_pending(self) -> None:
        """Drop a take that is prepared but not launched yet."""
        if not self._pending:
            return
        self._gen += 1
        self._pending = False
        self._launch_timer.stop()
        picker, self._picker = self._picker, None
        if picker is not None:
            picker._finish(None)                  # closes an open rectangle pick
        self._pending_cfg = None
        self._picker = None
        self._teardown()
        part, self._pending_part = self._pending_part, None
        if part and srm._size(part) == 0:
            srm._discard(part)                    # the empty reserved name

    def open_folder(self) -> None:
        from apps.recorder.record_dialog import output_folder
        res = self.manager.snapshot.last_result
        folder = os.path.dirname(res.path) if getattr(res, "path", "") else \
            output_folder(self._load_choices())
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def open_dialog(self) -> None:
        from apps.recorder.record_dialog import RecordDialog
        if macos.IS_MACOS:
            macos.ask_permission()                # macOS lists the app under Screen Recording
        reason = encoders.unsupported_reason(QGuiApplication.platformName())
        choices = self._load_choices()
        self._dialog_open = True
        try:
            dlg = RecordDialog(choices, self.manager.snapshot.last_result, reason,
                               tray_available=self.tray.available,
                               blur_available=encoders.has_filter("zmq") is not False,
                               notifications_available=self.silencer.available, parent=self.gui)
            accepted = dlg.exec() == dlg.DialogCode.Accepted
        finally:
            self._dialog_open = False
        if not accepted or reason:
            return
        choices.save(_settings())
        self.start_take(choices)

    # ---------------------------------------------------------- take

    def capture_rect(self, choices):
        """(capture-pixel rectangle clipped and even or None, logical QRect);
        the rectangle is None when the pick was cancelled or nothing is left.
        Each screen maps with its own pixel ratio (review R2 F4); on Windows
        the desktop's top-left may be negative (D-20)."""
        from core.recorder.region import native_union, to_native
        from core.recorder.screen import capture_root
        screens = QGuiApplication.screens()
        root_px = capture_root()
        if root_px is None:
            root_px = Rect(0, 0, 0, 0)
            for s in screens:
                g = s.geometry()
                n = to_native(Rect(g.x(), g.y(), g.width(), g.height()), (g.x(), g.y()),
                              s.devicePixelRatio())
                root_px = Rect(0, 0, max(root_px.w, n.x + n.w), max(root_px.h, n.y + n.h))
        screen = None
        if choices.region == "screen":
            screen = next((s for s in screens if s.name() == choices.screen), None) or \
                QGuiApplication.primaryScreen()
            g = screen.geometry()
        elif choices.region == "rect":
            from apps.recorder.region_picker import RegionPicker
            if self.highlight is not None:
                self.highlight.stop()
            self._picker = RegionPicker()
            picked = self._picker.pick()          # nested event loop: re-checked by the caller
            self._picker = None
            if picked is None:
                return None, None
            g = picked
            self.store.set("last_rect", [g.x(), g.y(), g.width(), g.height()])
        else:
            g = self.gui.frameGeometry()
        if screen is not None:
            o = screen.geometry().topLeft()
            native = to_native(Rect(g.x(), g.y(), g.width(), g.height()), (o.x(), o.y()),
                               screen.devicePixelRatio())
        else:                                     # a window or rectangle may span screens
            native = native_union(Rect(g.x(), g.y(), g.width(), g.height()),
                                  [(Rect(s.geometry().x(), s.geometry().y(), s.geometry().width(),
                                         s.geometry().height()), s.devicePixelRatio())
                                   for s in screens])
            if native is None:
                return None, g
        return clip_even(native, root_px), g

    def start_take(self, choices) -> bool:
        self.ensure_started()
        if (choices.blur_memory or choices.blur_title) and encoders.has_filter("zmq") is False:
            # The dialog greyed the blur out (no zmq filter, D-20): this take has none;
            # the saved choice stays for when the full ffmpeg is installed.
            choices = dataclasses.replace(choices, blur_memory=False, blur_title=False)
        if self._pending or self._capturing or self.manager.busy:
            return False                          # one take at a time (review R2 F1)
        # Reserved BEFORE the rectangle pick's nested event loop (review R3 F1):
        # a hotkey during the pick cancels this take instead of starting another.
        self._pending = True
        self._gen += 1
        gen = self._gen
        rect, logical = self.capture_rect(choices)
        if gen != self._gen or not self._pending:
            return False                          # cancelled while picking
        display, crop = os.environ.get("DISPLAY", ":0"), None
        if rect is not None and macos.IS_MACOS:   # one whole display, cut out with crop (D-21)
            from apps.recorder.video_masks import _screens
            display, rect, crop = macos.capture_source(
                rect, Rect(logical.x(), logical.y(), logical.width(), logical.height()), _screens())
        if rect is None:
            self._pending = False
            if logical is not None or choices.region != "rect":
                QMessageBox.warning(self.gui, TEXT["title"], TEXT["too_small"])
            return False
        folder = self._folder(choices)
        if folder is None:
            self._pending = False
            return False
        out_size = presets.output_size(rect.w, rect.h, choices.preset)
        encoder = encoders.gpu_encoder(choices.format, choices.preset, choices.fps, out_size)
        try:
            part = output.part_path(folder, _dt.datetime.now())
        except OSError as exc:                    # disk full, folder gone (review R3 F7)
            self._pending = False
            code = "DISK_FULL" if exc.errno == errno.ENOSPC else "FOLDER"
            self.manager.report_failure(srm.Failed(code, srm.TEXT.get(code, "") or str(exc)))
            QMessageBox.warning(self.gui, TEXT["title"], TEXT["folder_failed"].format(folder=folder))
            return False
        if gen != self._gen or not self._pending:
            srm._discard(part)
            return False
        masks = self.masks.initial(rect, self._mask_areas(choices)) \
            if self._mask_areas(choices) else ()
        cfg = RecordingConfig(
            display=display, crop=crop, rect=rect, masks=masks,
            output=part, fps=choices.fps, backend=encoders.capture_backend(),
            preset=choices.preset, video_format=choices.format, encoder=encoder,
            mic=(choices.mic_device or None) if choices.mic_enabled else None,
            computer=(choices.computer_device or None) if choices.computer_enabled else None)
        self._choices = choices
        self._pending_part, self._pending_cfg = cfg.output, cfg
        if not self._prepare(choices, logical):
            self._pending = False
            srm._discard(cfg.output)
            return False
        self._launch_timer.setProperty("gen", self._gen)
        self._launch_timer.start(PAINT_BARRIER_MS)
        return True

    def _folder(self, choices) -> Optional[str]:
        from apps.recorder.record_dialog import output_folder
        folder = output_folder(choices)
        try:
            os.makedirs(folder, exist_ok=True)
            if not os.access(folder, os.W_OK):
                raise OSError
        except OSError:
            QMessageBox.warning(self.gui, TEXT["title"], TEXT["folder_failed"].format(folder=folder))
            return None
        return folder

    # ---------------------------------------------------------- privacy

    def _memory_names(self):
        """The chart buttons of the memory panel (not its tool buttons)."""
        return getattr(getattr(self.gui, "memory_panel_instance", None), "buttons_container", None)

    def _title(self):
        return getattr(self.gui, "chart_title_label", None)

    def _mask_areas(self, choices) -> dict:
        from apps.recorder.video_masks import popup_area, title_bar_area, widget_area
        areas = {}
        if choices.blur_memory:
            areas["memory"] = widget_area(self._memory_names)
            areas["search"] = popup_area(_name_popups())
        if choices.blur_title:
            areas["title"] = widget_area(self._title)
            areas["titlebar"] = title_bar_area(lambda: self.gui)
        return areas

    def _prepare(self, choices, logical: QRect) -> bool:
        """Privacy and overlays up, before ffmpeg (INV-7.3)."""
        self._capturing = True
        self._logical = QRect(logical) if logical is not None else None
        targets = ([self._memory_names()] if choices.blur_memory else []) + \
                  ([self._title()] if choices.blur_title else [])
        targets = [t for t in targets if t is not None]
        if targets:
            self.privacy.apply(targets)          # no tooltip / menu / drag pixmap
        if self._mask_areas(choices):
            memory_panel = getattr(getattr(self.gui, "memory_panel_instance", None), "panel", None)
            self.masks.start(self.manager, watch=[self.gui, memory_panel], markers=targets)
            if choices.blur_memory:
                self.masks.watch_popups(_name_popups())
        if choices.highlight_enabled:
            self._show_highlight(choices)
        if choices.camera_enabled:
            self._show_bubble(choices, logical)
        if choices.hide_notifications:
            try:
                self.silencer.engage()
            except Exception:
                pass
        QGuiApplication.processEvents()
        return True

    def _launch_due(self) -> None:
        if self._launch_timer.property("gen") == self._gen and self._pending:
            self._launch(self._pending_cfg, self._gen)

    def _launch(self, cfg: RecordingConfig, gen: int) -> None:
        if gen != self._gen or not self._pending or not self._capturing or cfg is None:
            return                                # a cancelled or superseded take
        if self.manager.busy:                     # cannot happen while reserved; never tear
            return                                # down someone else's protection
        self._pending, self._pending_cfg, self._pending_part = False, None, None
        if cfg.masks:                             # where the areas are NOW (window may have moved)
            cfg = replace(cfg, masks=self.masks.initial(cfg.rect, self._mask_areas(self._choices)))
        self._result_before = self.manager.snapshot.last_result
        if not self.manager.start(replace(cfg, t0=time.time())):
            self._teardown()                      # reserved: no other take can be running
            srm._discard(cfg.output)
            return
        self._start_log(cfg)

    def _start_log(self, cfg: RecordingConfig) -> None:
        """The AI action log beside the take (D-23); a log that cannot be
        written never stops the recording."""
        from core.recorder import output
        area = self._logical or self.gui.frameGeometry()
        choices = self._choices
        meta = {"video_part": os.path.basename(cfg.output),
                "region": getattr(choices, "region", ""), "fps": cfg.fps,
                "screen_scale": QGuiApplication.primaryScreen().devicePixelRatio()}
        try:
            self.log.start(output.action_log_path(cfg.output), area, self.gui,
                           title=self._title, meta=meta)
        except Exception:
            pass

    def _show_highlight(self, choices) -> None:
        from apps.recorder.cursor_highlight import CursorHighlight
        from core.recorder.screen import compositor_running
        if self.highlight is None:
            self.highlight = CursorHighlight(translucent=compositor_running())
        self.highlight.configure(choices.highlight_color, choices.highlight_opacity,
                                 choices.highlight_size, choices.highlight_shape)
        self.highlight.start()

    def _show_bubble(self, choices, logical: QRect) -> None:
        from apps.recorder.camera_bubble import CameraBubble
        device = None
        try:
            from PySide6.QtMultimedia import QMediaDevices
            device = next((d for d in QMediaDevices.videoInputs()
                           if bytes(d.id().data()).decode(errors="replace") == choices.camera_device), None)
        except ImportError:
            pass
        geo = self.store.get("bubble") or {}
        self.bubble = CameraBubble(device, mirror=_settings().get("recorder.camera_mirror", True),
                                   ring=_settings().get("recorder.camera_ring", True),
                                   diameter=self._bubble_diameter(choices))
        self.bubble.moved.connect(lambda x, y, d: self.store.set(
            "bubble", {"x": round(x, 4), "y": round(y, 4), "diameter": d}))
        self.bubble.failed.connect(lambda text: self.store.set("camera_failure", text))
        if not self.bubble.start():
            self.bubble = None
            return
        if "x" in geo:
            s = self.bubble._screen_rect()
            self.bubble.place_center(int(s.left() + geo["x"] * s.width()),
                                     int(s.top() + geo["y"] * s.height()))
        else:
            self.bubble.place_default(logical)

    @staticmethod
    def _bubble_diameter(choices) -> int:
        """The dialog's Size choice decides each take (the wheel adjusts it
        live); clamped to the screen by the bubble itself."""
        from apps.recorder.camera_bubble import DEFAULT_DIAMETER, SIZES
        return SIZES.get(getattr(choices, "camera_size", "small"), DEFAULT_DIAMETER)

    def _teardown(self) -> None:
        """Every overlay and the privacy guard down; idempotent (INV-4, INV-7)."""
        self._capturing = False
        try:
            path = self.log.stop()                # no more frames: the log ends too
            if path:
                self._log_path = path
        except Exception:
            pass
        for step in (self.masks.stop, self.privacy.remove, self._hide_bubble, self._hide_highlight,
                     self._restore_notifications):
            try:
                step()
            except Exception:
                pass

    def _hide_bubble(self):
        bubble, self.bubble = self.bubble, None
        if bubble is not None:
            bubble.stop()
            bubble.deleteLater()

    def _hide_highlight(self):
        choices = self._choices or self._load_choices()
        if self.highlight is not None and not (choices.highlight_always and choices.highlight_enabled):
            self.highlight.stop()

    def _restore_notifications(self):
        self.silencer.restore()

    # ---------------------------------------------------------- state

    def _on_snapshot(self, snap) -> None:
        if snap.phase == srm.FINALIZING and self.bubble is not None:
            self.bubble.freeze()                  # camera off, last image kept (mobile §5.5)
        if (snap.phase == srm.IDLE and self._capturing and not self._pending
                and self.manager._proc is None):
            self._teardown()                      # ended without capture_ended (launch failure)
        if snap.phase == srm.IDLE and self._log_path and not self.manager.busy:
            self._finish_log(snap.last_result)
        self._refresh_tray()
        if snap.phase in (srm.STARTING, srm.RECORDING, srm.PAUSED, srm.FINALIZING):
            self._tick.start()
        else:
            self._tick.stop()

    def _finish_log(self, result) -> None:
        """The take's log takes the published video's name; a take that left
        no video leaves no log."""
        from apps.recorder.action_log import finish
        path, self._log_path = self._log_path, None
        if result is self._result_before or not getattr(result, "path", ""):
            srm._trash(path)
            return
        finish(path, result.path)

    def _refresh_tray(self) -> None:
        snap = self.manager.snapshot
        self.tray.show_phase(snap.phase, snap.elapsed)
        bar = self.bar()
        if bar is not None:
            bar.show_phase(snap.phase, snap.elapsed)

    def bar(self):
        """The recording bar in the menu bar, built at the first take."""
        if self._bar is None and self.manager.phase != srm.IDLE:
            gui = self.gui
            menubar = gui.menuBar() if gui is not None and hasattr(gui, "menuBar") else None
            if menubar is None:
                return None
            from apps.recorder.record_bar import RecordBar
            self._bar = RecordBar(menubar)
            self._bar.pause_requested.connect(self.pause)
            self._bar.resume_requested.connect(self.resume)
            self._bar.stop_requested.connect(self.stop)
            self._bar.delete_requested.connect(self.confirm_delete)
        return self._bar

    def close_app(self) -> None:
        """App close: stop and wait (bounded), privacy down, no popup."""
        self.cancel_pending()
        try:
            if self.manager.busy:
                self.manager.stop_and_wait(20)
        finally:
            self._teardown()
            if self.highlight is not None:
                self.highlight.stop()
            self.tray.show_phase(srm.IDLE)
            if self._bar is not None:
                self._bar.show_phase(srm.IDLE)


_CONTROLLERS: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def for_gui(gui) -> RecorderController:
    ctl = _CONTROLLERS.get(gui)
    if ctl is None:
        ctl = RecorderController(gui)
        _CONTROLLERS[gui] = ctl
    return ctl
