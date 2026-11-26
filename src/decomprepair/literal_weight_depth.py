"""One statement that reads a float literal, wrapped in two (or three) one-shot scopes: the literal outranks another.

loop.c moves a float constant used in a loop to the preheader, where it becomes a pseudo with one set outside the loop
and one reference per use inside it, each counted once more per loop round it (flow.c, `REG_N_REFS += loop_depth`).
global.c ranks `floor_log2 (refs) * refs / live length`, so a constant read once in the loop (3 references) loses its
float register to one read twice (5), and the loser of the last register is kept in an integer register.

On a 149-instruction N64 distance check (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`) the source had the target's
instructions everywhere but `1.0f` and `0.025f` held each other's registers and a position stayed in a float register
the target spills to `$s4`. Wrapping the one statement that reads `1.0f` once (`run_weight_scope`) reached 230 from 675;
two scopes round it (5 references against the other constant's 5, with a shorter life) reached 205 and the registers
were the target's. `run_weight_scope` wraps each unit once and `statement_scope_weight` only the top-level statements
of a loop body, so no family reached a nested statement twice. The compiler's reasons are read from the allocation
table, not confirmed in its source. The scopes are scaffolding no developer wrote; polishing removes them.

One child per simple statement inside a loop that holds a float literal other than zero, per depth; the judge decides."""
import re

from .integer_repair_support import edit, view
from .run_weight_scope import units

FAMILY = 'literal_weight_depth'
FAMILIES = (FAMILY,)
LIMIT = 32
DEPTHS = (2, 3)
_LITERAL = re.compile(r'(?<![\w.])(?:\d+\.\d*|\.\d+)(?:[eE][-+]?\d+)?[fF]?(?![\w.])')
_LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')


def _loops(part):
    """[(start, end)] of the bodies of the function's loops (`do { } while (0)` scopes aside)."""
    clean, found = part.clean, []
    for hit in _LOOP.finditer(clean, part.opening, part.end):
        if hit.group().startswith('do'):
            opening = hit.end() - 1
        else:
            depth, at = 0, hit.end() - 1
            while at < part.end:
                depth += (clean[at] == '(') - (clean[at] == ')')
                at += 1
                if not depth:
                    break
            opening = re.compile(r'\s*\{').match(clean, at)
            if not opening:
                continue
            opening = opening.end() - 1
        depth, at = 0, opening
        while at < part.end:
            depth += (clean[at] == '{') - (clean[at] == '}')
            at += 1
            if not depth:
                break
        if hit.group().startswith('do') and re.match(r'\s*while\s*\(\s*0\s*\)', clean[at:]):
            continue
        found.append((opening, at))
    return found


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    loops = _loops(part)
    if not loops:
        return []
    picked = []
    for start, end, text, _, kind in units(source, name):
        if kind != 2 or not any(a < start and end < b for a, b in loops):
            continue
        if any(float(m.rstrip('fF')) for m in _LITERAL.findall(part.clean[start:end])):
            picked.append((start, end, text.strip()))
    picked.sort()
    result = []
    for depth in DEPTHS:
        for start, end, text in picked:
            result.append((FAMILY, edit(source, [(start, end, 'do { ' * depth + text + ' } while (0);' * depth)])))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 91}
