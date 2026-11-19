"""m2c's shift pair for a narrow variable, written as the `s16` (or `s8`) variable it was.

A value kept in an `s16` local comes back from m2c as a word shifted up where it is set and down where it is read:

    if (...) { var_v0 = f(arg0) << 0x10; } else { var_v0 = (arg0 - 1) << 0x10; }
    temp_v0 = var_v0 >> 0x10;

gcc builds `(arg0 - 1) << 16` as a subtract then a shift; the game, which narrowed `arg0 - 1` to 16 bits, shifted
first and added `-1 << 16`. As `s16 var_v0; ... var_v0 = arg0 - 1; ... temp_v0 = var_v0;` an N64 function and its
twin were exact (both at 335 before). Only when every assignment shifts up by the same amount and every read
shifts down by it.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'narrow_shift_pair'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NARROW = {16: 's16', 24: 's8'}


def _amount(text):
    return int(text, 0)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    result = []
    for declared in re.finditer(r'(?m)^(?P<indent>[ \t]*)(?:s32|u32|int)\s+(?P<var>' + IDENT + r')\s*;[ \t]*\n', body):
        var = declared['var']
        sets = list(re.finditer(r'(?<![\w.>])' + var + r'\s*=(?!=)\s*(?P<value>[^;]*?)\s*<<\s*(?P<k>0x10|16|0x18|24)\s*;', body))
        reads = list(re.finditer(r'(?<![\w.>])' + var + r'\s*>>\s*(?P<k>0x10|16|0x18|24)\b', body))
        mentions = list(re.finditer(r'(?<![\w.>])' + var + r'\b', body))
        if not sets or not reads or len(mentions) != 1 + len(sets) + len(reads):
            continue
        amounts = {_amount(m['k']) for m in sets} | {_amount(m['k']) for m in reads}
        if len(amounts) != 1 or amounts.pop() not in NARROW:
            continue
        kind = NARROW[_amount(sets[0]['k'])]
        edits = [(declared.start() + len(declared['indent']), declared.end(), f'{kind} {var};\n')]
        for m in sets:
            value = source[opening + m.start('value'):opening + m.end('value')].strip()
            edits.append((m.start(), m.end(), f'{var} = {value};'))
        for m in reads:
            edits.append((m.start(), m.end(), var))
        text = source
        for a, b, new in sorted(edits, reverse=True):
            text = text[:opening + a] + new + text[opening + b:]
        result.append((FAMILY, text))
    return result[:3]
