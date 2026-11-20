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
type is the array's. An unsigned runtime bound is also supported when a matching nonzero guard encloses the walk.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'pointer_walk_index'
FAMILIES = (FAMILY,)

ID = r'[A-Za-z_]\w*'
UNSIGNED = r'(?:u32|unsigned(?:[ \t]+int)?)'
RUNTIME_BOUND = re.compile(rf'(?:\(\s*{UNSIGNED}\s*\)\s*)?({ID})')
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


def _guarded_start(clean, span, before, end, counter, bound):
    """Find the redundant initial guard around a do loop and its closing brace."""
    found = RUNTIME_BOUND.fullmatch(bound)
    if not found:
        return None
    limit = found[1]
    limit_decl = _decl(clean[:span[0]], limit, '')
    counter_decl = _decl(clean[span[0]:span[1]], counter, '')
    if not (limit_decl and counter_decl and
            re.fullmatch(rf'extern\s+{UNSIGNED}', limit_decl[1].strip()) and
            re.fullmatch(UNSIGNED, counter_decl[1].strip())):
        return None
    guard = re.search(rf'\b{counter}\s*=\s*0\s*;\s*if\s*\(\s*{limit}\s*!=\s*0[Uu]?\s*\)\s*{{\s*$', before)
    closing = re.match(r'\s*}(?!\s*else\b)', clean[end:span[1]])
    if guard and closing:
        return guard.start(), end + closing.end()
    return None


def without_unused_padding(source, name):
    """Drop the generated frame local only when its declaration is its sole use."""
    span = find(source, name)
    if not span:
        return None
    body = _blank(source)[span[0]:span[1]]
    padding = re.search(r'^[ \t]*u8[ \t]+__repair_frame\s*\[\s*[0-9]+\s*\]\s*;[ \t]*\n?', body, re.M)
    if padding and len(re.findall(r'\b__repair_frame\b', body)) == 1:
        return source[:span[0] + padding.start()] + source[span[0] + padding.end():]
    return None


def _indexed_variants(source, name):
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
        counter, bound = tail[1], tail[2].strip()
        constant = NUMBER.fullmatch(bound)
        loop_end = end + tail.end()
        before = clean[span[0]:do.start() + span[0]]
        init = re.search(rf'\b{re.escape(counter)}\s*=\s*0\s*;\s*({ID})\s*=\s*(?:&\s*({ID})(?:\s*\[\s*0\s*\])?|({ID}))\s*;\s*$', before)
        if not init:
            init = re.search(rf'\b({ID})\s*=\s*(?:&\s*({ID})(?:\s*\[\s*0\s*\])?|({ID}))\s*;\s*{re.escape(counter)}\s*=\s*0\s*;\s*$', before)
        start = init.start() if init else None
        if not constant:
            init = re.search(rf'\b({ID})\s*=\s*(?:&\s*({ID})(?:\s*\[\s*0\s*\])?|({ID}))\s*;\s*$', before)
            guarded = init and _guarded_start(clean, span, before[:init.start()], loop_end, counter, bound)
            if not guarded:
                continue
            start, loop_end = guarded
        elif not init or not re.search(r'[1-9a-fA-F]', constant[1]):
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
        if (re.search(r'\b(?:continue|break|goto)\b', inner)
                or re.search(rf'\b{counter}\s*(?:(?:[-+*/%|&^]|<<|>>)?=(?!=)|\+\+|--)', inner)
                or re.search(rf'(?:&|\+\+|--)\s*\b{counter}\b', clean[span[0]:end])):
            continue
        uses = list(re.finditer(rf'\b{re.escape(cursor)}\b', inner))
        derefs = list(re.finditer(rf'(?<![\w)\]])\*\s*{re.escape(cursor)}\b(?!\s*(?:\[|\+\+|--|[-+*/|&^]?=(?!=)))', inner))
        if not uses or len(uses) != len(derefs) or re.search(rf'(?:&|\+\+|--)\s*\*\s*{cursor}\b', inner):
            continue  # (the cursor used any other way than a plain read through it)
        if re.search(rf'\b{re.escape(cursor)}\b', clean[end:span[1]]):
            continue  # (read after the loop: its final value would be lost)
        body_src = source[opening + 1:opening + 1 + steps.start()]
        for deref in reversed(derefs):
            body_src = body_src[:deref.start()] + f'{array}[{counter}]' + body_src[deref.end():]
        start += span[0]
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:]).group()
        if not constant:
            loop_indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, span[0] + do.start()) + 1:]).group()
            if loop_indent.startswith(indent) and loop_indent != indent:
                body_src = re.sub(r'^' + re.escape(loop_indent[len(indent):]), '', body_src, flags=re.M)
        loop = f'for ({counter} = 0; {counter} < {bound}; {counter}++) {{' + body_src.rstrip() + '\n' + indent + '}'
        text = source[:start] + loop + source[loop_end:]
        if widen:
            if widen.end() > start:
                continue
            at = widen.end() - 1  # (the declaration's `;`)
            text = text[:at] + '[]' + text[at:]
        result.append((FAMILY, text))
    return result[:4]


def frame_variants(source, name):
    """Try a combined indexed loop and frame cleanup before the indexed-only variant."""
    if not without_unused_padding(source, name):
        return []
    indexed = _indexed_variants(source, name)
    return [(family, without_unused_padding(text, name)) for family, text in indexed] + indexed


def variants(source, name):
    # Keep both hypotheses available to callers that rank ordinary rewrite families.
    return frame_variants(source, name) or _indexed_variants(source, name)
