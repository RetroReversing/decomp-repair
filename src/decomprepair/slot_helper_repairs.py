"""A table slot address written through an inline helper that takes the table as a parameter.

`T = (i * 4) + TABLE;` and its spellings (`TABLE + i * 4`, `inline_fn(i, 4, TABLE)`) all gave the same insn order: the
first scheduler put the `sll` ahead of the `lui/addiu` for the table. The game's order, `lui/addiu` first and `sll`
after, came from passing the table as a parameter of a one-line inline function, and from holding a float argument of
the call that follows in a local ahead of it:

    T = (i * 4) + TABLE;                         f32 lit;  lit = 1.0f;
    g(a, b, *T, 1.0f, 10.0f);          ->        T = __repair_slot(TABLE, i);
                                                 g(a, b, *T, lit, 10.0f);

An N64 function (`gcc-2.7.2-kmc`): 120 to 60 with both parts (the helper alone moved the table's insns but kept the
constant after them).

Offered when a pointer-to-pointer local is assigned `(I * K) + SYM;` or `SYM + I * K;` (K a power of two or `<< n`)
and SYM is not a local. One variant with the helper, and one per float literal in the next call of the same block that
also holds it in a local.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'slot_helper'
FAMILIES = (FAMILY,)

HELPER = 'inline static {kind}__repair_slot(char *b, s32 i) {{ return ({kind}) (b + i * {scale}); }}\n'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '__repair_slot' in source:
        return []
    kinds = {m[2]: re.sub(r'\s*(\*+)$', r' \1', re.sub(r'\s+', ' ', m[1].strip())) for m in re.finditer(r'^[ \t]*([A-Za-z_]\w*(?:\s*\*)+)\s*(\w+);', clean[opening:end], re.M)}
    locals_ = set(re.findall(r'^[ \t]*[A-Za-z_][\w \t\*]*?\b(\w+)\s*(?:\[[^\]]*\])?\s*;', clean[opening:end], re.M))
    scale = r'(?:(\d+)|\(?\s*(\w+)\s*<<\s*(\d+)\s*\)?)'
    forms = [rf'\(\s*(\w+)\s*\*\s*(\d+)\s*\)\s*\+\s*(\w+)', rf'(\w+)\s*\+\s*\(?\s*(\w+)\s*\*\s*(\d+)\s*\)?']
    results = []
    for assign in re.finditer(r'^([ \t]*)(\w+) = ([^;\n]+);', clean[opening:end], re.M):
        target = assign[2]
        if target not in kinds or not kinds[target].count('*') >= 2:
            continue
        expr = assign[3].strip()
        m = re.fullmatch(forms[0], expr)
        if m:
            index, factor, table = m[1], m[2], m[3]
        else:
            m = re.fullmatch(forms[1], expr)
            if not m:
                continue
            table, index, factor = m[1], m[2], m[3]
        if table in locals_ or index == table or not re.fullmatch(r'[A-Za-z_]\w*', table):
            continue
        lo, hi = opening + assign.start(), opening + assign.end()
        helper = HELPER.format(kind=kinds[target], scale=factor).replace('{kind}', '')
        line = f'{assign[1]}{target} = __repair_slot({table}, {index});'
        base = source[:lo] + line + source[hi:]
        head = span[0]
        with_helper = base[:head] + helper + base[head:]
        results.append((FAMILY, with_helper))
        call = re.search(r'^[ \t]*\w+\([^;\n]*;', clean[hi:end], re.M)
        if call:
            at = hi + call.start()
            for lit in list(dict.fromkeys(re.findall(r'(?<![\w.])\d+\.\d*f\b', call[0])))[:2]:
                local = '__repair_lit'
                text = base[:lo] + f'{assign[1]}{local} = {lit};\n' + line + source[hi:at] \
                    + source[at:at + call.end() - call.start()].replace(lit, local, 1) + source[hi + call.end():]
                text = text[:head] + helper + text[head:]
                body = text.find('{', head + len(helper)) + 1
                results.append((FAMILY, text[:body] + f'\n  f32 {local};' + text[body:]))
    return results
