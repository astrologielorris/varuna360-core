# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The problem-report scrubber (SPEC-AIR-001 §3.3, shared with SPEC-PRL-001).

Every text that leaves the machine because of a problem report passes here:
the AI's diagnostic tool results BEFORE they reach the user's AI provider
(AIR-001 INV-2), and every field of the report BEFORE the preview renders
(INV-3). One function, one set of rules, no branches per engine.

WHAT IS REMOVED
---------------
- Names: every chart name in the chart index and the chart file stems
  (whole names, ``LibraryScrub`` rules), plus names the caller adds (the
  charts open in this session).
- Places: every birth place and country in the index, each comma part.
- Patterns: full dates, times of day, coordinates (decimal pairs, lat/lon
  fields, DMS, CHTK "48n51"), email addresses, phone numbers, URLs that
  carry a query string, secrets (API keys, bearer tokens, JWTs, license
  keys, long random strings), the home path and the profile segment.

WHAT IS KEPT
------------
- Bare four-digit years and version numbers ("5.2.3", "2026"): diagnostic,
  identify no one (``privacy.py`` makes the same choice for years).
- The timestamp a LOG LINE starts with ("2026-10-21T21:06:31 ERROR ..."):
  when the failure happened is the diagnosis. Only with ``log_lines=True``.

It REDUCES the risk, it is not a guarantee: anything phrased outside these
rules passes. The user reads the preview; the report text says so.

FAIL CLOSED
-----------
``build_context`` never invents safety it does not have: when the chart index
cannot be read, ``ScrubContext.library_ok`` is False. The AI's diagnostic
tools must then refuse (AIR-001 INV-2); a basic report still scrubs with the
patterns and the caller's names, and says the library was unavailable.

No Qt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from core.diagnostics import redact_home

MARK_NAME = "<name>"
MARK_PLACE = "<place>"
MARK_DATE = "<date>"
MARK_TIME = "<time>"
MARK_COORDS = "<coords>"
MARK_EMAIL = "<email>"
MARK_PHONE = "<phone>"
MARK_URL = "<url>"
MARK_SECRET = "<secret>"

_MONTHS = (r"(?:jan(?:uary|vier)?|feb(?:ruary)?|f[ée]v(?:rier)?|mar(?:ch|s)?|apr(?:il)?|avr(?:il)?|"
           r"may|mai|june?|juin|july?|juil(?:let)?|aug(?:ust)?|ao[uû]t|sep(?:t(?:ember|embre)?)?|"
           r"oct(?:ober|obre)?|nov(?:ember|embre)?|dec(?:ember)?|d[ée]c(?:embre)?)\.?")

