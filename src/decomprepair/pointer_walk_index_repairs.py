"""m2c's pointer walk over a global array, written back as the indexed `for` loop it came from.

m2c turns `for (i = 0; i < 4; i++) { p = ARR[i]; ... }` into a counter and a separate cursor that both step each pass:

    var_s2 = 0;
    var_s0 = &D_8010A500;
    do {
        temp_a0 = *var_s0;
        ...
        var_s2 += 1;
        var_s0 += 1;
    } while (var_s2 < 4U);

gcc 2.7.2 builds the walk with the cursor set up before the loop. The game's indexed loop derives the address from the
counter inside the loop, after the constants it hoisted, so the walk loads in a different place and keeps an extra
register. An N64 function was 470 points off with the walk and exact with `ARR[var_s2]`.

Offered only when the meaning is unchanged: the cursor starts at the array's first element and steps one element per
pass with the counter, it is read only as `*cursor` and never escapes, the bound is a positive constant (so the `for`
loop's first test always passes, like the `do` loop's first pass), and the declarations show the cursor's element
type is the array's.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'pointer_walk_index'
FAMILIES = (FAMILY,)

ID = r'[A-Za-z_]\w*'
NUMBER = re.compile(r'\(?\s*(?:\(\s*(?:u32|s32|unsigned(?:\s+int)?|int)\s*\)\s*)?(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*\)?')


def _step(var):
    v = re.escape(var)
    return rf'(?:{v}\s*\+=\s*1|{v}\s*\+\+|\+\+\s*{v}|{v}\s*=\s*{v}\s*\+\s*1)\s*;'


def _norm(t):
    return re.sub(r'\s+', ' ', re.sub(r'\b(?:extern|static|const|volatile)\b', ' ', t)).replace(' *', '*').strip()


def _decl(source, ident, tail):
    for m in re.finditer(rf'^[ \t]*([A-Za-z_][\w \t\*]*?)\b{re.escape(ident)}\s*{tail}\s*;', source, re.M):
        return m
    return None


def _element(source, array, cursor, address):
    """(array element type, cursor pointee type, scalar declaration to widen or None) from the declarations."""
    cur = _decl(source, cursor, '')
    cur = re.match(r'(.*)\*\s*$', cur[1]) if cur else None
    arr = _decl(source, array, r'\[[^\]]*\]')
    widen = None
    if not arr and address:
        # (m2c declares a global it only saw by address as a scalar: `extern void *D;` walked from `&D`. The game's
        # array is that type; widening the declaration is safe when nothing else in the file names it)
        arr = _decl(source, array, '')
        if arr and len(re.findall(rf'\b{re.escape(array)}\b', _blank(source))) == 2:
            widen = arr
        else:
            arr = None
    if not arr or not cur:
        return None
    return _norm(arr[1]), _norm(cur[1]), widen


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for do in re.finditer(r'\bdo\s*{', clean[span[0]:span[1]]):
        opening = span[0] + do.end() - 1
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        tail = re.match(r'\s*while\s*\(\s*(' + ID + r')\s*<\s*([^;]+?)\s*\)\s*;', clean[end:span[1]])
        if not tail:
            continue
        counter, bound = tail[1], NUMBER.fullmatch(tail[2].strip())
        if not bound or int(bound[1], 0) <= 0:
            continue
        before = clean[span[0]:do.start() + span[0]]
        init = re.search(rf'\b{re.escape(counter)}\s*=\s*0\s*;\s*({ID})\s*=\s*(?:&\s*({ID})(?:\s*\[\s*0\s*\])?|({ID}))\s*;\s*$', before)
        if not init:
            init = re.search(rf'\b({ID})\s*=\s*(?:&\s*({ID})(?:\s*\[\s*0\s*\])?|({ID}))\s*;\s*{re.escape(counter)}\s*=\s*0\s*;\s*$', before)
        if not init:
            continue
        cursor, array = init[1], init[2] or init[3]
        if cursor == counter:
            continue
        types = _element(source, array, cursor, bool(init[2]))
        if not types or types[0] != types[1]:
            continue
        widen = types[2]
        body = clean[opening + 1:end - 1]
        steps = re.search(rf'\s*(?:{_step(counter)}\s*{_step(cursor)}|{_step(cursor)}\s*{_step(counter)})\s*$', body)
        if not steps:
            continue
        inner = body[:steps.start()]
        if re.search(r'\b(?:continue|break|goto)\b', inner) or re.search(rf'\b{re.escape(counter)}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)', inner):
            continue
        uses = list(re.finditer(rf'\b{re.escape(cursor)}\b', inner))
        derefs = list(re.finditer(rf'(?<![\w)\]])\*\s*{re.escape(cursor)}\b(?!\s*(?:\[|\+\+|--|[-+*/|&^]?=(?!=)))', inner))
        if not uses or len(uses) != len(derefs):
            continue  # (the cursor used any other way than a plain read through it)
        if re.search(rf'\b{re.escape(cursor)}\b', clean[end:span[1]]):
            continue  # (read after the loop: its final value would be lost)
        body_src = source[opening + 1:opening + 1 + steps.start()]
        body_src = re.sub(rf'(?<![\w)\]])\*\s*{re.escape(cursor)}\b', f'{array}[{counter}]', body_src)
        loop = f'for ({counter} = 0; {counter} < {tail[2].strip()}; {counter}++) {{' + body_src.rstrip() + '\n' + \
            re.match(r'[ \t]*', source[source.rfind('\n', 0, span[0] + do.start()) + 1:]).group() + '}'
        start = span[0] + before.rfind(init.group().strip())
        text = source[:start] + loop + source[end + tail.end():]
        if widen:
            if widen.end() > start:
                continue
            at = widen.end() - 1  # (the declaration's `;`)
            text = text[:at] + '[]' + text[at:]
        result.append((FAMILY, text))
    return result[:4]
