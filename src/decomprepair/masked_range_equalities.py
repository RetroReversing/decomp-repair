"""A byte's range test written as the game's masked equality chain.

m2c folds `t == 9 || t == 10 || t == 11` into a range test of the first two plus the masked third:

    s8 t;
    t = M2C_FIELD(p, u8 *, 0x82);
    if (((u32)(t - 9) < 2U) || ((t & 0xFF) == 0xB)) {

gcc 2.7.2 then knows the byte is zero-extended, so it drops the `& 0xFF` (`andi`) the game keeps, and the signed local
loads it with `lb` where the game has `lbu`. When the same masked value is compared more than once the combiner cannot
fold the mask into one branch, and the `andi` stays. A KMC GCC 2.7.2 (-O2) N64 function with this shape went from 215
(an `lb`, a missing `andi`) to 15 with the local unsigned and the chain written out:

    u8 t;
    if (((t & 0xFF) == 9) || ((t & 0xFF) == 0xA) || ((t & 0xFF) == 0xB)) {

The three tests cover the same values, and the local's type only changes how the byte is loaded (`lbu` for `lb`):
every value compared is below 128, so a byte with the high bit set fails both spellings. Proposed only for a one-byte
local with one range test and a masked equality, all below 128.
"""
import re

from .float_arm_roles import IDENT, _body

FAMILIES = ('masked_range_equality_chain',)
LIMIT = 2
NUMBER = r'(?:0[xX][0-9A-Fa-f]+|\d+)'
MAX_SPAN = 4


def _value(text):
    return int(text, 16 if text[:2].lower() == '0x' else 10)


def variants(source, name, header=''):
    part = _body(source, name)
    if not part:
        return []
    clean, opening, end = part
    result = []
    for decl in re.finditer(r'(?m)^([ \t]*)(?:s8|u8|char|signed char|unsigned char)\s+(' + IDENT + r')\s*;', clean[opening:end]):
        var = decl[2]
        ranges = list(re.finditer(
            r'\(\s*\(\s*u32\s*\)\s*\(\s*' + var + r'\s*-\s*(' + NUMBER + r')\s*\)\s*<\s*(' + NUMBER + r')[uU]?\s*\)', clean[opening:end]))
        masked = re.findall(r'\(\s*\(?\s*' + var + r'\s*&\s*0[xX][fF][fF]\s*\)\s*==\s*(' + NUMBER + r')\s*\)', clean[opening:end])
        if len(ranges) != 1 or not masked:
            continue
        low, span = _value(ranges[0][1]), _value(ranges[0][2])
        if not 2 <= span <= MAX_SPAN or low + span > 128 or any(_value(m) >= 128 for m in masked):
            continue
        chain = ' || '.join(f'(({var} & 0xFF) == {hex(low + i).upper().replace("X", "x") if low + i > 9 else low + i})'
                            for i in range(span))
        at = opening + ranges[0].start()
        edits = [(at, opening + ranges[0].end(), chain)]
        if decl[0].split()[0] in ('s8', 'char', 'signed'):
            edits.append((opening + decl.start(), opening + decl.end(), re.sub(r'\b(?:s8|signed char|char)\b', 'u8', decl[0], 1)))
        out = source
        for x, y, new in sorted(edits, reverse=True):
            out = out[:x] + new + out[y:]
        if out != source:
            result.append((FAMILIES[0], out))
        if len(result) >= LIMIT:
            break
    return result
