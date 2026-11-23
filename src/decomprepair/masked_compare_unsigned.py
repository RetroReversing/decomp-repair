"""A comparison of a masked narrow value, read as unsigned the way the target compares it.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) voice-picker that compared the priority it was asked for
with the priority stored in a record: `if ((arg0 & 0xFF) < *(u8 *)(table + off)) return -1;`. Both sides are small
non-negative values, so the signedness of the compare changes no result, but the compiler emits `slt` for two ints and
`sltu` when one side is unsigned, and the target has `sltu`. A byte read and a masked word are both `int` after the
usual promotions; `((u32)(arg0 & 0xFF)) < *(u8 *)(...)` is the unsigned compare (1020 -> 820 with the other
signed compare of that function, a masked priority against a masked 16-bit link, written the same way).

masked_compare_unsigned
    `(X & K) OP Y` with `OP` one of `<`, `<=`, `>`, `>=`, a literal positive mask `K` of at most 0xFFFF and a right
    side that is another masked value, a `*(u8 *)` / `*(u16 *)` read or an unsigned narrow cast, becomes
    `((u32) (X & K)) OP Y`. The mirrored form (the masked value on the right) is cast on the right. One child per
    comparison, and one child with all of them when there are two or more. The comparison stays what the source meant:
    only operands that cannot be negative are cast.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'masked_compare_unsigned'
FAMILIES = (FAMILY,)
LIMIT = 8
_MASKED = r'\(\s*[\w.\[\]]+(?:\s*->\s*\w+)?\s*&\s*(?:0[xX][0-9A-Fa-f]{1,4}|[0-9]{1,5})\s*\)'
_NARROW_READ = r'\*\s*\(\s*\(\s*(?:u8|u16|unsigned\s+(?:char|short))\s*\*\s*\)'
_OPERATOR = r'(?<![<>-])(?:<=|>=|<|>)(?![<>=])'
_COMPARE = re.compile(rf'(?P<left>{_MASKED})\s*(?P<op>{_OPERATOR})\s*(?P<right>{_MASKED}|{_NARROW_READ}|\(\s*(?:u8|u16)\s*\))')
_MIRROR = re.compile(rf'(?P<left>{_NARROW_READ})(?P<mid>[^;{{}}]*?)\)\s*(?P<op>{_OPERATOR})\s*(?P<right>{_MASKED})')
_CAST = re.compile(r'\(\s*(?:u32|unsigned(?:\s+int)?|unsigned\s+long)\s*\)\s*$')


def _mask_ok(text):
    value = re.search(r'&\s*(0[xX][0-9A-Fa-f]+|\d+)', text)
    return bool(value) and 0 < int(value[1], 0) <= 0xFFFF


def _children(source, clean, low, high):
    out = []
    for hit in _COMPARE.finditer(clean, low, high):
        left = hit.start('left')
        if _CAST.search(clean[:left]) or not _mask_ok(hit['left']):
            continue
        if re.match(r'\(\s*[\w.\[\]]+\s*&', hit['right']) and not _mask_ok(hit['right']):
            continue
        out.append((left, hit.end('left'), f'((u32) {source[left:hit.end("left")]})'))
    for hit in _MIRROR.finditer(clean, low, high):
        right = hit.start('right')
        if _CAST.search(clean[:right]) or not _mask_ok(hit['right']):
            continue
        out.append((right, hit.end('right'), f'((u32) {source[right:hit.end("right")]})'))
    return sorted(set(out))


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    items = _children(source, part.clean, part.opening + 1, part.end)[:LIMIT]
    children = [(FAMILY, edit(source, [item])) for item in items]
    if len(items) > 1:
        children.append((FAMILY, edit(source, items)))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
