"""m2c's cast around a negated halfword (or byte) field before a shift, dropped.

For `lh; negu; sra` m2c writes `(s16) -M2C_FIELD(p, s16 *, 0) >> 1`. The cast makes GCC 2.8.1 load with `lhu`, negate,
then `sll 16; sra 17`, two instructions the target does not have; the game wrote `-p->x >> 1` (a 131-instruction
spawn-point routine, SN GCC 2.8.1 `-O2`, 995 -> 553 on the seed alone). The two differ only for the one value that has
no negation in the narrow type, so the judge decides.

negated_narrow_cast
    `(s8|s16) -M2C_FIELD(.., s8|s16 *, ..)` followed by `>>` loses the cast; every site at once, then each alone.
"""
import re

from .csource import _blank, find

FAMILY = 'negated_narrow_cast'
FAMILIES = (FAMILY,)

CAST = re.compile(r'\(\s*(?P<type>s8|s16)\s*\)\s*(?=-\s*M2C_FIELD\s*\([^()]*?,\s*(?P=type)\s*\*\s*,[^()]*\)\s*\)?\s*>>)')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    spans = [(m.start(), m.end()) for m in CAST.finditer(_blank(source), span[0], span[1])]
    if not spans:
        return []

    def without(drop):
        text = source
        for first, last in sorted(drop, reverse=True):
            text = text[:first] + text[last:]
        return text

    result = [(FAMILY, without(spans))]
    if len(spans) > 1:
        result += [(FAMILY, without([one])) for one in spans]
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
