"""Measure an inline multiply for three adjacent components with the same scale."""
import re

from .csource import _blank, find

FAMILY = 'inline_float_vector_scale'
ID = r'[A-Za-z_]\w*'
FLOAT = r'(?:f32|float)'
LITERAL = r'(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?[fF]'
GROUP = re.compile(
    rf'\b(?P<type>{FLOAT})\s+(?P<x>{ID})\s*=\s*(?P<first>(?P<array>{ID})\[\s*0\s*\]\s*\*\s*(?P<scale>{LITERAL}))\s*;\s*'
    rf'(?P=type)\s+(?P<y>{ID})\s*=\s*(?P<second>(?P=array)\[\s*1\s*\]\s*\*\s*(?P=scale))\s*;\s*'
    rf'(?P=type)\s+(?P<z>{ID})\s*=\s*(?P<third>(?P=array)\[\s*2\s*\]\s*\*\s*(?P=scale))\s*;'
)
LOAD = re.compile(r'\blwc1\s+(\$\w+),\s*(0x[\da-fA-F]+|\d+)?\((\$\w+)\)')
MUL = re.compile(r'\bmul\.s\s+(\$\w+),\s*(\$\w+),\s*(\$\w+)')


def _target_has_vector_scale(asm):
    lines = re.sub(r'/\*[^\n]*?\*/', '', asm).splitlines()
    for start, line in enumerate(lines):
        load = LOAD.search(line)
        if not load or int(load[2] or '0', 0):
            continue
        offsets = {}
        for end in range(start, min(start + 18, len(lines))):
            read = LOAD.search(lines[end])
            if read and read[3] == load[3]:
                offsets[int(read[2] or '0', 0)] = read[1]
            if len(offsets) >= 3:
                break
        if not {0, 4, 8} <= offsets.keys() or len({offsets[k] for k in (0, 4, 8)}) != 3:
            continue
        products = [m.groups() for line in lines[start:end+4] if (m := MUL.search(line))]
        scales = [{rhs if lhs == offsets[k] else lhs for _, lhs, rhs in products if offsets[k] in (lhs, rhs)}
                  for k in (0, 4, 8)]
        if set.intersection(*scales):
            return True
    return False


def variants(source, name, arch, asm, header=''):
    if arch != 'mips' or not (span := find(source, name)) or not _target_has_vector_scale(asm):
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    for group in GROUP.finditer(clean, opening, span[1]):
        kind, array = group['type'], group['array']
        if not re.search(rf'\b{kind}\s*\*\s*{array}\b', clean[span[0]:opening]):
            continue
        used = set(re.findall(ID, clean+'\n'+header))
        helper = '__repair_float_mul'
        while helper in used:
            helper += '_'
        result = source
        for key in ('third', 'second', 'first'):
            a, b = group.span(key)
            left, _, right = source[a:b].partition('*')
            result = result[:a]+f'{helper}({left.strip()}, {right.strip()})'+result[b:]
        declaration = f'inline static float {helper}({kind} lhs, {kind} rhs) {{ return lhs * rhs; }}\n\n'
        return [(FAMILY, result[:span[0]]+declaration+result[span[0]:])]
    return []
