"""A function-level word local that only one `case` of a switch uses, and only as a byte or halfword, declared in that
case's own block at the width it is read as: `s32 v;` ... `case 0x37: v = a + b; t = v; ... f(v & 0xFF);` as
`case 0x37: { u16 v; v = a + b; ... f(v & 0xFF); }`, and `u32 x;` ... `x = w >> 8; ... (x & 0xFF) * 12` as
`{ u8 x; x = w >> 8; ... x * 12 }`.

KMC GCC 2.7.2 (`-O2`, N64), a 1315-instruction sound-sequence interpreter: m2c's function-wide word locals are one
SImode pseudo whose sum is made in the call's argument register (`addu $a1, ..`), or whose shift is tied to the word
it reads; a narrow pseudo of the case's own (MIPS has no PROMOTE_MODE) is a separate mode, so the sum is made in `$v0`
and copied (`addu $v0; move $a1, $v0`), and the byte field's shift no longer ends the word's life (`srl $s0, $v0, 8;
srl $v0, $v0, 16`). Group-link clamp 1880 -> 1770 (`u16`), slot command 1910 -> 1880 (`u8`). The reading is from the
output; the judge decides.

A local qualifies when it is declared at the function's top as a word integer, named in exactly one case's statements,
and every read keeps only the bits of the new width: `v & K` (K fitting it), an assignment to a narrow local
(`t = v;` with `t` declared `u8`/`s8`/`u16`/`s16`, for 16 bits), or a cast to such a type. Its assignments are kept and its top declaration goes.
The case's statements are wrapped in a block that declares it; `v & 0xFF` reads of a `u8` lose the mask.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'case_local_narrow'
FAMILIES = (FAMILY,)
LIMIT = 16
_WORD = r'(?:u32|s32|int|unsigned int|unsigned|long|unsigned long)'
_NARROW8 = r'(?:u8|s8|unsigned char|signed char|char)'
_NARROW16 = r'(?:u16|s16|unsigned short|short)'
_CASE = re.compile(r'(?m)^(?P<ind>[ \t]*)(?:case\s+[^:\n]+|default)\s*:[ \t]*\n')


def _read_bits(seg, local, narrow8, narrow16):
    """The widest bits any read of `local` in `seg` keeps, or None when a read keeps the whole word."""
    widest = 0
    for m in re.finditer(rf'(?<![\w.>]){re.escape(local)}\b', seg):
        after = seg[m.end():]
        if re.match(r'\s*=(?!=)', after):
            continue  # an assignment
        mask = re.match(r'\s*&\s*(0[xX][0-9a-fA-F]+|\d+)\b', after)
        cast = re.search(r'\(\s*(u8|s8|u16|s16)\s*\)\s*\(?\s*$', seg[:m.start()])
        dest = re.search(rf'(?:^|[;{{}}\n])\s*({IDENT})\s*=\s*$', seg[:m.start()])
        if mask and re.match(r'\s*[;)]', after[mask.end():]):
            value = int(mask.group(1), 0)
            bits = 8 if value <= 0xFF else 16 if value <= 0xFFFF else None
        elif cast:
            bits = 8 if cast.group(1) in ('u8', 's8') else 16
        elif dest and re.match(r'\s*;', after) and (dest.group(1) in narrow8 or dest.group(1) in narrow16):
            bits = 8 if dest.group(1) in narrow8 else 16
        else:
            return None
        if bits is None:
            return None
        widest = max(widest, bits)
    return widest or None


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    body = clean[lo:hi]
    words = {m.group(1): m for m in re.finditer(rf'(?m)^[ \t]*(?:register\s+)?{_WORD}[ \t]+({IDENT})[ \t]*;[ \t]*\n', clean[lo:hi])}
    narrow8 = set(re.findall(rf'(?m)^[ \t]*(?:register\s+)?{_NARROW8}[ \t]+({IDENT})[ \t]*;', body))
    narrow16 = set(re.findall(rf'(?m)^[ \t]*(?:register\s+)?{_NARROW16}[ \t]+({IDENT})[ \t]*;', body))
    cases = list(_CASE.finditer(clean, lo, hi))
    out = []
    for k, case in enumerate(cases):
        start = case.end()
        end = cases[k + 1].start() if k + 1 < len(cases) else None
        if end is None:
            close = re.search(r'(?m)^[ \t]*\}', clean[start:hi])
            end = start + close.start() if close else hi
        seg = clean[start:end]
        if seg.count('{') != seg.count('}') or not re.search(r'\bbreak\s*;\s*\}?\s*$', seg):
            continue
        for local in words:
            if not re.search(rf'\b{re.escape(local)}\b', seg):
                continue
            outside = clean[lo:start] + clean[end:hi]
            if len(re.findall(rf'\b{re.escape(local)}\b', outside)) != 1:
                continue  # its declaration, and nothing else
            bits = _read_bits(seg, local, narrow8, narrow16)
            if not bits:
                continue
            kinds = ('u8',) if bits == 8 else ('u16', 's16')
            for kind in kinds:
                text = source[start:end]
                if kind == 'u8':
                    text = re.sub(rf'(?<![\w.>]){re.escape(local)}\s*&\s*(?:0[xX]0*[fF][fF]|255)\b(?=\s*[;)])', local, text)
                ind = case['ind']
                inner = text.rstrip('\n')
                new = f'{ind}{{\n{ind}  {kind} {local};\n{inner}\n{ind}}}\n'
                decl = words[local]
                d0, d1 = lo + decl.start(), lo + decl.end()
                out.append((FAMILY, source[:d0] + source[d1:start] + new + source[end:]))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
