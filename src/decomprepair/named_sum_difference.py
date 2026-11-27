"""A local plus a constant that meets another value in a `+` or `-`, named by an assignment inside the expression.

    x = (angle + 0x200) - (spread() >> 5);          int named_sum;
                                                    x = (named_sum = angle + 0x200) - (spread() >> 5);

GCC's constant folder reassociates `(a + C) - b` into `a - (b - C)`, so the compiled code subtracts the constant from the
other value instead of adding it to `a`. Parentheses and casts do not stop it; an assignment expression is not split.
Measured on a 98-instruction N64 actor setup (SN GCC 2.8.1, `-G0 -mips3 -O2`): the target's `addiu $s0, $s0, 0x200`
came out as `addiu $v0, $v0, -0x200` on the other operand until the sum was named (450 -> 240). A statement of its
own before the line is not the same source: it also moves the addition above the call in the other operand.

One child per such sum. Only a local or parameter declared with an integer type is named, in a local of the signedness
C's promotion gives it, so the value of the expression is unchanged.
"""
import re

from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view

NAMED = 'named_sum_difference'
FAMILIES = (NAMED,)
LIMIT = 8
_SUM = re.compile(rf'\(\s*(?P<local>{IDENT})\s*(?P<sign>[+-])\s*(?P<constant>{NUMBER})\s*\)')


def _local_type(part, name):
    found = re.findall(rf'(?<![\w.>])({INTEGER})\s+{name}\s*[;,=)]', part.clean[:part.end])
    return found[-1] if found else None


def _meets_a_value(clean, start, end):
    """The parenthesised sum is an operand of a binary `+` or `-` whose other operand is not a bare constant."""
    after = re.match(r'\s*([+-])(?![+\-=>])\s*', clean[end:])
    if after:
        return not re.match(rf'{NUMBER}\b', clean[end + after.end():])
    before = clean[:start].rstrip()
    if before[-1:] not in '+-' or before[-2:] in ('++', '--'):
        return False
    operand = before[:-1].rstrip()
    return bool(re.search(r'[\w)\]]$', operand)) and not re.search(rf'(?<![\w.]){NUMBER}$', operand)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    fresh = 'named_sum'
    number = 2
    while re.search(rf'\b{fresh}\b', clean):
        fresh = f'named_sum_{number}'
        number += 1
    found = []
    for hit in _SUM.finditer(clean, part.opening + 1, part.end):
        # `f(a + 1)` and `if (a + 1)` are not parenthesised operands
        if re.search(r'[\w\]]$', clean[:hit.start()].rstrip()) or not _meets_a_value(clean, hit.start(), hit.end()):
            continue
        declared = _local_type(part, hit['local'])
        if not declared:
            continue
        kind = 'unsigned int' if re.fullmatch(r'u32|unsigned\s+int', declared) else 'int'
        total = f'({fresh} = {hit["local"]} {hit["sign"]} {hit["constant"]})'
        declaration = f'\n    {kind} {fresh};'
        found.append((NAMED, edit(source, [(part.opening + 1, part.opening + 1, declaration),
                                           (hit.start(), hit.end(), total)])))
        if len(found) >= LIMIT:
            break
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}
