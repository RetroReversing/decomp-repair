"""A table slot's address written with the base and the index staged before it, so the base is materialised between the
index's two halves.

m2c writes a slot pointer as one expression, `p = &sTable[(s16) id];`. gcc 2.7.2 expands it as the index's shifts, then
the `la` of the table, then the add; the first scheduler launches the `la` just before the `sra` that the shifts folded
into, and the final order is `sll; sra; lui; addiu; addu`. The game's code has the `la` between the two shift halves
(`sll $v1,$s7,16; lui; addiu; sra $v1,$v1,14; addu`): written with the index in its own local first and the base in a
pointer local, the `sll 16` / `sra 16` are emitted, then the `la`, then the `sll 2` that combine merges into the `sra 14`
at its own (later) position, so the `la` ends up between them. In a 795-instruction N64 object spawner two such slot
lookups took 120 -> 60 -> 0 (the last two rows of its match). The reading of sched.c (equal-priority insns launch in
descending luid) is a hypothesis; the judge decides.

The shape: `V = &SYM[IDX];` where `SYM` is declared `extern T SYM[]` in the source or its header, `V` is a local pointer
and `IDX` mentions a cast to a narrow integer type (`(s16)`, `(u16)`, `(s8)`, `(u8)`) or a parameter. One child per site,
one with every site: `EX = IDX; TAB = SYM; V = &TAB[EX];` with two new locals (`s32` and a pointer of `V`'s type).
"""
import re

from .arm_block_support import IDENT, brace_pairs, local_declaration, statements
from .csource import _blank
from .integer_repair_support import edit, view

FAMILY = 'table_base_stage'
FAMILIES = (FAMILY,)

SLOT = re.compile(rf'(?P<v>{IDENT})\s*=(?!=)\s*&\s*(?P<sym>{IDENT})\s*\[(?P<idx>[^\[\];]+)\]\s*;')
NARROW = re.compile(r'\(\s*(?:s16|u16|s8|u8|short|unsigned short|signed char|unsigned char)\s*\)')


def _arrays(text):
    return set(re.findall(rf'(?m)^[ \t]*extern\b[^;()]*?\b({IDENT})\s*\[\s*[^\]]*\]\s*;', _blank(text or '')))


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    arrays = _arrays(clean[:part.opening]) | _arrays(header)
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs or not arrays:
        return []
    sites = []
    for block_open, block_close in sorted(pairs.items()):
        for start, end in statements(clean, block_open + 1, block_close):
            hit = SLOT.fullmatch(clean[start:end].strip())
            if not hit or hit['sym'] not in arrays or not NARROW.search(hit['idx']):
                continue
            declared = local_declaration(clean, part.opening, hit['v'])
            if not declared or not declared[1]:
                continue
            sites.append((start, end, hit, declared))
    if not sites:
        return []
    decl_at = clean.find('\n', part.opening) + 1
    indent = re.match(r'[ \t]*', source[decl_at:])[0] or '  '

    def names(number):
        return f'slot{number}_index', f'slot{number}_table'

    def fresh(number):
        return not any(re.search(rf'\b{n}\b', clean) for n in names(number))

    out, all_edits = [], []
    for number, (start, end, hit, declared) in enumerate(sites, 1):
        if not fresh(number):
            continue
        index, table = names(number)
        pad = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:start])[0]
        type_, stars = declared
        body = (f"{index} = {hit['idx'].strip()};\n{pad}{table} = {hit['sym']};\n{pad}{hit['v']} = &{table}[{index}];")
        edits = [(start, end, body), (decl_at, decl_at, f'{indent}s32 {index};\n{indent}{type_} {stars}{table};\n')]
        text = edit(source, edits)
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
        all_edits += edits
    if len(sites) > 1 and all_edits:
        text = edit(source, all_edits)
        if (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 92}  # the registry: no caller wiring (registry.py)
