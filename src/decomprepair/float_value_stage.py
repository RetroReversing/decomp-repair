"""A float expression bound for an integer store or a call argument, staged in a float local of its own.

`G = TABLE[i].vol * (1000.0f - d) / 1000.0f;` and `f(6, id, TABLE[i].vol * (1000.0f - d) / 1000.0f);` keep every
intermediate in a temporary. On KMC GCC 2.7.2 (N64) at `-O1` the converted operand then takes `$f0` and the constant
`$f4`, where the target has the operand in `$f4`, multiplied and divided in place, and the constant in `$f2`. Writing
`value = EXPR; G = value;` (and `value = EXPR; f(6, id, value);`), with one `f32` local shared by every such site,
gives that allocation. Measured on a 276-instruction sound-zone update: 80 -> 0 with both sites at once; the same two
sites through an existing float local stayed at 90 or worse, so the local is a new one. Hypothesis (not confirmed in
the compiler's source): the named local is one pseudo across both sites and is allocated before the constants.

Children, for each statement `LVALUE = EXPR;` and each call statement with one argument `EXPR`, where EXPR has an
operator and an `f`-suffixed literal and calls nothing: that site alone, then every site together through the one
local. Only unsuffixed-double-free expressions (so a `f32` local rounds the same), no `volatile`, and the other
arguments of a staged call must have no calls or side effects. MIPS only. The candidate is never a verdict.
"""
import re

from .csource import _blank, find

FAMILY = 'float_value_stage'
FAMILIES = (FAMILY,)
_LIMIT = 8
_LOCAL = 'staged_value'
_FLOAT_LITERAL = re.compile(r'(?<![\w.])(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?[fF]\b')
_DOUBLE = re.compile(r'(?<![\w.])(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?(?![\dfFeE.\w])|\b(?:double|f64)\b')
_STATEMENT = re.compile(r'(?<=[;{}])([ \t\n]*)([^;{}]+);')
_ASSIGN = re.compile(r'^((?:\*\s*)?[A-Za-z_]\w*(?:\s*(?:\[[^\[\]=]*\]|\.\s*\w+|->\s*\w+))*)\s*=(?!=)\s*(.+)$', re.S)
_CALL = re.compile(r'^([A-Za-z_]\w*)\s*\((.*)\)$', re.S)
_KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'sizeof'}
_OPERATOR = re.compile(r'(?<=[\w\)\]])\s*(?:[*/+]|-(?!>))')
_CALLED = re.compile(r'(?<![\w.>])(?!(?:s8|u8|s16|u16|s32|u32|f32)\b)[A-Za-z_]\w*\s*\(')


def _arguments(text):
    """[(start, end)] of the top-level arguments of a call's argument text; None when the brackets don't balance."""
    parts, depth, last = [], 0, 0
    for at, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if depth < 0:
            return None
        if char == ',' and not depth:
            parts.append((last, at))
            last = at + 1
    parts.append((last, len(text)))
    return None if depth else parts


def _value(text):
    """Is `text` a float calculation that a `f32` local holds as the compiler would?"""
    return bool(_FLOAT_LITERAL.search(text) and _OPERATOR.search(text) and not _DOUBLE.search(text)
                and not _CALLED.search(text) and not re.search(r'\+\+|--|(?<![=!<>])=(?!=)|\?|,|&&|\|\|', text))


def _sites(source, clean, lo, hi, floats):
    """[(statement start, value start, value end, indent)] for every statement that can stage its float value."""
    out = []
    for hit in _STATEMENT.finditer(clean, lo, hi):
        text, base = hit[2], hit.start(2)
        indent = hit[1].split('\n')[-1]
        if '\n' not in hit[1]:
            indent = None
        assign = _ASSIGN.match(text)
        if assign:
            if assign[1].strip() not in floats and _value(assign[2]):
                out.append((base, base + assign.start(2), base + assign.end(2), indent))
            continue
        call = _CALL.match(text.rstrip())
        if not call or call[1] in _KEYWORDS:
            continue
        spans = _arguments(call[2])
        if spans is None:
            continue
        args = [call[2][a:b] for a, b in spans]
        staged = [i for i, arg in enumerate(args) if _value(arg)]
        if len(staged) != 1:
            continue
        if any(_CALLED.search(a) or re.search(r'\+\+|--|(?<![=!<>])=(?!=)', a) for i, a in enumerate(args) if i != staged[0]):
            continue
        start, end = spans[staged[0]]
        start += len(args[staged[0]]) - len(args[staged[0]].lstrip())
        end -= len(args[staged[0]]) - len(args[staged[0]].rstrip())
        out.append((base, base + call.start(2) + start, base + call.start(2) + end, indent))
    return out[:_LIMIT]


def _apply(source, opening, sites, local):
    for start, lo, hi, indent in reversed(sites):
        gap = f'\n{indent}' if indent is not None else ' '
        source = f'{source[:start]}{local} = {source[lo:hi]};{gap}{source[start:lo]}{local}{source[hi:]}'
    return f'{source[:opening + 1]}\n    f32 {local};{source[opening + 1:]}'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    body = clean[span[0]:span[1]]
    if opening < 0 or re.search(r'\b(?:volatile|asm|__asm__)\b', body) or not re.search(r'\bf32\b', source):
        return []
    floats = set(re.findall(r'\b(?:f32|float)\s+([A-Za-z_]\w*)', body))
    sites = _sites(source, clean, opening, span[1], floats)
    if not sites:
        return []
    local, number = _LOCAL, 2
    while re.search(rf'\b{local}\b', source):
        local, number = f'{_LOCAL}{number}', number + 1
    groups = [[site] for site in sites]
    if len(sites) > 1:
        groups.append(sites)
    return [(FAMILY, _apply(source, opening, group, local)) for group in groups]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
