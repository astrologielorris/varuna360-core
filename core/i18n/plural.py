# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""Generic CLDR plural rule evaluator (SPEC-LOC-002 §3.4).

The rule strings are DATA: they live in each language's row of
``i18n/languages.json``, copied from CLDR (version pinned there). This module has
no per-language code: it parses the CLDR rule syntax (UTS #35, "Language Plural
Rules") and evaluates it.

Supported syntax: operands ``n i v w f t e c``; ``mod`` / ``%``; relations
``=`` and ``!=`` against a range list (``2..4``, ``1,3``, ``0..5,7``);
``and`` binds tighter than ``or``. Sample annotations (``@integer ...``,
``@decimal ...``) are ignored by the evaluator; ``samples()`` expands them for
tests (T-3).

Numbers may be given as int, float, Decimal or str. Use a str (``"1.0"``,
``"1c6"``) when visible fraction digits or the compact exponent matter.
Scientific notation (``1e20``, ``Decimal("1E-7")``) is normalized to the plain
decimal it denotes before the operands are derived; only a str in CLDR compact
form (``"1c6"``, ``"1.1e6"``) sets the ``e`` / ``c`` operand (see _plain_text).
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Callable, Dict, Iterable, List, Mapping, Tuple, Union

Number = Union[int, float, Decimal, str]
CATEGORIES = ("zero", "one", "two", "few", "many", "other")
_TOKEN = re.compile(r"\s*(\.\.|!=|=|,|%|[a-z]+|\d+(?:\.\d+)?)")


class PluralRuleError(ValueError):
    """A rule string the evaluator cannot parse."""


class Operands:
    """The CLDR operands of one number."""
    __slots__ = ("n", "i", "v", "w", "f", "t", "e")

    def __init__(self, value: Number):
        if isinstance(value, bool):
            value = int(value)
        if isinstance(value, int):
            self.n = Decimal(abs(value))
            self.i, self.v, self.w, self.f, self.t, self.e = abs(value), 0, 0, 0, 0, 0
            return
        text, exp = _plain_text(value)
        int_part, _, frac = text.partition(".")
        self.n = abs(Decimal(text))
        self.i = int(int_part or "0")
        self.v = len(frac)
        stripped = frac.rstrip("0")
        self.w = len(stripped)
        self.f = int(frac) if frac else 0
        self.t = int(stripped) if stripped else 0
        self.e = exp

    def get(self, name: str):
        if name == "c":
            name = "e"
        return getattr(self, name)


_COMPACT = re.compile(r"(\d+(?:\.\d+)?)[ce](\d+)")


def _plain_text(value: Number) -> Tuple[str, int]:
    """(plain unsigned decimal string, compact exponent) of a non-int number.

    Only a str in CLDR compact form (``"1c6"``, ``"1.1e6"``: lower-case c/e and
    unsigned exponent digits, as CLDR writes its samples) carries an exponent,
    which becomes the ``e`` / ``c`` operand. Any other scientific notation (a
    float such as ``1e20``, ``Decimal("1E+3")``, ``"2.5e-3"``) is the plain
    number it denotes, with e = c = 0; its visible fraction digits are those of
    the plain form (``Decimal("1E-7")`` -> ``"0.0000001"``, v = 7)."""
    text = repr(value) if isinstance(value, float) else str(value)
    text = text.strip().lstrip("+-")
    m = _COMPACT.fullmatch(text)
    if m:
        exp = int(m.group(2))
        return _shift_decimal(m.group(1), exp), exp
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"not a finite number: {value!r}")
    return format(abs(number), "f"), 0


def _shift_decimal(text: str, exp: int) -> str:
    """"1.1", 6 -> "1100000"; "1.0000001", 6 -> "1000000.1" (CLDR compact form)."""
    int_part, _, frac = text.partition(".")
    digits = int_part + frac
    point = len(int_part) + exp
    if point >= len(digits):
        return (digits + "0" * (point - len(digits))).lstrip("0") or "0"
    whole = digits[:point].lstrip("0") or "0"
    return f"{whole}.{digits[point:]}"


