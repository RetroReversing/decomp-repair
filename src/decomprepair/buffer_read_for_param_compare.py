"""A compare against a parameter where the target loads a value from the function's own local buffer.

A callee fills a local buffer (`char sp10[0x28]; f(arg0 + 0x10, sp10);`) and the game then tests a field the callee
wrote: `lh $v1, 0x36($sp)` and a compare with 1. m2c cannot see through the call, so the draft compares something it
does know, the parameter (`(unsigned char) arg0 == 1`), and scores one row off. When the target loads from a stack
offset inside the buffer's extent that the source never reads, and the source compares a parameter (with or without a
narrowing cast) against a constant, the compare reads the buffer there instead: `*(s16 *)(sp10 + 0x26) == 1`.

The buffer's frame offset is the one its address is taken at in the target (`addiu $a1, $sp, 0x10`, the number in the
name `sp10`), so the buffer offset is the load's frame offset minus it. One child per (compare, load) pair.
"""
import re

from .csource import _blank
from .field_width_repairs import IDENT, OPS

FAMILY = 'buffer_read_for_param_compare'
FAMILIES = (FAMILY,)
LIMIT = 12
LOAD = re.compile(r'\b(lbu|lb|lhu|lh|lw)\s+\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\s*\$sp\s*\)')
ELEMENT = {'char': 1, 'u8': 1, 's8': 1, 'unsigned char': 1, 'signed char': 1, 's16': 2, 'u16': 2, 's32': 4, 'u32': 4,
           'int': 4}
BUFFER = re.compile(rf'\b(?P<type>unsigned char|signed char|{IDENT})\s+(?P<name>{IDENT})\s*\[\s*(?P<size>0[xX][0-9a-fA-F]+|\d+)\s*\]\s*;')
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'


def variants(source, name, asm):
    if not asm:
        return []
    clean = _blank(source)
    head = re.search(rf'\b{re.escape(name)}\s*\(([^)]*)\)\s*{{', clean)
    if not head:
        return []
    params = set(re.findall(rf'({IDENT})\s*(?:,|$)', head[1].strip()))
    opening = head.end() - 1
    depth, end = 0, None
    for i in range(opening, len(clean)):
        depth += clean[i] == '{'
        depth -= clean[i] == '}'
        if depth == 0:
            end = i
            break
    if end is None or re.search(r'\b(?:asm|__asm__|goto|volatile)\b', clean[opening:end]):
        return []
    body = clean[opening:end]
    loads = [(op, int(off, 0)) for op, off in LOAD.findall(asm)]
    out = []
    for buf in BUFFER.finditer(body):
        size = int(buf['size'], 0) * ELEMENT.get(buf['type'], 0)
        label = re.fullmatch(r'sp([0-9A-Fa-f]+)', buf['name'])
        base = int(label[1], 16) if label else None
        if not size or base is None or not re.search(rf'addiu\s+\$\w+\s*,\s*\$sp\s*,\s*(?:0x)?{base:x}\b', asm, re.I):
            continue
        name_ = buf['name']
        for op, at in dict.fromkeys(loads):
            width = {'lbu': 1, 'lb': 1, 'lhu': 2, 'lh': 2, 'lw': 4}[op]
            if not base <= at < base + size or at + width > base + size or at % width:
                continue
            read = f'*({OPS[op]} *)({name_} + {hex(at - base)})'
            if read in clean or body.count(f'{name_}[') > 1:
                continue
            for site in re.finditer(rf'(?P<lhs>\(\s*(?:unsigned\s+|signed\s+)?(?:char|short|int|[su](?:8|16|32))\s*\)\s*)?'
                                    rf'(?P<param>(?<![\w.>])(?:{"|".join(map(re.escape, sorted(params)))})\b)\s*\)*\s*'
                                    rf'(?P<op>==|!=|<=|>=|<|>)\s*(?P<k>{NUMBER})\b', body):
                if not params:
                    break
                a = opening + site.start()
                b = opening + site.end('param')
                out.append((FAMILY, source[:a] + read + source[b:]))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 60}