# Order matters: secrets and URLs first (they contain digits that would
# otherwise be read as dates or phones), then coordinates, dates, times.
_PATTERNS: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    (MARK_SECRET, re.compile(r"\bVARD(?:-[A-Z0-9]{4}){4}\b")),                       # license key
    (MARK_SECRET, re.compile(r"\b(?:sk-ant-|sk-|ghp_|gho_|github_pat_|xox[bp]-|AIza)[A-Za-z0-9_\-]{12,}")),
    (MARK_SECRET, re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),  # JWT
    (MARK_SECRET, re.compile(r"(?i)\b(bearer|token|api[_-]?key|password|secret)(\s*[=:]\s*|\s+)[^\s,;'\"]{8,}")),
    (MARK_URL, re.compile(r"\bhttps?://[^\s'\"<>]*\?[^\s'\"<>]+")),
    (MARK_EMAIL, re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    (MARK_COORDS, re.compile(r"(?i)\b(?:lat(?:itude)?|lon(?:gitude)?|lng)\b\s*[=:]\s*-?\d{1,3}(?:\.\d+)?")),
    (MARK_COORDS, re.compile(r"(?<![\w.])-?\d{1,3}\.\d{3,}\s*[,;/ ]\s*-?\d{1,3}\.\d{3,}(?![\w.])")),
    (MARK_COORDS, re.compile(r"\b\d{1,3}\s*°\s*\d{1,2}\s*['′]?(?:\s*\d{1,2}(?:\.\d+)?\s*[\"″])?\s*[NSEWnsew]?")),
    (MARK_COORDS, re.compile(r"\b\d{1,3}[nsewNSEW]\d{2}(?:'\d{2})?\b")),
    (MARK_DATE, re.compile(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[T ]\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?)?\b")),
    (MARK_DATE, re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")),
    (MARK_DATE, re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b")),   # dots: 4-digit year only (versions)
    (MARK_DATE, re.compile(r"(?i)\b\d{1,2}(?:st|nd|rd|th|er)?\s+" + _MONTHS + r"\s+\d{2,4}\b")),
    (MARK_DATE, re.compile(r"(?i)\b" + _MONTHS + r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{2,4}\b")),
    (MARK_TIME, re.compile(r"(?i)\b\d{1,2}[:h]\d{2}(?::\d{2})?\s*(?:am|pm)?\b")),
    (MARK_PHONE, re.compile(r"(?<![\w])0\d(?:[\s.\-]?\d{2}){4}(?![\w])")),
    (MARK_PHONE, re.compile(r"(?<![\w+])\+\d{1,3}[\s.\-]?(?:\(?\d{1,4}\)?[\s.\-]?){2,5}\d{2,4}\b")),
    (MARK_SECRET, re.compile(r"(?<![A-Za-z0-9_\-])(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}(?![A-Za-z0-9_\-])")),
)

# A lowercase hex digest (sha1/sha256, ids): correlation evidence, never
# personal. Kept only when a digest label comes just before it ("sha256 ...",
# "checksum=..."); any other long hex string may be a key and goes as
# <secret> (review W0 m8, review W1 B1).
_HEX_DIGEST = re.compile(r"(?<![A-Za-z0-9])[0-9a-f]{32,64}(?![A-Za-z0-9])")
_DIGEST_LABEL = re.compile(r"(?i)(?:sha-?\d*|md5|digest|hash|checksum|commit|etag)\W{0,3}$")
_SECRET_LABEL = re.compile(r"(?i)(?:key|token|secret|passw|auth|bearer|api)")
_HEX_TOKEN = "\x00HEX{}\x00"

# An absolute path OUTSIDE the home folder (redact_home already turned the
# home into "~"): every directory segment can name a person
# (/mnt/Clients/Alice_Private/...), so the directories become "<path>" and
# only the file name stays (scrubbed like any text). System locations keep
# their directories: they name software, not people (review W0 B1).
# A directory segment may hold single spaces ("Alice Private/"): it is a
# directory because a separator follows it.
_SEG = r"[^\s'\"<>|:*?\\/]+(?: [^\s'\"<>|:*?\\/]+)*"
_ABS_PATH = re.compile(
    r"(?<![\w~.:/\\])(?:[A-Za-z]:[\\/]|\\\\|//|/|\.\.?[\\/])(?:" + _SEG + r"[\\/])+(?=[^\s'\"<>|:*?\\/]*)")
# Only the interpreter's own root-owned tree keeps its directories. Anywhere
# else (/opt, /dev/shm, a venv in a client folder), everything before a
# package anchor (site-packages, dist-packages, PyInstaller's _internal) is
# masked and the package part kept: "/opt/clients/Alice/venv/lib/python3.12/
# site-packages/PySide6/x.py" -> "<path>/site-packages/PySide6/x.py"
# (review W2 B1: a code file or a "PySide6" folder name kept whole paths).
_PYTHON_HOME = re.compile(r"/usr/(?:local/)?lib(?:64)?/python3\.\d+/")
_SOFTWARE_ANCHOR = re.compile(r"[\\/]((?:site-packages|dist-packages|_internal)[\\/])")
MARK_PATH = "<path>/"
MARK_DIR = "<dir>"

# Under the home folder ("~/..."), only these folder names stay; any other
# segment is the user's own naming and becomes "<dir>" (~/Clients/Alice/x).
_HOME_DIRS = frozenset({
    "Documents", "Desktop", "Downloads", ".config", ".local", "share", ".cache",
    ".varuna360", "varuna360", "Varuna360", "Library", "Application Support",
    "AppData", "Local", "Roaming", "Temp", "profiles", "<profile>", "logs", "cache",
    "AI", "tasks", "reports", "settings_requests", "Kala", "Charts", "Dropbox",
    "OneDrive", "license_cache", "ephe", "site-packages", "lib", "python3.12"})
_HOME_PATH = re.compile(r"~(?:[\\/]" + _SEG + r")+[\\/](?=[^\s'\"<>|:*?\\/]*)")


def _home_dirs(m) -> str:
    text = m.group(0)
    sep = "\\" if "\\" in text else "/"
    parts = re.split(r"[\\/]", text.rstrip("\\/"))
    kept = [parts[0]] + [p if p in _HOME_DIRS else MARK_DIR for p in parts[1:]]
    return sep.join(kept) + sep


# file:///mnt/x -> /mnt/x ; file://server/share -> //server/share (UNC).
_FILE_URL = re.compile(r"(?i)\bfile:(?://(?=/|[A-Za-z]:)|(?=//))")
# A chart or data file is named after its person: its name goes whatever the
# chart index knows (review W4: "/mnt/Clients/Alice Smith.chtk").
_CHART_FILE = re.compile(
    r"(?<![\w<])(?!(?i:pyproject|config|settings|session|defaults?|app|theme|"
    r"manifest|requirements)\.)"
    r"(?:[A-Z][^\s'\"<>|:*?\\/]*(?: [A-Z][^\s'\"<>|:*?\\/]*){0,2}"   # Alice Smith.chtk
    r"|[^\s'\"<>|:*?\\/]+)"                                        # alice_smith.toml
    r"(\.(?i:chtk|toml|jhd|aaf|mtx|zbs|sfcht|qck|chart|csv))\b")
_MODULE_PARTS: Dict[str, Any] = {"n": -1, "parts": frozenset()}


def _module_dirs(tail: str) -> str:
    """After a package anchor only the names of modules this process has
    loaded stay; any other folder becomes <dir> (review W3: "site-packages/
    Alice Smith/" kept a name)."""
    import sys
    if _MODULE_PARTS["n"] != len(sys.modules):
        _MODULE_PARTS.update(n=len(sys.modules), parts=frozenset(
            p for name in list(sys.modules) for p in name.split(".")))
    parts = _MODULE_PARTS["parts"]
    segs = re.split(r"([\\/])", tail)
    out = []
    for i, seg in enumerate(segs):
        if i == 0 or seg in ("/", "\\") or seg in parts:
            out.append(seg)
        elif seg:
            out.append(MARK_DIR)
    return "".join(out)


def _paths(value: str) -> Tuple[str, int]:
    count = 0

    def repl(m):
        nonlocal count
        text = m.group(0)
        home = _PYTHON_HOME.match(text)
        if home:                                  # stdlib: module folders only
            return home.group(0) + _module_dirs("x/" + text[home.end():])[2:]
        count += 1
        anchor = _SOFTWARE_ANCHOR.search(text)
        if anchor:                                # <path>/site-packages/PySide6/...
            return MARK_PATH + _module_dirs(text[anchor.start(1):])
        return MARK_PATH
    value = _FILE_URL.sub("", value)              # file:///mnt/... is a path (review W4)
    value = _ABS_PATH.sub(repl, value)
    value, n_files = _CHART_FILE.subn(r"<file>\1", value)
    count += n_files
    before = value.count(MARK_DIR)
    value = _HOME_PATH.sub(_home_dirs, value)
    return value, count + value.count(MARK_DIR) - before


# "2026-10-21T21:06:31 ERROR ..." at the start of a log line (core.diagnostics
# formatter). Protected only with log_lines=True.
_LOG_STAMP = re.compile(r"^(\s*(?:L\d+\s+)?)(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", re.MULTILINE)
_STAMP_TOKEN = "\x00STAMP{}\x00"


@dataclass
class ScrubResult:
    text: str
    counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class ScrubContext:
    """Built once per session (or per report). ``library_ok`` False means the
    chart index could not be read: names and places are only the caller's."""

    names: object = None          # LibraryScrub or None
    places: object = None         # LibraryScrub or None
    library_ok: bool = False
    name_count: int = 0
    place_count: int = 0

    def scrub(self, text, *, log_lines: bool = False) -> ScrubResult:
        return scrub(text, self, log_lines=log_lines)


def _place_parts(places: Iterable[str]) -> list:
    out = []
    for place in places:
        for part in re.split(r"[,;/()]", str(place or "")):
            part = part.strip()
            if len(part) >= 3 and not part.isdigit():
                out.append(part)
    return list(dict.fromkeys(out))


def _stems(paths: Iterable[str]) -> list:
    out = []
    for p in paths:
        try:
            stem = Path(str(p)).stem
        except Exception:
            continue
        if stem:
            out.append(re.sub(r"[_]+", " ", stem))
    return out


def build_context(extra_names: Iterable[str] = (), extra_places: Iterable[str] = (),
                  store_path: Optional[Path] = None) -> ScrubContext:
    """A context from the chart index plus the caller's names. Never raises;
    ``library_ok`` tells whether the index was read."""
    from core.name_scrub import LibraryScrub

    names = [str(n) for n in extra_names if n]
    places = [str(p) for p in extra_places if p]
    library_ok = False
    try:
        from core.chart_search.store import StoreReader
        reader = StoreReader.open(store_path)
        try:
            with reader.snapshot():
                names += list(reader.entry_names())
                names += _stems(reader.entry_paths())
                places += list(reader.entry_places())
        finally:
            reader.close()
        library_ok = True
    except Exception:
        library_ok = False
    # The report's own name policy (review W0 M4): no vocabulary exemption.
    # A chart named "Mars" IS scrubbed (capitalized, as a name is written):
    # privacy wins over the diagnostic word. Only the few prose words of
    # privacy._COMMON_WORDS stay ("the", "de"...).
    from core.name_blind import _COMMON_WORDS
    keep = frozenset(_COMMON_WORDS)
    try:
        name_scrub = LibraryScrub(names, keep=keep, marker=MARK_NAME) if names else None
    except Exception:
        name_scrub, library_ok = None, False
    try:
        parts = _place_parts(places)
        place_scrub = LibraryScrub(parts, keep=keep, marker=MARK_PLACE) if parts else None
    except Exception:
        place_scrub, library_ok = None, False
    return ScrubContext(names=name_scrub, places=place_scrub, library_ok=library_ok,
                        name_count=len(name_scrub) if name_scrub else 0,
                        place_count=len(place_scrub) if place_scrub else 0)


def _count(before: str, after: str, marker: str) -> int:
    return max(0, after.count(marker) - before.count(marker))


def scrub(text, ctx: Optional[ScrubContext] = None, *, log_lines: bool = False) -> ScrubResult:
    """Scrub one text. Never raises: on an internal error the text is
    replaced entirely (fail closed) rather than returned unscrubbed."""
    if text is None:
        return ScrubResult("", {})
    value = str(text)
    if not value:
        return ScrubResult(value, {})
    try:
        counts: Dict[str, int] = {}
        value = redact_home(value)
        value, n_paths = _paths(value)
        if n_paths:
            counts["<path>"] = n_paths
        hexes = []

        def keep_hex(m):
            before = m.string[max(0, m.start() - 24):m.start()]
            if _DIGEST_LABEL.search(before) and not _SECRET_LABEL.search(before):
                hexes.append(m.group(0))
                return _HEX_TOKEN.format(len(hexes) - 1)
            counts[MARK_SECRET] = counts.get(MARK_SECRET, 0) + 1
            return MARK_SECRET
        value = _HEX_DIGEST.sub(keep_hex, value)
        stamps = []
        if log_lines:
            def keep(m):
                stamps.append(m.group(2))
                return m.group(1) + _STAMP_TOKEN.format(len(stamps) - 1)
            value = _LOG_STAMP.sub(keep, value)
        for marker, rx in _PATTERNS:
            new = rx.sub(marker, value)
            n = _count(value, new, marker)
            if n:
                counts[marker] = counts.get(marker, 0) + n
            value = new
        if ctx is not None:
            for marker, lib in ((MARK_NAME, ctx.names), (MARK_PLACE, ctx.places)):
                if lib is None:
                    continue
                new = lib.text(value)
                n = _count(value, new, marker)
                if n:
                    counts[marker] = counts.get(marker, 0) + n
                value = new
        for i, stamp in enumerate(stamps):
            value = value.replace(_STAMP_TOKEN.format(i), stamp)
        for i, digest in enumerate(hexes):
            value = value.replace(_HEX_TOKEN.format(i), digest)
        return ScrubResult(value, counts)
    except Exception:
        return ScrubResult("<removed: could not be checked>", {"error": 1})


def scrub_tree(value, ctx: Optional[ScrubContext] = None, totals: Optional[Dict[str, int]] = None,
               *, keep_keys: Iterable = (), log_keys: Iterable = (),
               field_names: Iterable = ()):
    """Scrub every string in a JSON-like tree, dictionary KEYS included.

    ``keep_keys`` / ``log_keys`` name EXACT paths from the root: a string
    ("schema") is a top-level key, a tuple (("ai", "engine")) a nested one.
    A key elsewhere in the tree with the same leaf name is scrubbed like any
    text (review W0 B2: a nested "id" or "contact_email" must not inherit a
    top-level exemption). ``keep_keys`` values are the app's own protocol
    values and stay; ``log_keys`` hold log text (line timestamps kept).
    ``field_names``: the payload's own schema field names, never renamed as
    keys (a chart named "title" must not rename the report's title field and
    get the report refused by the server)."""
    def norm(paths):
        return frozenset(p if isinstance(p, tuple) else (p,) for p in paths)
    keep = norm(keep_keys)
    fields = frozenset(field_names)
    logs = norm(log_keys)
    totals = totals if totals is not None else {}

    def text(v, path):
        r = scrub(v, ctx, log_lines=path in logs)
        for m, n in r.counts.items():
            totals[m] = totals.get(m, 0) + n
        return r.text

    def walk(v, path):
        if isinstance(v, dict):
            out = {}
            for k, x in v.items():
                sub_path = path + (k,)
                key = k if (sub_path in keep or len(path) == 0 or not isinstance(k, str)
                            or k in fields) else text(k, ())
                out[key] = walk(x, sub_path)
            return out
        if isinstance(v, (list, tuple)):
            return [walk(x, path) for x in v]
        if isinstance(v, str):
            return v if path in keep else text(v, path)
        return v

    return walk(value, ())
