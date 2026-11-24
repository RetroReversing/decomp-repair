"""A table's cursor and byte offset that step with a counter, as reads through the counter: `k = 0; ..; { u32 off = 0;
q = T; do { if (*q == c) { ..; off += 4; q++; k++; .. } } while (*(u32 *)((char *)T + off) != 0); }` as `if (T[k] ==
c)` and `while (*(u32 *)((char *)T + (k << 2)) != 0)`, with the cursor and the offset gone.

KMC GCC 2.7.2 (`-O2`, N64), loop.c `strength_reduce`: the outer loop's reads of `T[k]` are givs of the counter `k`,
which an inner loop increments; the reduced registers' increments are emitted at the counter's own increment, after
the inner loop's givs (the target's `addiu $t0,4; addiu $a2,4; addiu $t6,4; ..; addiu $t5,4` then `k++` in the delay
slot). Source cursors (`q++`, `off += 4`) are incremented where they are written instead, before the givs. The exit
test's address stays `(plus (reg) (symbol))` (the target's `lui $v0,%hi(T); addu $v0,$v0,$t6; lw $v0,%lo(T)($v0)`)
only when the byte offset is a register already at expansion: `(k << 2)` is a shift insn, where `k * 4` or `T[k]`
expand to a multiply that `memory_address` forces through a temporary holding `T`.

On a 681-instruction bit-stream decoder's code-assignment pass, both at once 235 -> 230 (the cursor alone 245, the
offset alone 450); checked on 1200 generated streams. Offered: both, and each alone.

Rewrites a block that declares `E off = 0;` (or sets it) and sets a pointer `q = T;` (`T` a global array), when the
statements `off += sizeof;`, `q++;` and `k++;` sit together in one loop body and the counter `k` is set to 0 before the
block with no other assignment in between. The reads `*q` become `T[k]` and `*(E *)((char *)T + off)` becomes
`*(E *)((char *)T + (k << S))` for a 4-byte (S = 2) or 2-byte (S = 1) element. Declines on `volatile`.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'stepped_cursor_index'
FAMILIES = (FAMILY,)

_SHIFT = {'4': 2, '2': 1}


def _line(clean, at):
    start = clean.rfind('\n', 0, at) + 1
    end = clean.find('\n', at)
    return start, end + 1


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    out = []
    for steps in re.finditer(rf'(?m)^[ \t]*({IDENT})\s*\+=\s*([24])\s*;\s*\n[ \t]*({IDENT})\s*\+\+\s*;\s*\n[ \t]*({IDENT})\s*\+\+\s*;',
                             clean[lo:hi]):
        off, size, cursor, counter = steps.group(1), steps.group(2), steps.group(3), steps.group(4)
        at = lo + steps.start()
        init_off = None
        for m in re.finditer(rf'(?m)^[ \t]*(?:u32\s+|s32\s+)?{off}\s*=\s*0\s*;[ \t]*\n', clean[lo:at]):
            init_off = m
        init_cursor = None
        for m in re.finditer(rf'(?m)^[ \t]*{cursor}\s*=\s*({IDENT})\s*;[ \t]*\n', clean[lo:at]):
            init_cursor = m
        if not init_off or not init_cursor:
            continue
        table = init_cursor.group(1)
        first = lo + min(init_off.start(), init_cursor.start())
        zero = None
        for m in re.finditer(rf'(?m)^[ \t]*{counter}\s*=\s*0\s*;', clean[lo:first]):
            zero = m
        if not zero or re.search(rf'(?<![\w.>]){counter}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|\+\+\s*{counter}|{counter}\s*\+\+',
                                 clean[lo + zero.end():first]):
            continue
        # the uses, after the inits; any other assignment to the cursor or the offset declines
        depth, opening = 0, None
        for i in range(first - 1, lo - 1, -1):  # the block the inits are in
            depth += (clean[i] == '}') - (clean[i] == '{')
            if depth < 0:
                opening = i
                break
        if opening is None:
            continue
        depth, scope_end = 0, None
        for i in range(opening, hi):
            depth += (clean[i] == '{') - (clean[i] == '}')
            if depth == 0:
                scope_end = i
                break
        if scope_end is None or scope_end < at:
            continue
        body = clean[first:scope_end]
        sets = re.findall(rf'(?<![\w.>])(?:{cursor}|{off})\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|(?:{cursor}|{off})\s*(?:\+\+|--)', body)
        if len(sets) != 4:
            continue
        reads_cursor = [m for m in re.finditer(rf'\*\s*{cursor}\b(?!\s*\+\+)', body)]
        reads_off = [m for m in re.finditer(
            rf'\*\s*\(\s*(\w+)\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*{table}\s*\+\s*{off}\s*\)', body)]
        if not reads_cursor and not reads_off:
            continue
        shift = _SHIFT[size]
        cur_line = _line(clean, lo + steps.start(3))
        off_line = _line(clean, lo + steps.start(1))
        cur_init = _line(clean, lo + init_cursor.start() + len(init_cursor.group(0)) - 2)
        off_init = _line(clean, lo + init_off.start() + len(init_off.group(0)) - 2)
        cursor_edits = [(cur_line[0], cur_line[1], ''), (cur_init[0], cur_init[1], '')] + [
            (first + m.start(), first + m.end(), f'{table}[{counter}]') for m in reads_cursor]
        off_edits = [(off_line[0], off_line[1], ''), (off_init[0], off_init[1], '')] + [
            (first + m.start(), first + m.end(), f'*({m.group(1)} *)((char *){table} + ({counter} << {shift}))') for m in reads_off]
        rest = clean[first:scope_end]
        for start, end, _ in sorted(cursor_edits, reverse=True):
            rest = rest[:start - first] + rest[end - first:]
        if re.search(rf'\b{cursor}\b', rest):
            cursor_edits = []  # the cursor has another use: only the offset goes
            reads_cursor = []
        if reads_cursor and reads_off:
            out.append((FAMILY, edit(source, cursor_edits + off_edits)))
        if reads_cursor:
            out.append((FAMILY, edit(source, cursor_edits)))
        if reads_off:
            out.append((FAMILY, edit(source, off_edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
