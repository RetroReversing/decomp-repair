"""A switch on an unsigned value written on its signed form: `switch ((s32) p->state)`.

The other direction of `unsigned_switch` (unsigned_switch_repairs.py). m2c types a state word by the loads it sees,
often `u32`, and GCC lowers a small switch differently by the operand's signedness. SN GCC 2.8.1 dispatches four
small cases (0..3) of an unsigned index as a chain of `beq`s, and of a signed one as a compare tree split by `slti`
(`beq 1; slti 2; beqz; beq 2; beq 3`); the chain also hands the case-0 store the dispatch's own constant register,
which then cross-jumps with the other arms' state stores and moves every later arm. A 568-instruction N64 state
machine (sn-n64-281, -mfp32) went 2835 -> 40 with its inner switch's state word signed (then 0 with an unrelated local
reuse); typing the field `s32` and the cast compile alike.

Offered for each switch (up to four) whose operand is not already a signed cast, only when every case label is a
plain non-negative number below 2**31: a value that is negative as `s32` matches none of those labels either way, so
the program does not change. When `asm` is given, only when the target compares with `slti` (a signed compare tree);
the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'signed_switch'
FAMILIES = (FAMILY,)
LIMIT = 4

SWITCH = re.compile(r'\bswitch\s*\(')
CASE = re.compile(r'\bcase\s+([^:]+?)\s*:')
NUMBER = re.compile(r'(0[xX][0-9a-fA-F]+|\d+)[uUlL]*')
SIGNED_CAST = re.compile(r'^\(\s*(?:s8|s16|s32|int|signed\b[^)]*)\s*\)')
PLAIN = re.compile(r'[A-Za-z_]\w*(?:\s*(?:->|\.)\s*[A-Za-z_]\w*)*')


def _value(text):
    m = NUMBER.fullmatch(text.strip())
    return int(m[1], 0) if m else None


def variants(source, name, asm=''):
    """One child per switch: its operand cast to `s32`."""
    if asm and not re.search(r'\bslti\b', asm):
        return []
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    for sw in SWITCH.finditer(clean, span[0], span[1]):
        paren_end = close(clean, sw.end() - 1, '(', ')')
        if not paren_end:
            continue
        operand = source[sw.end():paren_end - 1].strip()
        if not operand or SIGNED_CAST.match(operand):
            continue
        opening = clean.find('{', paren_end, span[1])
        if opening < 0 or clean[paren_end:opening].strip():
            continue
        end = close(clean, opening, '{', '}')
        if not end:
            continue
        values = [_value(m[1]) for m in CASE.finditer(clean, opening, end)]
        if not values or any(v is None or v >= 2 ** 31 for v in values):
            continue
        cast = f'(s32) {operand}' if PLAIN.fullmatch(operand) else f'(s32) ({operand})'
        out.append((FAMILY, source[:sw.end()] + cast + source[paren_end - 1:]))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
