"""A byte constant compared in a loop, written as a local set among the entry assignments.

KMC gcc 2.7.2 hoists a literal that a loop compares against (`x != 0xFF`, which no `beq` can take as an immediate) into a
saved register with `li`, and loop.c puts that `li` just before the loop. m2c leaves the literal in each comparison, so
the `li` lands after every assignment that precedes the loop. In a 219-instruction N64 sequencer function (`-G0 -mips3
-mgp32 -mfp32 -O2`) the target's prologue read `s4 = 1; s6 = 0; s1 = 0; s3 = 0xFF; s2 = 0; s5 = 0;`: the constant
between the counters, which can only be written as a variable of its own, `k = 0xFF;`, put at that place among the
entry assignments and compared in the loop (`x != k`). The expression stays equal (nothing in the loop writes `k`), so
the compiler cannot fold it back (cse works inside one path and the loop head is a join); only where the `li` sits in
the entry block changes, and with it the scheduler's order of the saved-register saves (140 -> 0 on its own, every
other row already exact). The explanation is read from the dumps (loop.c's placement of hoisted constants), a hypothesis.

A literal of two or more hex digits at least 0x80 (a byte value that needs a register), compared with `==` or `!=` at
least twice after the first loop, and a run of plain `name = number;` assignments just before that loop: one child per
place in the run (the start, between each pair, the end).
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'entry_constant_local'
FAMILIES = (FAMILY,)
LIMIT = 8

LOOP = re.compile(r'(?<![\w.>])(?:do\s*\{|for\s*\(|while\s*\()')
COMPARE = re.compile(r'(!=|==)\s*(0[xX][0-9A-Fa-f]{2,}|[0-9]{3,})[uU]?\b')
RUN_LINE = re.compile(r'(?m)^([ \t]*)[A-Za-z_]\w*\s*=\s*(?:0[xX][0-9A-Fa-f]+|-?[0-9]+)\s*;[ \t]*\n')


def _value(text):
    return int(text, 16 if text.lower().startswith('0x') else 10)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    loop = LOOP.search(clean, part.opening + 1, part.end)
    if not loop:
        return []
    counts = {}
    for hit in COMPARE.finditer(clean, loop.start(), part.end):
        value = _value(hit[2])
        if 0x80 <= value <= 0xFFFF:
            counts.setdefault(hit[2], []).append(hit)
    literals = [literal for literal, hits in counts.items() if len(hits) >= 2]
    if not literals:
        return []
    # the run of plain constant assignments that ends right at the loop
    run = []
    position = loop.start()
    before = clean[part.opening + 1:position]
    lines = list(RUN_LINE.finditer(before))
    end = len(before)
    for hit in reversed(lines):
        if before[hit.end():end].strip():
            break
        run.insert(0, hit)
        end = hit.start()
    if not run:
        return []
    found = []
    base = part.opening + 1
    for literal in literals[:2]:
        local = 'const_' + re.sub(r'\W', '', literal.lower())
        if re.search(rf'(?<![\w.>]){local}\b', clean):
            continue
        replace = [(hit.start(2), hit.end(2), local) for hit in counts[literal]]
        indent = run[0][1]
        declaration = (base, base, f'\n    s32 {local};')
        for place in range(len(run) + 1):
            at = base + (run[place].start() if place < len(run) else run[-1].end())
            assign = (at, at, f'{indent}{local} = {literal};\n')
            found.append((FAMILY, edit(source, [declaration, assign] + replace)))
            if len(found) >= LIMIT:
                return found
    return found


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 10}  # the registry: no caller wiring (registry.py)
