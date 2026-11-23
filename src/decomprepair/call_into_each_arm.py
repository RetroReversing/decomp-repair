"""A call written once after an `if`/`else` chain, written at the end of each arm: the arms' shared `jal` is then cross-jumped.

m2c writes a call that every arm of a chain reaches once, after the chain, with the arms setting the variables it takes:

    if (border) { t = f(k); a3 = g(k); a1 = t; } else { switch (mode) { ... a1 = 0x11; ... } a3 = 0; }
    h(obj, a1, 1, a3);

gcc 2.7.2 then loads the call's arguments once, after the join, and the delay slot of the one `jal` is filled from the
join. The game's code has the call in each arm; the final `jump_optimize` cross-jumps the two identical `jal`s (and their
delay slots) into one, which leaves each arm to set its own argument registers before the shared jump. That is the
object code an arm-by-arm write produces, and no spelling of the one call after the join reaches it (a 795-instruction
object-spawner function of an N64 game: 1615 -> 745, with three register rows left from the same hunk). The reading is a
hypothesis from jump.c (cross-jumping merges jumps to one label whose preceding insns match); the judge decides.

The shape: a statement call directly after the closing brace of an `else` block of a braced `if`/`else` chain, at least one
of whose arguments is a variable some arm assigns. One child copies the call to the end of every arm that falls through
to it (an arm ending in `return`, `goto`, `break` or `continue` is left alone) and removes the original. The sibling
family `call_into_arms` (tail_call_arm_repairs) covers the narrower case of one variable set only as each arm's last
statement; this one keeps the variables, which is what the 795-instruction function needed.
"""
import re

from .arm_block_support import IDENT, KEYWORDS, arm_chain, brace_pairs, indentation, line_start
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'call_into_each_arm'
FAMILIES = (FAMILY,)

CALL = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<callee>{IDENT})\s*\(')
EXITS = re.compile(r'(?:return|goto|break|continue)\b[^;{}]*;\s*$')


def _assigned(text):
    return set(re.findall(rf'(?<![\w.>\]])({IDENT})\s*(?:[-+*/|&^]|<<|>>)?=(?!=)', text))


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    by_close = {close_at: open_at for open_at, close_at in pairs.items()}
    out = []
    for hit in CALL.finditer(clean, part.opening + 1, part.end - 1):
        if hit['callee'] in KEYWORDS:
            continue
        opening = hit.end() - 1
        end = close(clean, opening, '(', ')')
        if not end:
            continue
        stop = re.match(r';[ \t]*(?=\n)', clean[end:])
        if not stop:
            continue
        before = clean[:hit.start()].rstrip()
        if not before.endswith('}'):
            continue
        blocks = arm_chain(clean, by_close, len(before) - 1)
        if not blocks:
            continue
        arms = ' '.join(clean[a + 1:b] for a, b in blocks)
        arguments = clean[opening + 1:end - 1]
        if not set(re.findall(IDENT, arguments)) & _assigned(arms):
            continue
        edits = []
        for a, b in blocks:
            if EXITS.search(clean[a + 1:b].rstrip()):
                continue
            if clean[line_start(clean, b):b].strip():
                break  # the closing brace shares its line with a statement: not rewritten
            inner = indentation(clean, b) + '  '
            edits.append((line_start(clean, b), line_start(clean, b), inner + source[hit.start('callee'):end].strip() + ';\n'))
        else:
            if not edits:
                continue
            first = line_start(clean, hit.start())
            last = end + stop.end()
            edits.append((first, last + 1, ''))
            text = edit(source, edits)
            if text != source and (FAMILY, text) not in out:
                out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 60}  # the registry: no caller wiring (registry.py)
