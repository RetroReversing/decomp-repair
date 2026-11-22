"""A search loop's "nothing found" value set once on the way out, not carried round the loop.

m2c (and a first hand-written draft) spell a search as `found = 0; while (C) { found = e; if (T) break; ...; found = 0; }`:
`found` is live across the loop's back edge, so it conflicts with every register the loop's loads use. KMC GCC 2.7.2's
original had the value written on each exit only: the break path sets `found = e`, the condition's failing exit
falls into a block that sets `found = 0`, and the two meet after it. With that shape `found` shares a register with the
loop's loaded word (it was `$v1` against the target's `$v0`), and the compiler fills the exits' delay slots with the two
assignments (`beq ..; addu $v0,$a1,$zero` and `bne ..; addu $v0,$zero,$zero`). Four such loops in a 219-instruction N64
function (`-G0 -mips3 -mgp32 -mfp32 -O2`) went 285 -> 180 with it, then 20 once the variable the call-argument loop
shared was split (`argument_loop_split`); with a few small edits the function matched. Spelling it with `if (!C) found = 0`
after a `for (;;)` or with a ternary after the loop was far worse (3450 and 4955): the exit's block must be the one
the failing condition falls into. The register explanation is read from the allocator's conflict table, a hypothesis.

`variants` offers `X = 0; while (C) { X = E; if (T) break; MID X = 0; }` (one statement per line or several, no inner
braces, X not read by C, T or MID) as
`while (C) { if (T) { X = E; goto L; } MID } X = 0; L: ;`, and the loop already in the second form's reverse is left
alone. The judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'loop_exit_value_block'
FAMILIES = (FAMILY,)


def _loop(variable):
    x = re.escape(variable)
    return re.compile(
        rf'(?P<init>(?<![\w.>]){x}\s*=\s*0\s*;\s*)'
        rf'while\s*\((?P<cond>[^{{}};]*)\)\s*{{\s*'
        rf'{x}\s*=\s*(?P<value>[^;{{}}]+?)\s*;\s*'
        rf'if\s*\((?P<test>[^{{}};]*)\)\s*break\s*;'
        rf'(?P<mid>[^{{}}]*?)'
        rf'{x}\s*=\s*0\s*;\s*}}')


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|volatile)\b', part.body):
        return []
    clean, found, number = part.clean, [], 0
    for variable in sorted(set(re.findall(rf'(?<![\w.>])({IDENT})\s*=\s*0\s*;\s*while\b', part.body))):
        read = re.compile(rf'(?<![\w.>]){re.escape(variable)}\b')
        edits = []
        for hit in _loop(variable).finditer(clean, part.opening + 1, part.end):
            if read.search(hit['cond']) or read.search(hit['test']) or read.search(hit['mid']):
                continue
            number += 1
            label = f'exit_value_{number}'
            mid = ' '.join(source[hit.start('mid'):hit.end('mid')].split())
            mid = f' {mid} ' if mid else ' '
            text = (f'while ({hit["cond"]}) {{ if ({hit["test"]}) {{ {variable} = {hit["value"]}; goto {label}; }}'
                    f'{mid}}} {variable} = 0; {label}:;')
            edits.append((hit.start(), hit.end(), text))
        if edits:
            found.append((FAMILY, edit(source, edits)))
    return found
