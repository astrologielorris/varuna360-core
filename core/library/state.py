# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""``<library>/.library/library_state.sqlite`` (SPEC-LIB-002 §3.3, D-22, D-40).

Owner only (0600 in a 0700 folder). Two kinds of table:

- **kept** (a rebuild of the index never touches them): ``skips`` (a group
  left for 7 days), ``opened`` (last opened per chart path), ``ai_guesses``
  (a paid answer), ``meta`` (the profile's last run).
- **caches** (rebuilt from the chart files and the profile at any time):
  ``ratings``, the mirror of each ``.toml``'s ``[rating]`` keyed by path with
  the file's mtime and size, and ``guesses``, the rule guesses per group.

D-40 (simplification): the caches live here, not in the Find Chart store, so
the store's schema, its export and its rebuild stay as they are.
Nothing in this file is a rating: a rating lives in its chart file.
"""
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, Iterable, Optional

from core.library import admin

NAME = "library_state.sqlite"
SKIP_DAYS = 7

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS skips (grp TEXT PRIMARY KEY, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS opened (path TEXT PRIMARY KEY, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ai_guesses (grp TEXT PRIMARY KEY, who TEXT, known INTEGER,
    folder TEXT, model TEXT, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ratings (path TEXT PRIMARY KEY, mtime REAL, size INTEGER,
    rating TEXT);
CREATE TABLE IF NOT EXISTS guesses (grp TEXT PRIMARY KEY, data TEXT NOT NULL,
    profile_version INTEGER, at REAL NOT NULL);
"""


class State:
    """One connection; use from one thread at a time."""

    def __init__(self, library_root: Path):
        folder = admin.root(Path(library_root))
        self.path = folder / NAME
        new = not self.path.exists()
        self.conn = sqlite3.connect(str(self.path), timeout=5)
        if new:
            os.chmod(self.path, 0o600)
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------------------------------------------------------- kept
    def skip(self, group: str, at: Optional[float] = None) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO skips VALUES (?, ?)",
                              (group, time.time() if at is None else at))

    def unskip(self, group: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM skips WHERE grp = ?", (group,))

    def skipped(self, now: Optional[float] = None) -> set:
        """Groups skipped in the last ``SKIP_DAYS`` days."""
        since = (time.time() if now is None else now) - SKIP_DAYS * 86400
        return {g for (g,) in self.conn.execute("SELECT grp FROM skips WHERE at >= ?", (since,))}

    def mark_opened(self, path: str, at: Optional[float] = None) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO opened VALUES (?, ?)",
                              (path, time.time() if at is None else at))

    def opened(self) -> Dict[str, float]:
        return dict(self.conn.execute("SELECT path, at FROM opened"))

    def set_ai_guess(self, group: str, who, known, folder: str, model: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO ai_guesses VALUES (?, ?, ?, ?, ?, ?)",
                              (group, who, known, folder, model, time.time()))

    def ai_guesses(self) -> Dict[str, dict]:
        return {g: {"who": w, "known": k, "folder": f, "model": m}
                for g, w, k, f, m in self.conn.execute(
                    "SELECT grp, who, known, folder, model FROM ai_guesses")}

    def get_meta(self, key: str, default=None):
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key: str, value) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                              (key, json.dumps(value)))

    # ---------------------------------------------------------- caches
    def mirror(self) -> Dict[str, tuple]:
        """path -> (mtime, size, rating dict or None)."""
        return {p: (m, s, json.loads(r) if r else None)
                for p, m, s, r in self.conn.execute("SELECT path, mtime, size, rating FROM ratings")}

    def set_mirror(self, rows: Iterable[tuple]) -> None:
        """``(path, mtime, size, rating or None)`` rows."""
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO ratings VALUES (?, ?, ?, ?)",
                [(p, m, s, json.dumps(r, ensure_ascii=False) if r else None)
                 for p, m, s, r in rows])

    def forget_mirror(self, paths: Iterable[str]) -> None:
        with self.conn:
            self.conn.executemany("DELETE FROM ratings WHERE path = ?", [(p,) for p in paths])

    def guesses(self) -> Dict[str, dict]:
        return {g: json.loads(d) for g, d in self.conn.execute("SELECT grp, data FROM guesses")}

    def set_guesses(self, rows: Dict[str, dict], version: int) -> None:
        now = time.time()
        with self.conn:
            self.conn.execute("DELETE FROM guesses")
            self.conn.executemany(
                "INSERT INTO guesses VALUES (?, ?, ?, ?)",
                [(g, json.dumps(d, ensure_ascii=False), version, now) for g, d in rows.items()])
