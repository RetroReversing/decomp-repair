"""A round-down to a power of two assigned to a local, the scale back written as a left shift.

`size = ((u32) (entry + 0xF) >> 4) * 0x10;` and `size = (entry + 0xF) / 16 * 16;` are the same value as
`size = ((entry + 0xF) >> 4) << 4;`, but not always the same registers: an N64 sound-bank loader (sn-n64-281 GCC 2.8.1,
`-G0 -mips3 -O2 -mfp64`, 147 instructions) loaded the entry, added and shifted in the destination's own saved register
with either scaled spelling, and in `$v0` as the target does with the `<< 4` (40 -> 0). One result on one function, so
why the compiler tells the two apart is a hypothesis.

`variants` takes `x = (E >> N) * M;` with M the number 1 << N, and `x = E / M * M;` with M a power of two and E starting
with a `(u32)` cast, or naming only things declared `u32` (a signed quotient rounds toward zero, a shift does not).
`x` is a plain local or parameter: a destination in memory was not measured. One child with every site, then one per site.
`round_up_steps` is the neighbouring shape, a variable rounded into itself, written as three statements.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'shift_back_scale'
FAMILIES = (FAMILY,)
LIMIT = 6
NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
ASSIGN = re.compile(rf'(?<![\w.>\]])(?P<x>{IDENT})\s*=(?!=)\s*(?P<value>[^;={{}}]+);')
SCALED = re.compile(rf'(?P<head>.*\S)\s*\*\s*(?P<m>{NUMBER})\s*', re.S)
DIVIDED = re.compile(rf'(?P<dividend>.*\S)\s*/\s*(?P<d>{NUMBER})\s*', re.S)
SHIFTED = re.compile(rf'.*>>\s*(?P<n>{NUMBER})\s*', re.S)
U32_CAST = re.compile(r'\(\s*u32\s*\)')


def _grouped(text):
    """Whether `text` is one parenthesised expression."""
    return text.startswith('(') and close(text, 0, '(', ')') == len(text)


def _unsigned(dividend, context):
    if U32_CAST.match(dividend) or (_grouped(dividend) and U32_CAST.match(dividend[1:-1].strip())):
        return True
    # the names that give the value: a member or local, not a base it is read through or a subscript
    read = re.sub(r'\[[^\[\]]*\]', '', dividend)
    names = re.findall(rf'(?<!\w)({IDENT})\b(?!\s*(?:\.|->|\())', read)
    return bool(names) and all(re.search(rf'\bu32\s+{name}\b', context) for name in names)


def _rewrite(value, context):
    """`value` with its scale written as a shift, or None."""
    scaled = SCALED.fullmatch(value)
    if not scaled:
        return None
    scale = int(scaled['m'], 0)
    if scale < 2 or scale & (scale - 1):
        return None
    shift, head = scale.bit_length() - 1, scaled['head']
    if _grouped(head):
        inner = head[1:-1].strip()
        shifted = SHIFTED.fullmatch(inner)
        # `(E >> N) * M`: the group's last operator is the shift itself
        if shifted and int(shifted['n'], 0) == shift:
            return f'{head} << {shift}'
    divided = DIVIDED.fullmatch(head)
    if not divided or int(divided['d'], 0) != scale:
        return None
    dividend = divided['dividend']
    if not (_grouped(dividend) or re.fullmatch(IDENT, dividend)) and not (
            U32_CAST.match(dividend) and _grouped(dividend[U32_CAST.match(dividend).end():].strip())):
        return None
    if not _unsigned(dividend, context):
        return None
    return f'({dividend} >> {shift}) << {shift}'


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = _blank(source)
    context = _blank(header) + '\n' + clean
    sites = []
    for hit in ASSIGN.finditer(clean, part.opening, part.end):
        if not re.search(r'(?:\A|[;{}:)])\s*\Z', clean[:hit.start()]):
            continue
        start, end = hit.start('value'), hit.start('value') + len(hit['value'].rstrip())
        value = source[start:end]
        # comments or literals inside the value: leave it
        if value != clean[start:end] or value.count('(') != value.count(')'):
            continue
        new = _rewrite(value, context)
        if new:
            sites.append((start, end, new))
    out = [(FAMILY, edit(source, [site])) for site in sites]
    if len(sites) > 1:
        out.insert(0, (FAMILY, edit(source, sites)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 900}
