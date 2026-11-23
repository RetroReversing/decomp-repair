"""A local declared before another of its type, so it wins global.c's tie between them.

GCC 2.7.2's `global.c` colours pseudos in the order of `allocno_compare`: the priority
`floor_log2 (refs) * refs / live_length * 10000 * size` truncated to an integer, and when two pseudos come out equal,
the lower allocno number first. Allocno numbers follow pseudo numbers, and pseudo numbers follow the order the
declarations were expanded: a function-level local is numbered when the function starts, a local declared at the top
of an inner block only when that block is entered (`declaration_scope_hoist` has the same numbering for spill slots).
Two accumulators that are read and written the same number of times and live almost exactly as long therefore end up
equal, and the one declared first takes the lower callee-saved register.

A 3034-instruction actor-motion handler (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) kept the x and z offsets of a
move in two floats held in `$s5` and `$s6`; an earlier search had declared the x one at the top of an inner block, after
the function-level z one. Both had 24 references and lives of 1769 and 1771 instructions, the same priority 542 once
truncated, so the z one (the lower pseudo) took `$s5` and every one of their 48 `mtc1`/`mfc1`/`move` rows was swapped
(240 in the app's judge). Declared at function level just before the z one, it took `$s5`: 240 -> 0.

For each local of a plain scalar or pointer type declared without an initializer, whose name is declared once, the
child moves its declaration to the function's own declarations right before another function-level local of exactly
the same type that it now follows (one declared later in the function, or one declared at the top of an inner block).
Inner-block locals come first (their late numbering is the usual accident of an earlier search), then pairs whose
names occur equally often in the function, most often first: those are the long-lived pairs whose priorities can tie.
Hypothesis about which pair matters; the judge decides.
"""
import re

from .declaration_scope_hoist import _depth, _line, _statement_block
from .declaration_scope_sink_repairs import CONTROL, DECLARATION, KEYWORDS, _blocks
from .integer_repair_support import IDENT, edit, view

FAMILY = 'priority_tie_declaration_order'
FAMILIES = (FAMILY,)
LIMIT = 8


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    blocks = _blocks(clean, part.opening, part.end)
    outer = [block for block in blocks if block[0] == part.opening]
    if not outer:
        return []
    body_start, body_end = part.opening + 1, outer[0][1]
    top, inner = [], []
    for match in DECLARATION.finditer(clean, body_start, body_end):
        if CONTROL.search(match['type']) or match['type'].strip().split()[-1] in KEYWORDS:
            continue
        if clean[:match.start('type')].rstrip()[-1:] not in ('', ';', '{', '}'):
            continue
        if _depth(clean, body_start, match.start()) == 0:
            top.append(match)
        elif _statement_block(clean, blocks, match.start()):
            inner.append(match)
    if not top:
        return []
    body = clean[body_start:body_end]
    declared = {}
    for kind, local in re.findall(rf'(?<![\w.>])({IDENT})[\s*]+({IDENT})\s*[;,\[=](?!=)', body):
        if kind not in KEYWORDS:
            declared[local] = declared.get(local, 0) + 1

    def uses(local):
        return len(re.findall(rf'(?<![\w.>]){re.escape(local)}\b', body))

    def kind(match):
        return ' '.join(source[match.start('type'):match.end('type')].split())

    candidates = []
    for mover in top + inner:
        if declared.get(mover['name']) != 1 or re.search(rf'&\s*{re.escape(mover["name"])}\b', body):
            continue
        for other in top:
            if other is mover or kind(other) != kind(mover) or declared.get(other['name']) != 1:
                continue
            if mover in top and other.start() > mover.start():
                continue  # already declared first
            a, b = uses(mover['name']), uses(other['name'])
            candidates.append(((mover not in inner, abs(a - b), -min(a, b), -other.start()), mover, other))
    candidates.sort(key=lambda item: item[0])
    found = []
    for _, mover, other in candidates:
        start, end = _line(clean, mover)
        at = _line(clean, other)[0]
        indent = re.match(r'[ \t]*', source[at:])[0]
        text = f'{indent}{source[mover.start("type"):mover.end()].strip()}\n'
        child = edit(source, [(start, end, ''), (at, at, text)])
        if child != source and all(child != c for _, c in found):
            found.append((FAMILY, child))
        if len(found) >= LIMIT:
            break
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
