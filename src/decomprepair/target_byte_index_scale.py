"""Correct a draft's doubled index scale when the target proves byte indexing.

A draft used a halfword pointer as the base for an already byte-scaled index.
The target instead loaded the same base field, read its halfword count, and
used a 4-byte-scaled index for a word at offset 12. Casting the base to u8 *
changed the intended address and improved one KMC MIPS candidate 3925 to 3775.
This is a target-evidenced draft correction, not an equivalent C rewrite.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'target_byte_index_scale'
FAMILIES = (FAMILY,)
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'
IDENT = r'[A-Za-z_]\w*'


def _sites(asm):
    lines = [re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', line).strip()) for line in (asm or '').splitlines()]
    sites = set()
    for i, line in enumerate(lines):
        load = re.fullmatch(r'(?i:lw) (\$\w+),\s*(' + NUM + r')\((\$\w+)\)', line)
        if not load:
            continue
        base, field = load[1], int(load[2], 0)
        tail = lines[i + 1:i + 12]
        for n, row in enumerate(tail):
            shift = re.fullmatch(r'(?i:sll) (\$\w+),\s*(\$\w+),\s*(?:0x2|2)', row)
            if not shift or n + 2 >= len(tail):
                continue
            prefix = tail[:n]
            proof = False
            for j, text in enumerate(prefix):
                half = re.fullmatch(r'(?i:lh) (\$\w+),\s*(?:0x0|0)\(' + re.escape(base) + r'\)', text)
                if not half:
                    continue
                for k in range(j + 1, len(prefix)):
                    compare = re.fullmatch(r'(?i:slt) (\$\w+),\s*' + re.escape(shift[2]) + r',\s*' + re.escape(half[1]), prefix[k])
                    if compare and any(re.match(r'(?i:beqz) ' + re.escape(compare[1]) + r'\s*,', item) for item in prefix[k + 1:]):
                        proof = True
            if not proof:
                continue
            reg = re.escape(shift[1])
            if not re.fullmatch(r'(?i:addu) ' + reg + r',\s*' + reg + r',\s*' + re.escape(base), tail[n + 1]):
                continue
            word = re.fullmatch(r'(?i:lw) \$\w+,\s*(' + NUM + r')\(' + reg + r'\)', tail[n + 2])
            if word:
                sites.add((field, int(word[1], 0)))
    return sites


def variants(source, name, asm):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(asm)
    if not sites:
        return []
    # The destination is a word, while the base expression is explicitly a
    # halfword pointer. An already scaled byte offset must not be scaled again.
    pattern = re.compile(
        r'M2C_FIELD\s*\(\s*\(\s*\(\s*' + IDENT + r'\s*\*\s*(?:4|0x4)\s*\)\s*\+\s*'
        r'(?P<base>M2C_FIELD\s*\(\s*' + IDENT + r'\s*,\s*s16\s*\*\s*\*\s*,\s*(?P<field>' + NUM + r')\s*\))'
        r'\s*\)\s*,\s*s32\s*\*\s*,\s*(?P<offset>' + NUM + r')\s*\)')
    result = []
    for match in pattern.finditer(part.clean, part.opening + 1, part.end):
        if (int(match['field'], 0), int(match['offset'], 0)) not in sites:
            continue
        result.append((FAMILY, edit(source, [(match.start('base'), match.start('base'), '(u8 *) ')])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',), 'order': 40}
