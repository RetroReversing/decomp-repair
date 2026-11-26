"""A narrow local or parameter m2c typed from one access, as the `int` the source had.

m2c types a local from the load that fills it: `s8 temp_s1 = M2C_FIELD(p, s8 *, 0xE);`. gcc 2.7.2 then reads the
field with `lbu` and sign-extends where the value is used, or keeps a halfword parameter's `sll`/`sra`; the game
read it with `lb` into an `int` and used it as it was. Two N64 functions holding a byte field across a call (86.6%,
90.0%) and one storing an `s16` parameter (70.0%) were exact with the local or parameter as `s32`. One variant per
local or parameter, each alone, and all the narrow locals together. A constant-only
mode compared to a byte field gets a dedicated trial before the general cap.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'narrow_widening'
CONSTANT_MODE_FAMILY = 'narrow_constant_mode'
FAMILIES = (FAMILY, CONSTANT_MODE_FAMILY)

NARROW = r'(?:s8|u8|s16|u16|signed\s+char|unsigned\s+char|short|unsigned\s+short|char)'
IDENT = r'[A-Za-z_]\w*'


def _constant_modes(clean, opening, end):
    body = clean[opening:end]
    if re.search(r'\b(?:asm|__asm__|sizeof|typeof|__typeof__|_Generic)\b|(?m:^\s*#)', body):
        return []
    result = []
    declarations = re.compile(rf'(?m)^[ \t]*(u8)\s+(?P<name>{IDENT})\s*;')
    for declaration in declarations.finditer(clean, opening, end):
        start = declaration.start()
        prefix = clean[opening:start]
        if prefix.count('{') - prefix.count('}') != 1:
            continue
        name = declaration['name']
        write = re.compile(r'\s*(?:[+*/%&|^-]=|<<=|>>=|\+\+|--|=(?!=))')
        constant = re.compile(r'\s*=\s*([0-9]|0[xX][0-9A-Fa-f])\s*;')
        values = set()
        valid = True
        for hit in re.finditer(rf'\b{name}\b', body):
            before = body[:hit.start()]
            after = body[hit.end():]
            if re.search(r'(?:\.|->|&\s*\(*|\+\+|--|\b(?:u8|s8|int|char|short|float|double|u32|s32))\s*$', before):
                if opening+hit.start() != declaration.start('name'):
                    valid = False
                    break
            if write.match(after):
                if not (literal := constant.match(after)):
                    valid = False
                    break
                values.add(int(literal[1], 0))
        compare = rf'\b{name}\s*(?:!=|==)\s*\(+\s*\*\s*\(+\s*(?:u8|unsigned\s+char)\s*\*'
        if valid and len(values) >= 2 and re.search(compare, body):
            result.append(declaration.span(1))
    return result[:4]


def _widened_with_casts(source, clean, opening, end, start, stop):
    """The local as `s32` with its old narrow type written at each read, so the value a use sees is unchanged.

    A call's result held in a `u16` local and tested as `(u16) (ret + 2) < 2` was exact as `s32 ret` with `(u16) ret`
    at the array subscripts (KMC gcc 2.7.2 `-O1`: 5 -> 0); widening alone sign-extends differently and was 1660.
    A read already inside a cast to the narrow type is left alone."""
    kind = ' '.join(clean[start:stop].split())
    declared = re.compile(r'\s+(' + IDENT + r')\s*;').match(clean, stop)
    if not declared:
        return None
    name = declared[1]
    body_end = end
    if re.search(r'&\s*' + name + r'\b|(?:\+\+|--)\s*' + name + r'\b|\b' + name + r'\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)',
                 clean[opening:body_end]):
        return None
    covered = []
    for cast in re.finditer(r'\(\s*' + kind.replace(' ', r'\s+') + r'\s*\)\s*\(', clean[opening:body_end]):
        at = opening + cast.end() - 1
        closing = close(clean, at, '(', ')')
        if closing:
            covered.append((at, closing))
    reads = []
    for hit in re.finditer(r'(?<![\w.>])' + name + r'\b', clean[opening:body_end]):
        at = opening + hit.start()
        before, after = clean[opening:at], clean[at + len(name):body_end]
        if (declared.start(1) == at or re.match(r'\s*=(?!=)', after)
                or re.search(r'\(\s*' + kind + r'\s*\)\s*$', before)
                or any(a < at < b for a, b in covered)):
            continue
        reads.append(at)
    if not reads:
        return None
    text = source
    for at in sorted(reads, reverse=True):
        text = text[:at] + f'(({kind}) {name})' + text[at + len(name):]
    return text[:start] + 's32' + text[stop:]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    signature_at = clean.rfind('(', span[0], opening)
    found = []
    for m in re.finditer(r'(?<![\w*])(' + NARROW + r')\s+(' + IDENT + r')\s*(?=[,)])', clean[signature_at:opening]):
        found.append((signature_at + m.start(1), signature_at + m.end(1)))
    for m in re.finditer(r'(?m)^[ \t]*(?:register\s+)?(' + NARROW + r')\s+(' + IDENT + r')\s*;', clean[opening:end]):
        found.append((opening + m.start(1), opening + m.end(1)))
    modes = _constant_modes(clean, opening, end)
    result = [(CONSTANT_MODE_FAMILY, source[:start] + 's32' + source[stop:]) for start, stop in modes]
    for start, stop in found[:8]:
        if (start, stop) in modes:
            continue
        # An unsigned parameter shifted beyond its declared width may have been inferred from one byte store.
        # Keep logical right shifts logical when trying the word-sized parameter as well.
        kind = ' '.join(clean[start:stop].split())
        param = re.match(r'\s+(' + IDENT + r')\b', clean[stop:opening]) if start < opening else None
        width = 8 if kind in ('u8', 'unsigned char') else 16 if kind in ('u16', 'unsigned short') else None
        if param and width:
            shifts = re.findall(r'\b' + re.escape(param[1]) + r'\s*>>\s*(0[xX][0-9a-fA-F]+|\d+)', clean[opening:end])
            if any(int(value, 16 if value.lower().startswith('0x') else 10) >= width for value in shifts):
                result.append((FAMILY, source[:start] + 'u32' + source[stop:]))
        text = source[:start] + 's32' + source[stop:]
        if text != source:
            result.append((FAMILY, text))
    locals_ = [(a, b) for a, b in found if a > opening]
    for start, stop in locals_:
        cast = _widened_with_casts(source, clean, opening, end, start, stop)
        if cast:
            result.append((FAMILY, cast))
    if len(locals_) > 1:
        # (an N64 function's two halfword locals were exact only together: 402 -> 2 -> exact)
        text = source
        for start, stop in sorted(locals_, reverse=True):
            text = text[:start] + 's32' + text[stop:]
        result.append((FAMILY, text))
    return result
