"""`a - (e - K)` with the bracket in a local of its own.

GCC reassociates a constant out of a bracketed term: `angle = facing - (spread - 0x455);` compiles as
`(facing + 0x455) - spread`, an `addiu` on the wrong value. Where the target takes the constant from the other term
first, the game computed that term as a value of its own. On a 67-instruction N64 routine (SN64 GCC 2.8.1,
`-G0 -mips3 -O2`) staging it in a new local was one step of an exact match; reusing a dead local instead
(`dead_local_stage`) ties its register to that local's other uses.

Children: each `x ± (e ± K)` assignment with `e ± K` set in a new local just before it.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'constant_term_stage'
FAMILIES = (FAMILY,)
LIMIT = 4
_ASSIGN = re.compile(rf'(?<=[;{{}}])(?P<gap>\s*)(?P<to>{IDENT}(?:(?:\.|->){IDENT})*)\s*=(?!=)\s*'
                     rf'(?P<left>{IDENT}(?:(?:\.|->){IDENT})*)\s*[-+]\s*(?=\()')
_TAIL = re.compile(rf'[-+]\s*{NUMBER}\s*$')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for hit in _ASSIGN.finditer(part.clean, part.opening, part.end):
        opening = hit.end()
        end = close(part.clean, opening, '(', ')')
        if not end or part.clean[end:].lstrip()[:1] != ';':
            continue
        inner = part.clean[opening + 1:end - 1]
        tail = _TAIL.search(inner)
        # the constant is the bracket's own last term, not an operand of a tighter operator inside it
        if not tail or not re.search(r'[\w\])]\s*$', inner[:tail.start()]):
            continue
        # the bracket's value has to be computed where the statement stands: only statements, not `if (c) a = ..;`
        word = 'term'
        while re.search(rf'\b{word}\b', source):
            word += '_'
        value = source[opening + 1:end - 1].strip()
        body = part.opening + 1
        out.append((FAMILY, edit(source, [
            (body, body, f'\n    s32 {word};'),
            (hit.start('to'), hit.start('to'), f'{word} = {value};{hit["gap"] or " "}'),
            (opening, end, word)])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}
