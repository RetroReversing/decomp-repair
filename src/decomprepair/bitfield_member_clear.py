"""A word cleared with a mask of contiguous bits, written as a compound clear of a wider bit-field member:
`(*(s32 *)((char *)(p) + 0x58)) &= -0x1C1;` as `((struct MaskField0 { u32 hi:16; u32 f:14; u32 lo:2; } *)...)->f &= ~0x70;`.

KMC GCC 2.7.2 (`-O2`, N64): written on the word, the `and` takes the loaded word first and the mask second
(`and $v0, $a3, $v0`): cse's fold_rtx puts an operand it knows to be constant second, whatever order the C gives.
A compound `&=` on a bit-field wider than the cleared bits is an extract, an `and` and an insert
(store_fixed_bit_field, expmed.c); combine folds the three back into one word `and` with the mask register first
(`li $v0, -0x1c1; ... and $v0, $v0, $a3`), and cse never sees the constant beside the word. Measured on toys: fields
(bit 0, 9..12 wide), (2, 14), (4, 8), (5, 4), (6, 4), (6, 10) give the mask-first order; the exact field (`f = 0` or
`f &= 0`), the whole word, a field that reaches bit 31 and a byte- or halfword-aligned field (`lhu`/`andi`) do not.
A 2,503-instruction projectile update matched 5 -> 0 with the 14-bit field at bits 2..15 that the same word's other
update (`(v & 0xFFFF0003) | (... * 4)`) shows. Which layout the game declared is not readable from one clear, so each
site gives a child per plausible layout; the reading of combine is from the output, the judge decides.

A site is `L &= K;`, or the staged `{ s32 andMask = K; andMask &= L; L = andMask; }` that mask_local_twice_set makes,
where `L` is `(*(s32 *)(ADDR))` (or `u32`/`int`) and `~K` is one run of bits below bit 31 that `andi` cannot clear.
"""
import re

from .integer_repair_support import view

FAMILY = 'bitfield_member_clear'
FAMILIES = (FAMILY,)
LIMIT = 4
TAG = 'MaskField'
_NUM = r'(?:-\s*(?:0x[0-9A-Fa-f]+|\d+)|~\s*(?:0x[0-9A-Fa-f]+|\d+)|0x[0-9A-Fa-f]+|\d+)[uUlL]*'
_LHS = r'\(\*\((?:s32|u32|int|unsigned int|unsigned) \*\)(?P<addr>\((?:[^;{}\n])+?\))\)'
_PLAIN = re.compile(rf'(?m)^(?P<ind>[ \t]*)(?P<lhs>{_LHS})\s*&=\s*(?P<k>{_NUM})\s*;[ \t]*\n')
_STAGED = re.compile(rf'(?m)^(?P<ind>[ \t]*)\{{\s*s32 (?P<v>\w+) = (?P<k>{_NUM});\s*(?P=v) &= (?P<lhs>{_LHS});\s*'
                     rf'(?P=lhs) = (?P=v);\s*\}}[ \t]*\n')


def _bits(k):
    k = re.sub(r'\s+|[uUlL]+$', '', k)
    value = ~int(k[1:], 0) if k.startswith('~') else -int(k[1:], 0) if k.startswith('-') else int(k, 0)
    bits = ~value & 0xFFFFFFFF
    if not bits or bits >> 31 or (value & 0xFFFFFFFF) <= 0xFFFF:
        return None
    low = (bits & -bits).bit_length() - 1
    run = bits >> low
    if run & (run + 1):
        return None
    return low, low + run.bit_length() - 1


def _layouts(a, b):
    out = []
    for lo, width in ((a, b - a + 2), (a - 1, b - a + 2), (0, b + 1)):
        if lo < 0 or width <= b - a + 1 or lo + width >= 32 or (lo, width) in out:
            continue
        if lo % 8 == 0 and width in (8, 16):
            continue
        out.append((lo, width))
    return out


def _struct(tag, lo, width):
    parts = [f'u32 hi:{32 - lo - width};', f'u32 f:{width};'] + ([f'u32 lo:{lo};'] if lo else [])
    return f"struct {tag} {{ {' '.join(parts)} }};"


def _sites(source, name):
    part = view(source, name)
    if not part:
        return None, []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(rf'\b{TAG}\d', clean):
        return part, []
    found = []
    for pattern in (_PLAIN, _STAGED):
        for hit in pattern.finditer(clean, lo, hi):
            span = _bits(hit['k'])
            if span and '++' not in hit['lhs'] and '--' not in hit['lhs']:
                found.append((hit, span))
    return part, sorted(found, key=lambda item: item[0].start())[:LIMIT]


def variants(source, name, header=''):
    part, sites = _sites(source, name)
    children = []
    for hit, (a, b) in sites:
        for index, (lo, width) in enumerate(_layouts(a, b)):
            tag = f'{TAG}{index}'
            mask = ((1 << (b - a + 1)) - 1) << (a - lo)
            line = f"{hit['ind']}((struct {tag} *){hit['addr']})->f &= ~0x{mask:X};\n"
            out = source[:hit.start()] + line + source[hit.end():]
            out = out[:part.opening + 1] + f'\n    {_struct(tag, lo, width)}' + out[part.opening + 1:]
            children.append((FAMILY, out))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
