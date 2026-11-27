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


def edits(source, name, asm):
    """Every byte-step site as (start, end, replacement) on `source`, in the order `variants` offers them."""
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
    # (a pointer parameter too: `func(arg1, arg0 + 4)` with `s32 *arg0` passed 0x10 bytes where the game passed 4,
    # exact as `(s8 *) arg0 + 4`)
    signature = re.search(r'\b' + re.escape(name) + r'\s*\(([^)]*)\)\s*{', clean[span[0]:span[1]])
    for m in re.finditer(r'(?:^|,)\s*(?:const\s+)?(?P<type>[A-Za-z_]\w*)\s*(?P<stars>\*+)\s*(?P<name>' + IDENT + r')\s*(?=,|$)',
                         signature[1] if signature else ''):
        pointee = m['type'] + (' *' * (len(m['stars']) - 1))
        if pointee in SIZES and m['name'] not in pointers:
            pointers[m['name']] = SIZES[pointee]
    # (a global pointer the function steps, `extern u16 *D;` ... `D += 0xC;`: an N64 list walk stepped 0xC bytes where
    # the draft stepped 0x18; exact as `D += 6;`)
    outside = clean[:span[0]] + clean[span[1]:]
    for m in re.finditer(r'(?m)^[ \t]*extern\s+(?:const\s+)?(?P<type>[A-Za-z_]\w*)\s*(?P<stars>\*+)\s*(?P<name>' + IDENT
                         + r')\s*;', outside):
        pointee = m['type'] + (' *' * (len(m['stars']) - 1))
        if pointee in SIZES and m['name'] not in pointers:
            pointers[m['name']] = SIZES[pointee]
    result = []
    for local, size in pointers.items():
        for step in re.finditer(r'\b' + local + r'\s*(?P<op>[-+])=\s*(?P<n>0x[0-9a-fA-F]+|\d+)\s*;', body):
            n = int(step['n'], 0)
            if n % size or n == 0 or n not in found or n * size in found:
                continue
            result.append((opening + step.start('n'), opening + step.end('n'), str(n // size)))
        for use in re.finditer(r'(?<![\w.>)])\b' + local + r'\s*\+\s*(?P<n>0x[0-9a-fA-F]+|\d+)\b', body):
            n = int(use['n'], 0)
            if n not in found or n * size in found:
                continue
            at = opening + use.start()
            result.append((at, at, '(s8 *) '))
    # `*((i * 4) + &D)` on a symbol of a 4-byte type scales the index again: an N64 function stored at `i * 16`
    # where the game stored at `i * 4`, exact as `(&D)[i]`. The index may be any one operand: a name, a call, or a
    # parenthesised expression (`*((((Rec *) arg0)->type * 4) + &D)`, an m2c field view of a parameter's halfword)
    for use in re.finditer(r'\*\s*\(', body):
        before = body[:use.start()].rstrip()[-1:]
        if before.isalnum() or before in ('_', ')', ']'):  # a multiplication, not a load or store through the sum
            continue
        opened = use.end() - 1
        closed = close(body, opened, '(', ')')
        if not closed:
            continue
        start = opened + 1
        term = re.fullmatch(r'\s*\((?P<i>.+?)\s*\*\s*(?P<k>0x[0-9a-fA-F]+|\d+)\s*\)\s*\+\s*&\s*(?P<d>' + IDENT + r')\s*',
                            body[start:closed - 1], re.S)
        if not term or not _operand(term['i']):
            continue
        declared = re.search(r'(?m)^[ \t]*extern\s+(?P<t>[A-Za-z_]\w*)\s+' + term['d'] + r'\s*;', outside)
        size = SIZES.get(declared['t']) if declared else None
        k = int(term['k'], 0)
        if not size or k % size:
            continue
        original = source[opening + start + term.start('i'):opening + start + term.end('i')]
        index = original if k == size else f"{original} * {k // size}"
        result.append((opening + use.start(), opening + closed, f"(&{term['d']})[{index}]"))
    return result


def _operand(text):
    """Whether `text` is one operand of `*`: a name, a call of a name, or wholly parenthesised."""
    named = re.match(IDENT, text)
    at = named.end() if named else 0
    if named and at == len(text):
        return True
    return text[at:at + 1] == '(' and close(text, at, '(', ')') == len(text)


def variants(source, name, asm):
    """One child per site, at most six."""
    return [(FAMILY, source[:start] + text + source[end:]) for start, end, text in edits(source, name, asm)[:6]]
