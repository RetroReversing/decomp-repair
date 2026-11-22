"""Two byte-valued locals held as 16-bit values, so the compiler never widens them.

m2c types a pair of locals that carry bytes (a low and a high bound unpacked from one word) as `u32`, and masks every
read with `& 0xFF`. gcc 2.7.2 then keeps each in a full register and masks again where the game did not. A KMC N64
function at 380 became exact (with other rewrites) when the pair was a `u16` and the code was written the way a
16-bit local reads:

    u32 hi; u32 lo;                      u16 hi; u16 lo;
    lo = w >> 8; hi = w >> 24;           lo = (u16)(w >> 8); hi = (u16)(w >> 24);
    if (hi < (lo & 0xFF)) {              if ((u8)hi < (u8)lo) {
        u32 tmp = lo; ...                    u16 tmp = lo; ...
    store(((lo & 0xFF) + r) << 8)        store((helper(lo) + r) << 8)     (the helper is `arg & 0xFF`)

Each of these steps alone made it worse (380 -> 970 -> 770 -> 510) and the last one, reusing the game's own mask helper
for the second mask so the compiler shares the one `andi`, brought it to 180, so the whole set is one child here.
The narrowing child alone is offered too, for a function that has no mask helper.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'masked_byte_pair'
FAMILIES = (FAMILY,)

WIDE = r'(?:u32|s32|int|unsigned\s+int)'
MASK = r'(?:0[xX][fF][fF]|255)'
DECL = re.compile(rf'(?m)^(?P<indent>[ \t]*){WIDE}\s+(?P<name>{IDENT})\s*;')
HELPER = re.compile(rf'(?P<helper>{IDENT})\s*\(\s*{WIDE}\s+(?P<arg>{IDENT})\s*\)\s*{{\s*return\s*'
                    rf'(?:\(\s*(?:s32|u32|int)\s*\)\s*)?\(?\s*(?P=arg)\s*&\s*{MASK}\s*\)?\s*;\s*}}')


def _helpers(source):
    return {m['helper'] for m in HELPER.finditer(source)}


def _gated(body):
    """Locals that are masked to a byte when read and unpacked with a right shift when written."""
    names = []
    for hit in DECL.finditer(body):
        name = hit['name']
        if (re.search(rf'\(\s*{name}\s*&\s*{MASK}\s*\)', body)
                and re.search(rf'\b{name}\s*=\s*[^;=]*>>[^;]*;', body)):
            names.append(name)
    return names


def _narrow(body, names):
    group = '|'.join(names)
    out = re.sub(rf'(?m)^([ \t]*){WIDE}(\s+(?:{group})\s*;)', r'\1u16\2', body)
    out = re.sub(rf'\b({group})(\s*=\s*)([^;=]*>>[^;=]*?)\s*;',
                 lambda m: m.group(0) if m.group(3).lstrip().startswith('(u16)')
                 else f'{m.group(1)}{m.group(2)}(u16)({m.group(3)});', out)
    out = re.sub(rf'\b{WIDE}(\s+{IDENT}\s*=\s*(?:{group})\s*;)', r'u16\1', out)
    out = re.sub(rf'\b({group})\s*<\s*\(\s*({group})\s*&\s*{MASK}\s*\)', r'(u8)\1 < (u8)\2', out)
    return out


def _share_mask(body, names, helpers):
    """`((x & 0xFF) + y)` -> `(helper(x) + y)` where the helper already reads `x`."""
    for helper in sorted(helpers):
        for name in names:
            if re.search(rf'\b{helper}\s*\(\s*{name}\s*\)', body):
                body = re.sub(rf'\(\s*\(\s*{name}\s*&\s*{MASK}\s*\)\s*\+', f'({helper}({name}) +', body)
    return body


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = source[part.opening:part.end]
    names = _gated(part.clean[part.opening:part.end])
    if len(names) < 2:
        return []
    narrowed = _narrow(body, names)
    shared = _share_mask(narrowed, names, _helpers(source))
    result = []
    for text in (shared, narrowed):
        candidate = source[:part.opening] + text + source[part.end:]
        if candidate != source and all(candidate != c for _, c in result):
            result.append((FAMILY, candidate))
    return result
