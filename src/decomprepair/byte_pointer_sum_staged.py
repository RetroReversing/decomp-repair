"""A pointer sum `v = X + P;` of a byte pointer P, as an integer sum with X first staged in a local of its own.

    temp_a0_2 = (arg1 * 0x18) + p;  ->  { s32 __repair_sum; __repair_sum = (arg1 * 0x18) + (s32) p; temp_a0_2 = (void *) __repair_sum; }

`X + P` (and `P + X`) on a `char *`, `u8 *` or `void *` is pointer arithmetic, and the C front end builds the add pointer
first: `addu $a0,$a0,$v0`. Two KMC GCC 2.7.2 `-O1` twins (42 instructions each, an N64 game's table minimum) had
`addu $a0,$v0,$a0`, the only difference (5). As an integer, the operand order written is kept, but assigned straight to
V (`v = (void *) (X + (s32) P);`, also offered) it scored 45: expand computed the index's sign extension into V itself,
which then lost `$a0` to another pseudo. Staged in a local of its own, both twins were exact. `byte_pointer_sum_int_first`
does the same for a sum under a pointer cast and for `v = X + (P + I)`. A hypothesis from the expansion and the
allocation dumps; the judge decides.

Offered when V is declared a pointer, P a byte pointer (`byte_pointer_sum_int_first._byte_pointer`), X has no call,
assignment or P in it and is not a constant (a constant offset is an `addiu`, with no order to change).
Children (`byte_pointer_sum_staged`): the staged form and the unstaged one, per site, at most `LIMIT`.
"""
import re

from .byte_pointer_sum_int_first import TERM, _byte_pointer
from .integer_repair_support import IDENT, edit, view

FAMILY = 'byte_pointer_sum_staged'
FAMILIES = (FAMILY,)
LIMIT = 8
CONSTANT = re.compile(r'\(?\s*(?:0[xX][0-9a-fA-F]+|\d+)\s*\)?')
PLAIN = re.compile(rf'(?<![\w.>])(?P<v>{IDENT})\s*=\s*(?P<a>{TERM})\s*\+\s*(?P<b>{TERM})\s*;')


def _pointer_local(clean, name):
    """Whether NAME is declared as a pointer (any element type)."""
    return re.search(rf'\b{IDENT}\s*\*+\s*{re.escape(name)}\s*[;,=)]', clean) is not None


def variants(source, name):
    """`v = X + P;` or `v = P + X;` with P a byte pointer and V a pointer: the integer sum, X first, staged in a local
    of its own and unstaged."""
    part = view(source, name)
    if not part:
        return []
    clean, out = part.clean, []
    for hit in PLAIN.finditer(clean, part.opening, part.end):
        a, b, v = hit['a'].strip(), hit['b'].strip(), hit['v']
        if re.fullmatch(IDENT, b) and _byte_pointer(clean, b):
            x, p = a, b
        elif re.fullmatch(IDENT, a) and _byte_pointer(clean, a):
            x, p = b, a
        else:
            continue
        # a constant offset is an `addiu`: no operand order to change
        if (not x or x[0] in '*&' or CONSTANT.fullmatch(x) or re.search(rf'\b{re.escape(p)}\b', x)
                or re.search(r'\+\+|--|[<>&|^?:!=]', x)
                or re.search(rf'\b{IDENT}\s*\(', x.replace('(s32)', '')) or not _pointer_local(clean, v)
                or v == p or _byte_pointer(clean, x)):
            continue
        before = clean[:hit.start()].rstrip()
        if before and before[-1] not in ';{}':
            continue
        start, end = hit.start(), hit.end()
        for text in (f'{{ s32 __repair_sum; __repair_sum = {x} + (s32) {p}; {v} = (void *) __repair_sum; }}',
                     f'{v} = (void *) ({x} + (s32) {p});'):
            out.append((FAMILY, edit(source, [(start, end, text)])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
