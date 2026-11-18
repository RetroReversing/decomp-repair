"""A call's address argument `BASE + (INDEX * C)` computed as the source did: element index first, then the base.

gcc 2.7.2's second scheduler breaks ties by the order the source produced the instructions. For a loop calling
`cb(M2C_FIELD(arg0, s32 *, 0) + (i * 0xC), 0, sel == i)` an N64 game had `i * 3`, then the base's `lw`, then the
`sll 2`: the source had an index of 4-byte elements, read before the base,

    t = i * 3;
    p = M2C_FIELD(arg0, s32 *, 0);
    cb(p + t * 4, 0, sel == i);

(or `s32 *p` and `p + t`). m2c folds the element size into one multiplier, so the draft schedules `i * 0xC` whole
before the load. The rewrite stages it, for a word-sized integer base (the sum is integer arithmetic, so the value
is the same) and a multiplier of 4 times a constant above 1. Only expression-statement calls whose other
arguments have no side effects, so loading the base before them changes no value.
"""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, split_args
from .pattern_repairs import close

FAMILY = 'call_index_staging'
FAMILIES = (FAMILY,)
WORD = r'(?:s32|u32|int|unsigned int|M2C_UNK|M2C_UNK32)'
BASE = re.compile(r'\s*(M2C_FIELD\(\s*(' + IDENT + r')\s*,\s*(' + WORD + r')\s*\*\s*,\s*(?:0[xX][0-9a-fA-F]+|\d+)\s*\))\s*$')
INDEX = re.compile(r'\s*\(?\s*((?:\(\s*u8\s*\)\s*)?' + IDENT + r')\s*\*\s*(0[xX][0-9a-fA-F]+|\d+)\s*\)?\s*$')


def _fresh(clean, base):
    name, n = base, 1
    while re.search(r'\b' + name + r'\b', clean):
        n += 1
        name = f'{base}{n}'
    return name


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for statement in re.finditer(r'(?m)^([ \t]*)(?=\S[^;{}]*;)', clean[opening+1:end]):
        start = opening + 1 + statement.end()
        semicolon = clean.find(';', start)
        text = clean[start:semicolon]
        call = re.match(r'(.*?)\(', text, re.S)
        if not call or re.search(r'=(?!=)|\b(?:if|while|for|return|switch)\b', text[:call.end()]):
            continue
        # the callee is a plain name or a field load; find its argument list (the last top-level parentheses)
        args_open = start + len(text.rstrip()) - 1
        if clean[args_open] != ')':
            continue
        depth, pos = 0, args_open
        while pos >= start:
            depth += (clean[pos] == ')') - (clean[pos] == '(')
            if depth == 0:
                break
            pos -= 1
        if pos < start or close(clean, pos) != args_open + 1:
            continue
        args = [(pos + 1 + a, pos + 1 + b) for a, b in split_args(clean[pos+1:args_open])]
        for index, (a, b) in enumerate(args):
            parts = split_sum(clean[a:b])
            if not parts:
                continue
            base, scaled = BASE.match(parts[0]), INDEX.match(parts[1])
            if not base or not scaled:
                continue
            factor = int(scaled[2], 0)
            if factor % 4 or factor // 4 < 2:
                continue
            others = clean[start:pos] + ''.join(clean[x:y] for i, (x, y) in enumerate(args) if i != index)
            # (no assignment or call; `s32 (**)(s32, ...)` in a field macro's type is no call)
            if re.search(r'=(?!=)|\+\+|--|\b(?!M2C_FIELD\b|sizeof\b)' + IDENT + r'\s*\((?!\s*\*)',
                         others.replace('==', '').replace('!=', '').replace('<=', '').replace('>=', '')):
                continue
            t, p = _fresh(clean, 'temp_index'), _fresh(clean, 'temp_base')
            indent = statement[1]
            elements = scaled[2][:2] + format(factor // 4, 'X') if scaled[2].lower().startswith('0x') else str(factor // 4)
            for ptr in (False, True):
                kind = base[3] + (' *' if ptr else ' ')  # (`s32 *temp_base;` or `s32 temp_base;`)
                field = source[a + base.start(1):a + base.end(1)]
                value = re.sub(re.escape(base[3]) + r'\s*\*', base[3] + ' **', field, count=1) if ptr else field
                staged = f'{t} = {scaled[1]} * {elements};\n{indent}{p} = {value};\n{indent}'
                argument = f'{p} + {t}' if ptr else f'{p} + {t} * 4'
                edits = [(opening + 1, opening + 1, f'\n    s32 {t};\n    {kind}{p};'),
                         (start, start, staged), (a, b, (' ' if clean[a] == ' ' else '') + argument)]
                text_out = source
                for x, y, z in sorted(edits, reverse=True):
                    text_out = text_out[:x] + z + text_out[y:]
                result.append((FAMILY, text_out))
            break
    return result[:4]


def split_sum(text):
    """`A + B` at the top level of `text` (one `+`), else None."""
    depth = 0
    plus = []
    for pos, char in enumerate(text):
        depth += (char == '(') - (char == ')')
        if char == '+' and depth == 0:
            plus.append(pos)
    if len(plus) != 1:
        return None
    return text[:plus[0]], text[plus[0]+1:]
