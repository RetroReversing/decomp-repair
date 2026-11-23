"""`index * 4` in an address spelled `index << 2` (and back), for a loop that keeps hoisting the table's address.

A KMC GCC 2.7.2 loop body stored a byte through `sym + (u8 global) * 4`. Written with the multiplication the compiler
hoisted the symbol's `lui/addiu` into a saved register for the whole loop (a `$s5` the target never has, 3062); with
`<< 2` the address stayed folded into the store as `lui $at; addu $at,$at,idx; sb ..., %lo(sym)($at)` (1925, then the
rest of the function's rows were the only ones left). expand turns both into the same shift, so the difference is in
what the earlier passes see in the source (a `MULT` is a candidate induction expression for loop.c; a shift is not,
a hypothesis not read in loop.c). One occurrence per child, then all of them in one child; the judge decides.

The operand may also be a parenthesised expression (m2c's `temp_s2 + ((*((s8 *) p)) * 8)`, a loaded byte scaled into a
record offset) or sit inside a parenthesis of its own (`base + (i * 2)`). Outside loops it moves the add's operands:
a 1133-instruction effect spawner (KMC GCC 2.7.2) has `addu $v0, $s2, $v0` for both of its scaled record reads, which
only the shift gave (125 -> 115, both together); written with `*` the index came first.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'index_shift_spelling'
FAMILIES = (FAMILY,)
LIMIT = 24
_SHIFTS = {2: 1, 4: 2, 8: 3, 16: 4}
_PRODUCT = re.compile(rf'(?P<pre>[+\[]\s*\(?\s*)(?P<x>{IDENT})\s*\*\s*(?P<k>2|4|8|16)(?P<post>\s*[\])])')
_GROUP_PRODUCT = re.compile(r'\)\s*\*\s*(?P<k>2|4|8|16)(?P<post>\s*[\])])')


def _group_products(clean, start, end):
    """(start, end, text) for `+ (EXPR) * k)` / `+ ((EXPR) * k))` / `[(EXPR) * k]`: a parenthesised operand (a loaded
    byte, a cast) scaled in an address, as m2c writes `temp_s2 + ((*((s8 *) p)) * 8)`."""
    found = []
    for hit in _GROUP_PRODUCT.finditer(clean, start, end):
        depth, at = 0, hit.start()
        while at > start:
            depth += (clean[at] == ')') - (clean[at] == '(')
            if depth == 0:
                break
            at -= 1
        if depth or at <= start:
            continue
        before = clean[:at].rstrip()
        if before.endswith('(') and before[:-1].rstrip()[-1:] in '+[':
            pass
        elif before[-1:] not in '+[':
            continue
        found.append((at, hit.start('k') + len(hit['k']), at))
    return found
_SHIFT = re.compile(rf'(?P<pre>[+\[]\s*)\(?\s*(?P<x>{IDENT})\s*<<\s*(?P<k>[1-4])\s*\)?(?P<post>\s*[\])])')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    spans = []
    for hit in _PRODUCT.finditer(part.clean, part.opening + 1, part.end):
        spans.append((hit.start('x'), hit.end('k'), f'({hit["x"]} << {_SHIFTS[int(hit["k"])]})'))
    for at, stop, _ in _group_products(part.clean, part.opening + 1, part.end):
        operand = source[at:part.clean.rfind(')', at, stop) + 1]
        k = int(re.search(r'(2|4|8|16)\s*$', part.clean[at:stop])[1])
        spans.append((at, stop, f'({operand} << {_SHIFTS[k]})'))
    for hit in _SHIFT.finditer(part.clean, part.opening + 1, part.end):
        end = hit.end('k') + (1 if part.clean[hit.end('k'):].lstrip().startswith(')') and '(' in part.clean[hit.start('pre'):hit.start('x')] else 0)
        spans.append((hit.start('x') - (1 if part.clean[hit.start('x') - 1] == '(' else 0), end if end <= hit.end('post') else hit.end('k'),
                      f'{hit["x"]} * {1 << int(hit["k"])}'))
    spans.sort()
    result = [('index_shift_spelling', edit(source, [one])) for one in spans]
    if len(spans) > 1:
        result.append((FAMILY, edit(source, spans)))
    return list(dict.fromkeys(result))[:LIMIT]
