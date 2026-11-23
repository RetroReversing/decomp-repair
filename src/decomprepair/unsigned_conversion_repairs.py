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

The two arms may also store through one lvalue with a narrowing cast, where no variable is assigned (a field of a record read
as `*(u16 *)((char *)p + 0x26)`): `LV = (u16) ((s32) (F - 2.1474836e9f) | 0x80000000);` and `LV = (u16) (s32) F;` become `LV =
(u16) (u32) F;` (two such conversions in a 443-instruction display-state updater were 1915 -> 855 -> 0 once written back,
one site at a time).
"""
import re

from .csource import _blank, find
from .integer_repair_support import edit
from .pattern_repairs import close

FAMILY = 'float_unsigned_conversion'
SCHEDULING = 'float_unsigned_conversion_scheduling'
FAMILIES = (FAMILY, SCHEDULING)

IDENT = r'[A-Za-z_]\w*'
CONDITION = re.compile(r'^\s*(?P<not>!\s*\(\s*)?(?:\(\s*(?:u32|unsigned(?:\s+int)?)\s*\)\s*)?(?P<float>' + IDENT
                       + r')\s*(?P<op>>=|<)\s*2\.1474836e9f\s*\)?\s*$')
ASSIGNED = re.compile(r'(?:register\s+)?(?P<var>' + IDENT + r')\s*=(?!=)')
MASK = re.compile(r'&\s*(?P<mask>0[xX][fF]{2}|0[xX][fF]{4}|255|65535)\s*;')
NARROW = {0xFF: 'u8', 0xFFFF: 'u16'}


def _cast_store(arms, flt):
    """`LV = (T) (u32) F;` for arms that store the two truncations through one lvalue with a narrowing cast:
    `LV = (T) ((s32) (F - 2.1474836e9f) | 0x80000000);` and `LV = (T) (s32) F;` (a field of a record, `*(u16 *)((char *)p + 0x26)`,
    where the draft's variable form above has a name to assign), or None."""
    for high, low in (arms, arms[::-1]):
        top = re.fullmatch(r'\s*(?P<lv>[^=;]+?)\s*=(?!=)\s*\(\s*(?P<t>\w+)\s*\)\s*\(\s*\(s32\)\s*\(\s*' + re.escape(flt)
                           + r'\s*-\s*2\.1474836e9f\s*\)\s*\|\s*0x80000000\s*\)\s*;\s*', high)
        bottom = re.fullmatch(r'\s*(?P<lv>[^=;]+?)\s*=(?!=)\s*\(\s*(?P<t>\w+)\s*\)\s*\(s32\)\s*' + re.escape(flt) + r'\s*;\s*', low)
        if top and bottom and top['lv'].strip() == bottom['lv'].strip() and top['t'] == bottom['t']:
            return f"{top['lv'].strip()} = ({top['t']}) (u32) {flt};"
    return None


def _schedule_sites(source, condition, arms, ranges, cond_span, flipped, isolated):
    """Record a positive branch to flip or a negative branch's high-bit write to isolate."""
    if condition['op'] != '>=' or any(re.search(r'\b(?:for|while|do|switch|break|continue)\b', arm) for arm in arms):
        return
    value = condition['float']
    high, low = (1, 0) if condition['not'] else (0, 1)
    pattern = (rf'\b(?P<result>{IDENT})\s*=\s*\(s32\)\s*\(\s*{value}\s*-\s*2\.1474836e9f\s*\)\s*;'
               rf'\s*(?P<bit>(?P=result)\s*=\s*(?P=result)\s*\|\s*0x80000000\s*;)')
    hit = re.search(pattern, arms[high])
    if not hit or not re.search(rf'\b{hit["result"]}\s*=\s*\(s32\)\s*{value}\s*;', arms[low]):
        return
    start, end = cond_span
    if condition['not']:
        bit_start, bit_end = (ranges[high][0] + position for position in hit.span('bit'))
        isolated.append([(bit_start, bit_end, f'do {{ {source[bit_start:bit_end]} }} while (0);')])
    else:
        a, b = ranges
        cond = source[start:end]
        flipped.append([(start, end, f'!({cond.strip()})'),
                        (*a, source[b[0]:b[1]]), (*b, source[a[0]:a[1]])])


def _schedule_variants(source, flipped, isolated):
    paired = []
    for flip in flipped:
        for fence in isolated:
            if not flip[0][0] < fence[0][0] < flip[-1][1]:
                paired.append((SCHEDULING, edit(source, flip + fence)))
                if len(paired) == 4:
                    return paired
    return paired + [(SCHEDULING, edit(source, changes)) for changes in (flipped + isolated)[:4 - len(paired)]]


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
    flipped, isolated = [], []
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
        if '#' not in clean[opening:end]:
            _schedule_sites(source, condition, arms,
                            [(then_open + 1, then_close - 1), (else_open + 1, else_close - 1)],
                            (cond_open + 1, cond_close - 1), flipped, isolated)
        targets = {m['var'] for arm in arms for m in ASSIGNED.finditer(arm)}
        flt = condition['float']
        stored = _cast_store([source[then_open + 1:then_close - 1], source[else_open + 1:else_close - 1]], flt)
        if stored:
            text = source[:opening + hit.start()] + stored + source[else_close:]
            if text not in [t for _, t in result]:
                result.append((FAMILY, text))
            continue
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
    return result[:4] + _schedule_variants(source, flipped, isolated)
