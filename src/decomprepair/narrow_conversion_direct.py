"""A float stored into a narrow field through an `int` cast, converted directly, with the masked word update after it
kept in an integer local the function has finished with.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) object initialiser (392 instructions, 197 -> 27). Its
draft stored a float into a halfword field the way m2c spells the conversion, and updated the flag word right after:

    rec->x78 = (s16) ((s32) obj->f40);
    rec->x7A = 0;
    temp = rec->flags & 3;
    rec->flags = temp | 0x8010;

The target fills the `mfc1`'s delay with the `andi` (`trunc.w.s; mfc1 $v0; andi $a1,$v1,3; sh $v0; ori $v0,$a1,..`);
the draft put the `andi` above the conversion, so the flag load and the conversion shared `$v0` and a `nop` followed
the `mfc1`. Two edits, neither of which moved anything alone (each 197 -> 197 or worse), gave the target's six rows:

  * the conversion written directly, `(s16) (obj->f40)`: the narrowing then comes after the `fix:SI` as a copy of
    its own (`(set (reg:HI) (subreg:HI (reg:SI)))`, read in the first scheduler's dump), and the first scheduler
    issues the conversion ahead of the flag word's `and`, so the conversion's value and the loaded word are live
    together and take `$v0` and `$v1`;
  * the masked word held in a local the function reuses (the loop counter `i`, written before its next read), not a
    one-off temporary: a one-off temporary is local to the block, ties to the loaded word that dies in the `and`
    (`$v1`), and, set once, is boosted by the first scheduler as a "birthing" insn above the conversion; the reused
    local is global (`$a1`) and is not.

Both are hypotheses from the dumps of this one function, not proven from the compiler source.

narrow_conversion_direct
    Each `(T) ((s32) EXPR)` with `T` an 8- or 16-bit integer type (`(int)`/`(u32)` inner casts too) written as
    `(T) (EXPR)`; one child per conversion.
narrow_conversion_rmw_reuse
    The same edit, combined with the first masked update that follows the conversion in its block (`t = W OP K;` then
    `W = t OP2 K2;`, `t` a top-level integer local) written through another top-level integer local `y` that does
    not occur in the update, has no address taken and is written before its next read (and, inside a loop, before
    every read in the loop): one child per `y`, at most three per conversion, the locals the code reaches soonest after
    the update first (the game reused the counter of the loop that follows).

The exact judge decides every child.
"""
import re

from .c_scan import close
from .dead_scratch_reuse import _valid
from .integer_repair_support import DECL, view

FAMILY = 'narrow_conversion_direct'
REUSE = 'narrow_conversion_rmw_reuse'
FAMILIES = (FAMILY, REUSE)
LIMIT = 8
PER_CONVERSION = 3
NARROW = r'(?:[su]8|[su]16|(?:un)?signed\s+(?:char|short)|char|short)'
_CAST = re.compile(rf'\(\s*{NARROW}\s*\)\s*\((?P<inner>\s*\(\s*(?:s32|u32|int|unsigned\s+int)\s*\)\s*)')
_IDENT = r'[A-Za-z_]\w*'


def _conversions(clean, low, high):
    """(start, end) of each inner `(s32) ` cast to drop, inside a narrow cast's own parentheses."""
    out = []
    for hit in _CAST.finditer(clean, low, high):
        opening = hit.start('inner') - 1
        if close(clean, opening, '(', ')') < 0:
            continue
        out.append(hit.span('inner'))
    return out


def _update(clean, start, high):
    """The first `t = W OP K; W = t OP2 K2;` pair after `start` in the same block: (t, span of the pair)."""
    depth = 0
    for i in range(start, high):
        if clean[i] in '{}':
            if clean[i] == '}':
                depth -= 1
                if depth < 0:
                    return None
            else:
                depth += 1
            continue
        if depth or clean[i] != '\n':
            continue
        pair = re.match(rf'\n[ \t]*(?P<t>{_IDENT})[ \t]*=[ \t]*(?P<w>[^;=\n]+?)[ \t]*[&|^][ \t]*[^;\n]+;[ \t]*\n'
                        rf'[ \t]*(?P<w2>[^;=\n]+?)[ \t]*=[ \t]*(?P=t)[ \t]*[&|^][ \t]*[^;\n]+;', clean[i:high])
        if pair and re.sub(r'\s+', '', pair['w']) == re.sub(r'\s+', '', pair['w2']):
            return pair['t'], (i + pair.start('t'), i + pair.end())
    return None


def variants(source, name):
    """Proposals: narrow conversions written directly, alone and with the masked update after them reusing a local."""
    part = view(source, name)
    if not part:
        return []
    clean, low, high = part.clean, part.opening + 1, part.end
    declared = [m for m in DECL.finditer(clean, low, high)]
    integers = [m['name'] for m in declared]
    out = []
    for start, end in _conversions(clean, low, high):
        direct = source[:start] + source[end:]
        out.append((FAMILY, direct))
        found = _update(clean, end, high)
        if not found or found[0] not in integers:
            continue
        temp, (first, last) = found
        shift = end - start
        candidates = []
        for other in dict.fromkeys(integers):
            if other == temp or re.search(rf'&\s*{re.escape(other)}\b', clean[low:high]):
                continue
            if not _valid(clean, low, high, temp, other, first, last):
                continue
            later = re.search(rf'(?<![\w.>]){re.escape(other)}(?!\w)', clean[last:high])
            candidates.append((later.start() if later else high, other))
        for _, other in sorted(candidates)[:PER_CONVERSION]:
            stretch = re.sub(rf'(?<![\w.>]){re.escape(temp)}(?!\w)', other, source[first:last])
            out.append((REUSE, direct[:first - shift] + stretch + direct[last - shift:]))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 62}
