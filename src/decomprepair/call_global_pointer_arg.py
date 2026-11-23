"""A global word passed to a call outside a loop, read through a pointer local to it.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) probe handler, 60 -> 0 on the exact judge (the last two
rows). Its third display call, after the loop, passed a global word as the second of eleven arguments,
`show(0, gMessage, buffer, -1, -1, 1, 0, 0, 6, 0, 60)`, and the target loads the word in argument order:
`move $a0,$zero; lui $a1; lw $a1,gMessage; move $a2,$s4`. Read from the dumps (`-dr -dc -dS`): `calls.c` copies the
argument `(mem (symbol_ref))` into a pseudo before the stack arguments' stores; outside a loop nothing folds it back
(combine refuses a MEM source across the stores, `use_crosses_set_p`; loop.c only folds it in a loop and only for a
`const` object), and the first scheduler hoists that pseudo's load above the `$a2` move. Written `*p` with
`p = &gMessage`, the argument expands as `(set (reg a1) (mem (reg p)))` in the argument moves themselves (no pseudo
copy in the `.rtl` dump), and combine then folds the constant address in (a constant source may cross stores): the
load sits between `$a0` and `$a2`. A matched sibling of the function spells its call exactly so
(`{ s32 *state = &gMessage; show(0, *state, ...); }`). Why `calls.c` skips the copy for a register address is read
from the dump, not from the cost code: a hypothesis.

call_global_pointer_arg
    `f(a, G, b);` becomes `{ const T *G_ptr = &G; f(a, *G_ptr, b); }` for a call statement whose argument is exactly
    the name of an `extern` integer word (`const` or not, never `volatile`) of this file or header, when every other
    argument has no call, `++`, `--` or assignment. One child per such call and one with all of them when there are two
    or more. The read is the same read, so the program's behaviour is unchanged; the exact judge decides every child.
"""
import re

from .call_global_stage import plain_calls
from .integer_repair_support import IDENT, INTEGER, edit, view

FAMILY = 'call_global_pointer_arg'
FAMILIES = (FAMILY,)
LIMIT = 8
_EXTERN = re.compile(rf'\bextern\s+(?:const\s+)?(?P<type>{INTEGER})\s+(?P<name>{IDENT})\s*;')
_IMPURE = re.compile(rf'\+\+|--|(?<![=!<>])=(?!=)|\b(?!(?:sizeof)\b){IDENT}\s*\(')


def _words(source, header, body):
    """{name: type} of the non-volatile `extern` integer words not shadowed by a local or parameter."""
    found = {}
    for text in (header, source):
        for hit in _EXTERN.finditer(text):
            found[hit['name']] = ' '.join(hit['type'].split())
    shadowed = set(re.findall(rf'\b(?:{INTEGER}|void|struct\s+{IDENT}|{IDENT})\s*\**\s+({IDENT})\s*(?=[;=,\[)])', body))
    return {name: kind for name, kind in found.items() if name not in shadowed}


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    words = _words(source, header, part.body)
    if not words:
        return []
    taken = set(re.findall(IDENT, source + header))
    calls = []
    for start, end, _, spans in plain_calls(part, ()):
        texts = [part.clean[a:b] for a, b in spans]
        hits = [(a + m.start(1), a + m.end(1), m[1], (a, b)) for (a, b), t in zip(spans, texts)
                if (m := re.fullmatch(rf'\s*({IDENT})\s*', t)) and m[1] in words]
        if len(hits) != 1 or f'{hits[0][2]}_ptr' in taken:
            continue
        if any(_IMPURE.search(t) for span, t in zip(spans, texts) if span != hits[0][3]):
            continue
        calls.append((start, end + 1 + part.clean[end + 1:].index(';') + 1, hits[0]))
    calls = calls[:LIMIT]

    def make(items):
        changes = []
        for start, stop, (a, b, word, _) in items:
            changes.append((start, start, f'{{ const {words[word]} *{word}_ptr = &{word}; '))
            changes.append((a, b, f'*{word}_ptr'))
            changes.append((stop, stop, ' }'))
        return edit(source, changes)

    children = [(FAMILY, make([item])) for item in calls]
    if len(calls) > 1:
        children.append((FAMILY, make(calls)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
