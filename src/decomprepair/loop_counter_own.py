"""A loop counter whose variable the function also uses for unrelated values, given a variable of its own.

m2c names variables after registers, and a hand rewrite often reuses one integer local for a loop counter and for
values computed in other parts of the function (`for (kt = 0; kt < p->n; kt++) {}` early on and `kt = (u32)b >> 5;` in
a switch arm later). One variable is one pseudo: global.c then colours the loop's counter and the arm's field as one
allocno with the uses and live length of both, and both land in one register. In the game they were two variables
(the target keeps the counter in `$v1` and the field in `$a2`). An SN GCC 2.8.1 model loader (sn-n64-281, 618
instructions): its empty parts loop given its own counter, 470 -> 410 (420 -> 360 under `-mfp32`). The
`loop_counter_roles_repairs` family leaves such a variable alone, since it requires every mention to lie in a loop.

`variants` finds `for (v = N; ...; ...)` loops whose integer variable `v` is mentioned outside the loop too, is never
address-taken, is not read before the loop, and after the loop is set before it is read in every switch arm or block
that follows (the first mention of `v` in each `case`/`default` segment after the loop is a plain `v = e;` whose `e`
does not mention `v`, and so is the first mention after the loop). The loop then gets a new variable of `v`'s type,
declared with the function's other locals. One child per loop.
"""
import re

from . import c_scan
from .integer_repair_support import IDENT, INTEGER, _address_taken, edit, view

FAMILY = 'loop_counter_own'
FAMILIES = (FAMILY,)
LIMIT = 4
FOR = re.compile(rf'\bfor\s*\(\s*(?P<v>{IDENT})\s*=\s*[^;]*;')
SEGMENT = re.compile(r'\b(?:case\b[^;{}]*?[^:]:(?!:)|default\s*:)')


def _sets_first(clean, lo, hi, v):
    """Whether the first mention of v in clean[lo:hi] is a plain set from an expression without v (or none at all)."""
    first = re.search(rf'\b{v}\b', clean[lo:hi])
    if not first:
        return True
    at = lo + first.start()
    if not re.search(r'(?:^|[;{}:])\s*$', clean[lo:at]) and not re.search(r'[;{}:]\s*$', clean[:at]):
        return False
    set_ = re.match(rf'{v}\s*=(?!=)\s*(?P<e>[^;]*);', clean[at:hi])
    return bool(set_) and not re.search(rf'\b{v}\b', set_['e'])


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto)\b', part.body):
        return []
    clean, results = part.clean, []
    for loop in FOR.finditer(clean, part.opening + 1, part.end):
        v = loop['v']
        decl = re.search(rf'(?m)^(?P<ind>[ \t]*)(?P<t>{INTEGER})\s+{v}\s*;', clean[part.opening:part.end])
        if not decl or _address_taken(part.body, v):
            continue
        header = c_scan.close(clean, clean.index('(', loop.start()), '(', ')')
        if header < 0:
            continue
        after = re.match(r'\s*{', clean[header + 1:part.end])
        if after:
            end = c_scan.close(clean, header + 1 + after.end() - 1) + 1
        else:
            end = clean.find(';', header + 1) + 1
        if end <= 0:
            continue
        before = clean[part.opening + decl.end():loop.start()]
        mentioned_after = re.search(rf'\b{v}\b', clean[end:part.end])
        if re.search(rf'\b{v}\b', before) or not mentioned_after:
            continue
        cuts = [end] + [m.start() for m in SEGMENT.finditer(clean, end, part.end)] + [part.end]
        if not all(_sets_first(clean, lo, hi, v) for lo, hi in zip(cuts, cuts[1:])):
            continue
        fresh = f'{v}_loop'
        if re.search(rf'\b{fresh}\b', clean):
            continue
        edits = [(m.start() + loop.start(), m.end() + loop.start(), fresh)
                 for m in re.finditer(rf'\b{v}\b', clean[loop.start():end])]
        line = part.opening + decl.end()
        edits.append((line, line, f'\n{decl["ind"]}{decl["t"]} {fresh};'))
        results.append((FAMILY, edit(source, tuple(edits))))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 700}  # the registry: no caller wiring (registry.py)
