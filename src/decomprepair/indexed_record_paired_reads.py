"""Offer direct indexed field reads when the target shares their address.

On one KMC function a byte-address temporary for a 16-byte record produced a
less favorable address register than spelling both reads as indexed fields.
The reason for GCC's register choice is a hypothesis, not compiler-source proof.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'indexed_record_paired_reads'


def variants(source, name, asm, flags=()):
    part = view(source, name)
    if not part or '-mgp32' not in flags or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    # Require the target to load both fields through the same computed address.
    rows = [re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', row).strip()) for row in (asm or '').splitlines()]
    witnessed = False
    for i, row in enumerate(rows):
        found = re.search(r'\blwc1\s+\$\w+,\s*(?:0xc|12)\((\$\w+)\)', row, re.I)
        if found and any(re.search(r'\blbu\s+\$\w+,\s*(?:0xa|10)\(' + re.escape(found[1]) + r'\)', x, re.I) for x in rows[i + 1:i + 8]):
            witnessed = True
            break
    if not witnessed:
        return []
    pattern = re.compile(
        r'(?m)^(?P<indent>[ \t]*)(?P<addr>' + IDENT + r')\s*=\s*\*\(u8\s*\*\*?\)\s*\(\(u8\s*\*\)\s*(?P<root>' + IDENT + r')\s*\+\s*(?P<offset>0x[0-9a-fA-F]+|\d+)\)\s*\+\s*(?P<index>' + IDENT + r')\s*\*\s*(?:0x10|16)\s*;\s*'
        r'(?P<byte>' + IDENT + r')\s*=\s*\(u8\)\s*\(\(\(u8\s*\*\)\s*(?P=addr)\)\[(?:0x[Aa]|10)\]\)\s*;\s*'
        r'(?P<float>' + IDENT + r')\s*=\s*(?P<before>[^;]*?)M2C_FIELD\(\s*(?P=addr)\s*,\s*f32\s*\*\s*,\s*(?:0x[Cc]|12)\s*\)(?P<after>[^;]*);')
    result = []
    for match in pattern.finditer(part.clean, part.opening + 1, part.end):
        address = match['addr']
        if len(re.findall(r'\b' + re.escape(address) + r'\b', part.clean[part.opening:part.end])) != 4:
            continue
        # No calls or writes between repeated root reads; the arithmetic must be pure.
        if (re.search(r'\b(?:volatile|sizeof)\b|\+\+|--|(?<![=!<>])=(?!=)', match['before'] + match['after'])
                or any(call != 'M2C_FIELD' for call in re.findall(r'\b([A-Za-z_]\w*)\s*\(', match['before'] + match['after']))):
            continue
        typename = '__repair_indexed_pair'
        while re.search(r'\b' + typename + r'\b', source):
            typename += '_'
        record = f'(({typename} *) *(u8 **)((u8 *) {match["root"]} + {match["offset"]}))[{match["index"]}]'
        layout = f'typedef struct {{ u8 pad[10]; u8 byte; u8 pad2; f32 real; }} {typename};\n'
        replacement = (f'{match["indent"]}{match["byte"]} = {record}.byte;\n'
                       f'{match["indent"]}{match["float"]} = {match["before"]}{record}.real{match["after"]};')
        start = find(source, name)[0]
        result.append((FAMILY, edit(source, [(start, start, layout), (match.start(), match.end(), replacement)])))
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'asm', 'flags'), 'archs': ('mips',), 'order': 41}
