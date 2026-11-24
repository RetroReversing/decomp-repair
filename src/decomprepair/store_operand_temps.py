"""A store whose value reads two array elements, the elements loaded into block-scoped temporaries first.

GCC 2.x expands `P[I] = E;` address first, then `E` left to right, and local-alloc (local-alloc.c) gives a basic
block's quantities registers in priority order, `floor_log2(refs) * refs / (death - birth)`: where each value is born
decides which one gets `$v0`, `$v1`, `$a0`. Loading the two elements into temporaries before the store moves both loads
ahead of the address and lets the address be born between them, so the address's quantity can outrank the second
load and take the register after the first chain's.

A 681-instruction N64 bit-stream decoder (KMC GCC 2.7.2 `-O2`): the fill loop's store
`sb[y] = (sym[k] << 7) + len[k];` gave the address `$a0` and the length `$v1` where the target has the address in
`$v1` and the length in `$a0`; written `{ __typeof__(sym[k]) t0 = sym[k], t1 = len[k]; sb[y] = (t0 << 7) + t1; }`
the inner loop's three block-local registers are the target's.

Child, for a statement `L = E;` whose `E` (no call, assignment, `++`, `--` or `?:`) reads exactly two distinct
indexed elements `A[I]` and `B[J]` of plain names: the statement wrapped in a block that declares `t0` and `t1` with
those elements (in either order) and `E` reading them. The candidate is never a verdict: the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'store_operand_temps'
FAMILIES = (FAMILY,)
LIMIT = 6
_STORE = re.compile(rf'(?<![\w.>])(?P<lhs>{IDENT}\s*\[[^\]\[;]+\])\s*=(?!=)\s*(?P<e>[^;{{}}]+);')
_ELEM = re.compile(rf'(?<![\w.>]){IDENT}\s*\[[^\]\[]+\]')


def _pure(expr):
    return not re.search(rf'[?;{{}}]|\+\+|--|(?<![=!<>])=(?!=)|{IDENT}\s*\(', expr)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _STORE.finditer(clean, part.opening + 1, part.end):
        expr = hit['e']
        if not _pure(expr):
            continue
        elems = []
        for m in _ELEM.finditer(expr):
            text = re.sub(r'\s+', '', m.group())
            if text not in [e for e, _ in elems]:
                elems.append((text, m))
        if len(elems) != 2:
            continue
        start, end = hit.start(), hit.end()
        raw_e = source[hit.start('e'):hit.end('e')]
        lhs = source[hit.start('lhs'):hit.end('lhs')]
        for order in (elems, elems[::-1]):
            names = {order[0][0]: 't0', order[1][0]: 't1'}
            body = _ELEM.sub(lambda m, names=names: names.get(re.sub(r'\s+', '', m.group()), m.group()), raw_e).strip()
            decl = ', '.join(f'{names[e]} = {e}' for e, _ in order)
            first = order[0][0]
            text = f'{{ __typeof__({first}) {decl}; {lhs} = {body}; }}'
            out.append((FAMILY, edit(source, [(start, end, text)])))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
