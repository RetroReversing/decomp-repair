"""A low-bits mask of an unsigned value, written as the remainder by a power of two, and the other way round.

    s = (c & 0xF) * w;      <->      s = (c % 16) * w;

For an unsigned (or zero-extended `u8` / `u16`) value both give the same bits, but KMC GCC 2.7.2 `-O1` masks a `u16`
parameter in its own register for the remainder (`andi $a3, $a3, 0xffff; srl $v0, $a3, 4; ...; andi $a3, $a3, 0xf`)
and through a fresh one for the mask: a 315-instruction N64 text-glyph builder went 10 -> 0 on this alone, and no
other family offered it.

Children (`unsigned_mask_modulo`): each `v & (2^k - 1)` or `v % 2^k` where every declaration of `v` in the function
is `u8`, `u16`, `u32` or `unsigned`, one site per child.
"""
import re

from .csource import _blank, find

FAMILY = 'unsigned_mask_modulo'
FAMILIES = (FAMILY,)
LIMIT = 12
UNSIGNED = r'(?:u8|u16|u32|unsigned(?:\s+(?:char|short|int|long))?)'
MASK = re.compile(r'(?<![\w.>*&])(?P<v>[A-Za-z_]\w*)\s*(?P<op>&(?!&)|%)\s*(?P<k>0[xX][0-9a-fA-F]+|\d+)(?![\w.])')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    head = clean.rfind('\n', 0, clean.rfind(name, 0, clean.find('{', span[0], span[1]))) + 1
    text = clean[head:span[1]]
    result = []
    for found in MASK.finditer(clean, head, span[1]):
        value, number = found['v'], int(found['k'], 0)
        modulus = number if found['op'] == '%' else number + 1
        if modulus < 2 or modulus > 0x10000 or modulus & (modulus - 1):
            continue
        # declared with a type word before the name: every such declaration is an unsigned one, not a pointer
        declared = re.findall(rf'([A-Za-z_]\w*)[ \t]+{value}\s*(?=[;,)=\[])', text)
        declared = [word for word in declared if word not in ('return', 'else', 'case', 'goto')]
        if not declared or not all(re.fullmatch(r'u8|u16|u32|unsigned|char|short|int|long', word) for word in declared):
            continue
        if not re.search(rf'\b{UNSIGNED}[ \t]+{value}\s*[;,)=]', text):
            continue
        # `a * v & 7` and `v & 7 + 1` group around other operands: leave them
        before = clean[:found.start()].rstrip()[-1:]
        after = clean[found.end():].lstrip()[:2]
        if before not in '(=,' or not (after[:1] in ');,]' or found['op'] == '&' and after[:1] == '|' != after[1:2]):
            continue
        replacement = f'{value} % {modulus}' if found['op'] == '&' else f'{value} & {hex(modulus - 1)}'
        if found['op'] == '&' and after[:1] == '|':
            replacement = f'({replacement})'
        result.append((FAMILY, source[:found.start()] + replacement + source[found.end():]))
        if len(result) >= LIMIT:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
