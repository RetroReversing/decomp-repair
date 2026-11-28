"""m2c's unguarded counted `do` loop, written as the `for` loop it came from, its `i = 0;` moved into the header.

A loop with a constant bound needs no entry test, so GCC compiles `for (i = 0; i < 163; i++)` to a bare bottom-tested
loop and m2c writes it back as one:

    i = 0;                                          for (i = 0; i < 163U; i++) {
    store(..);  call(..);   (any number)      ->    ...
    do {                                            }
        t = rows[i].a;
        i += 1;                                     store(..);  call(..);
        if (t != 0) f(rows[i - 1].b, t);            for (i = 0; i < 163U; i++) {
    } while (i < 163U);                                 t = rows[i].a;
                                                        if (t != 0) f(rows[i].b, t);
                                                    }

The two are not the same to GCC: the `for` leaves a loop-continue note before its step, which reorg.c reads when it
fills the delay slot of a branch that skips to the step (`beql` with the step in it against `beqz`), and m2c's early
`i += 1;` and `i - 1` are how it wrote a step the scheduler had moved up. m2c also leaves `i = 0;` where the scheduler
put it, above a hundred calls. `counted_loop_shapes` and `guarded_do_for_repairs` need the guard around the `do`.

Taken when the counter is set to 0 in plain statements that don't name it, the `do` body steps it once by one at its
own top level, has no `continue` or `goto`, reads it after the step only as `(i - 1)`, and the bound is a number above
zero. One child with every such loop, then one per loop. A loader on SN GCC 2.8.1 (`-G0 -mips3 -O2`) needed it to
reach 0. The judge decides.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'unguarded_do_for'
FAMILIES = (FAMILY,)

_ID = r'[A-Za-z_]\w*'
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uU]?'
LIMIT = 6


def _loops(clean, opening, end):
    """[(init span, do start, body open, body close, counter, bound, step span)]"""
    found = []
    for head in re.finditer(r'(?<![\w.])do\s*\{', clean[opening:end]):
        start = opening + head.start()
        body_open = opening + head.end() - 1
        body_close = close(clean, body_open)
        if body_close < 0:
            continue
        tail = re.compile(rf'\}}\s*while\s*\(\s*(?P<i>{_ID})\s*<\s*(?P<n>{_NUM})\s*\)\s*;').match(clean, body_close)
        if not tail or int(tail['n'].rstrip('uU'), 0) <= 0:
            continue
        counter = tail['i']
        body = clean[body_open + 1:body_close]
        if re.search(r'(?<![\w.])(?:continue|goto)\b', body):
            continue
        steps = [s for s in re.finditer(rf'(?<![\w.>])(?:{counter}\s*\+=\s*1[uU]?|{counter}\s*\+\+|\+\+\s*{counter}'
                                        rf'|{counter}\s*=\s*{counter}\s*\+\s*1[uU]?)\s*;', body)
                 if body.count('{', 0, s.start()) == body.count('}', 0, s.start())]
        if len(steps) != 1 or body[:steps[0].start()].rstrip()[-1:] not in ('', ';', '}', '{'):
            continue
        after = re.sub(rf'\(\s*{counter}\s*-\s*1\s*\)|(?<![\w.>]){counter}\s*-\s*1\b(?=\s*\])', ' ',
                       body[steps[0].end():])
        if re.search(rf'(?<![\w.>]){counter}\b', after):
            continue
        writes = re.findall(rf'(?<![\w.>]){counter}\s*(?:\+\+|--|(?:[-+*/%&|^]|<<|>>)?=(?!=))|(?:\+\+|--)\s*{counter}\b'
                            rf'|(?<!&)&\s*{counter}\b', body)
        if len(writes) != 1:
            continue
        sets = list(re.finditer(rf'(?m)^[ \t]*{counter}\s*=\s*0[uU]?\s*;[ \t]*\n', clean[opening:start]))
        if not sets:
            continue
        init = (opening + sets[-1].start(), opening + sets[-1].end())
        between = clean[init[1]:start]
        if re.search(rf'(?<![\w.>]){counter}\b|[{{}}]|(?<![\w.])(?:if|else|goto|return|break|continue|case)\b'
                     rf'|(?m:^\s*\w+\s*:(?!:))', between):
            continue
        step = (body_open + 1 + steps[0].start(), body_open + 1 + steps[0].end())
        found.append((init, start, body_open, body_close, counter, tail['n'], step))
    return found


def _line(source, start, end):
    a, b = source.rfind('\n', 0, start) + 1, source.find('\n', end)
    b = len(source) if b < 0 else b + 1
    return (a, b) if not source[a:start].strip() and not source[end:b].strip() else (start, end)


def _edits(source, clean, loop):
    init, start, body_open, body_close, counter, bound, step = loop
    tail = re.compile(r'\}\s*while\s*\([^;]*\)\s*;').match(clean, body_close)
    edits = [(*init, ''), (start, body_open, f'for ({counter} = 0; {counter} < {bound}; {counter}++) '),
             (*_line(source, *step), ''), (body_close + 1, tail.end(), '')]
    for use in re.finditer(rf'\(\s*{counter}\s*-\s*1\s*\)|(?<![\w.>]){counter}\s*-\s*1\b(?=\s*\])',
                           clean[step[1]:body_close]):
        edits.append((step[1] + use.start(), step[1] + use.end(), counter))
    return edits


def _apply(source, edits):
    for a, b, text in sorted(edits, reverse=True):
        source = source[:a] + text + source[b:]
    return source


def variants(source, name):
    """Proposals: each unguarded counted `do` as its `for`; all of them together first."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    loops = _loops(clean, opening, span[1])
    groups = [_edits(source, clean, loop) for loop in loops]
    if not groups:
        return []
    every = [edit for group in groups for edit in group]
    ordered = sorted(every)
    out = []
    if len(groups) > 1 and not any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
        out.append((FAMILY, _apply(source, every)))
    out += [(FAMILY, _apply(source, group)) for group in groups]
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