def _tokens(src: str) -> List[str]:
    out, pos = [], 0
    src = src.strip()
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise PluralRuleError(f"unexpected text at {pos}: {src[pos:]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


def _condition(rule: str) -> str:
    """The rule without its sample annotations."""
    return rule.split("@", 1)[0].strip()


def compile_rule(rule: str) -> Callable[[Operands], bool]:
    """Compile one CLDR condition (samples allowed and ignored) to a predicate.
    An empty condition (the ``other`` category) is always true."""
    toks = _tokens(_condition(rule))
    if not toks:
        return lambda ops: True
    return _RuleParser(toks, rule).parse()


class _RuleParser:
    """Recursive descent over the tokens of one condition: ``or`` of ``and`` of relations."""
    __slots__ = ("toks", "pos", "rule")

    def __init__(self, toks: List[str], rule: str):
        self.toks = toks
        self.pos = 0
        self.rule = rule

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else None

    def take(self, expected=None):
        tok = self.peek()
        if tok is None or (expected is not None and tok != expected):
            raise PluralRuleError(f"expected {expected!r} at token {self.pos} in {self.rule!r}")
        self.pos += 1
        return tok

    def value(self) -> int:
        tok = self.take()
        if not tok.isdigit():
            raise PluralRuleError(f"expected an integer, got {tok!r} in {self.rule!r}")
        return int(tok)

    def parse(self) -> Callable[[Operands], bool]:
        ors = [self.and_condition()]
        while self.peek() == "or":
            self.take()
            ors.append(self.and_condition())
        if self.pos != len(self.toks):
            raise PluralRuleError(f"trailing tokens in {self.rule!r}")
        return lambda ops: any(o(ops) for o in ors)

    def and_condition(self) -> Callable[[Operands], bool]:
        parts = [self.relation()]
        while self.peek() == "and":
            self.take()
            parts.append(self.relation())
        return lambda ops: all(p(ops) for p in parts)

    def relation(self) -> Callable[[Operands], bool]:
        operand = self.take()
        if operand not in ("n", "i", "v", "w", "f", "t", "e", "c"):
            raise PluralRuleError(f"unknown operand {operand!r} in {self.rule!r}")
        modulus = None
        if self.peek() in ("mod", "%"):
            self.take()
            modulus = self.value()
        op = self.take()
        if op not in ("=", "!="):
            raise PluralRuleError(f"unknown relation {op!r} in {self.rule!r}")
        return _relation_test(operand, modulus, self.ranges(), op == "!=")

    def ranges(self) -> Tuple[Tuple[int, int], ...]:
        items: List[Tuple[int, int]] = []
        while True:
            lo = hi = self.value()
            if self.peek() == "..":
                self.take()
                hi = self.value()
            items.append((lo, hi))
            if self.peek() != ",":
                return tuple(items)
            self.take()


def _relation_test(operand: str, modulus, ranges: Tuple[Tuple[int, int], ...],
                   negate: bool) -> Callable[[Operands], bool]:
    def test(ops: Operands) -> bool:
        x = ops.get(operand)
        if modulus is not None:
            x = x % modulus
        if isinstance(x, Decimal) and x != x.to_integral_value():
            hit = False          # a fractional n is in no integer range
        else:
            xi = int(x)
            hit = any(lo <= xi <= hi for lo, hi in ranges)
        return hit != negate
    return test


class PluralRules:
    """One language's rule set (cardinal or ordinal): category -> rule string."""

    def __init__(self, rules: Mapping[str, str]):
        unknown = set(rules) - set(CATEGORIES)
        if unknown:
            raise PluralRuleError(f"unknown plural categories {sorted(unknown)}")
        self.rules = dict(rules)
        self.categories = tuple(c for c in CATEGORIES if c in rules or c == "other")
        self._compiled = [(c, compile_rule(r)) for c, r in rules.items()
                          if c != "other"]

    def category(self, number: Number) -> str:
        ops = Operands(number)
        for cat, test in self._compiled:
            if test(ops):
                return cat
        return "other"


def samples(rule: str) -> Dict[str, List[str]]:
    """Expand the ``@integer`` / ``@decimal`` samples of a rule string into
    concrete number strings (ranges ``a~b`` expanded; ``…`` dropped)."""
    out: Dict[str, List[str]] = {}
    for chunk in rule.split("@")[1:]:
        kind, _, body = chunk.partition(" ")
        vals: List[str] = []
        for item in body.split(","):
            item = item.strip()
            if not item or item == "…":
                continue
            if "~" in item:
                lo, hi = item.split("~")
                vals.extend(_expand_range(lo, hi))
            else:
                vals.append(item)
        out.setdefault(kind, []).extend(vals)
    return out


def _expand_range(lo: str, hi: str) -> Iterable[str]:
    if "." not in lo:
        return [str(x) for x in range(int(lo), int(hi) + 1)]
    digits = len(lo.split(".")[1])
    step = Decimal(1).scaleb(-digits)
    cur, end, vals = Decimal(lo), Decimal(hi), []
    while cur <= end:
        vals.append(f"{cur:.{digits}f}")
        cur += step
    return vals
