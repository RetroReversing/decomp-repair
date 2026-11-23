"""A word local that only ever holds `expr & MASK`, declared as the byte or halfword the mask fits.

m2c declares every local as a word. A local that is set only from a masked value (`index = flags & 0xF;`, the low
nibble of a halfword the routine just read) is the game's `u8`/`u16` local, and the compiler treats the two differently:
a narrow local is a promoted subreg pseudo, so the `andi` that sets it and the zero-extension the word form needs
are one insn, and the pseudo no longer takes the register of the `and`'s temporary by preference. On a 578-instruction
menu routine (`gcc-2.7.2-kmc -O2 -G0 -mips3 -mgp32 -mfp32`) the `s32` form left the state pointer and the record pointer one
register off in both arms of a lookup and every later register of the block with them: 1040 -> 660 with the local written
`u8`, and no family offered it (`byte_parameter_sign` and `masked_counter_repairs` handle byte counters and
parameters, not a local set from a mask).

Offered only when the meaning is unchanged: a plain local of the function (declared once, no initialiser, not `volatile`,
not an array, pointer or float, its address never taken) whose every assignment is a whole statement `name = E & MASK;`
with a literal mask of 1..0xFFFF (the value then fits the narrow type), and which no compound assignment, `++` or
`--` touches. `u8` for masks up to 0xFF, `u16` above; `register` is kept.

`variants` gives, labelled `masked_local_narrow`, one child per such local and one with all of them.
"""
import re

from .case_temporary_repairs import DECLARATION, _mentions
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'masked_local_narrow'
FAMILIES = (FAMILY,)
LIMIT = 8
WORD_TYPES = ('s32', 'int', 'u32', 'unsigned int', 'signed int', 'long', 'unsigned long', 'unsigned')
MASK = re.compile(r'\s*=(?!=)\s*(?P<rhs>[^;{}]*?[^;{}\s])\s*&\s*(?P<mask>0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*;')
REVERSED = re.compile(r'\s*=(?!=)\s*(?P<mask>0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*&\s*(?P<rhs>[^;{}]*[^;{}\s])\s*;')


def _mask_value(text):
    return int(text, 0)


def _narrow_type(clean, var, opening, end, decl):
    kind = re.sub(r'\b(?:register|signed)\b', '', decl['type']).strip()
    kind = re.sub(r'\s+', ' ', kind)
    if kind not in WORD_TYPES or 'volatile' in decl['type'] or '*' in decl['type'] or '[' in clean[decl.start():decl.end()]:
        return None
    pattern = _mentions(var)
    widest = 0
    assigns = 0
    for m in pattern.finditer(clean, opening + 1, end):
        if decl.start() <= m.start() < decl.end():
            continue
        before = clean[max(opening, m.start() - 2):m.start()]
        after = clean[m.end():m.end() + 80]
        if re.search(r'&\s*$', before) and not re.search(r'&&\s*$', before):
            return None  # (address taken)
        if re.match(r'\s*(?:\+\+|--|[-+*/%|&^]=|<<=|>>=)', after) or re.search(r'(?:\+\+|--)\s*$', before):
            return None
        if re.match(r'\s*=(?!=)', after):
            hit = MASK.match(after) or REVERSED.match(after)
            if not hit or not re.search(r'(?:^|[;{}])\s*$', clean[:m.start()]):
                return None
            value = _mask_value(hit['mask'])
            if not 0 < value <= 0xFFFF:
                return None
            widest = max(widest, value)
            assigns += 1
    if not assigns:
        return None
    return 'u8' if widest <= 0xFF else 'u16'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    names = {}
    for m in DECLARATION.finditer(clean, opening + 1, end):
        if clean[opening + 1:m.start()].count('{') == clean[opening + 1:m.start()].count('}'):
            names[m['name']] = None if m['name'] in names else m
    targets = []
    for var, decl in names.items():
        if decl is None or var in _parameters(clean, span[0], opening):
            continue
        narrow = _narrow_type(clean, var, opening, end, decl)
        if narrow:
            targets.append((var, decl, narrow))
    if not targets:
        return []

    def build(chosen):
        text = source
        for var, decl, narrow in sorted(chosen, key=lambda t: -t[1].start()):
            register = 'register ' if re.search(r'\bregister\b', decl['type']) else ''
            text = text[:decl.start()] + f"{decl['indent']}{register}{narrow} {var};\n" + text[decl.end():]
        return text

    out = [(FAMILY, build([t])) for t in targets]
    if len(targets) > 1:
        out.append((FAMILY, build(targets)))
    return [(f, t) for f, t in out if t != source][:LIMIT]


def _parameters(clean, start, opening):
    return set(re.findall(r'[A-Za-z_]\w*', clean[start:opening]))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 44}
