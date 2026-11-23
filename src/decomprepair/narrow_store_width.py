"""A word store of a value m2c narrowed, written as the narrow store the target has (and the value held unnarrowed).

m2c types a store by the widest access it saw, so a halfword field written from a halfword value can come out as
`*((s32 *) (((char *) rec) + 0x40)) = (s16) value;`: a `sw` of a sign-extended value where the target has `sh`. The
cast on the right says the game's value was a halfword, and the target's own instructions say whether the store was one:
`narrow_store_width` changes the pointer type to the cast's (`s16`/`u16` for `sh`, `s8`/`u8` for `sb`) and drops the now
implied cast, only when the target's assembly stores that width at that offset (`sh $reg, 0x40($reg)`). One child per
site (the first 12), and one with all of them. Measured on a 616-instruction audio command builder: two such stores,
5645 -> 5245. Every child is judged: a narrower store changes what the program writes, so it is made only on the
target's own evidence.

`narrow_roundtrip_hold` is the next row of the same function: m2c narrows a converted value twice, once into the local
and once at the store (`v = (s16) ((s32) f); *((s16 *) p) = (s16) ((s32) f);`), where the target keeps the word the
conversion made and stores its low half (`sh`, no `sll`/`sra` pair): the local holds `(s32) f` and the store writes the
local. Only when the target stores that width at that offset and its assembly has no halfword sign extension at all
(5245 -> 5035 with the width change above)."""
import re

from .integer_repair_support import edit, view

FAMILY = 'narrow_store_width'
FAMILY_HOLD = 'narrow_roundtrip_hold'
FAMILIES = (FAMILY, FAMILY_HOLD)

LIMIT = 12
_CAST = {'s16': ('sh', 's16'), 'u16': ('sh', 'u16'), 's8': ('sb', 's8'), 'u8': ('sb', 'u8')}
_STORE = re.compile(
    r'\*\s*\(\(\s*(?P<wide>[su]32|int|unsigned(?:\s+int)?)\s*\*\s*\)\s*\(\(\(\s*char\s*\*\s*\)\s*(?P<base>[A-Za-z_]\w*)\s*\)\s*'
    r'\+\s*(?P<offset>0[xX][0-9a-fA-F]+|\d+)\s*\)\s*\)\s*=\s*\(\s*(?P<narrow>[su](?:8|16))\s*\)\s*')
_HOLD = re.compile(
    r'(?P<v>[A-Za-z_]\w*)\s*=\s*\(\s*(?P<n>[su](?:8|16))\s*\)\s*\(\s*\(\s*s32\s*\)\s*(?P<e>[^;]+?)\s*\)\s*;\s*'
    r'\*\s*\(\(\s*(?P=n)\s*\*\s*\)\s*\(\(\(\s*char\s*\*\s*\)\s*(?P<base>[A-Za-z_]\w*)\s*\)\s*\+\s*'
    r'(?P<offset>0[xX][0-9a-fA-F]+|\d+)\s*\)\s*\)\s*=\s*\(\s*(?P=n)\s*\)\s*\(\s*\(\s*s32\s*\)\s*(?P=e)\s*\)\s*;')
_ASM = re.compile(r'\b(sh|sb)\s+\$\w+\s*,\s*(-?(?:0[xX][0-9a-fA-F]+|\d+))\(')
_SIGN = re.compile(r'\bsra\s+\$\w+\s*,\s*\$\w+\s*,\s*(?:0x10|16)\b|\bseh\b|\bseb\b')


def _stores(asm):
    """{(mnemonic, offset)} of the narrow stores the target has."""
    return {(match[1], int(match[2], 0)) for match in _ASM.finditer(asm or '')}


def _statement_end(clean, start):
    depth = 0
    for index in range(start, len(clean)):
        char = clean[index]
        depth += (char in '([{') - (char in ')]}')
        if char == ';' and depth == 0:
            return index
        if depth < 0:
            return None
    return None


def _holds(part, stores, asm):
    if _SIGN.search(asm or ''):
        return []
    out = []
    for hit in _HOLD.finditer(part.clean, part.opening, part.end):
        if (_CAST[hit['n']][0], int(hit['offset'], 0)) not in stores:
            continue
        text = (f"{hit['v']} = (s32) {hit['e']};\n"
                f"*(({hit['n']} *) (((char *) {hit['base']}) + {hit['offset']})) = {hit['v']};")
        out.append((hit.start(), hit.end(), text))
    return out


def variants(source, name, asm=''):
    part = view(source, name)
    stores = _stores(asm)
    if not part or not stores:
        return []
    sites = []
    for hit in _STORE.finditer(part.clean, part.opening, part.end):
        mnemonic, narrow = _CAST[hit['narrow']]
        if (mnemonic, int(hit['offset'], 0)) not in stores:
            continue
        if _statement_end(part.clean, hit.end()) is None:
            continue
        # the pointer type, and the cast it makes redundant
        sites.append([(hit.start('wide'), hit.end('wide'), narrow), (hit.start('narrow') - 1, hit.end(), '')])
        if len(sites) >= LIMIT:
            break
    out = [(FAMILY, edit(source, one)) for one in sites]
    if len(sites) > 1:
        out.append((FAMILY, edit(source, [item for one in sites for item in one])))
    holds = _holds(part, stores, asm)
    out += [(FAMILY_HOLD, edit(source, [one])) for one in holds[:LIMIT]]
    if holds:
        out.append((FAMILY_HOLD, edit(source, holds[:LIMIT] + [item for one in sites for item in one])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 250,
          'archs': ('mips',)}
