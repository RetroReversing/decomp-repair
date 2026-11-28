"""A float literal an `if` compares against, set in a local inside a one-shot scope two or three deep just before it.

SN64 GCC 2.8.1 (`-G0 -mips3 -O2 -mgas -meb -mcpu=VR4300 -mhard-float -mfp32`), a 144-instruction N64 text-scrolling
screen at 215: the tail was `v -= 0.5; if ((f32) y < 0.0f)`, and the target had the zero in `$f0` and the converted
`y` in `$f2`, loaded after the store (`swc1; mtc1 $zero, $f0; mtc1 $s1, $f2; cvt.s.w $f2, $f2; c.lt.s $f2, $f0`)
where ours had the zero hoisted above the store and the two registers exchanged. Measured, with `float limit;` set
before the test and compared against: set plainly 215, in one `do { } while (0)` 20 (order right, registers still
exchanged), nested two or three deep 0. The nested scopes give the zero's definition more weight in flow.c's loop-depth
reference count, so local-alloc takes it before the conversion's shorter-lived value (hypothesis for the allocator
step: the measured scores are the evidence). The local and the scopes are scaffolding; polishing removes them.

    if ((f32) y < 0.0f) {     ->   do { do { limit = 0.0f; } while (0); } while (0);
                                   if ((f32) y < limit) {

Offered when the target compares floats, for each `if` (not an `else if`) whose condition has an `f`-suffixed literal
as an operand of a comparison: depths 2, 1 and 3 for the first such literal of each `if`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_compare_limit_weight'
FAMILIES = (FAMILY,)
LIMIT = 9
DEPTHS = (2, 1, 3)

_COMPARES = re.compile(r'\bc\.(?:lt|le|eq|olt|ole|ult|ule|ueq)\.s\b')
_LITERAL = r'(?:\d+\.\d*|\.\d+|\d+(?=[eE]))(?:[eE][+-]?\d+)?[fF]'
_RELATION = r'(?:<=|>=|==|!=|(?<![-<>])<(?![<=])|(?<![-<>])>(?![>=]))'
_RIGHT = re.compile(_RELATION + r'\s*(' + _LITERAL + r')(?=\s*(?:\)|&&|\|\|))')
_LEFT = re.compile(r'(?:(?<=\()|(?<=&&)|(?<=\|\|))\s*(' + _LITERAL + r')\s*' + _RELATION)


def _fresh(clean, base='limit'):
    name, n = base, 2
    while re.search(r'\b' + name + r'\b', clean):
        name, n = f'{base}{n}', n + 1
    return name


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm or not _COMPARES.search(asm):
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    results = []
    local = _fresh(clean)
    for m in re.finditer(r'(?<=[;{}])(\s*)if\s*\(', clean[opening:end]):
        start = opening + m.start() + len(m[1])
        cond_open = opening + m.end() - 1
        cond_close = close(clean, cond_open)
        if not cond_close:
            continue
        condition = clean[cond_open:cond_close]
        hit = _RIGHT.search(condition) or _LEFT.search(condition)
        if not hit:
            continue
        a, b = cond_open + hit.start(1), cond_open + hit.end(1)
        line = source.rfind('\n', 0, start) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        for depth in DEPTHS:
            setting = 'do { ' * depth + f'{local} = {source[a:b]};' + ' } while (0);' * depth
            text = source[:start] + setting + '\n' + indent + source[start:a] + local + source[b:]
            text = text[:opening + 1] + f'\n    float {local};' + text[opening + 1:]
            results.append((FAMILY, text))
    return results[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm')}
