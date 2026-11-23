"""A field stored and read back at once, the read kept as a load through a volatile lvalue.

`((Rec *) e)->value = arg0; v = ((Rec *) e)->value;`: in KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) cse forwards the
store to the read (`v` is `arg0`'s register), where the target stored the field and loaded it back one instruction later
(`sw $a0, 4($s2); lw $a2, 4($s2)`), the reload then holding the pointer the next loops walk. A volatile read of the same
lvalue is the one spelling found that keeps the load (a different cast, the member form against the cast form and an
unsigned store did not): 2805 -> 2525 on a 384-instruction function (isolated judge; no other family offered it). The program
reads the value it just stored either way; `volatile` only says that the read happens.

For two consecutive statements `L = <expression>;` and `V = L;` whose `L` is the same member or dereference text, the child reads
`V = *(volatile __typeof__ (L) *) &(L);`. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .pattern_repairs import close

FAMILY = 'store_reload_volatile'
FAMILIES = (FAMILY,)
PAIR = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<lvalue>(?:\*[^;=\n]+?|[^;=\n]*?(?:->|\.)\s*{IDENT}))[ \t]*=(?!=)[ \t]*[^;\n]+;[ \t]*\n'
                  rf'(?P=indent)(?P<dest>{IDENT})[ \t]*=[ \t]*(?P<again>[^;\n]+?)[ \t]*;')
LIMIT = 4


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    end = close(clean, opening, '{', '}') or span[1]
    if re.search(r'\b(?:asm|__asm__)\b|^\s*#', clean[opening:end], re.M):
        return []
    result = []
    for pair in PAIR.finditer(clean, opening, end):
        lvalue = pair['lvalue'].strip()
        if re.sub(r'\s+', '', pair['again']) != re.sub(r'\s+', '', lvalue) or 'volatile' in lvalue:
            continue
        reload = f'*(volatile __typeof__ ({lvalue}) *) &({lvalue})'
        result.append((FAMILY, edit(source, [(pair.start('again'), pair.end('again'), reload)])))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
