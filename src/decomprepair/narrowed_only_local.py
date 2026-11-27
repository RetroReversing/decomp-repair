"""A word local whose only read goes into a narrower variable, declared that narrow.

m2c types a local that holds a call's result `s32`. When its one read is the source of a narrower assignment
(`angle = facing - spread;` with `s16 angle`), the game often declared the local narrow too: GCC then copies the result
without the conversion a wider local gets. On a 67-instruction N64 routine (SN64 GCC 2.8.1, `-G0 -mips3 -O2`) declaring
that local `s16` was one step of an exact match (1219 -> 765). `cast_reads_narrow` is the same for a written cast.

Children: each such local retyped, one at a time.
"""
import re

from .integer_repair_support import DECL, edit, locals_for, refs, view

FAMILY = 'narrowed_only_local'
FAMILIES = (FAMILY,)
LIMIT = 6
_WIDE = ('s32', 'u32', 'int')
_NARROW = ('s16', 'u16', 's8', 'u8')


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    narrow = {hit['name']: hit['type'] for hit in DECL.finditer(part.clean, part.opening + 1, part.end)
              if hit['type'] in _NARROW}
    if not narrow:
        return []
    out = []
    for decl in locals_for(part):
        if decl['type'] not in _WIDE:
            continue
        writes, reads = [], []
        for hit in refs(part, decl):
            (writes if re.match(r'\s*=(?!=)', part.clean[hit.end():]) else reads).append(hit)
        if len(writes) != 1 or len(reads) != 1:
            continue
        begin = max(part.clean.rfind(mark, part.opening, reads[0].start()) for mark in ';{}') + 1
        stop = part.clean.find(';', reads[0].end())
        target = re.match(r'\s*(\w+)\s*=(?!=)', part.clean[begin:reads[0].start()])
        if not target or target[1] not in narrow:
            continue
        # a sum or difference of the value: no operator on it that reads its upper bits, the other terms aside
        expression, count = part.clean[begin + target.end():reads[0].start()] + '_' + part.clean[reads[0].end():stop], 1
        while count:
            expression, count = re.subn(r'\([^()]*\)', '#', expression)
        if re.search(r'[/%<>=!?&|,\[(]', expression.replace('->', '.')):
            continue
        out.append((FAMILY, edit(source, [(decl.start('type'), decl.end('type'), narrow[target[1]])])))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}
