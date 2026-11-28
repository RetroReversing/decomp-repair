"""A left shift written as its own statement: `total = (a + b) << 16;` becomes `total = (a + b); total <<= 16;`.

The two spellings give the scheduler a different graph. With the shift in the same expression, SN GCC 2.8.1 (N64,
`-G0 -mips3 -O2`) scheduled a following `size >>= 16;` and its use above the shift; as two statements the sum, the shift
and the next value's shift come out in the target's order. Measured on one 165-instruction LZ unpacker that assembles a
byte-swapped 32-bit length from two halves: 120 -> 0. The scheduling account is a hypothesis; the judge decides.

`variants` finds `X = E << K;` where `X` is an integer local declared in the function, `K` an integer constant and the
`<<` is the expression's outermost operator (`E` is parenthesized or a single name), and writes `X = E; X <<= K;`. A left
shift only drops high bits, so truncating `E` to `X`'s type first gives the same value. One child with every such
statement and one per statement.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view

FAMILY = 'shift_assign_split'
FAMILIES = (FAMILY,)
LIMIT = 8
STATEMENT = re.compile(rf'(?<=[;{{}}])\s*(?P<text>(?P<dest>{IDENT})\s*=(?!=)\s*(?P<expr>[^;{{}}=]+?)\s*<<\s*'
                       r'(?P<count>0[xX][0-9a-fA-F]+|\d+)\s*;)')


def _closed(expr):
    """`expr` is one operand: a name, or a parenthesized group that spans all of it."""
    if re.fullmatch(IDENT, expr):
        return True
    if not expr.startswith('(') or not expr.endswith(')'):
        return False
    depth = 0
    for at, char in enumerate(expr):
        depth += {'(': 1, ')': -1}.get(char, 0)
        if depth == 0:
            return at == len(expr) - 1
    return False


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    locals_ = {hit['name'] for hit in re.finditer(rf'(?<![\w*])(?:{INTEGER})\s+(?P<name>{IDENT})\s*(?=[;=])',
                                                   part.clean[part.opening:part.end])}
    sites = [hit for hit in STATEMENT.finditer(part.clean, part.opening, part.end)
             if hit['dest'] in locals_ and _closed(hit['expr'].strip())
             and not re.search(r'\+\+|--', hit['expr']) and not re.search(rf'\b{hit["dest"]}\b', hit['expr'])]
    if not sites:
        return []

    def build(chosen):
        edits = []
        for hit in chosen:
            line = source.rfind('\n', 0, hit.start('text')) + 1
            indent = source[line:hit.start('text')]
            between = '\n' + indent if not indent.strip() else ' '
            value = source[hit.start('expr'):hit.end('expr')].strip()
            edits.append((hit.start('text'), hit.end('text'),
                          f'{hit["dest"]} = {value};{between}{hit["dest"]} <<= {hit["count"]};'))
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
