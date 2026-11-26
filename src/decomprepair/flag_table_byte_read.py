"""A flag table read as words where the target loads bytes: a word dereference only compared with zero, as `u8`.

    if (*(s32 *)(table + i) != 0) {...}      ->      if (*(u8 *)(table + i) != 0) {...}

m2c types a table by its first use and writes a flag test as the word it loaded; the game's source tested a byte
(`lbu $v0,0x0($v0)` then `beqz`), and a word read there is a different instruction (200 points on a 29-instruction
loop, KMC GCC 2.7.2 `-O2`). `flag_table_byte_read`: for each `*(s32 *)(...)` (also `u32`, `s16`, `u16`, `int`) that is
compared with zero (`!= 0`, `== 0`) or is the whole `if`/`while` test, a child with `u8` there (`s8` when the target has
`lb` and no `lbu` of that kind), each site alone and every site together. Needs the target's assembly: nothing is
offered unless it loads a byte through a register with no relocation (`lbu`/`lb $r, 0x0($r)`). Only the plain cast
dereference is read; fields of a record (`M2C_FIELD`, `->`) are left to the field-width families."""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'flag_table_byte_read'
FAMILIES = (FAMILY,)
SITE = re.compile(r'\*\s*\(\s*(?P<t>s32|u32|s16|u16|int)\s*\*\s*\)\s*\(')
BYTE = re.compile(r'\b(?P<op>lbu|lb)\s+\$\w+,\s*(?:0x)?0?\(\$\w+\)')
RELOC = re.compile(r'%lo')


def variants(source, name, asm=''):
    ops = {m['op'] for row in (asm or '').splitlines() if not RELOC.search(row) for m in BYTE.finditer(row)}
    part = view(source, name)
    if not ops or not part:
        return []
    kind = 'u8' if 'lbu' in ops else 's8'
    spans = []
    for site in SITE.finditer(part.clean, part.opening, part.end):
        stop = close(part.clean, site.end() - 1)
        if not stop:
            continue
        after = part.clean[stop:stop + 12]
        before = part.clean[max(part.opening, site.start() - 12):site.start()]
        zero = re.match(r'\s*(?:!=|==)\s*0\b', after)
        whole = re.search(r'\b(?:if|while)\s*\(\s*!?\s*$', before) and re.match(r'\s*\)', after)
        if zero or whole:
            spans.append((site.start('t'), site.end('t'), kind))
    out = [(FAMILY, edit(source, [s])) for s in spans]
    if len(spans) > 1:
        out.append((FAMILY, edit(source, spans)))
    return out[:6]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
