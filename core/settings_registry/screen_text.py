# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The screen boundary of the message vocabulary (SPEC-SET-003 D-21, W6c).

A message key of ``cli_text`` (``TEXT`` and ``PENDING_TEXT``), its
structured form ``<key>: <field>=<value> ...`` and the ``[COPY PENDING]``
marker belong to the command line and to the protocol replies an AI engine
reads. They never reach a window. The contract (review fix round 3):

(a) text the APP writes (labels, tool reply sentences, drawer rows,
    refusals, tool errors) never holds a key or the marker: at source;
(b) the AI's OWN free text gets one final gate on what is shown (after
    Markdown and whitespace), on the whole answer, live and on reopen;
(c) the gate removes only the key or marker token, never the data, values
    or setting names around it.

- ``screen_reply(reply)``: a whole reply in words. A change made (applied,
  stale, not saved, no app) always shows its own approved sentence with its
  data values cleaned, or nothing when a field it names is missing; a
  refusal shows its approved text when complete and clean, otherwise the
  approved ``app.refused`` line with its reason code; so does a reply whose
  status cannot be told.
- ``clean_text(text)`` / ``clean_parts(parts)``: free text (one text, or the
  pieces of one shown text such as an answer's segments across tool calls):
  every key and marker found in the text AS SHOWN (``_view``: NFKC, no zero
  width characters, no Markdown delimiters, whitespace runs as one space)
  is removed, the token only.
- ``clean_data(value)``: ``clean_text`` on every string of a JSON value,
  dictionary keys included.

Setting keys (``chart.show_outer_planets``) are data and stay visible: no
setting key is a message key (``test_ai_settings_no_raw_keys`` pins it).
The protocol reply itself is never changed here: callers render a copy.
The task page's final gate (``task_window.html`` ``gateTurn``) runs the same
pattern (``page_pattern``) on the same view of the rendered text.

Qt-free, data only.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional

from core.settings_registry import cli_text

MARKER = cli_text.COPY_PENDING
# The reason code shown for a reply that is not a refusal and cannot be
# shown in its own words (a malformed tool result).
MALFORMED_REASON = "tool_error"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def vocabulary() -> frozenset:
    """Every message key: approved and pending."""
    return frozenset(cli_text.TEXT) | frozenset(cli_text.PENDING_TEXT)


# The marker in any case and spacing (it never occurs in normal English).
_MARKER = (r"\[\s{0,3}[Cc][Oo][Pp][Yy]\s{0,3}[Pp][Ee][Nn][Dd][Ii][Nn][Gg]\s{0,3}\]")


@lru_cache(maxsize=4)
def _pattern(keys: frozenset):
    """A message key in its EXACT form, the only form the app ever writes
    (review R4-1): case-sensitive, contiguous, standing alone (not part of a
    longer dotted name: a setting name or ``help.zr_jd.custom`` is data); or
    the marker in any case and spacing. Normal English (``Advanced. On``,
    ``Help. Show``) is never a key. A key written in another case or spaced
    is P3 (only an obfuscating provider writes one, SPEC-SET-003 §4.5b).
    Only the token itself: what follows it is data and stays (R3-4)."""
    alternation = "|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True))
    return re.compile(r"(?<![\w.])(?:%s)(?![\w])(?!\.\w)|%s" % (alternation, _MARKER),
                      re.ASCII)


def _regex():
    return _pattern(vocabulary())


def page_pattern() -> str:
    """The same pattern for the task page's own floor and final gate
    (JavaScript, flag ``g``; review R2-5): built from the same vocabulary."""
    return _regex().pattern


# The view of a text (reviews R3-1, R3-6): what a screen shows of it, the
# text the pattern runs on. Format characters (zero width) are dropped, every
# character is NFKC normalised (a fullwidth letter is the letter), Markdown
# emphasis and code delimiters (``*``, a backtick, ``~``, an ``_`` not inside
# a word) and an escaping backslash are dropped (the page renders them away)
# and every whitespace run is one space. Each view character maps back to
# the original characters it came from, so only those are removed.
_DELIMS = frozenset("*`~")
_ESCAPABLE = frozenset("\\`*_{}[]()#+-.!|~>")
_PLAIN_RUN = re.compile(r"[^\s\\*`~_\x80-\U0010ffff]+")


def _dropped(text: str, i: int, before: str = "", after: str = "") -> bool:
    """Whether ``text[i]`` is not shown: a format character, a Markdown
    delimiter, an escaping backslash, an ``_`` not between two letters or
    digits. ``before`` / ``after``: the character just outside ``text`` when
    the next piece joins it directly (review R6-1: a key split at an
    underscore between two segments is judged on the joined text)."""
    ch = text[i]
    if ch in _DELIMS or unicodedata.category(ch) == "Cf":
        return True
    prev = text[i - 1] if i > 0 else before
    nxt = text[i + 1] if i + 1 < len(text) else after
    if ch == "\\":
        return bool(nxt) and nxt in _ESCAPABLE
    if ch == "_":
        return not (prev.isalnum() and nxt.isalnum())
    return False


def _view(parts, breaks=()):
    """``parts`` (the pieces of one shown text) joined as a screen shows
    them: directly, or with a block break (one space) before each part whose
    index is in ``breaks``. Returns the view string and, per view character,
    ``(part, start, end)`` in the original (None for a block break)."""
    chars, where = [], []

    def space(src):
        if chars and chars[-1] == " ":
            last = where[-1]
            if src is not None and last is not None and last[0] == src[0]:
                where[-1] = (src[0], last[1], src[2])
            return
        chars.append(" ")
        where.append(src)

    for p, text in enumerate(parts):
        if p in breaks:
            space(None)
        before = parts[p - 1][-1:] if p > 0 and p not in breaks else ""
        after = parts[p + 1][:1] if p + 1 < len(parts) and p + 1 not in breaks else ""
        i, n = 0, len(text)
        while i < n:
            run = _PLAIN_RUN.match(text, i)
            if run:
                j = run.end()
                chars.extend(text[i:j])
                where.extend((p, k, k + 1) for k in range(i, j))
                i = j
                continue
            ch = text[i]
            if _dropped(text, i, before, after):
                i += 1
                continue
            for c in unicodedata.normalize("NFKC", ch):
                if c.isspace():
                    space((p, i, i + 1))
                elif unicodedata.category(c) != "Cf":
                    chars.append(c)
                    where.append((p, i, i + 1))
            i += 1
    return "".join(chars), where


def _found(view: str):
    return list(_regex().finditer(view))


def has_raw(text: Any) -> bool:
    """Whether ``text``, as a screen shows it, holds a message key or the
    marker anywhere (embedded, on any line, any case, spaced, split around
    its dots, formatted, zero width or fullwidth)."""
    return isinstance(text, str) and bool(_found(_view([text])[0]))


def _offsets(parts):
    out, pos = [], 0
    for text in parts:
        out.append(pos)
        pos += len(text)
    return out


def _span(match, where, offsets, joined):
    """The original characters of one key in the view, ``[start, end)`` in
    the parts joined, widened over the Markdown delimiters that wrap it on
    BOTH sides alike (`` `help.zr_jd` `` goes whole); a delimiter that opens
    or closes a larger span stays, so the span stays balanced (review R5-4).
    None for none."""
    hits = [(offsets[w[0]] + w[1], offsets[w[0]] + w[2])
            for w in where[match.start():match.end()] if w is not None]
    if not hits:
        return None
    a, b = min(h[0] for h in hits), max(h[1] for h in hits)
    while (a > 0 and b < len(joined) and joined[a - 1] == joined[b]
           and joined[b] in _WRAP):
        a, b = a - 1, b + 1
    # a key whose own text holds the closing (or opening) half of a span
    # (``**help**.zr_jd``) takes the other half with it
    inner = _RUN.findall(joined[a:b])
    if len(inner) == 1:
        left, right = _RUN_END.search(joined, 0, a), _RUN.match(joined, b)
        if left and left.group(0) == inner[0]:
            a = left.start()
        elif right and right.group(0) == inner[0]:
            b = right.end()
    return a, b


_WRAP = "*`~_"     # Markdown delimiters a key can be wrapped in
_RUN = re.compile(r"[*`~]+")
_RUN_END = re.compile(r"[*`~]+$")


def _cut(joined: str, a: int, b: int):
    """``[a, b)`` widened by the one space the removal would leave doubled
    (or before a punctuation mark, or at a line's edge); nothing else of the
    text goes (review R3-4)."""
    left = joined[a - 1] if a > 0 else "\n"
    right = joined[b] if b < len(joined) else "\n"
    if left in " \t" and (right in " \t\n" or right in ".,;:!?)" or right in _WRAP):
        a -= 1
    elif (left == "\n" or left in _WRAP) and right in " \t":
        b += 1
    return a, b


def _delete(parts, a: int, b: int):
    """``[a, b)`` of the parts joined removed from the parts themselves."""
    out, pos = [], 0
    for text in parts:
        lo, hi = max(a, pos) - pos, min(b, pos + len(text)) - pos
        out.append(text[:lo] + text[hi:] if lo < hi else text)
        pos += len(text)
    return out


def _clean_pass(parts, breaks=()):
    """One pass: every key and marker found in the view removed from the
    original parts (from the end backwards, a key split between parts from
    each of them); None when there is none."""
    view, where = _view(parts, breaks)
    found = _found(view)
    if not found:
        return None
    offsets, joined = _offsets(parts), "".join(parts)
    spans = [sp for sp in (_span(m, where, offsets, joined) for m in found) if sp]
    out = list(parts)
    for a, b in sorted(spans, reverse=True):
        a, b = _cut("".join(out), a, b)
        out = _delete(out, a, b)
    return out


def clean_parts(parts, breaks=()):
    """The pieces of ONE shown text with every message key and marker
    removed, judged on the pieces joined as shown (directly, or with a block
    break before each index in ``breaks``: a working note is its own block);
    only the key or marker token goes, never the data around it (review
    R3-4). Repeated until a pass finds nothing; still raw after that: every
    piece empty."""
    parts = [p if isinstance(p, str) else "" for p in parts]
    breaks = frozenset(breaks)
    for _ in range(32):
        out = _clean_pass(parts, breaks)
        if out is None:
            return parts
        parts = out
    return parts if not _found(_view(parts, breaks)[0]) else [""] * len(parts)


def clean_text(text: Any) -> Any:
    """``text`` with every message key and every marker removed: the key or
    marker token only, never the data around it (its own ``field=value``
    pairs, setting names, values: review R3-4); repeated until a pass finds
    nothing, the result stripped; never raw (an empty string before a raw
    one). Not a string: as is."""
    if not isinstance(text, str) or not has_raw(text):
        return text
    out = clean_parts([text])[0].strip()
    return "" if has_raw(out) else out


def clean_data(value: Any) -> Any:
    """``clean_text`` on every string of a JSON value, dictionary keys too."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, dict):
        return {clean_text(k) if isinstance(k, str) else k: clean_data(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_data(v) for v in value]
    return value


def required_fields(key: str) -> Iterable[str]:
    """The fields the approved text of ``key`` names (none when pending)."""
    return _PLACEHOLDER.findall(cli_text.TEXT.get(key) or "")


def _reason_code(reply: Dict[str, Any]) -> str:
    reason = reply.get("reason")
    if isinstance(reason, str) and reason and re.fullmatch(r"[a-z_]+", reason):
        return reason
    return MALFORMED_REASON


def refused_line(reply: Dict[str, Any]) -> str:
    """The approved ``app.refused`` line with the reply's reason code (a
    reply that has none, or not a plain code: ``tool_error``)."""
    return cli_text.message("app.refused", reason=_reason_code(reply))


_SKIP_FIELDS = ("status", "offline", "v", "id", "target", "message")


def _outcome_line(reply: Dict[str, Any], key: str) -> str:
    """A reply that is not a refusal (applied, stale, not saved, no app),
    review R2-3: always its own approved sentence, its data values cleaned
    (``clean_data``), never the refused line. An incomplete one (a field its
    sentence names is missing) has no approved sentence that would be true:
    no sentence at all (empty), never a refusal."""
    from core.settings_registry import app_requests as ar
    if any(name not in reply for name in required_fields(key)):
        return ""
    cleaned = {k: clean_data(v) for k, v in reply.items() if k not in _SKIP_FIELDS}
    line = ar.reply_message({**reply, **cleaned})
    if not line or cli_text.is_structured(key, line):
        return ""
    return clean_text(line)


def _malformed(reply: Any) -> bool:
    """A reply whose status or reason is not a plain code (review R2-6)."""
    if not isinstance(reply, dict) or not isinstance(reply.get("status"), str):
        return True
    reason = reply.get("reason")
    return reason is not None and not (isinstance(reason, str)
                                       and re.fullmatch(r"[a-z_]+", reason))


def screen_reply(reply: Optional[Dict[str, Any]]) -> str:
    """A reply in words for a screen (see the module docstring). Fails
    closed (review R2-6): a malformed reply, or any error while screening,
    gives the approved refused line with ``tool_error``."""
    try:
        if _malformed(reply):
            return refused_line({})
        return _screen_reply(reply)
    except Exception:                                             # noqa: BLE001
        return refused_line({})


# The reply field that says when an applied change shows (AI setting
# redesign, td-bztjj): ``next_start`` = read at startup only.
APPLIES_FIELD, NEXT_START = "applies", "next_start"


def _changed_line(reply: Dict[str, Any]) -> str:
    """An applied change in the Settings words (AI setting redesign, item 5):
    ``Changed {label} to {value}.``, the setting's label and the value's own
    label (``labels``), then the next-start note when the change shows only
    after a restart. "" when the reply names no registry key or value."""
    from core import settings_registry as registry
    from core.settings_registry.labels import display_label, value_label
    key, value = reply.get("key"), reply.get("value", _ABSENT)
    if not isinstance(key, str) or not registry.has(key) or value is _ABSENT:
        return ""
    line = cli_text.message("app.changed", label=display_label(key),
                            value=clean_text(value_label(key, value)))
    if reply.get(APPLIES_FIELD) == NEXT_START:
        line = f"{line} {cli_text.message('app.next_start')}"
    return clean_text(line)


_ABSENT = object()


def _screen_reply(reply: Dict[str, Any]) -> str:
    from core.settings_registry import app_requests as ar
    if reply.get("status") == ar.APPLIED and not reply.get("offline"):
        line = _changed_line(reply)
        if line:
            return line
    key = ar.message_key(reply)
    if reply.get("status") in (ar.APPLIED, ar.STALE, ar.NOT_SAVED, ar.NO_APP) \
            and not cli_text.is_pending(key):
        return _outcome_line(reply, key)
    if cli_text.is_pending(key):
        return refused_line(reply)
    # Every field the approved words name must be in the reply (a malformed
    # tool result, review F3): else the structured form would show.
    fields = {k for k in reply if k not in _SKIP_FIELDS}
    if key == "app.refused":
        if not isinstance(reply.get("reason"), str):
            return refused_line(reply)
        fields.add("reason")
    if any(name not in fields for name in required_fields(key)):
        return refused_line(reply)
    line = ar.reply_message(reply)
    if not line or cli_text.is_structured(key, line) or has_raw(line):
        return refused_line(reply)
    return line


SETTINGS_TOOL = "set_app_setting"


def _screen_object(obj: Any, settings_reply: bool) -> Any:
    """One unwrapped tool result for a screen: a settings reply's ``message``
    becomes ``screen_reply`` (the protocol keeps its own copy); every other
    string loses any message key or marker (``clean_data``)."""
    if settings_reply and isinstance(obj, dict) and _malformed(obj):
        # Fails closed (R2-6): the refused line alone, no raw field shown.
        return {"status": "refused", "message": refused_line({})}
    if settings_reply and isinstance(obj, dict):
        shown = {k: v for k, v in obj.items() if k != "message"}
        out = clean_data(shown)
        message = screen_reply(obj)
        if message:
            out["message"] = message
        return out
    return clean_data(obj)


def screen_tool_payload(tool_name: str, payload: Any) -> Any:
    """A COPY of a tool result as a window shows it (the AI task window's
    tool-result drawer, review F1): the MCP envelope kept (``content`` text
    blocks holding JSON, ``json`` blocks, or a bare value), every block
    screened by ``_screen_object``. ``set_app_setting`` replies are shown as
    the panel shows them. The payload the engine received is untouched."""
    try:
        return _screen_tool_payload(tool_name, payload)
    except Exception:                                             # noqa: BLE001
        return closed_payload()


def closed_payload() -> Dict[str, Any]:
    """What a window shows of a tool result it could not screen (review
    R2-6, fails closed): the approved refused line, nothing of the result."""
    import json
    return {"content": [{"type": "text", "text": json.dumps(
        {"status": "refused", "message": refused_line({})})}], "isError": True}


def _screen_tool_payload(tool_name: str, payload: Any) -> Any:
    import json
    settings_reply = (tool_name or "").split("__")[-1] == SETTINGS_TOOL
    if isinstance(payload, str):
        try:
            inner = json.loads(payload)
        except ValueError:
            return clean_text(payload)
        return json.dumps(_screen_object(inner, settings_reply), ensure_ascii=False)
    if isinstance(payload, dict) and isinstance(payload.get("content"), list):
        blocks = []
        for block in payload["content"]:
            if isinstance(block, dict) and block.get("type") == "text" \
                    and isinstance(block.get("text"), str):
                blocks.append({**block, "text": _screen_tool_payload(tool_name, block["text"])})
            elif isinstance(block, dict) and block.get("type") == "json":
                blocks.append({**block, "value": _screen_object(block.get("value"),
                                                                settings_reply)})
            else:
                blocks.append(clean_data(block) if isinstance(block, dict) else block)
        return {**payload, "content": blocks}
    return _screen_object(payload, settings_reply)


class StreamScreen:
    """A streamed answer through the screen boundary (reviews R2-2, R4-2): the
    ASSEMBLED text is screened, never fragment by fragment (a key can be
    split across deltas), and incrementally: the text already screened and
    shown stays, each ``feed`` checks only the new text with ``BACK``
    characters of context before it, and keeps back the last ``HOLD``
    characters (and any key reaching into them) until more text comes.
    ``flush`` (a segment's end) screens the whole text once more. Each call
    returns ``("delta", text)`` to append, ``("replace", old, new)`` when
    text already shown must change, or None."""

    HOLD = 96              # more than the longest key (36) or marker
    BACK = 96              # context before the shown end (a key's left edge)

    def __init__(self):
        self.raw = ""
        self.sent = ""
        self.pos = 0       # raw[:pos] is screened and shown (as ``sent``)

    def reset(self) -> None:
        self.raw = ""
        self.sent = ""
        self.pos = 0

    def feed(self, text: str):
        self.raw += text or ""
        cut = len(self.raw) - self.HOLD
        if cut <= self.pos:
            return None
        start = max(0, self.pos - self.BACK)
        window = self.raw[start:]
        view, where = _view([window])
        spans = sorted((a + start, b + start) for a, b in
                       (sp for sp in (_span(m, where, [0], window) for m in _found(view)) if sp))
        for a, b in reversed(spans):
            if a < cut < b:
                cut = a
        if cut <= self.pos:
            return None
        piece = self.raw[self.pos:cut]
        for a, b in reversed(spans):
            if a >= self.pos and b <= cut:
                a, b = _cut(self.raw, a, b)
                a, b = max(a, self.pos), min(b, cut)
                piece = piece[:a - self.pos] + piece[b - self.pos:]
        self.pos = cut
        if not piece:
            return None
        self.sent += piece
        return ("delta", piece)

    def flush(self):
        out = self._emit(clean_text(self.raw))
        self.pos = len(self.raw)
        return out

    def _emit(self, target: str):
        if target.startswith(self.sent):
            delta = target[len(self.sent):]
            self.sent = target
            return ("delta", delta) if delta else None
        old, self.sent = self.sent, target
        return ("replace", old, target)
