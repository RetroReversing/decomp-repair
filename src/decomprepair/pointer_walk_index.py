"""A do-while that walks a pointer and counts with a second variable, written as the counter indexing the table.

m2c writes a loop over a global table as

    n = 0; if (count > 0) { p = &table; do { x = *p; n += 1; ...; p = p + 1; } while (n < count); }

On KMC GCC 2.7.2 (N64) loop.c reduces the pointer and the counter separately and keeps the compare on the counter, but
the pointer is a register of its own, live through the loop and the table's address is set before the loop's guard is
folded: the target has the count in the register the pointer then takes (`move $a1,$a0` before `lui $a0`), the counter in
`$v1` and the walk through `((void **) &table)[n]`. Written `x = ((void **) &table)[n]; ...; n += 1;` the pointer is
the compiler's own strength-reduced giv and the count's copy appears. A text-layout function went 340 -> 95 on this
edit (the last of five steps; with the other four its rows fell from 415 to 95, two register rows from the target).
Hypothesis (not confirmed in the compiler's source): loop.c creating the reduced pointer itself, after the guard's
test of the count, so the count's live range ends before the pointer starts.

Children, for `do { ...; p = p + 1; ... } while (n < N);` (also `p += 1`, `p++`) whose counter `n` is stepped once per
iteration (`n += 1`, `n++`) and is zero when the loop is reached (`n = 0;` is the last thing the text says of it), whose
pointer is set by the statement just before the loop and read only as `*p`, and that has no `continue` of its own:
every `*p` is `((T *) E)[n]`, the pointer's set and step are removed and the counter's step moves to the end of the
body (the counter is read nowhere else in it). Only MIPS. The candidate is never a verdict: the judge decides.
"""
import re

from .c_scan import close, own_loop_statements
from .csource import _blank, find

FAMILY = 'pointer_walk_index'
FAMILIES = (FAMILY,)
_ID = r'[A-Za-z_]\w*'
_PATH = rf'{_ID}(?:\.{_ID})*'
_DO = re.compile(r'\bdo\s*\{')
_WHILE = re.compile(rf'\s*while\s*\(\s*({_PATH})\s*(?:<|!=)\s*([^;{{}}]+?)\s*\)\s*;')


def _step(text, name):
    """[(start, end)] of the statements stepping `name` by one."""
    n = re.escape(name)
    pattern = rf'(?<![\w.>])(?:{n}\s*\+=\s*1|{n}\s*=\s*{n}\s*\+\s*1|{n}\s*\+\+|\+\+\s*{n})\s*;[ \t]*\n?'
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    out = []
    for hit in _DO.finditer(clean, opening, span[1]):
        body_open = hit.end() - 1
        body_close = close(clean, body_open)
        tail = _WHILE.match(clean, body_close + 1) if body_close > 0 else None
        if not tail or own_loop_statements(clean, body_open + 1, body_close, 'continue'):
            continue
        counter = tail[1]
        body = clean[body_open + 1:body_close]
        steps = _step(body, counter)
        if len(steps) != 1 or len(re.findall(rf'(?<![\w.>]){re.escape(counter)}(?![\w.])', body)) != 1:
            continue
        before = clean[opening:hit.start()]
        setup = re.search(rf'(?<![\w.>])({_ID})\s*=\s*([^;{{}}=]+?)\s*;\s*$', before)
        if not setup:
            continue
        pointer, base = setup[1], setup[2]
        pointer_steps = _step(body, pointer)
        if len(pointer_steps) != 1 or re.search(rf'(?<![\w.>]){re.escape(pointer)}\b', base):
            continue
        last = [m for m in re.finditer(rf'(?<![\w.>]){re.escape(counter)}(?![\w.])[^;]*;', before[:setup.start()])]
        if not last or not re.fullmatch(rf'{re.escape(counter)}\s*=\s*0\s*;', last[-1].group()):
            continue
        rest = body[:pointer_steps[0][0]] + body[pointer_steps[0][1]:]
        for mention in re.finditer(rf'(?<![\w.>]){re.escape(pointer)}\b', rest):
            if not re.search(r'\*\s*\(?\s*$', rest[:mention.start()]):
                break
        else:
            if re.search(rf'(?<![\w.>]){re.escape(pointer)}\b', clean[tail.end():span[1]]) or re.search(rf'{re.escape(pointer)}\b', tail[2]):
                continue
            declared = re.search(rf'\b((?:{_ID}\s+)*{_ID}\s*\*+)\s*{re.escape(pointer)}\s*[;,]', clean[opening:hit.start()])
            if not declared:
                continue
            kind = re.sub(r'\s+', ' ', declared[1]).replace(' *', ' *').strip()
            element = f'(({kind}) {base})[{counter}]'
            text = source[body_open + 1:body_close]
            pieces = pointer_steps + steps
            replaced = text
            for s, e in sorted(pieces, reverse=True):
                replaced = replaced[:s] + replaced[e:]
            replaced = re.sub(rf'\*\s*\(?\s*(?<![\w.>]){re.escape(pointer)}\b\s*\)?', lambda _match, element=element: element, replaced)
            indent = re.search(r'([ \t]*)\}$', source[:body_close + 1])
            step_text = source[body_open + 1:body_close][steps[0][0]:steps[0][1]].strip()
            tail_indent = (indent[1] if indent else '') + '  '
            new_body = replaced.rstrip() + f'\n{tail_indent}{step_text}\n{indent[1] if indent else ""}'
            start = setup.start() + opening
            out.append((FAMILY, source[:start] + source[start + len(setup.group()):hit.start()] + source[hit.start():body_open + 1]
                        + new_body + source[body_close:]))
    return [x for x in out if x[1] != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
