"""A temporary that holds `w & M` for one use, written to hold `w` with the mask moved into that use.

m2c names the intermediate of `r = (w & 0xFF) - 0x10` after the masked value: `t = w & 0xFF; r = t - 0x10;`. When the
draft's `t` is a local shared with other blocks (m2c reuses one name per register), the mask's result becomes that
shared, global pseudo, which global.c places by the whole variable's priority; the target's `andi $v0, $v1, 0xFF` ties
the masked value to the subtraction's own register instead. Holding the word in the shared local and masking at the
use (`t = w; r = (t & 0xFF) - 0x10;`) keeps the local's other blocks as they were and leaves the mask a block-local
value: the last two rows of an effect spawner's fade-out case (KMC GCC 2.7.2, 95 -> 85).

Two adjacent statements `A = (B & K);` `D = A OP E;` with A a plain local, B a plain local, K a literal: the child is
`A = B;` `D = ((A & K)) OP E;`. Offered only when A is not read again before it is next assigned (or the function
ends), so the value A holds afterwards is never seen.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'temp_operand_stage'
FAMILIES = (FAMILY,)
LIMIT = 8

_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_PAIR = re.compile(rf'(?P<first>(?P<a>{IDENT})\s*=\s*\(?\s*(?P<b>{IDENT})\s*&\s*(?P<k>{_NUM})\s*\)?\s*;)'
                   rf'(?P<gap>\s*)(?P<second>(?P<d>{IDENT})\s*=\s*(?P=a)\s*(?P<op>[-+|^&*]|<<|>>)\s*(?P<e>[^;{{}}]+);)')


def _read_before_set(clean, name, start, end):
    """True when NAME is read after START before it is next assigned (or before END)."""
    for hit in re.finditer(rf'(?<![\w.>]){re.escape(name)}\b', clean[start:end]):
        after = clean[start + hit.end():start + hit.end() + 3]
        if re.match(r'\s*=(?!=)', after):
            return False
        return True
    return False


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for hit in _PAIR.finditer(part.clean, part.opening + 1, part.end):
        a, b = hit['a'], hit['b']
        if a == b or a == hit['d'] or re.search(rf'\b{re.escape(a)}\b', hit['e']):
            continue
        if _read_before_set(part.clean, a, hit.end(), part.end):
            continue
        text = edit(source, [(hit.start('first'), hit.end('first'), f'{a} = {b};'),
                             (hit.start('second'), hit.end('second'),
                              f"{hit['d']} = (({a} & {hit['k']})) {hit['op']} {source[hit.start('e'):hit.end('e')]};")])
        out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
