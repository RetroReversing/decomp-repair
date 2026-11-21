"""Keep a selected allocation size wide after the target's untruncated shift."""
import re

from .csource import _blank, find

FAMILY = 'widen_scaled_local'
ID = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|[1-9][0-9]*)'
SELECT = re.compile(
    rf'\b(?P<name>{ID})\s*=\s*(?P<low>{NUMBER})\s*;\s*'
    rf'if\s*\(\s*{ID}\s*!=\s*0\s*\)\s*{{\s*(?P=name)\s*=\s*(?P<high>{NUMBER})\s*;\s*}}\s*'
    rf'(?P<scale>(?P=name))\s*\*=\s*(?P<factor>{NUMBER})\s*;'
)


def variants(source, name, arch, asm, header=''):
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    for hit in SELECT.finditer(clean, *span):
        factor, low, high = (int(hit[k], 0) for k in ('factor', 'low', 'high'))
        if factor < 2 or factor & (factor - 1) or max(low, high) > 32767:
            continue
        if not 32768 <= max(low, high) * factor <= 0x7fffffff:
            continue
        shift = factor.bit_length() - 1
        evidence = rf'\baddiu\s+(\$\w+),\s*\$zero,\s*(?:{high}|0[xX]0*{high:x})\s*\n(?:\s*\.\w+:\s*\n)?\s*sll\s+\1,\s*\1,\s*(?:{shift}|0[xX]0*{shift:x})\b'
        if not re.search(evidence, re.sub(r'/\*[^\n]*?\*/', '', asm), re.I):
            continue
        value = hit['name']
        decl = re.search(rf'\b(?P<type>short|s16)\s+{value}\s*;', clean[span[0]:hit.start()])
        if not decl or re.search(rf'\b{value}\b', clean[span[0]+decl.end():hit.start()]):
            continue
        tail = clean[hit.end():span[1]]
        reads = list(re.finditer(rf'\b{value}\b', tail))
        if not reads or re.search(rf'&\s*{value}\b|\b{value}\s*(?:[+*/-]?=(?!=)|\+\+|--)', tail):
            continue
        used = set(re.findall(ID, clean+'\n'+header))
        scaled = '__repair_scaled_size'
        while scaled in used:
            scaled += '_'
        tail_source = source[hit.end():span[1]]
        for read in reversed(reads):
            tail_source = tail_source[:read.start()] + scaled + tail_source[read.end():]
        decl_end = span[0]+decl.end()
        decl_start = span[0]+decl.start('type')
        decl_type_end = span[0]+decl.end('type')
        indent = re.match(r'[^\S\n]*', source[source.rfind('\n', 0, decl_start)+1:]).group()
        child = (source[:decl_start]+'s32'+source[decl_type_end:decl_end]+f'\n{indent}s32 {scaled};'
                 +source[decl_end:hit.start('scale')]+f'{scaled} = {value} * {hit["factor"]};'
                 +tail_source+source[span[1]:])
        return [(FAMILY, child)]
    return []
