"""Reuse a computed XOR in a branch-local equality test."""
import re

from .csource import _blank, find

FAMILY = 'guard_xor_reuse'
ID = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][\da-fA-F]+|[1-9]\d*|0)'
PATTERN = re.compile(
    rf'\b(?P<diff>{ID})\s*=\s*(?P<key>{ID})\s*\^\s*(?P<mask>{NUM})\s*;\s*'
    rf'if\s*\(\s*(?P=key)\s*==\s*{NUM}\s*\)\s*{{\s*'
    rf'{ID}\s*=\s*(?P<test>(?P=key)\s*!=\s*(?P<compare>{NUM}))\s*;'
)


def variants(source, name, arch, asm, header=''):
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    asm = re.sub(r'/\*[^\n]*?\*/', '', asm)
    macros = set(re.findall(rf'(?m)^\s*#\s*define\s+({ID})\b', source+'\n'+header))
    for hit in PATTERN.finditer(clean, *span):
        mask = int(hit['mask'], 0)
        if not 0 < mask <= 0xffff or mask != int(hit['compare'], 0):
            continue
        diff, key = hit['diff'], hit['key']
        if diff == key or {diff, key} & macros:
            continue
        prefix = clean[span[0]:hit.start()]
        kind = r'(?:s32|u32|int|unsigned(?:\s+int)?)'
        if any(not re.search(rf'(?m)^\s*{kind}\s+{v}\s*;', prefix) for v in (diff, key)):
            continue
        evidence = (rf'\bxori\s+(\$\w+),\s*\$\w+,\s*(?:{mask}|0[xX]0*{mask:x})\s*\n'
                    rf'(?:[^\n]*\n){{0,8}}?\s*sltu\s+\$\w+,\s*\$zero,\s*\1\b')
        if re.search(evidence, asm, re.I):
            a, b = hit.span('test')
            return [(FAMILY, source[:a]+f'{diff} != 0'+source[b:])]
    return []
