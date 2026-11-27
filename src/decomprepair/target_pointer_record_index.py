"""Use a 16-byte indexed record for a target-observed pointer field.

A MIPS draft computes a byte address using a 16-byte stride, then reads its
first word as a pointer. The target contains the same base load, shift, add
and pointer load. Spelling that as an indexed one-pointer record changed a
KMC candidate from 235 to 225. The record padding only represents the proven
stride; it does not claim the identities of the remaining fields.
"""
import re

from .csource import find
from .integer_repair_support import IDENT, edit, view

FAMILY = 'target_pointer_record_index'
FAMILIES = (FAMILY,)
NUM = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def _witness(asm, offset):
    rows = [re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', x).strip()) for x in (asm or '').splitlines()]
    for i, row in enumerate(rows):
        base = re.fullmatch(r'(?i:lw) (\$\w+),\s*(' + NUM + r')\(\$\w+\)', row)
        if not base or int(base[2], 0) != offset:
            continue
        for j, text in enumerate(rows[i + 1:i + 6], i + 1):
            idx = re.fullmatch(r'(?i:sll) (\$\w+),\s*\$\w+,\s*(?:4|0x4)', text)
            if not idx:
                continue
            for k, text in enumerate(rows[j + 1:j + 4], j + 1):
                add = re.fullmatch(r'(?i:addu) (\$\w+),\s*' + re.escape(idx[1]) + r',\s*' + re.escape(base[1]), text)
                if add and any(re.fullmatch(r'(?i:lw) \$\w+,\s*(?:0|0x0)\(' + re.escape(add[1]) + r'\)', x) for x in rows[k + 1:k + 4]):
                    return True
    return False


def variants(source, name, asm, flags=(), header=''):
    part = view(source, name)
    if not part or '-mgp32' not in flags or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    context = source + '\n' + (header or '')
    if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:u8|s8)\b|\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:u8|s8)\s*;', context):
        return []
    pattern = re.compile(
        r'(?m)^(?P<indent>[ \t]*)(?P<addr>' + IDENT + r')\s*=\s*\(u8\s*\*\)\s*(?P<root>' + IDENT + r')\s*\+\s*(?P<offset>' + NUM + r')\s*;\s*'
        r'(?P=addr)\s*=\s*\*\(u8\s*\*\s*\*\s*\)\s*(?P=addr)\s*\+\s*(?P<index>' + IDENT + r')\s*\*\s*(?:0x10|16)\s*;\s*'
        r'(?P<out>' + IDENT + r')\s*=\s*\*\(u8\s*\*\s*\*\s*\)\s*(?P=addr)\s*;')
    result = []
    for match in pattern.finditer(part.clean, part.opening + 1, part.end):
        address = match['addr']
        decl = re.search(r'(?m)^[ \t]*void\s*\*\s*' + re.escape(address) + r'\s*;[ \t]*\n', part.clean[part.opening:match.start()])
        if not decl or not _witness(asm, int(match['offset'], 0)):
            continue
        declaration_start = part.opening + decl.start()
        declaration_end = part.opening + decl.end()
        mentions = list(re.finditer(r'\b' + re.escape(address) + r'\b', part.clean[part.opening:part.end]))
        if len(mentions) != 5 or re.search(r'&\s*' + re.escape(address) + r'\b', part.clean[part.opening:part.end]):
            continue
        typename = 'IndexedPointerRecord'
        while re.search(r'\b' + typename + r'\b', context):
            typename += '_'
        struct = f'typedef struct {{ u8 *pointer; u8 reserved[12]; }} {typename};\n'
        expr = (f'{match["indent"]}{match["out"]} = (({typename} *) *(u8 **)((u8 *) {match["root"]} + '
                f'{match["offset"]}))[{match["index"]}].pointer;')
        func_start = find(source, name)[0]
        result.append((FAMILY, edit(source, [(func_start, func_start, struct),
                                              (declaration_start, declaration_end, ''),
                                              (match.start(), match.end(), expr)])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'flags', 'header'), 'archs': ('mips',), 'order': 40}
