# Copyright (C) 2026 Lorris Turpin / 360 Hearts in the Sky
# Licensed under AGPL-3.0 — see LICENSE file for details.
"""CHTK text helpers: line split, timezone field, gender field.

Pure functions (no Qt, no managers) shared by core.chtk_reader,
managers.birth_data_manager and the Edit CHTK tab. Kept out of
chtk_reader.py, whose size is ratcheted by the South Indian architecture
guard. Format reference: docs/CHTK_FORMAT_SPECIFICATION.md.
"""
import re

# A run of whitespace, or a colon with whitespace around it, separates the
# fields of a CHTK offset: '-5 30' and '-05 : 30' read like '-05:30'.
_TZ_SEP_RE = re.compile(r'\s*:\s*|\s+')


def split_chtk_lines(text, keep_trailing=False):
    """Split decoded CHTK text into lines the way Kala does.

    Kala ends every line with CRLF. Line 8 (gender) can carry a short binary
    blob after the gender letter (e.g. ``m:\\x0e\\n0N>``) holding a lone LF,
    CR, form feed or record separator. Universal newlines (``readlines`` /
    ``splitlines``) cut the blob into an extra line and shift every later
    field down by one, so the latitude lands in the timezone slot (Napoleon
    III, Meher Baba, Edward IV, Dead Native 03/05 in the Kala database).
    When the text holds a CRLF, split on CRLF ONLY, so the blob stays inside
    line 8 as it does in Kala. Every Varuna360 writer emits CRLF too, so a
    lone LF in a CRLF file is never a real line break. LF-only text keeps
    the old behaviour. By default a trailing newline yields no extra empty
    line (the ``readlines`` count); ``keep_trailing`` keeps it (the
    write-back path rejoins the list and must stay byte-identical).
    """
    text = text.lstrip('\ufeff')
    lines = text.split('\r\n') if '\r\n' in text else text.replace('\r', '\n').split('\n')
    if lines and lines[-1] == '' and not keep_trailing:
        lines.pop()
    return lines


def read_chtk_text(path):
    """Decode a CHTK file (UTF-16 first, Kala native, then UTF-8) without
    newline translation, so split_chtk_lines sees the real CRLF endings."""
    try:
        with open(path, 'r', encoding='utf-16', newline='') as f:
            return f.read()
    except (UnicodeDecodeError, UnicodeError):
        with open(path, 'r', encoding='utf-8', newline='') as f:
            return f.read()


def normalize_chtk_timezone(tz_str):
    """CHTK line 13 -> (normalized '±HH:MM:SS', ok).

    ok is False when the text is empty or not an offset ('?', 'lmt', a
    coordinate); the normalized value is then the '+00:00:00' fallback.
    The CHTK sign is kept as written (inverted convention: '-5 30' means
    UTC+5:30; BirthDataManager inverts it). Handles '+7:00', decimal
    seconds '04:44:10.00', '>' comment markers, whitespace separators
    ('-5 30' KN Rao, '5 36' Orville Wright), the hybrid '+Europe/Lisbon:00:00'
    and a pure IANA name (returned as the name, ok True, for
    BirthDataManager to resolve date-aware).
    """
    if not tz_str or not str(tz_str).strip():
        return '+00:00:00', False
    tz_str = str(tz_str).strip()
    if '>' in tz_str:
        tz_str = tz_str.split('>')[0].strip()
    if '/' in tz_str:
        return _normalize_iana_hybrid(tz_str)
    return _normalize_offset(tz_str)


def _normalize_iana_hybrid(tz_str):
    """'+Europe/Lisbon:00:00' -> '+00:00:00'; 'Europe/Paris' -> itself."""
    sign = '-' if tz_str.startswith('-') else '+'
    numbers = []
    for part in tz_str.split('/')[-1].split(':'):
        try:
            numbers.append(int(part))
        except ValueError:
            continue
    if len(numbers) >= 2:
        seconds = numbers[2] if len(numbers) > 2 else 0
        return f"{sign}{abs(numbers[0]):02d}:{abs(numbers[1]):02d}:{abs(seconds):02d}", True
    return tz_str.lstrip('+-'), True


