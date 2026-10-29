# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 - see LICENSE file for details.
"""Rate and Sort's controller (SPEC-LIB-002 §4.3 to §4.12), owned by the panel.

``RateSortController(panel, ai_widget)`` builds the ``RateSortSection``, reads
the library in a ``LoadWorker`` (the one step that may read chart files: the
ratings mirror), keeps the visit and its UNDO history, writes a rating only on
CONFIRM AND NEXT / Enter (INV-2) through ``core.library.rate``, files rated
downloads through ``chart_sort`` (preview first, INV-6) and converts ``.chtk``
charts. Nothing is written while the first chart folder is the old Kala
folder (INV-9). State lives here, not on ``ChartGUI`` (Rule 4b).
"""
from __future__ import annotations

import os
import time
import warnings
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from core import chart_sort
from core.library import convert, privacy, profile as profile_mod, queue, rate, rating, scores, stats
from core.library.paths import is_kala_folder, library_root
from core.library.state import State
from core.settings_registry import default as registry_default
from managers.settings_manager import get_settings
from panels.find_chart import filing
from panels.find_chart.rate_sort import DONE_TEXT, FILE_ROWS, UP_TO_DATE, RateSortSection

VISIT_KEY = "ui.library_visit_size"
_FOLDER_FOR = {privacy.PRIVATE: "Private", privacy.REVIEW: "Private", privacy.MIXED: "Private",
               privacy.PUBLIC: "Public"}
_PARKED = set()


class LoadWorker(QThread):
    loaded = Signal(object, object)
    failed = Signal(str)

    def __init__(self, database, root, store_file, parent=None):
        super().__init__(parent)
        self.database, self.root, self.store_file = database, root, store_file
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from core.chart_search.errors import NoIndexError
        try:
            lib, state = rate.load(self.database, self.root, store_file=self.store_file,
                                   cancelled=lambda: self._cancel)
            try:
                # Read here, off the GUI thread: the Kala guard reads the
                # latest library plan, an 8 MB file.
                extra = {"stats": stats.overview(lib),
                         "last": state.get_meta("profile_last_run", {}),
                         "kala": is_kala_folder(lib.database, lib.library_root)}
            finally:
                state.close()
            self.loaded.emit(lib, extra)
        except NoIndexError:
            self.failed.emit("Rebuild the index (INDEX, below) to rate your charts.")
        except Exception as exc:  # noqa: BLE001 - shown in the section, never a crash
            self.failed.emit(f"The library could not be read: {exc}")


class ConvertWorker(QThread):
    done = Signal(object)

    def __init__(self, database, parent=None):
        super().__init__(parent)
        self.database = database
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            self.done.emit(convert.convert_folder(Path(self.database), lambda: self._cancel))
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"converted": [], "failed": [("", str(exc))]})


