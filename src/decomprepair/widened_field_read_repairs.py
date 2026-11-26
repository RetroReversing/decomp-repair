"""A halfword field m2c read narrowly, cast to int and compared, read as the word it is.

m2c types a field by the widest access it sees and widens what the code does with it. A game that compared a record's
first two halfwords with zero in one load (`lw $v0, -0x10($s2)`, then `bnez`) shows up as

    if (((s32) M2C_FIELD(rec, u16 *, -0x10) == 0) && (M2C_FIELD(rec, u16 *, -0xC) == 0)) {

where m2c took only the halfword at the offset it was asked about. The compiler loads a halfword with `lhu`, so the
cast cannot give the word load, and the offsets after it stay as they are. Reading the field as `s32` gives the `lw`.

For each `(s32)`/`(u32)` cast directly around an m2c halfword read that is then compared or masked, one variant reads
it as a word at the same offset. The judge decides; a read the game really made narrowly does not match. At most eight
variants, in source order.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'widened_field_read'
FAMILIES = (FAMILY,)

LIMIT = 8
_CAST = re.compile(r'\(\s*(?P<cast>s32|u32|int|unsigned\s+int)\s*\)\s*M2C_FIELD\s*\(')
_AFTER = re.compile(r'\s*(?:==|!=|<=|>=|<|>|&(?!&)|\|(?!\|))')
_HALF = re.compile(r'\s*([su]16)\s*\*\s*')


def _python_split(text):
    pieces, depth, start = [], 0, 0
    for index, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == ',' and depth == 0:
            pieces.append(text[start:index])
            start = index + 1
    pieces.append(text[start:])
    return pieces


_split = _python_split
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _split(text):
        return _scan.top_pieces(text, ',', 2)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    result = []
    for hit in _CAST.finditer(clean, span[0], span[1]):
        opening = hit.end() - 1
        closing = close(clean, opening)
        if not closing or not _AFTER.match(clean[closing:closing + 8]):
            continue
        arguments = _split(clean[opening + 1:closing - 1])
        if len(arguments) != 3 or not _HALF.fullmatch(arguments[1]):
            continue
        word = 's32' if hit['cast'] in ('s32', 'int') else 'u32'
        pieces = [arguments[0], f' {word} *', arguments[2]]
        text = source[:hit.start()] + f'M2C_FIELD({",".join(pieces)})' + source[closing:]
        result.append((FAMILY, text))
        if len(result) == LIMIT:
            break
    return result
