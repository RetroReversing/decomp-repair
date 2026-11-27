"""A record pointer that first holds the widened index it is computed from: one variable for the index and the address.

    p = (i * 0x24) + TABLE;     ->     p = (T *)(s32)i;  p = ((s32)p * 0x24) + TABLE;

m2c writes the element address as one expression from a narrow index (an `s16` kept unextended in a saved register).
GCC 2.7.2 then extends the index into a scratch register (`sra $v0`) and only the finished address reaches the pointer's
saved register. A target that extends straight into the pointer's register (`sra $s0,$v0,16; sll $v0,$s0,3; addu
$v0,$v0,$s0; ...; addu $s0,$v0,$v1`) had one pseudo for both values: the original's variable held the index and was then
overwritten with the address (a KMC GCC 2.7.2 `-O1 -g` record initialiser, 35 -> 0; spelling the index as an `s32` local
of its own, as `&TABLE[i * 0x24]` or as `(s32)arg` left the seven register rows). The allocation reading is a hypothesis;
the judge decides.

pointer_index_carrier
    `P = (I * K) + B;`, `P = B + (I * K);` or `P = &B[I * K];` with P a pointer local declared in the function, I an
    identifier other than P, K an integer literal and B an identifier. Child: `P = (T *)(s32)I;` on the line before and
    the address computed from `(s32)P`. At most 4.
"""
import re

from .csource import _blank, find

FAMILY = 'pointer_index_carrier'
FAMILIES = (FAMILY,)
ID = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
LIMIT = 4
_FORMS = (
    (re.compile(rf'\(?\s*(?P<i>{ID})\s*\*\s*(?P<k>{NUM})\s*\)?\s*\+\s*(?P<b>{ID})'), '(((s32){p} * {k}) + {b})'),
    (re.compile(rf'(?P<b>{ID})\s*\+\s*\(?\s*(?P<i>{ID})\s*\*\s*(?P<k>{NUM})\s*\)?'), '({b} + ((s32){p} * {k}))'),
    (re.compile(rf'&\s*(?P<b>{ID})\s*\[\s*(?P<i>{ID})\s*\*\s*(?P<k>{NUM})\s*\]'), '({b} + ((s32){p} * {k}))'),
)


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return None
    depth = 0
    for i in range(opening, span[1]):
        depth += (clean[i] == '{') - (clean[i] == '}')
        if depth == 0:
            return opening, i + 1
    return None


def variants(source, name):
    part = _body(source, name)
    if not part:
        return []
    opening, end = part
    body = source[opening:end]
    pointers = {m['p']: m['t'].strip() for m in re.finditer(
        rf'(?m)^[ \t]*(?P<t>(?:const\s+)?{ID}(?:\s+{ID})?)\s*\*\s*(?P<p>{ID})\s*;', body)}
    if not pointers:
        return []
    out = []
    for m in re.finditer(rf'(?m)^(?P<ind>[ \t]*)(?P<p>{ID})\s*=\s*(?P<rhs>[^;\n]+);[ \t]*$', body):
        p = m['p']
        if p not in pointers:
            continue
        rhs = m['rhs'].strip()
        for form, template in _FORMS:
            f = form.fullmatch(rhs)
            if not f or f['i'] == p or f['b'] == p:
                continue
            t = pointers[p]
            address = template.format(p=p, k=f['k'], b=f['b'])
            if t != 'void':
                address = f'({t} *){address}'
            new = f"{m['ind']}{p} = ({t} *)(s32){f['i']};\n{m['ind']}{p} = {address};"
            start = opening + m.start()
            out.append((FAMILY, source[:start] + new + source[opening + m.end():]))
            break
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
