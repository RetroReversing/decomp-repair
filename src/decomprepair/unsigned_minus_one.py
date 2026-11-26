"""A halfword given -1 that the target builds as `ori $r,$zero,0xFFFF`: the field is unsigned.

GCC 2.x stores -1 into an `s16` from `addiu $r,$zero,-1` and into a `u16` from `ori $r,$zero,0xFFFF`. A KMC GCC 2.7.2
(`-O1`) list initialiser over an array of records was one opcode off (200) with `s16 prev, next` and exact with `u16`:
the other stores of those fields compile the same either way.

unsigned_minus_one
    The target has `ori $r,$zero,0xFFFF`: every `s16` struct member or global the source declares and assigns `-1` to is
    declared `u16`, all together, then each name alone.

The exact judge decides every child."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT

FAMILY = 'unsigned_minus_one'
FAMILIES = (FAMILY,)
LIMIT = 4
TARGET = re.compile(r'\bori\s+\$\w+\s*,\s*\$zero\s*,\s*\(?\s*0[xX][fF]{4}\b')


def variants(source, name, asm='', arch='mips'):
    if arch != 'mips' or not TARGET.search(asm or ''):
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    names = dict.fromkeys(re.findall(r'(?:\.|->|[;{}]\s*)(' + IDENT + r')\s*=\s*-\s*1\s*;', clean[span[0]:span[1]]))
    places = {}
    for member in names:
        for hit in re.finditer(r'\b(s16)\s+(?:' + IDENT + r'\s*,\s*)*' + member + r'\s*(?=[;\[,])', clean):
            places.setdefault(member, set()).add(hit.span(1))

    def apply(spans):
        text = source
        for a, b in sorted(spans, reverse=True):
            text = text[:a] + 'u16' + text[b:]
        return text

    result = []
    if places:
        result.append(apply(set().union(*places.values())))
    result.extend(apply(spans) for spans in places.values())
    return [(FAMILY, text) for text in dict.fromkeys(result)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'arch'), 'archs': ('mips',)}
