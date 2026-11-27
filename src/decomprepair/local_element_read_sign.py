"""One element of a local byte or halfword array read with the other sign: `lbu` in the target, `lb` in ours.

A local `s8 pos[2]` is what `-1` stores and a signed test of `pos[0]` need, and every later read of it loads with `lb`.
The target of a 115-instruction high-score insertion routine (SN64 GCC 2.8.1, `-G0 -mips3 -O2`, N64) loaded `pos[1]`
with `lbu` where its value is shifted left and truncated to a byte: the read was `(u8) pos[1]`. The cast is the whole
difference (200 -> 0 on the exact judge); the casts and the result's width around it compiled to `lb`.

`local_element_read_sign`: only when the target loads from `$sp` with a sign the declaration does not give
(`lbu` for an `s8` array, `lb` for a `u8` one, and the halfword pair), each read `a[k]` (a literal k) is cast to the
target's type, one child per read, then all together. Stores, increments and addresses are left alone. The judge
decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'local_element_read_sign'
FAMILIES = (FAMILY,)
LIMIT = 6
_LOAD = re.compile(r'\b(lbu|lb|lhu|lh)\s+\$\w+\s*,\s*(?:0[xX][0-9a-fA-F]+|\d+)?\(\$sp\)')
# declared type -> (the target's load that disagrees, the type that gives it)
_OTHER = {'s8': ('lbu', 'u8'), 'u8': ('lb', 's8'), 's16': ('lhu', 'u16'), 'u16': ('lh', 's16'),
          'signed char': ('lbu', 'u8'), 'unsigned char': ('lb', 's8'), 'short': ('lhu', 'u16'),
          'unsigned short': ('lh', 's16')}
_ARRAY = re.compile(rf'(?<![\w.>])(?P<type>{"|".join(sorted(_OTHER, key=len, reverse=True))})\s+'
                    rf'(?P<name>{IDENT})\s*\[\s*{NUMBER}\s*\]\s*;')


def _reads(clean, part, name, start):
    for hit in re.finditer(rf'(?<![\w.>]){name}\s*\[\s*{NUMBER}\s*\]', clean[:part.end]):
        if hit.start() < start:
            continue
        before = clean[:hit.start()].rstrip()
        after = clean[hit.end():].lstrip()
        if (re.match(r'(?:\+\+|--|\[|(?:<<|>>|[+\-*/%&|^])?=(?!=))', after) or before.endswith(('++', '--'))
                or re.search(r'(?<!&)&$', before)):
            continue
        yield hit


def variants(source, name, asm=''):
    part = view(source, name)
    if not part:
        return []
    loads = set(_LOAD.findall(asm or ''))
    if not loads:
        return []
    clean = part.clean
    found = []
    for declared in _ARRAY.finditer(clean, part.opening + 1, part.end):
        load, kind = _OTHER[declared['type']]
        if load not in loads:
            continue
        edits = [(hit.start(), hit.start(), f'({kind}) ') for hit in _reads(clean, part, declared['name'], declared.end())
                 if not re.search(rf'\(\s*{kind}\s*\)$', clean[:hit.start()].rstrip())]
        found += [(FAMILY, edit(source, [one])) for one in edits[:LIMIT]]
        if len(edits) > 1:
            found.append((FAMILY, edit(source, edits)))
    return found[:LIMIT + 1]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',),
          'order': 80}