def confirm_convert(parent, count: int, folder) -> bool:
    """CONVERT TO TOML moves every .chtk of the folder: asked first, Cancel
    the default (the only bulk action that had no preview)."""
    from PySide6.QtWidgets import QMessageBox
    from panels.find_chart import kit
    box = kit.style_dialog(QMessageBox(parent))
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Convert to TOML")
    box.setText(f"Convert {count:,} chart{'' if count == 1 else 's'} in {folder} to .toml?")
    box.setInformativeText("Each .chtk file moves to the CHTK backup folder inside this folder. "
                           "Nothing is deleted, but programs that read .chtk files, such as "
                           "Kala, no longer find these charts in their old place.")
    convert_button = box.addButton("Convert", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(box.addButton(QMessageBox.StandardButton.Cancel))
    box.exec()
    return box.clickedButton() is convert_button


def birth_line(chart) -> str:
    date, _, clock = chart.birth_local.partition(" ")
    when = "no birth time" if chart.no_birth_time or not clock else clock[:5]
    parts = [date, when] + ([chart.place] if chart.place else [])
    return " · ".join(p for p in parts if p)


class RateSortController(QObject):
    def __init__(self, panel, ai_widget=None, store_file=None):
        super().__init__(panel)
        self.panel = panel
        self.store_file = store_file
        self.view = v = RateSortSection()
        if ai_widget is not None:
            v.set_ai_widget(ai_widget)
        self.ai_widget = ai_widget
        self.lib = None
        self.state = None
        self.extra = {}
        self.visit: list[str] = []      # group ids
        self.arcs: list[str] = []       # "open" / "rated" / "skipped"
        self.current = -1
        self.values: dict = {}
        self.touched: set = set()
        self.history: list[tuple] = []
        self.focus_row = 0
        self._expect = None
        self._worker = None
        self._convert_worker = None
        self._chtk_count = 0
        self._file_worker = None
        self._proposal = None
        self._new_visit_wanted = True
        self._kala = False
        v.plane.picked.connect(self._on_plane)
        for r in v.rows.values():
            r.changed.connect(self._on_row)
        v.skip_button.clicked.connect(self.skip)
        v.undo_button.clicked.connect(self.undo)
        v.undo_done_button.clicked.connect(self.undo)
        v.confirm_button.clicked.connect(self.confirm)
        v.convert_button.clicked.connect(self._convert_current)
        v.more_button.clicked.connect(self._rate_more)
        v.preview_button.clicked.connect(self._preview)
        v.file_button.clicked.connect(self._file)
        v.file_undo_button.clicked.connect(self._file_undo)
        v.sort_log_button.clicked.connect(self._open_sort_log)
        v.run_button.clicked.connect(lambda: self.refresh())
        v.rules_button.clicked.connect(self._toggle_rules)
        v.convert_all_button.clicked.connect(self._convert_all)
        for r in v.file_rows:
            r.combo.currentTextChanged.connect(self._invalidate_preview)
        v.card.installEventFilter(self)
        self._show_empty("Reading the library...")

    # ---------------------------------------------------------- folders
    def database(self):
        return self.panel._first_folder()

    @staticmethod
    def library_root():
        return library_root(get_settings().get("paths.library_root", ""))

    def visit_size(self) -> int:
        try:
            return max(1, int(get_settings().get(VISIT_KEY, registry_default(VISIT_KEY))))
        except (TypeError, ValueError):
            return 5

    # ---------------------------------------------------------- loading
    def refresh(self, new_visit: bool = False) -> None:
        """Read the library again (sheet open, RUN NOW, after a change)."""
        self._new_visit_wanted = self._new_visit_wanted or new_visit
        database = self.database()
        self.view.path_label.setText(str(chart_sort.unsorted_dir(database)) if database else "")
        if not database:
            self._show_empty("Add a chart folder first.")
            return
        if self._worker is not None:
            return
        worker = LoadWorker(database, self.library_root(), self.store_file)
        worker.loaded.connect(lambda lib, extra, w=worker: w is self._worker and self._loaded(lib, extra))
        worker.failed.connect(lambda m, w=worker: w is self._worker and self._show_empty(m))
        worker.finished.connect(lambda w=worker: self._release(w))
        self._worker = worker
        worker.start()

    def _release(self, worker):
        if worker is self._worker:
            self._worker = None
            worker.deleteLater()

    def _ensure_state(self):
        if self.state is None or Path(self.state.path).parent.parent != Path(self.lib.library_root):
            if self.state is not None:
                self.state.close()
            self.state = State(Path(self.lib.library_root))

    def _loaded(self, lib, extra) -> None:
        old = self.lib
        self.lib, self.extra = lib, extra
        self._ensure_state()
        self._kala = extra["kala"] if "kala" in extra else is_kala_folder(lib.database, lib.library_root)
        if old is None or old.database != lib.database:
            self._new_visit_wanted = True
        if self._new_visit_wanted:
            self._start_visit()
        self._show(extra.get("stats"))  # the worker's count of this same library

    def _start_visit(self, keep_trail: bool = False) -> None:
        self._new_visit_wanted = False
        exclude = set(self.visit) if keep_trail else set()
        groups = queue.visit(self.lib, self.visit_size(), exclude=exclude)
        self.visit = [g.id for g in groups]
        self.arcs = ["open"] * len(self.visit)
        self.history = []
        self.current = 0 if self.visit else -1
        self._load_current()

    def _rate_more(self) -> None:
        self._start_visit(keep_trail=True)
        self._show()

    # ---------------------------------------------------------- current chart
    def group(self):
        if self.lib is None or not 0 <= self.current < len(self.visit):
            return None
        return self.lib.groups.get(self.visit[self.current])

    def _load_current(self) -> None:
        g = self.group()
        self.values, self.touched, self.focus_row = {}, set(), 0
        self._expect = None
        if g is None:
            return
        if g.confirmed:
            self.values = {k: v for k, v in g.rating.items() if k in rating.ROWS}
            self.touched = set(self.values)
        else:
            self.values = {r: g.guess[r]["value"] for r in rating.ROWS if r in g.guess}
        try:
            self._expect = rating.fingerprint(g.main.path)
        except OSError:
            self._expect = None

    def _next_open(self) -> None:
        for i in range(len(self.visit)):
            if self.arcs[i] == "open":
                self.current = i
                self._load_current()
                return
        self.current = -1
        self._load_current()

    # ---------------------------------------------------------- edits
    def _set(self, row, value, *, accept=False) -> None:
        if self.group() is None or self._kala:
            return
        self.history.append(("set", self.current, row, self.values.get(row), row in self.touched))
        if value is None:
            self.values.pop(row, None)
        else:
            self.values[row] = value
        self.touched.add(row)
        self._render_card()

    def _on_plane(self, who, known) -> None:
        if self.group() is None or self._kala:
            return
        self.history.append(("pair", self.current, dict(self.values), set(self.touched)))
        self.values["who"], self.values["known"] = who, known
        self.touched |= {"who", "known"}
        self._render_card()

    def _on_row(self, row, value) -> None:
        self.focus_row = rating.ROWS.index(row)
        self._set(row, value)
        self.view.card.setFocus(Qt.MouseFocusReason)

    def accept_row(self) -> None:
        row = rating.ROWS[self.focus_row]
        if row in self.values and row not in self.touched:
            self.history.append(("set", self.current, row, self.values[row], False))
            self.touched.add(row)
        self.focus_row = min(len(rating.ROWS) - 1, self.focus_row + 1)
        self._render_card()

    def confirm(self) -> None:
        g = self.group()
        if g is None or self._kala or g.main.chtk:
            return
        if "who" not in self.values or "known" not in self.values:
            self.view.card_message.setText("Choose who this person is and how known they are first.")
            return
        accepted = [r for r in rating.ROWS if r in self.values and r not in self.touched]
        try:
            path, previous, _table = rate.confirm(self.state, self.lib, g, self.values,
                                                  accepted=accepted, expect=self._expect)
        except rating.Changed:
            self._reread(g)
            self.view.card_message.setText("This chart changed on disk since it was shown. "
                                           "It is shown again as it is now.")
            self._show()
            return
        except Exception as exc:  # noqa: BLE001 - refused write: said, never a crash
            self.view.card_message.setText(f"Not saved: {exc}")
            return
        self.history.append(("confirm", self.current, g.id, path, previous,
                             dict(self.values), set(self.touched), getattr(g, "written", None)))
        self.arcs[self.current] = "rated"
        self._next_open()
        self._show()

    def _reread(self, g) -> None:
        """After a refused write: the chart's rating as it is on disk now, in
        the group and the mirror, then the card from it."""
        path = g.main.path
        try:
            table = rating.read(path)
        except (OSError, ValueError):
            table = {}
        queue.note_rated(self.state, path, table or None)
        if "who" in table and "known" in table:
            g.rating, g.rated_path = table, path
            if 0 <= self.current < len(self.arcs):
                self.arcs[self.current] = "rated"
            self._next_open()
        else:
            g.rating, g.rated_path = {}, ""
            self._load_current()

    def _reread_group(self, g, path) -> None:
        """The group's rating as the file holds it now (mirror too)."""
        try:
            table = rating.read(path)
        except (OSError, ValueError):
            table = {}
        queue.note_rated(self.state, path, table or None)
        if "who" in table and "known" in table:
            g.rating, g.rated_path = table, path
        else:
            g.rating, g.rated_path = {}, ""

    def skip(self) -> None:
        g = self.group()
        if g is None:
            return
        self.state.skip(g.id)
        self.history.append(("skip", self.current, g.id, dict(self.values), set(self.touched)))
        self.arcs[self.current] = "skipped"
        self._next_open()
        self._show()

    def undo(self) -> None:
        if not self.history:
            return
        entry = self.history.pop()
        kind, idx = entry[0], entry[1]
        if kind == "set":
            _k, _i, row, old, was = entry
            if old is None:
                self.values.pop(row, None)
            else:
                self.values[row] = old
            if not was:
                self.touched.discard(row)
        elif kind == "pair":
            self.values, self.touched = entry[2], entry[3]
        elif kind == "confirm":
            _k, _i, gid, path, previous, values, touched, written = entry
            group = self.lib.groups[gid]
            try:
                rate.restore(self.state, self.lib, group, path, previous, expect=written)
            except rating.Changed:
                self._reread_group(group, path)
                self.view.card_message.setText("This chart was changed after you rated it, "
                                               "so the newer rating is kept.")
                self._show()
                return
            except Exception as exc:  # noqa: BLE001
                self.history.append(entry)
                self.view.card_message.setText(f"Undo failed: {exc}")
                return
            self.arcs[idx], self.current = "open", idx
            self._load_current()
            self.values, self.touched = values, touched
        elif kind == "skip":
            _k, _i, gid, values, touched = entry
            self.state.unskip(gid)
            self.arcs[idx], self.current = "open", idx
            self._load_current()
            self.values, self.touched = values, touched
        self._show()

    def _convert_current(self) -> None:
        g = self.group()
        if g is None or not g.main.chtk or self._kala:
            return
        chart = g.main
        try:
            target = convert.convert_in_place(Path(chart.path), Path(self.lib.database))
        except Exception as exc:  # noqa: BLE001
            self.view.card_message.setText(f"Not converted: {exc}")
            return
        st = target.stat()
        chart.path, chart.mtime, chart.size = str(target), st.st_mtime, st.st_size
        chart.rel = chart.rel[:-len(".chtk")] + ".toml"
        chart.refresh()
        self._load_current()
        self.view.card_message.setText("Converted to .toml; the .chtk is in CHTK backup.")
        self._show()

    # ---------------------------------------------------------- keys
    def eventFilter(self, obj, event):  # noqa: N802 - Qt name
        if obj is self.view.card and event.type() == QEvent.KeyPress:
            return self._key(event)
        return super().eventFilter(obj, event)

    def _key(self, e) -> bool:
        key, text = e.key(), e.text().lower()
        row = rating.ROWS[self.focus_row]
        if key == Qt.Key_Up:
            self.focus_row = max(0, self.focus_row - 1)
        elif key == Qt.Key_Down:
            self.focus_row = min(len(rating.ROWS) - 1, self.focus_row + 1)
        elif key in (Qt.Key_Left, Qt.Key_Right):
            step = 1 if key == Qt.Key_Right else -1
            if row == "who":
                cur = self.values.get("who")
                i = rating.WHO.index(cur) + step if cur in rating.WHO else 0
                self._set("who", rating.WHO[max(0, min(len(rating.WHO) - 1, i))])
            else:
                cur = self.values.get(row)
                self._set(row, max(0, min(5, (cur if cur is not None else -1) + step)))
            return True
        elif text.isdigit():
            n = int(text)
            if row == "who" and 1 <= n <= len(rating.WHO):
                self._set("who", rating.WHO[n - 1])
            elif row != "who" and n <= 5:
                self._set(row, n)
            return True
        elif key == Qt.Key_Space:
            self.accept_row()
            return True
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            self.confirm()
            return True
        elif text == "s":
            self.skip()
            return True
        elif text == "z":
            self.undo()
            return True
        else:
            return False
        self._render_card()
        return True

    # ---------------------------------------------------------- display
    def _show_empty(self, reason: str) -> None:
        v = self.view
        v.reason_label.setText(reason)
        v.reason_label.setVisible(bool(reason))
        for w in (v.card, v.done_label, v.done_row, v.file_box, v.profile_box):
            w.hide()

    def _show(self, numbers=None) -> None:
        """``numbers``: ``stats.overview(self.lib)`` when the caller has it."""
        v, lib = self.view, self.lib
        s = numbers or (stats.overview(lib) if lib is not None else self.extra.get("stats"))
        if s:
            self.extra["stats"] = s
            v.set_waiting(s["waiting"], s["unrated"])
            parts = [f"{s['rated']:,} of {s['charts']:,} rated"]
            if s["this_week"]:
                parts.append(f"{s['this_week']:,} this week")
            if s["weeks_in_row"] > 1:
                parts.append(f"{s['weeks_in_row']} weeks in a row")
            v.progress_label.setText(" · ".join(parts))
            v.ring.set_library(s["rated"] / s["charts"] if s["charts"] else 0.0)
            self._show_stats(s)
        v.ring.set_visit([(a, self._arc_zone(i)) for i, a in enumerate(self.arcs)], self.current)
        if self._kala:
            self._show_empty(rate.KALA_REASON)
            return
        if lib is not None and not lib.groups:
            self._show_empty("No chart of the first chart folder is in the index yet. "
                             "Press REBUILD INDEX below.")
            v.profile_box.show()
            self._show_profile()
            return
        v.reason_label.hide()
        g = self.group()
        v.card.setVisible(g is not None)
        if g is not None:
            self._render_card()
        else:
            waiting = s["waiting"] if s else 0
            v.done_label.setText(DONE_TEXT if self.visit and waiting else
                                 (DONE_TEXT + " " + UP_TO_DATE if self.visit else UP_TO_DATE))
        v.done_label.setVisible(g is None)
        v.done_row.setVisible(g is None)
        v.more_button.setText(f"RATE {self.visit_size()} MORE")
        v.more_button.setVisible(g is None and bool(s and s["waiting"]))
        v.undo_done_button.setVisible(g is None and bool(self.history))
        self._show_filing()
        v.profile_box.show()
        self._show_profile()

    def _arc_zone(self, i):
        if self.lib is None or i >= len(self.visit):
            return None
        g = self.lib.groups.get(self.visit[i])
        return g.zone() if g else None

    def _render_card(self) -> None:
        v, g = self.view, self.group()
        if g is None:
            return
        chart = g.main
        v.name_label.setText(chart.name)
        v.name_label.setToolTip(chart.path)
        v.birth_label.setText(birth_line(chart))
        who, known = self.values.get("who"), self.values.get("known")
        zone = rating.zone(who, known)
        both = {"who", "known"} <= self.touched
        v.set_badge(zone, not both)
        why = self._why(g)
        v.why_header.setVisible(bool(why))
        for i, w in enumerate(v.why_lines):
            w.setText(why[i] if i < len(why) else "")
            w.setVisible(i < len(why))
        v.plane.set_point(who, known, both)
        v.plane.set_trail([(self.lib.groups[gid].rating.get("who"), self.lib.groups[gid].rating.get("known"))
                           for i, gid in enumerate(self.visit)
                           if self.arcs[i] == "rated" and gid in self.lib.groups])
        for i, (row, w) in enumerate(v.rows.items()):
            value = self.values.get(row)
            source = g.guess.get(row, {}).get("source", "") if row not in self.touched else ""
            w.set_state(value, row not in self.touched, source)
            w.set_focused(i == self.focus_row)
        v.readout_label.setText(self._readouts(g))
        is_chtk = chart.chtk
        v.convert_button.setVisible(is_chtk)
        v.confirm_button.setVisible(not is_chtk)
        v.confirm_button.setEnabled(who is not None and known is not None)
        for w in (v.plane, *v.rows.values()):
            w.setEnabled(not is_chtk)
        v.undo_button.setEnabled(bool(self.history))
        v.card_message.setVisible(bool(v.card_message.text()))

    def _why(self, g) -> list:
        lines = []
        f = queue.facts(self.lib, g)
        folders = "/".join(f["folders"])
        if folders:
            lines.append(f"Folder {folders}")
        sources = sorted({x["source"] for r, x in g.guess.items() if r not in self.touched})
        if sources:
            lines.append("Profile rule: " + ", ".join(sources))
        if g.copies > 1:
            lines.append(f"{g.copies} copies")
        if f.get("first_seen"):
            lines.append(f"Known to the library since {f['first_seen']}")
        return lines[:len(self.view.why_lines)]

    def _readouts(self, g) -> str:
        rec = dict(g.record or {})
        rows = {k: v for k, v in self.values.items() if k in rating.ROWS}
        rec["rating"] = rows if {"who", "known"} <= set(rows) else None
        guess = None if rec["rating"] else rows
        try:
            pr = scores.privacy_readout(rec, guess=guess)
            pf = scores.preference_readout(rec)
        except Exception:  # noqa: BLE001 - a read-out is a hint, never a crash
            return ""
        return f"privacy {pr} / 10 · preference {pf} / 10 · computed"

    def _show_stats(self, s) -> None:
        v = self.view
        v.tiles.set_stats(s)
        bits = []
        if s["oldest"]:
            bits.append(f"In the library since {s['oldest']}" +
                        (f", newest {s['newest']}" if s["newest"] != s["oldest"] else ""))
        if s["ai_made"]:
            bits.append(f"{s['ai_made']:,} made by AI tools")
        if s["opened_this_month"]:
            bits.append(f"{s['opened_this_month']:,} opened this month")
        v.stats_line.setText(" · ".join(bits))
        v.stats_line.setVisible(bool(bits))
        n = s["chtk"]
        self._chtk_count = n
        v.chtk_label.setText(f"{n:,} in the old CHTK format" if n else "")
        v.chtk_label.setVisible(bool(n))
        v.convert_all_button.setVisible(bool(n) and not self._kala and self._convert_worker is None)

    def _show_profile(self) -> None:
        v = self.view
        doc = self.lib.profile if self.lib is not None else profile_mod.builtin()
        meta = doc.get("profile") or {}
        n = len(doc.get("rules") or [])
        v.profile_name.setText(f"“{meta.get('name', '')}” · {n} rule{'' if n == 1 else 's'}")
        writer = str(meta.get("written_by", ""))
        if writer == "builtin":
            text = "Built-in rules: folder names, copies, name tags. No AI involved."
        elif writer.startswith("ai:"):
            text = f"Written once by AI from your library stats on {meta.get('written', '')}."
        else:
            text = "Your own rules."
        if doc.get("_error"):
            text += f" Your profile file was not used: {doc['_error']}"
        v.profile_writer.setText(text)
        last = self.extra.get("last") or {}
        if last.get("at"):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(last["at"]))
            v.profile_last.setText(f"Last ran {when} · {last.get('guesses', 0):,} guesses made")
        v.profile_last.setVisible(bool(last.get("at")))
        if v.rules_text.isVisible():
            v.rules_text.setText("\n".join(profile_mod.describe(doc)))

    def _toggle_rules(self) -> None:
        v = self.view
        on = not v.rules_text.isVisible()
        v.rules_text.setVisible(on)
        v.rules_button.setText("HIDE RULES" if on else "SHOW RULES")
        self._show_profile()

    # ---------------------------------------------------------- filing
    def ready_to_file(self) -> list:
        """``(group, file name)`` of every confirmed chart directly in the
        unsorted downloads folder (D-6)."""
        if self.lib is None:
            return []
        out = []
        for g in self.lib.groups.values():
            if not g.confirmed or not g.rated_path:
                continue
            rel = os.path.relpath(g.rated_path, self.lib.database).split(os.sep)
            if len(rel) == 2 and rel[0] == chart_sort.UNSORTED_FOLDER and os.path.exists(g.rated_path):
                out.append((g, rel[1]))
        return sorted(out, key=lambda gf: gf[1].lower())

    def _show_filing(self) -> None:
        v = self.view
        if self.lib is None:
            return
        items = self.ready_to_file()
        busy = self._file_worker is not None
        v.file_box.setVisible(bool(items) or bool(v.file_result.text()))
        folders = chart_sort.RATED_FOLDERS + tuple(
            f for f in chart_sort.categories(self.lib.database) + chart_sort.SAFE_FOLDERS
            if f not in chart_sort.RATED_FOLDERS)
        shown = {r.filename: r.folder() for r in v.file_rows if r.isVisible()}
        for i, row in enumerate(v.file_rows):
            if i < len(items):
                g, name = items[i]
                default = shown.get(name) or _FOLDER_FOR[privacy.effective_privacy({"rating": g.rating})]
                row.set_move(name, g.zone(), folders, default)
                row.show()
            else:
                row.hide()
        extra = len(items) - FILE_ROWS
        v.file_more.setText(f"and {extra:,} more (shown after these are filed)" if extra > 0 else "")
        v.file_more.setVisible(extra > 0)
        v.file_note.setText("Confirmed charts of your downloads, with the folder they would go "
                            "to. Nothing moves until you file them." if items else "")
        v.file_note.setVisible(bool(items))
        v.preview_button.setVisible(bool(items))
        v.preview_button.setEnabled(not busy)
        ready = self._proposal is not None and not busy
        v.file_button.setVisible(bool(items))
        v.file_button.setEnabled(ready)
        n = len(self._proposal.moves) if self._proposal is not None else 0
        v.file_button.setText(f"FILE {n} CHART{'' if n == 1 else 'S'}" if ready else "FILE CHARTS")
        v.preview_text.setVisible(self._proposal is not None)

    def _invalidate_preview(self, *_a) -> None:
        if self._proposal is not None:
            self._proposal = None
            self.view.preview_text.setText("")
            self._show_filing()

    def _preview(self) -> None:
        v = self.view
        moves = [(r.filename, r.folder()) for r in v.file_rows if r.isVisible()]
        try:
            self._proposal = chart_sort.proposal_from_ratings(self.lib.database, moves)
        except chart_sort.SortError as exc:
            self._proposal = None
            v.preview_text.setText(f"No preview: {exc}")
            v.preview_text.show()
            return
        v.preview_text.setText("\n".join(f"Downloads/{m.filename} → {m.folder}/{m.filename}"
                                         for m in self._proposal.moves))
        v.file_result.setText("")
        self._show_filing()

    def _file(self) -> None:
        if self._proposal is None or self._file_worker is not None or self._kala:
            return
        from core.library import admin
        if any(m.folder == "Private" for m in self._proposal.moves):
            # Private charts stay owner only (LIB-001 §3.5), from the first filing.
            admin.ensure_dir(Path(self.lib.database) / "Private", True)
        worker = filing.SortWorker.for_apply(self._proposal, self._proposal.moves,
                                                   self.lib.database)
        self._start_file_worker(worker)

    def _file_undo(self) -> None:
        if self._file_worker is not None or self.lib is None:
            return
        binding = getattr(self, "_file_entry", None)
        if not binding:
            return
        database, entry = binding    # the folder that filing acted on
        worker = filing.SortWorker.for_undo(chart_sort.unsorted_dir(database), entry)
        self._start_file_worker(worker)

    def _start_file_worker(self, worker) -> None:
        worker.applied.connect(self._filed)
        worker.undone.connect(self._file_undone)
        worker.failed.connect(lambda _k, m: self._file_done(f"Nothing more moved: {m}"))
        worker.finished.connect(lambda w=worker: self._file_released(w))
        self._file_worker = worker
        self._show_filing()
        worker.start()

    def _file_released(self, worker) -> None:
        if worker is self._file_worker:
            self._file_worker = None
            self._show_filing()

    def _filed(self, report) -> None:
        moved = sum(1 for r in report.results if r.moved)
        self._log_path = report.log_path
        self._file_entry = (self.lib.database, report.entry_id)  # UNDO: this filing only
        for r in report.results:
            if r.moved and r.folder == "Private":
                try:
                    os.chmod(Path(self.lib.database) / "Private" / r.filename, 0o600)
                except OSError:
                    pass
        self._proposal = None
        self.view.preview_text.setText("")
        self._file_done(f"{moved:,} chart{'' if moved == 1 else 's'} filed. "
                        + filing.REBUILD_NUDGE + ".")
        self._after_moves(moved)

    def _file_undone(self, report) -> None:
        self._file_entry = None
        self._file_done(filing.undo_text(report))
        self.view.file_undo_button.hide()
        self._after_moves(0)

    def _file_done(self, text) -> None:
        v = self.view
        v.file_result.setText(text)
        v.file_result.show()
        v.file_undo_button.setVisible(True)
        v.sort_log_button.setVisible(True)

    def _after_moves(self, moved) -> None:
        panel = self.panel
        if moved and hasattr(panel, "_moved_since_rebuild"):
            panel._moved_since_rebuild += moved
        if hasattr(panel, "refresh_unsorted_downloads"):
            panel.refresh_unsorted_downloads(force_recount=True)
        self.refresh()

    def _open_sort_log(self) -> None:
        if self.lib is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(chart_sort.unsorted_dir(self.lib.database))))

    # ---------------------------------------------------------- conversion
    def _convert_all(self) -> None:
        if self._convert_worker is not None or self.lib is None or self._kala:
            return
        if not confirm_convert(self.view, self._chtk_count, self.lib.database):
            return
        worker = ConvertWorker(self.lib.database)
        worker.done.connect(self._converted)
        worker.finished.connect(lambda w=worker: self._convert_released(w))
        self._convert_worker = worker
        self.view.convert_all_button.hide()
        self.view.stats_message.setText("Converting...")
        worker.start()

    def _convert_released(self, worker) -> None:
        if worker is self._convert_worker:
            self._convert_worker = None
            worker.deleteLater()

    def _converted(self, result) -> None:
        n, bad = len(result["converted"]), len(result["failed"])
        text = (f"{n:,} chart{'' if n == 1 else 's'} converted to .toml; the .chtk files are in "
                "CHTK backup. Rebuild Index to rate them.")
        if bad:
            text += f" {bad:,} could not be converted and stay as they were."
        self.view.stats_message.setText(text)

    # ---------------------------------------------------------- closing
    def stop(self, *, app_quit=False) -> None:
        """Panel close: stop after the current step; a worker still running
        after 5 s is parked. App quit: waited for."""
        if app_quit:
            for parked in list(_PARKED):
                parked.cancel() if hasattr(parked, "cancel") else None
                parked.wait()
        for name in ("_worker", "_convert_worker", "_file_worker"):
            worker = getattr(self, name)
            if worker is None:
                continue
            setattr(self, name, None)
            if hasattr(worker, "cancel") and name != "_file_worker":
                worker.cancel()
            with warnings.catch_warnings():  # a signal with no slot warns
                warnings.simplefilter("ignore", RuntimeWarning)
                for sig in ("loaded", "failed", "done", "applied", "undone", "progress",
                            "proposed"):
                    signal = getattr(worker, sig, None)
                    if signal is None:
                        continue
                    try:
                        signal.disconnect()
                    except (RuntimeError, TypeError):
                        pass
            done = worker.wait() if app_quit else worker.wait(5000)
            if not (done and not worker.isRunning()):
                _PARKED.add(worker)
                worker.finished.connect(lambda w=worker: _PARKED.discard(w))
        if self.state is not None:
            self.state.close()
            self.state = None
