"""A read of an N64 boot variable (`extern u32 osMemSize;`) written as a read of its fixed address.

IPL3 leaves a few words at 0x80000300-0x80000318 (TV type, ROM type and base, reset type, CIC, version, memory size).
Through the symbol, SN64 GCC 2.8.1 builds the address in a register of its own (`lui $v0; lw $a3, 0x318($v0)`); as
`*(u32 *) 0x80000318` the assembler expands the load into the destination (`lui $a3; lw $a3, 0x318($a3)`). A memory
set-up routine matched with it: 410 -> 0 (sn-n64-281 -G0 -mips3 -O2). The names are libultra's and the `D_8000031x`
form; a symbol the function writes or takes the address of otherwise is left alone. The exact judge decides.
"""
import re

from .csource import _blank
from .integer_repair_support import edit, view

FAMILY = 'boot_variable_literal'
FAMILIES = (FAMILY,)
ADDRESSES = {'osTvType': 0x80000300, 'osRomType': 0x80000304, 'osRomBase': 0x80000308, 'osResetType': 0x8000030C,
             'osCicId': 0x80000310, 'osVersion': 0x80000314, 'osMemSize': 0x80000318}
ADDRESSES.update({f'D_{address:08X}': address for address in list(ADDRESSES.values())})
_TYPE = r'(?:[su](?:32|16|8)|unsigned\s+int|signed\s+int|int|unsigned\s+long|long)'


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    context = part.clean[:part.opening] + '\n' + _blank(header or '')
    body = part.clean[part.opening:part.end]
    rewrites = []
    for symbol, address in ADDRESSES.items():
        if not re.search(rf'\b{symbol}\b', body):
            continue
        declared = re.search(rf'\bextern\s+(?:volatile\s+)?(?P<type>{_TYPE})\s+{symbol}\s*;', context)
        word = ' '.join(declared['type'].split()) if declared else 'u32'
        edits, taken = [], []
        # `*(T *)&symbol`: the cast names the width and signedness of this read
        for hit in re.finditer(rf'\*\s*\(\s*(?P<type>(?:volatile\s+)?{_TYPE})\s*\*\s*\)\s*&\s*{symbol}\b', body):
            edits.append((hit.start(), hit.end(), f'*({hit["type"]} *) 0x{address:08X}'))
        for hit in re.finditer(rf'(?<![\w.>])\b{symbol}\b', body):
            if any(start <= hit.start() < end for start, end, _ in edits):
                continue
            before, after = body[:hit.start()].rstrip(), body[hit.end():].lstrip()
            address_of = before.endswith('&') and not before.endswith('&&')
            written = re.match(r'(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--|\[|\.|->', after) or before.endswith(('++', '--'))
            if address_of or written or not declared:
                taken.append(hit)
                break
            edits.append((hit.start(), hit.end(), f'(*({word} *) 0x{address:08X})'))
        if edits and not taken:
            rewrites.append([(part.opening + start, part.opening + end, text) for start, end, text in edits])
    out = [edit(source, changes) for changes in rewrites]
    if len(rewrites) > 1:
        out.insert(0, edit(source, [change for changes in rewrites for change in changes]))
    return [(FAMILY, text) for text in out]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
