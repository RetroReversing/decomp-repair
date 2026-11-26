"""A local set only from `E & 0xFF` (or `& 0xFFFF`), retyped to the unsigned type the mask implies with the mask dropped, or the reverse.

m2c writes a byte as a wider local with an explicit mask: `s16 t; t = (x >> 0x1F) & 0xFF;`. The compiler folds a
redundant `&` away when the local is a halfword or word it can already prove narrow, so the target's `andi $a0, $a0,
0xFF` is not emitted from that spelling (measured, KMC GCC 2.7.2 `-O2 -G0 -mips3 -mgp32 -mfp32`, a 40-instruction
function that stores one flag byte to four table slots): `s16 t = E & 0xFF` was 100 with the `andi` missing, and
`u8 t = E` (no mask) was exact: the narrow local carries the zero-extension that the target's `andi` is, and
`masked_local_narrow` (which keeps the mask, and takes only word-typed locals) could not offer it from an `s16`.

Offered for a plain local of the function (declared once, no initialiser, not volatile, not an array, pointer or float,
address never taken, not touched by compound assignments or `++`/`--`) whose every assignment is a whole statement
`name = E & MASK;` (MASK `0xFF` or `0xFFFF`, either operand order):
- `retype_drop`: `u8`/`u16` and every mask removed (one child per local, and one with all);
- `retype_keep`: the same type with the masks kept, when the local's type was not already that one.
When `asm` is given and has no `andi ... 0xFF` (`0xFFFF`), nothing is offered: the target has no such zero-extension, so
a mask is not what is missing.

The reverse (`narrow_unmask`): a `u8`/`u16` local whose every assignment is an unmasked, non-constant expression, in a
function whose target has the `andi` and whose source has no mask of that width, becomes `s32` with each assignment
`E & 0xFF`. A hypothesis like every other family's: the judge decides.
"""
import re

from .case_temporary_repairs import DECLARATION, _mentions
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'mask_local_retype'
REVERSE = 'narrow_unmask'
FAMILIES = (FAMILY, REVERSE)
LIMIT = 8
INTEGER = ('s8', 'u8', 's16', 'u16', 's32', 'u32', 'int', 'unsigned int', 'signed int', 'unsigned', 'short',
           'unsigned short', 'char', 'unsigned char', 'signed char', 'signed short')
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'
MASK = re.compile(rf'\s*=(?!=)\s*(?P<rhs>[^;{{}}]*?[^;{{}}\s])\s*&\s*(?P<mask>{NUMBER})[uUlL]*\s*;')
REVERSED = re.compile(rf'\s*=(?!=)\s*(?P<mask>{NUMBER})[uUlL]*\s*&\s*(?P<rhs>[^;{{}}]*[^;{{}}\s])\s*;')
PLAIN = re.compile(r'\s*=(?!=)\s*(?P<rhs>[^;{}]*?[^;{}\s])\s*;')
ANDI = re.compile(r'\bandi\s+\$\w+\s*,\s*\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)')
NARROW = {0xFF: 'u8', 0xFFFF: 'u16'}


def _scan(clean, var, opening, end, decl):
    """Every assignment of `var` as (start, end, rhs, mask or None), or None when the local isn't a plain one."""
    kind = re.sub(r'\b(?:register)\b', '', decl['type'])
    kind = re.sub(r'\s+', ' ', kind).strip()
    if kind not in INTEGER or 'volatile' in decl['type'] or '*' in decl['type']:
        return None
    pattern = _mentions(var)
    found = []
    for m in pattern.finditer(clean, opening + 1, end):
        if decl.start() <= m.start() < decl.end():
            continue
        before = clean[max(opening, m.start() - 2):m.start()]
        after = clean[m.end():m.end() + 400]
        if re.search(r'&\s*$', before) and not re.search(r'&&\s*$', before):
            return None
        if re.match(r'\s*(?:\+\+|--|[-+*/%|&^]=|<<=|>>=|\[)', after) or re.search(r'(?:\+\+|--)\s*$', before):
            return None
        if re.match(r'\s*=(?!=)', after):
            if not re.search(r'(?:^|[;{}])\s*$', clean[:m.start()]):
                return None
            hit = MASK.match(after) or REVERSED.match(after)
            if hit and int(hit['mask'], 0) in NARROW:
                found.append((m.end(), m.end() + hit.end(), hit['rhs'], int(hit['mask'], 0)))
                continue
            plain = PLAIN.match(after)
            if not plain:
                return None
            found.append((m.end(), m.end() + plain.end(), plain['rhs'], None))
    return kind, found


def variants(source, name, asm=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    params = set(re.findall(r'[A-Za-z_]\w*', clean[span[0]:opening]))
    seen = {}
    for m in DECLARATION.finditer(clean, opening + 1, end):
        if clean[opening + 1:m.start()].count('{') == clean[opening + 1:m.start()].count('}'):
            seen[m['name']] = None if m['name'] in seen else m
    masks = {int(x, 0) for x in ANDI.findall(asm or '')}
    out = []
    for var, decl in seen.items():
        if decl is None or var in params:
            continue
        scanned = _scan(clean, var, opening, end, decl)
        if not scanned or not scanned[1]:
            continue
        kind, found = scanned
        widths = {w for _, _, _, w in found}
        if None not in widths and len(widths) == 1:
            width = widths.pop()
            if asm and width not in masks:
                continue
            narrow = NARROW[width]
            register = 'register ' if re.search(r'\bregister\b', decl['type']) else ''
            line = f"{decl['indent']}{register}{narrow} {var};\n"
            drop = [(s, e, f' = {r};') for s, e, r, _ in found]
            out.append((FAMILY, (decl, line, drop, var)))
            if kind != narrow:
                out.append((FAMILY, (decl, line, [], var)))
        elif widths == {None} and kind in ('u8', 'u16', 'unsigned char', 'unsigned short') and asm:
            width = 0xFF if kind in ('u8', 'unsigned char') else 0xFFFF
            if width not in masks or re.search(rf'&\s*(?:0[xX]0*{width:X}|{width})\b', clean[opening:end], re.I):
                continue
            if any(re.fullmatch(NUMBER, r.strip()) or '(' not in r and '[' not in r and ' ' not in r.strip() for _, _, r, _ in found):
                continue
            register = 'register ' if re.search(r'\bregister\b', decl['type']) else ''
            line = f"{decl['indent']}{register}s32 {var};\n"
            wide = [(s, e, f' = ({r}) & 0x{width:X};') for s, e, r, _ in found]
            out.append((REVERSE, (decl, line, wide, var)))
    if not out:
        return []

    def build(items):
        edits = []
        for decl, line, rewrites, _ in items:
            edits.append((decl.start(), decl.end(), line))
            edits.extend(rewrites)
        text = source
        for s, e, r in sorted(edits, reverse=True):
            text = text[:s] + r + text[e:]
        return text

    children = []
    for family, item in out:
        children.append((family, build([item])))
    for family in (FAMILY, REVERSE):
        group = [item for f, item in out if f == family and item[2]]
        if len({i[3] for i in group}) > 1:
            first = {}
            for item in group:
                first.setdefault(item[3], item)
            children.append((family, build(list(first.values()))))
    return [(f, t) for f, t in children if t != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 44}