def _normalize_offset(tz_str):
    """'[±]H[:MM[:SS]]' with ':' or whitespace separators -> '±HH:MM:SS'."""
    sign = '+'
    if tz_str.startswith(('+', '-')):
        sign, tz_str = tz_str[0], tz_str[1:]
    parts = _TZ_SEP_RE.sub(':', tz_str.strip()).split(':')
    try:
        # float() handles "10.00" from LMT-era CHTK files
        hours = int(float(parts[0]))
        minutes = int(float(parts[1])) if len(parts) > 1 else 0
        seconds = int(float(parts[2])) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        return '+00:00:00', False
    return f"{sign}{abs(hours):02d}:{abs(minutes):02d}:{abs(seconds):02d}", True


def prepare_offset_for_regex(tz_str):
    """BirthDataManager._parse_chtk_timezone pre-step. Hybrid
    '+Europe/Lisbon:00:00' keeps its sign and numeric tail ('+00:00'); a pure
    IANA name returns None (cannot be resolved without the birth date, so
    the caller returns 0.0 and _build_canonical resolves it). Then drop a
    '>' comment, read whitespace like ':' ('-5 30'), and give an unsigned
    H:MM form a '+' (USA unsigned convention = positive CHTK offset)."""
    if '/' in tz_str:
        last = tz_str.split('/')[-1]
        if ':' not in last:
            return None
        tz_str = ('-' if tz_str.startswith('-') else '+') + last.split(':', 1)[1]
    tz_str = _TZ_SEP_RE.sub(':', tz_str.split('>')[0].strip())
    tz_str = re.sub(r'^([+-]):', r'\1', tz_str)
    if ':' in tz_str and not tz_str.startswith(('+', '-')):
        tz_str = '+' + tz_str
    return tz_str


def chtk_tz_parse_warnings(raw, iana_timezone):
    """tz_warnings entry for a CHTK line 13 the reader could not read
    (CHTKReader sets 'timezone_parse_error' to the raw text). The chart is
    still built at UTC+0; this says so instead of staying silent
    (SPEC-TZ-001 8a). Covers pre-1900 charts, which
    verify_timezone_consistency's Check C cannot see. No guess is made."""
    if raw.get('timezone_parse_error') is None:
        return []
    bad = str(raw['timezone_parse_error']).strip()
    shown = repr(bad) if bad else '(empty)'
    return [f"Timezone: CHTK timezone field {shown} is not an offset; using "
            f"UTC+0 (coordinates suggest {iana_timezone}). Check line 13 of "
            f"the chart file"]


def kala_gender(gender_raw):
    """CHTK line 8 -> 'Male' / 'Female' / 'Unknown'.

    Codes: m/1 Male, f/2 Female, 0 unset (Kala's third code, td-n0z9).
    '... >gender' tagged forms take their first digit. Kala also writes the
    gender letter followed by an opaque binary blob ('f*\\x0c?PD<',
    'm\\n":PIF', 'mlfMpT;'): the first letter carries the gender.
    """
    raw = gender_raw.lower()
    if raw in ('m', '1'):
        return 'Male'
    if raw in ('f', '2'):
        return 'Female'
    if raw == '0':
        return 'Unknown'
    if 'gender' in raw:
        return _tagged_gender(gender_raw)
    if raw[:1] in ('m', 'f'):
        return 'Male' if raw[:1] == 'm' else 'Female'
    return 'Unknown'


def _tagged_gender(gender_raw):
    """'1 >gender' -> Male: first digit of the leading number, 1 Male,
    2 Female, else Unknown."""
    digits = ''
    for char in gender_raw:
        if char.isdigit():
            digits += char
        elif digits and char != ' ':
            break
    return {'1': 'Male', '2': 'Female'}.get(digits[:1], 'Unknown')
