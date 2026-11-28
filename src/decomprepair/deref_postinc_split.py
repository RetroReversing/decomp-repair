"""A read through a post-incremented pointer, `x = *p++;`, written as the read and then the step: `x = *p; p++;`.

SN GCC 2.8.1 (N64, `-G0 -mips3 -O2`) expands `x = *p++` with a copy of the old pointer kept for the read. When `p` is a
variable whose address is taken (a stream position the callees advance), the two spellings differ in more than order:
`x = *p++` leaves a register holding `&p` that common subexpression elimination hands on to the next block that passes
`&p` to a call, so that block's `addiu $a0, $sp, K` is computed early, in the block of the read. Written as two statements
the address is computed where the target has it. Measured on one 165-instruction LZ unpacker: 540 -> 180 (the byte of a
match length). The compiler account is a hypothesis from the pass dumps (jump through sched); the judge decides.

`variants` finds `X = *P++;` and `X = *P--;` statements (`X`, `P` plain names, `X` not `P`) and writes
`X = *P; P++;`: one child with every such statement and one per statement. A statement that is the unbraced body of an
`if`, `else` or loop is left alone, since two statements there would change what the condition covers.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'deref_postinc_split'
FAMILIES = (FAMILY,)
LIMIT = 8
# only after a `;` or a brace: the unbraced body of a condition, and a labelled statement, are not matched
STATEMENT = re.compile(rf'(?<=[;{{}}])(?P<space>\s*)(?P<text>(?P<dest>{IDENT})\s*=\s*\*\s*(?P<var>{IDENT})\s*'
                       r'(?P<op>\+\+|--)\s*;)')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    sites = [hit for hit in STATEMENT.finditer(part.clean, part.opening, part.end) if hit['dest'] != hit['var']]
    if not sites:
        return []

    def build(chosen):
        edits = []
        for hit in chosen:
            line = source.rfind('\n', 0, hit.start('text')) + 1
            indent = source[line:hit.start('text')]
            between = '\n' + indent if not indent.strip() else ' '
            edits.append((hit.start('text'), hit.end('text'),
                          f'{hit["dest"]} = *{hit["var"]};{between}{hit["var"]}{hit["op"]};'))
        return edit(source, edits)

    results = []
    for chosen in ([sites] if len(sites) > 1 else []) + [[site] for site in sites]:
        text = build(chosen)
        if (FAMILY, text) not in results:
            results.append((FAMILY, text))
        if len(results) >= LIMIT:
            break
    return results


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}
