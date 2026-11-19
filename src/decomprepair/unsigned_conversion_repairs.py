"""m2c's expansion of a float converted to an unsigned integer, written back as the conversion.

gcc converts a float to `u32` with a test against 2^31: below it a plain truncation, at or above it the truncation of
`f - 2^31` with the top bit set. m2c writes out both branches:

    if (temp_fv1 >= 2.1474836e9f) {
        ret = ((s32) (temp_fv1 - 2.1474836e9f) | 0x80000000) & 0xFF;
    } else {
        ret = (s32) temp_fv1 & 0xFF;
    }

Compiled as written that is two truncations, a test and an `or` the source never had, and a frame slot for them: an
N64 function was 84.1% so and exact as `ret = (u8) (u32) temp_fv1;`. The condition may come as `>=`, `<`, `!(... >=
...)` or with a cast on the float; an arm may still carry the `register` an earlier permuter bug put on it.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_unsigned_conversion'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
CONDITION = re.compile(r'^\s*(?P<not>!\s*\(\s*)?(?:\(\s*(?:u32|unsigned(?:\s+int)?)\s*\)\s*)?(?P<float>' + IDENT
                       + r')\s*(?P<op>>=|<)\s*2\.1474836e9f\s*\)?\s*$')
ASSIGNED = re.compile(r'(?:register\s+)?(?P<var>' + IDENT + r')\s*=(?!=)')
MASK = re.compile(r'&\s*(?P<mask>0[xX][fF]{2}|0[xX][fF]{4}|255|65535)\s*;')
NARROW = {0xFF: 'u8', 0xFFFF: 'u16'}


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in re.finditer(r'\bif\s*\(', clean[opening:end]):
        cond_open = opening + hit.end() - 1
        cond_close = close(clean, cond_open)
        if not cond_close or '2.1474836e9f' not in clean[cond_open:cond_close]:
            continue
        condition = CONDITION.match(clean[cond_open + 1:cond_close - 1])
        then = re.match(r'\s*\{', clean[cond_close:end])
        if not condition or not then:
            continue
        then_open = cond_close + then.end() - 1
        then_close = close(clean, then_open, '{', '}')
        other = re.match(r'\s*else\s*\{', clean[then_close:end]) if then_close else None
        if not other:
            continue
        else_open = then_close + other.end() - 1
        else_close = close(clean, else_open, '{', '}')
        if not else_close:
            continue
        arms = [clean[then_open + 1:then_close - 1], clean[else_open + 1:else_close - 1]]
        if any(re.search(r'\b(?:goto|return|if)\b|[{}]', arm) for arm in arms):
            continue
        targets = {m['var'] for arm in arms for m in ASSIGNED.finditer(arm)}
        flt = condition['float']
        if len(targets) != 1 or not all(flt in arm for arm in arms) or '0x80000000' not in ''.join(arms):
            continue
        var = targets.pop()
        masks = {int(m['mask'], 0) for arm in arms for m in MASK.finditer(arm)}
        if len(masks) > 1:
            continue
        mask = masks.pop() if masks else None
        forms = [f'{var} = (u32) {flt}' + (f' & 0x{mask:X}' if mask else '') + ';']
        if mask in NARROW:
            forms.append(f'{var} = ({NARROW[mask]}) (u32) {flt};')
        for form in forms:
            text = source[:opening + hit.start()] + form + source[else_close:]
            if text not in [t for _, t in result]:
                result.append((FAMILY, text))
    return result[:4]
