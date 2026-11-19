"""Constants the target's instructions use in place of the ones in borrowed C.

C adapted from a matched twin keeps the twin's sizes and counts when the function it is borrowed for differs only in
those: an N64 function, its C taken from a sibling that allocates 64 records of 0x3C bytes, was 98.7% with
`0x3C00, 0xC, 0xF00, 0x40, 0x3C` where its own instructions have `0x2C00, 0xD, 0x1640, 0xC0, 0x2C`; with those it was
exact. The literals in the C that no instruction of the target has, and the target's immediates the C doesn't have,
are paired, in the order each appears and smallest with smallest, when there are as many of one as of the other. A hypothesis like every other
family's: the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'target_constant'
FAMILIES = (FAMILY,)

LITERAL = re.compile(r'(?<![\w.])(0[xX][0-9a-fA-F]+|\d+)([uUlL]*)(?![\w.])')
# arithmetic with an immediate operand; stack-pointer adjustments and memory offsets aren't the C's constants
IMMEDIATE = re.compile(r'\b(addiu|addi|ori|andi|xori|slti|sltiu|daddiu)\s+\$(\w+)\s*,\s*\$(\w+)\s*,\s*(-?(?:0x[0-9a-fA-F]+|\d+))\s*$',
                       re.M)


def immediates(asm):
    """The target's immediate operands in order, as numbers."""
    found = []
    for hit in IMMEDIATE.finditer(asm or ''):
        if 'sp' in (hit[2], hit[3]):
            continue
        found.append(int(hit[4], 0))
    return found


def variants(source, name, asm):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    targets = immediates(asm)
    if not targets:
        return []
    have = set(targets) | {-n for n in targets}
    literals = [m for m in LITERAL.finditer(clean, opening, end)]
    values = [int(m[1], 0) for m in literals]
    # (small numbers stand for too many things — counts, flags, field offsets — to pair by position)
    missing = list(dict.fromkeys(v for v in values if v not in have and v > 1))
    extra = list(dict.fromkeys(t for t in targets if t not in values and -t not in values and t > 1))
    if not missing or len(missing) != len(extra) or len(missing) > 8:
        return []
    result = []
    # in the order each appears, and smallest with smallest: a loop's step and bound swap places when scheduled
    for pairs in (dict(zip(missing, extra)), dict(zip(sorted(missing), sorted(extra)))):
        text = source
        for m in reversed(literals):
            value = int(m[1], 0)
            if value in pairs:
                new = pairs[value]
                written = (f'0x{new:X}' if m[1].lower().startswith('0x') else str(new)) + m[2]
                text = text[:m.start()] + written + text[m.end():]
        if text != source and text not in [t for _, t in result]:
            result.append((FAMILY, text))
    return result
