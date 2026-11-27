"""Widen a masked byte and stage a separate linked-loop comparison copy.

In one KMC function these two source changes together changed score 210 to 10.
The target masks a byte, scales it, then later copies it for a loop. The reason
for the compiler's register choice remains a hypothesis.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'masked_loop_copy'


def _witness(asm):
    lines = [re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', row).strip()) for row in (asm or '').splitlines()]
    for i, row in enumerate(lines):
        mask = re.search(r'\bandi\s+(\$\w+),\s*\$\w+,\s*(?:0xff|255)\b', row, re.I)
        if not mask:
            continue
        tail = lines[i + 1:i + 65]
        scale = any(re.search(r'\bsll\s+\$\w+,\s*' + re.escape(mask[1]) + r',\s*(?:4|0x4)\b', x, re.I) for x in tail[:5])
        copy = any(re.search(r'\b(?:move|addu)\s+\$\w+,\s*' + re.escape(mask[1]) + r'\b', x, re.I) for x in tail)
        if scale and copy:
            return True
    return False


def variants(source, name, asm, flags=()):
    part = view(source, name)
    if not part or '-mgp32' not in flags or not _witness(asm):
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|goto|asm|__asm__)\b', body):
        return []
    decl = re.compile(r'(?m)^[ \t]*u8\s+(?P<phase>' + IDENT + r')\s*;')
    result = []
    for d in decl.finditer(body):
        phase = d['phase']
        pattern = re.compile(
            r'\b' + re.escape(phase) + r'\s*=\s*\(?\s*' + IDENT + r'\s*&\s*(?:0[xX][fF][fF]|255)\s*\)?\s*;'
            r'(?P<middle>.*?)'
            r'(?P<indent>^[ \t]*)(?P<cursor>' + IDENT + r')\s*=\s*M2C_FIELD\([^;]*\);\s*'
            r'while\s*\(\s*(?P=cursor)\s*!=\s*NULL\s*\)\s*\{\s*'
            r'if\s*\(\s*M2C_FIELD\([^;]*?\)\s*==\s*(?P<comparison>' + re.escape(phase) + r')\s*\)', re.M | re.S)
        match = pattern.search(body, d.end())
        if not match or len(re.findall(r'\b' + re.escape(phase) + r'\b', body)) != 4:
            continue
        if not re.search(r'\b' + re.escape(phase) + r'\s*\*\s*(?:0x10|16)\b', match['middle']):
            continue
        if re.search(r'\b' + re.escape(phase) + r'\s*(?:[+*/%&|^-]?=|\+\+|--)', match['middle']):
            continue
        holder = '__repair_masked_loop_copy'
        while re.search(r'\b' + holder + r'\b', source):
            holder += '_'
        base = part.opening
        decl_text = d[0].replace('u8', 'u32', 1) + f'\n    s32 {holder};'
        result.append((FAMILY, edit(source, [
            (base + d.start(), base + d.end(), decl_text),
            (base + match.start('indent'), base + match.start('indent'), f'{match["indent"]}{holder} = {phase};\n'),
            (base + match.start('comparison'), base + match.end('comparison'), holder),
        ])))
    return result


REPAIR = {'families': (FAMILY,), 'variants': variants, 'needs': ('source', 'name', 'asm', 'flags'), 'archs': ('mips',), 'order': 42}
