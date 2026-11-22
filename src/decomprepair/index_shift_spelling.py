"""`index * 4` in an address spelled `index << 2` (and back), for a loop that keeps hoisting the table's address.

A KMC GCC 2.7.2 loop body stored a byte through `sym + (u8 global) * 4`. Written with the multiplication the compiler
hoisted the symbol's `lui/addiu` into a saved register for the whole loop (a `$s5` the target never has, 3062); with
`<< 2` the address stayed folded into the store as `lui $at; addu $at,$at,idx; sb ..., %lo(sym)($at)` (1925, then the
rest of the function's rows were the only ones left). expand turns both into the same shift, so the difference is in
what the earlier passes see in the source (a `MULT` is a candidate induction expression for loop.c; a shift is not,
a hypothesis not read in loop.c). One occurrence per child, then all of them in one child; the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'index_shift_spelling'
FAMILIES = (FAMILY,)
LIMIT = 8
_SHIFTS = {2: 1, 4: 2, 8: 3, 16: 4}
_PRODUCT = re.compile(rf'(?P<pre>[+\[]\s*)(?P<x>{IDENT})\s*\*\s*(?P<k>2|4|8|16)(?P<post>\s*[\])])')
_SHIFT = re.compile(rf'(?P<pre>[+\[]\s*)\(?\s*(?P<x>{IDENT})\s*<<\s*(?P<k>[1-4])\s*\)?(?P<post>\s*[\])])')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    spans = []
    for hit in _PRODUCT.finditer(part.clean, part.opening + 1, part.end):
        spans.append((hit.start('x'), hit.end('k'), f'({hit["x"]} << {_SHIFTS[int(hit["k"])]})'))
    for hit in _SHIFT.finditer(part.clean, part.opening + 1, part.end):
        end = hit.end('k') + (1 if part.clean[hit.end('k'):].lstrip().startswith(')') and '(' in part.clean[hit.start('pre'):hit.start('x')] else 0)
        spans.append((hit.start('x') - (1 if part.clean[hit.start('x') - 1] == '(' else 0), end if end <= hit.end('post') else hit.end('k'),
                      f'{hit["x"]} * {1 << int(hit["k"])}'))
    spans.sort()
    result = [('index_shift_spelling', edit(source, [one])) for one in spans]
    if len(spans) > 1:
        result.append((FAMILY, edit(source, spans)))
    return list(dict.fromkeys(result))[:LIMIT]
