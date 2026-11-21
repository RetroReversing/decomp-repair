"""Recompute a bounded byte offset from its companion loop counter."""
import re

from .csource import _blank, find

FAMILY = 'counter_derived_loop_offset'
ID = r'[A-Za-z_]\w*'
NUM = r'(?:0[xX][\da-fA-F]+|[1-9]\d*|0)'
LOOP = re.compile(
    rf'\bdo\s*{{(?P<body>[^{{}}]*?)'
    rf'\b(?P<count>{ID})\s*\+=\s*1\s*;\s*'
    rf'(?P<step>(?P<offset>{ID})\s*\+=\s*(?P<stride>{NUM})\s*;)\s*'
    rf'}}\s*while\s*\(\s*(?P=count)\s*<\s*(?P<bound>{NUM})\s*\)\s*;'
)


def variants(source, name, arch, asm):
    if arch != 'mips' or not (span := find(source, name)):
        return []
    clean = _blank(source)
    target = re.sub(r'/\*[^\n]*?\*/', '', asm)
    for hit in LOOP.finditer(clean, *span):
        count, offset = hit['count'], hit['offset']
        stride, bound = (int(hit[key], 0) for key in ('stride', 'bound'))
        shifts = [n for n in range(stride.bit_length()-1, -1, -1) if stride & (1 << n)]
        if count == offset or len(shifts) != 2 or not 0 < stride * bound <= 0x7fffffff:
            continue
        prefix = clean[span[0]:hit.start()]
        setup = rf'\b{count}\s*=\s*0\s*;\s*(?:{ID}\s*=\s*{NUM}\s*;\s*)*{offset}\s*=\s*0\s*;\s*$'
        initialized = re.search(setup, prefix)
        if not initialized or not prefix[:initialized.start()].rstrip().endswith((';', '{', '}')):
            continue
        if len(re.findall(rf'\b{count}\b', initialized[0])) != 1:
            continue
        if any(not re.search(rf'[;{{}}]\s*(?:s32|u32)\s+{v}\s*;', prefix[:initialized.start()]) for v in (count, offset)):
            continue
        dirty = rf'(?:&|\+\+|--)\s*\b(?:{count}|{offset})\b|\b(?:{count}|{offset})\s*(?:\+\+|--|(?:[+*/%&|^-]|<<|>>)?=(?!=))'
        if re.search(dirty, hit['body']) or re.search(r'\b(?:goto|continue)\b', hit['body']):
            continue
        if re.search(rf'&\s*\b(?:{count}|{offset})\b', prefix):
            continue
        last_store = re.search(rf'\b({ID})\s*\+\s*{offset}\s*\)\s*=\s*[^;]+;\s*$', hit['body'])
        if not last_store:
            continue
        evidence = (rf'\b(?:sw|sh|sb)\s+\$\w+,\s*%lo\({last_store[1]}\)\(\$\w+\)\s*\n'
                    rf'\s*addiu\s+(\$\w+),\s*\1,\s*(?:1|0[xX]1)\s*\n'
                    rf'\s*sltiu?\s+(\$\w+),\s*\1,\s*(?:{bound}|0[xX]{bound:x})\s*\n'
                    rf'\s*bnez\s+\2,\s*[^\n]+\n'
                    rf'\s*addiu\s+(\$\w+),\s*\3,\s*(?:{stride}|0[xX]{stride:x})\b')
        if not re.search(evidence, target, re.I):
            continue
        a, b = hit.span('step')
        value = ' + '.join(f'({count} << {shift})' if shift else count for shift in shifts)
        return [(FAMILY, source[:a]+f'{offset} = {value};'+source[b:])]
    return []
