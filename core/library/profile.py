# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""The sorting profile (SPEC-LIB-002 §3.4): rules as data, never code.

``<library>/.library/sorting_profile.json`` when it exists, else the
built-in ``builtin_profile.json``. ``validate`` names the place of every
problem; ``guess(profile, facts)`` gives, per row, the value of the matching
rule with the highest weight, its weight as confidence and its label as source.

``facts`` (all optional): ``folders`` (folder names of the chart, relative to
its chart folder), ``name``, ``stem`` (file name without suffix), ``copies``,
``variants``, ``no_birth_time``, ``origin``, ``first_seen`` (ISO date),
``opened`` (epoch seconds), ``biography`` (its status).
"""
import datetime
import functools
import json
import re
import time
from pathlib import Path
from typing import List, Mapping, Optional

from core.library import admin, rating

FILE = "sorting_profile.json"
BUILTIN = Path(__file__).with_name("builtin_profile.json")
WRITERS = ("builtin", "user")  # and "ai:<model>"

_LIST_CONDITIONS = ("folder_word", "name_tag", "origin")
_INT_CONDITIONS = ("copies_at_least", "variants_at_least", "known_days_at_least",
                   "opened_within_days")
_BOOL_CONDITIONS = ("no_birth_time",)
_STR_CONDITIONS = ("biography",)
CONDITIONS = _LIST_CONDITIONS + _INT_CONDITIONS + _BOOL_CONDITIONS + _STR_CONDITIONS


class ProfileError(ValueError):
    """The profile does not follow the rule schema; the message names the place."""


@functools.lru_cache(maxsize=65536)
def _token_set(text: str) -> frozenset:
    # One split per distinct folder, name or file stem: a profile run asks for
    # the same few hundred words once per rule and per chart (5,000+ charts).
    text = (text or "").lower()
    return frozenset({t for t in re.split(r"[^0-9a-zà-ÿ]+", text) if t} | ({text} if text else set()))


def _tokens(text: str) -> set:
    return set(_token_set(text or ""))


def validate(doc, *, ai: bool = False) -> List[str]:
    """Every problem, each with its place (``rules[3].guess.who``). ``ai``: an
    AI-written profile may guess rows 1 and 2 only (D-24)."""
    errors = []
    if not isinstance(doc, Mapping):
        return ["the profile is not an object"]
    meta = doc.get("profile")
    if not isinstance(meta, Mapping) or not isinstance(meta.get("name"), str):
        errors.append("profile.name is missing")
    elif not isinstance(meta.get("version"), int):
        errors.append("profile.version is not a whole number")
    rules = doc.get("rules")
    if not isinstance(rules, list):
        return errors + ["rules is not a list"]
    for i, rule in enumerate(rules):
        at = f"rules[{i}]"
        if not isinstance(rule, Mapping):
            errors.append(f"{at} is not an object")
            continue
        if not isinstance(rule.get("label"), str) or not rule["label"].strip():
            errors.append(f"{at}.label is missing")
        weight = rule.get("weight")
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not 0 < weight <= 1:
            errors.append(f"{at}.weight must be above 0 and at most 1")
        when = rule.get("when")
        if not isinstance(when, Mapping) or not when:
            errors.append(f"{at}.when is missing")
        else:
            for key, value in when.items():
                place = f"{at}.when.{key}"
                if key not in CONDITIONS:
                    errors.append(f"{place} is not a known condition")
                elif key in _LIST_CONDITIONS and not (
                        isinstance(value, list) and value and all(isinstance(v, str) for v in value)):
                    errors.append(f"{place} must be a list of words")
                elif key in _INT_CONDITIONS and (isinstance(value, bool) or not isinstance(value, int)
                                                 or value < 0):
                    errors.append(f"{place} must be a whole number")
                elif key in _BOOL_CONDITIONS and not isinstance(value, bool):
                    errors.append(f"{place} must be true or false")
                elif key in _STR_CONDITIONS and not isinstance(value, str):
                    errors.append(f"{place} must be a word")
        guess = rule.get("guess")
        if not isinstance(guess, Mapping) or not guess:
            errors.append(f"{at}.guess is missing")
            continue
        for row, value in guess.items():
            place = f"{at}.guess.{row}"
            if row not in rating.ROWS:
                errors.append(f"{place} is not a rating row")
            elif ai and row in ("know_them", "favourite"):
                errors.append(f"{place}: only you can rate this row")
            elif row == "who" and value not in rating.WHO:
                errors.append(f"{place} is not one of {', '.join(rating.WHO)}")
            elif row != "who" and rating._level(value) is None:
                errors.append(f"{place} must be 0 to 5")
    return errors


def builtin() -> dict:
    return json.loads(BUILTIN.read_text(encoding="utf-8"))


def load(library_root: Optional[Path]) -> dict:
    """The user's profile when it exists and is valid, else the built-in one.
    A broken file is reported in ``doc["_error"]`` and the built-in one runs."""
    path = Path(library_root) / admin.ADMIN / FILE if library_root else None
    if path is None or not path.exists():
        return builtin()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        doc = None
        problems = [f"cannot be read: {exc}"]
    else:
        writer = str((doc.get("profile") or {}).get("written_by", "")) if isinstance(doc, dict) else ""
        problems = validate(doc, ai=writer.startswith("ai:"))
    if problems:
        fallback = builtin()
        fallback["_error"] = f"{FILE}: " + "; ".join(problems[:3])
        return fallback
    return doc


def save(library_root: Path, doc: dict) -> Path:
    """Write a valid profile; the previous version is kept beside it."""
    writer = str((doc.get("profile") or {}).get("written_by", ""))
    problems = validate(doc, ai=writer.startswith("ai:"))
    if problems:
        raise ProfileError("; ".join(problems))
    folder = admin.root(Path(library_root))
    path = folder / FILE
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        version = (old.get("profile") or {}).get("version", 0)
        admin.write_text(folder / f"sorting_profile.v{version}.json", path.read_text(encoding="utf-8"))
    admin.write_text(path, json.dumps(doc, ensure_ascii=False, indent=2))
    return path


@functools.lru_cache(maxsize=4096)
def _lowered(words: tuple) -> frozenset:
    return frozenset(w.lower() for w in words)


def matches(when: Mapping, facts: Mapping, now: Optional[float] = None, _memo=None) -> bool:
    """``_memo``: a dict kept by ``guess`` for one ``facts``, so the chart's
    words are made once for all the rules."""
    now = time.time() if now is None else now
    memo = {} if _memo is None else _memo
    for key, want in when.items():
        if key == "folder_word":
            have = memo.get("folders")
            if have is None:
                have = set()
                for part in facts.get("folders") or ():
                    have |= _token_set(part or "")
                memo["folders"] = have
            if not have & _lowered(tuple(want)):
                return False
        elif key == "name_tag":
            have = memo.get("name")
            if have is None:
                have = memo["name"] = (_token_set(facts.get("name", "") or "")
                                       | _token_set(facts.get("stem", "") or ""))
            if not have & _lowered(tuple(want)):
                return False
        elif key == "origin":
            if facts.get("origin") not in want:
                return False
        elif key == "copies_at_least":
            if int(facts.get("copies") or 1) < want:
                return False
        elif key == "variants_at_least":
            if facts.get("variants") is None or facts["variants"] < want:
                return False
        elif key == "no_birth_time":
            if bool(facts.get("no_birth_time")) != want:
                return False
        elif key == "known_days_at_least":
            try:
                since = datetime.date.fromisoformat(facts.get("first_seen") or "")
            except ValueError:
                return False
            if (datetime.date.fromtimestamp(now) - since).days < want:
                return False
        elif key == "opened_within_days":
            opened = facts.get("opened")
            if not opened or now - opened > want * 86400:
                return False
        elif key == "biography":
            if facts.get("biography") != want:
                return False
        else:
            return False
    return True


def guess(profile: Mapping, facts: Mapping, now: Optional[float] = None) -> dict:
    """``{row: {"value", "confidence", "source"}}`` for the rows a rule sets."""
    out = {}
    memo = {}
    for rule in profile.get("rules") or ():
        if not matches(rule["when"], facts, now, memo):
            continue
        for row, value in rule["guess"].items():
            if row not in out or rule["weight"] > out[row]["confidence"]:
                out[row] = {"value": value, "confidence": float(rule["weight"]),
                            "source": rule["label"]}
    return out


def describe(profile: Mapping) -> List[str]:
    """Each rule in plain words (SHOW RULES)."""
    lines = []
    for rule in profile.get("rules") or ():
        sets = ", ".join(f"{rating.ROW_TITLES[r].lower()}: {rating.words(r, v) or v}"
                         for r, v in rule["guess"].items())
        lines.append(f"{rule['label']} → {sets} (weight {rule['weight']:g})")
    return lines
