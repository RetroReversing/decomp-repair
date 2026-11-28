"""A byte offset added to the address of a symbol m2c declared as one word, written as byte arithmetic.

m2c declares a table it only saw through one address as `extern s32 X;` and writes `*((&X) + off)` or `off + (&X)`,
where `off` is already the byte offset (an index times the record size). C scales it by four again: the target has
`sll v0,v0,2` for the last factor of the stride and ours has `sll v0,v0,4`, and the symbol's load reads far past the
record. Seen on a KMC gcc 2.7.2 `-O1` function with two such symbols (155 -> 30 with both written as bytes).

word_symbol_byte_offset
    Every `&X` that is added to something, for each `X` declared as a lone word, is written `(u8 *)&X`; a read or write
    through that sum gets the word's type back, `*(s32 *)(...)`. One child for all symbols together, then one per symbol.

A rewrite that changes what the C computes when the offset really counted words: the exact judge decides.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'word_symbol_byte_offset'
FAMILIES = (FAMILY,)
LIMIT = 6
# `(s32) *(..)`: m2c casts a read, and the `*` after the cast is a read too (a product's `(a) *` names a variable)
_AFTER_CAST = r'\(\s*(?:s8|u8|s16|u16|s32|u32|s64|u64|f32|f64|int|char|short|long|M2C_UNK)\s*\**\s*\)'
_DECLARATION = re.compile(r'(?m)^[ \t]*extern\s+(?P<type>s32|u32|int|M2C_UNK)\s+(?P<name>[A-Za-z_]\w*)\s*;')


def _sum_site(clean, start, stop, low):
    """For the `&X` at [start, stop): None when it is no operand of a `+`, else the unary `*` of the sum it is read
    through, or -1 when the sum is only a value."""
    while True:  # out through parentheses around the lone address
        before, after = clean[low:start].rstrip(), clean[stop:]
        if not (before.endswith('(') and after.lstrip().startswith(')')):
            break
        start = low + len(before) - 1
        stop = len(clean) - len(after.lstrip()) + 1
    if before.endswith(')'):  # already cast: `(u8 *)&X`
        if re.search(r'\*\s*\)$', before):
            return None
    follows = re.match(r'\s*\+(?![+=])', clean[stop:])
    if not (follows or re.search(r'(?<!\+)\+$', before)):
        return None
    depth = 0
    for at in range(start - 1, low - 1, -1):
        if clean[at] in ')]':
            depth += 1
        elif clean[at] in '([':
            if not depth:
                break
            depth -= 1
        elif not depth and clean[at] in ';{}':
            return -1
    else:
        return -1
    if clean[at] != '(' or not close(clean, at):
        return -1
    star = re.search(r'(?:^|[=(,;{}+\-/&|^<>!?:]|\breturn|' + _AFTER_CAST + r')\s*(\*)\s*$', clean[low:at])
    return low + star.start(1) if star else -1


def variants(source, name, header=''):
    part = view(source, name)
    if not part or '&' not in source:
        return []
    clean, low = part.clean, part.opening + 1
    types = {m['name']: ('s32' if m['type'] == 'M2C_UNK' else m['type'])
             for m in _DECLARATION.finditer(clean)}
    found = {}
    for symbol, kind in types.items():
        changes = []
        for hit in re.finditer(rf'(?<![\w&])&\s*{re.escape(symbol)}\b(?!\s*(?:\[|\.|->))', clean[:part.end]):
            if hit.start() < low:
                continue
            star = _sum_site(clean, hit.start(), hit.end(), low)
            if star is None:
                continue
            changes.append((hit.start(), hit.start(), '(u8 *)'))
            if star >= 0:
                changes.append((star + 1, star + 1, f'({kind} *)'))
        if changes:
            found[symbol] = changes
    if not found:
        return []
    groups = [list(found)] if len(found) > 1 else []
    groups += [[symbol] for symbol in found]
    return [(FAMILY, edit(source, sorted({change for symbol in group for change in found[symbol]})))
            for group in groups[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
