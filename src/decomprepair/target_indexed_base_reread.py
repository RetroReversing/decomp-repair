"""Restore a target-observed indexed table reread after intervening calls.

An event handler draft kept an indexed channel-table address across callbacks.
The target reloaded the table pointer and recomputed the address before reading
its byte and float fields. Replacing the stale alias with a fresh read changed
one KMC MIPS score from 3775 to 3280. This changes the draft's behavior if a
callback changes the table; the target's post-call loads provide the evidence.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'target_indexed_base_reread'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def _sites(asm):
    lines = [re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', line).strip()) for line in (asm or '').splitlines()]
    sites = set()
    for i, text in enumerate(lines):
        load = re.fullmatch(r'(?i:lw) (\$\w+),\s*(' + NUM + r')\(\$\w+\)', text)
        if not load or not any(re.match(r'(?i:jalr?)\s', row) for row in lines[max(0, i - 16):i]):
            continue
        for j, row in enumerate(lines[i + 1:i + 4], i + 1):
            shift = re.fullmatch(r'(?i:sll) (\$\w+),\s*\$\w+,\s*4', row)
            if not shift:
                continue
            for k, addrow in enumerate(lines[j + 1:j + 4], j + 1):
                addr = re.fullmatch(r'(?i:addu) (\$\w+),\s*' + re.escape(shift[1]) + r',\s*' + re.escape(load[1]), addrow)
                if not addr:
                    continue
                reg = re.escape(addr[1])
                tail = lines[k + 1:k + 9]
                floats = [m for row in tail if (m := re.fullmatch(r'(?i:lwc1) \$\w+,\s*(' + NUM + r')\(' + reg + r'\)', row))]
                bytes_ = [m for row in tail if (m := re.fullmatch(r'(?i:lbu) \$\w+,\s*(' + NUM + r')\(' + reg + r'\)', row))]
                sites.update((int(load[2], 0), int(b[1], 0), int(f[1], 0)) for b in bytes_ for f in floats)
    return sites


def variants(source, name, asm):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(asm)
    if not sites:
        return []
    setup = re.compile(
        r'(?P<old>' + IDENT + r')\s*=\s*\(u8\s*\*\)\s*(?P<root>' + IDENT + r')\s*\+\s*(?P<field>' + NUM + r')\s*;\s*'
        r'(?P=old)\s*=\s*\*\(u8\s*\*\s*\*\s*\)\s*(?P=old)\s*\+\s*(?P<index>' + IDENT + r')\s*\*\s*(?:0x10|16)\s*;')
    result = []
    for m in setup.finditer(part.clean, part.opening + 1, part.end):
        old = re.escape(m['old'])
        tail = re.compile(
            r'(?P<new>' + IDENT + r')\s*=\s*(?P<alias>' + old + r')\s*;\s*'
            r'' + IDENT + r'\s*=\s*\(u8\)\s*\(\s*\(\s*\(u8\s*\*\)\s*(?P<bytebase>' + old + r')\s*\)\s*\[\s*(?P<byte>' + NUM + r')\s*\]\s*\)\s*;\s*'
            r'[^;]*M2C_FIELD\s*\(\s*(?P=new)\s*,\s*f32\s*\*\s*,\s*(?P<float>' + NUM + r')\s*\)')
        for end in tail.finditer(part.clean, m.end(), part.end):
            if (int(m['field'], 0), int(end['byte'], 0), int(end['float'], 0)) not in sites:
                continue
            middle = part.clean[m.end():end.start()]
            if not re.search(r'\b(?:M2C_FIELD\s*\([^;]+\)|' + IDENT + r')\s*\(', middle):
                continue
            if re.search(r'\b(?:' + re.escape(m['root']) + '|' + re.escape(m['index']) + r')\s*(?:\+\+|--|[+\-*/]?=(?!=))', middle):
                continue
            reread = f'*(u8 **)((u8 *) {m["root"]} + {m["field"]}) + {m["index"]} * 0x10'
            result.append((FAMILY, edit(source, [(end.start('bytebase'), end.end('bytebase'), end['new']),
                                                  (end.start('alias'), end.end('alias'), reread)])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',), 'order': 40}
