"""Constant offsets from one symbol written as the separate globals the game declared.

At `-O1` (KMC gcc 2.7.2) several accesses written off one byte array, `*(s16 *) ((u8 *) D_X + 0x8C6) = 0;` and the
next ones, share one base register (`lui $v0; addiu $v0, $v0, %lo(D_X+0x8C6); sh $zero, ($v0); sh $v1, 2($v0)`),
while the target addresses each one by itself (`lui $at, %hi(D_X + 0x8C8); sh $v0, %lo(D_X + 0x8C8)($at)`): the game
had a global of its own at each address, and splat only had a name for the first. This writes each access the target
addresses that way as its own `extern`, named after its address, with the type the access reads. A block of fourteen
stores in a 296-instruction state routine was 3705 with the offsets and 180 split (controlled: nothing else changed).

The meaning is the same bytes at the same addresses. Only accesses whose offset the target shows as
`%lo(SYMBOL + offset)($at)` are rewritten, and at least two of them must be present.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'offset_symbol_split'
FAMILIES = (FAMILY,)

_TARGET = re.compile(r'%lo\(\s*(D_[0-9A-Fa-f]{8})\s*\+\s*(0[xX][0-9A-Fa-f]+|\d+)\s*\)\(\$at\)')
_TYPE = r'(?P<type>(?:s|u)(?:8|16|32)|f32)'
_NUM = r'(?P<off>0[xX][0-9A-Fa-f]+|\d+)'
_BYTES = r'(?:\(\s*(?:u8|s8|char)\s*\*\s*\)\s*)?'
# `*(T *) (D + K)`, `*((T *) (((u8 *) D) + K))` and m2c's `M2C_FIELD(D, T *, K)`
_FORMS = (
    r'\*\s*\(\s*\(\s*' + _TYPE + r'\s*\*\s*\)\s*\(\s*\(\s*(?:u8|s8|char)\s*\*\s*\)\s*(?P<sym>D_[0-9A-Fa-f]{8})\s*\)\s*\+\s*'
    + _NUM + r'\s*\)\s*\)',
    r'\*\s*\(\s*\(\s*' + _TYPE + r'\s*\*\s*\)\s*\(\s*\(\s*\(\s*(?:u8|s8|char)\s*\*\s*\)\s*(?P<sym>D_[0-9A-Fa-f]{8})\s*\)\s*\+\s*'
    + _NUM + r'\s*\)\s*\)',
    r'\*\s*\(\s*' + _TYPE + r'\s*\*\s*\)\s*\(\s*' + _BYTES + r'(?P<sym>D_[0-9A-Fa-f]{8})\s*\+\s*' + _NUM + r'\s*\)',
    r'\*\s*\(\s*' + _TYPE + r'\s*\*\s*\)\s*\(\s*\(\s*(?:u8|s8|char)\s*\*\s*\)\s*(?P<sym>D_[0-9A-Fa-f]{8})\s*\)\s*\+\s*'
    + _NUM + r'(?!\w)(?!\s*[-+*/])',
    r'M2C_FIELD\s*\(\s*&?\s*(?P<sym>D_[0-9A-Fa-f]{8})\s*,\s*' + _TYPE + r'\s*\*\s*,\s*' + _NUM + r'\s*\)',
)


def _declared(header_and_source, symbol):
    """The element type of a global declared as a byte array (`extern u8 D_X[];`), else None."""
    m = re.search(r'\bextern\s+(?:volatile\s+)?(u8|s8|char|M2C_UNK)\s+' + symbol + r'\s*\[[^\]]*\]\s*;', header_and_source)
    return m[1] if m else None


def variants(source, name, asm=''):
    span = find(source, name)
    if not span or not asm:
        return []
    shown = {}
    for symbol, offset in _TARGET.findall(asm):
        shown.setdefault(symbol, set()).add(int(offset, 0))
    if not shown:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    edits, taken, wanted = [], [], {}

    def claim(start, stop, symbol, offset, kind):
        if offset not in shown.get(symbol, ()) or any(start < b and a < stop for a, b in taken):
            return
        new = f'D_{int(symbol[2:], 16) + offset:08X}'
        if wanted.setdefault(new, kind) != kind:
            return
        taken.append((start, stop))
        edits.append((start, stop, new))

    for form in _FORMS:
        for m in re.compile(form).finditer(clean, opening, end):
            claim(m.start(), m.end(), m['sym'], int(m['off'], 0), m['type'])
    for symbol in shown:
        kind = _declared(clean, symbol)
        if kind in ('u8', 's8'):
            for m in re.finditer(r'(?<![\w&.>])' + symbol + r'\s*\[\s*' + _NUM + r'\s*\]', clean[:end]):
                if m.start() > opening:
                    claim(m.start(), m.end(), symbol, int(m['off'], 0), kind)
    if len(edits) < 2:
        return []
    externs = []
    for new, kind in wanted.items():
        if not any(text == new for _, _, text in edits):
            continue
        old = re.search(r'\bextern\s+([^;{}()]*?)\s*\b' + new + r'\b([^;]*);', clean)
        if old:
            if old[1].split() != [kind] or old[2].strip():
                return []
        else:
            externs.append(f'extern {kind} {new};')
    text = source
    for start, stop, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[stop:]
    if externs:
        # above the function, after any typedefs and externs it already has
        at = source.rfind('\n', 0, span[0]) + 1
        text = text[:at] + '\n'.join(externs) + '\n' + text[at:]
    return [(FAMILY, text)]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
