"""Byte steps m2c wrote on typed pointers, which C scales a second time.

m2c sometimes keeps a pointer typed (`void **p`, `s32 *p`, `M2C_UNK *p`) but writes its step or offset in bytes:
`p += 4;` advances 16 bytes, `p + 0x50` reaches 0x140. The target's own immediate says which it meant: two N64 loops
stepped 4 bytes where the draft stepped 0x10 (exact as `p += 1;`), and a function passed `p + 0x50` bytes where the
draft passed 0x140 (exact as `(s8 *) p + 0x50`). Offered only when the target has the byte value as an immediate and
not the scaled one; and an index into a symbol of a 4-byte type, `*((i * 4) + &D)`, as `(&D)[i]`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'pointer_byte_step'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
SIZES = {'s32': 4, 'u32': 4, 'f32': 4, 'M2C_UNK': 4, 'M2C_UNK32': 4, 'int': 4, 'void *': 4, 's16': 2, 'u16': 2,
         'M2C_UNK16': 2, 'f64': 8, 's64': 8, 'u64': 8}


def immediates(asm):
    return {int(m[1], 0) for m in re.finditer(r'\b(?:addiu|daddiu|addi)\s+\$\w+\s*,\s*\$\w+\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))\s*$',
                                              asm or '', re.M)}


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    found = immediates(asm)
    pointers = {}
    for m in re.finditer(r'(?m)^[ \t]*(?:const\s+)?(?P<type>[A-Za-z_]\w*)\s*(?P<stars>\*+)\s*(?P<name>' + IDENT + r')\s*;', body):
        pointee = m['type'] + (' *' * (len(m['stars']) - 1))
        if pointee in SIZES:
            pointers[m['name']] = SIZES[pointee]
    result = []
    for local, size in pointers.items():
        for step in re.finditer(r'\b' + local + r'\s*(?P<op>[-+])=\s*(?P<n>0x[0-9a-fA-F]+|\d+)\s*;', body):
            n = int(step['n'], 0)
            if n % size or n == 0 or n not in found or n * size in found:
                continue
            at = opening + step.start('n')
            result.append((FAMILY, source[:at] + str(n // size) + source[opening + step.end('n'):]))
        for use in re.finditer(r'(?<![\w.>)])\b' + local + r'\s*\+\s*(?P<n>0x[0-9a-fA-F]+|\d+)\b', body):
            n = int(use['n'], 0)
            if n not in found or n * size in found:
                continue
            at = opening + use.start()
            result.append((FAMILY, source[:at] + '(s8 *) ' + source[at:]))
    # `*((i * 4) + &D)` on a symbol of a 4-byte type scales the index again: an N64 function stored at `i * 16`
    # where the game stored at `i * 4`, exact as `(&D)[i]`
    outside = clean[:span[0]] + clean[span[1]:]
    for use in re.finditer(r'\*\s*\(\s*\(\s*(?P<i>' + IDENT + r')\s*\*\s*(?P<k>0x[0-9a-fA-F]+|\d+)\s*\)\s*\+\s*&\s*(?P<d>'
                           + IDENT + r')\s*\)', body):
        declared = re.search(r'(?m)^[ \t]*extern\s+(?P<t>[A-Za-z_]\w*)\s+' + use['d'] + r'\s*;', outside)
        size = SIZES.get(declared['t']) if declared else None
        k = int(use['k'], 0)
        if not size or k % size:
            continue
        index = use['i'] if k == size else f"{use['i']} * {k // size}"
        result.append((FAMILY, source[:opening + use.start()] + f"(&{use['d']})[{index}]" + source[opening + use.end():]))
    return result[:4]
